from __future__ import annotations

from typing import Any, Mapping

from growthevo.llm.planner import GuardedLLMGrowthPlanner, LLMPlannerConfig
from growthevo.models import (
    Channel,
    EventType,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
    UserObservation,
)
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.engine import GrowthEvoRuntime


class FakeClient:
    def __init__(
        self,
        output: Mapping[str, Any] | None = None,
        *,
        provider_name: str = "fake",
        model: str = "fake-pinned-v1",
        error: Exception | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.output = output
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error is not None:
            raise self.error
        if self.output is None:
            raise AssertionError("fake output not configured")
        return self.output


def _constraints(**overrides: object) -> GrowthConstraints:
    values: dict[str, object] = {
        "max_budget": 100.0,
        "min_roi": 1.0,
        "max_fatigue": 0.8,
        "max_churn_risk": 0.5,
        "max_touches_24h": 2,
        "max_touches_7d": 6,
        "max_offer_value": 20.0,
    }
    values.update(overrides)
    return GrowthConstraints(**values)  # type: ignore[arg-type]


def _goal(**overrides: object) -> GrowthGoal:
    values: dict[str, object] = {
        "metric": "incremental_ltv",
        "horizon_days": 30,
        "target_delta": 0.05,
        "constraints": _constraints(),
    }
    values.update(overrides)
    return GrowthGoal(**values)  # type: ignore[arg-type]


def _observation(**overrides: object) -> UserObservation:
    values: dict[str, object] = {
        "user_id": "secret-user-123",
        "natural_conversion": 0.20,
        "channel_uplift": {Channel.PUSH: 0.08, Channel.EMAIL: 0.04},
        "uplift_uncertainty": 0.05,
        "ltv": 100.0,
        "fatigue": 0.10,
        "churn_risk": 0.10,
        "touches_24h": 0,
        "touches_7d": 1,
        "spend_to_date": 0.0,
        "days_since_last_active": 0,
        "lifecycle_stage": "active",
        "consented_channels": frozenset({Channel.PUSH, Channel.EMAIL}),
    }
    values.update(overrides)
    return UserObservation(**values)  # type: ignore[arg-type]


def _proposal(
    option: GrowthOption = GrowthOption.RETAIN,
    *,
    confidence: float = 0.91,
    exploration_priority: float = 0.0,
) -> Mapping[str, Any]:
    return {
        "option": option.value,
        "rationale": "Retention is the strongest semantic objective under the supplied causal state.",
        "confidence": confidence,
        "exploration_priority": exploration_priority,
    }


def test_llm_can_only_propose_semantic_option_and_context_is_redacted() -> None:
    client = FakeClient(_proposal())
    planner = GuardedLLMGrowthPlanner(client)
    belief = build_causal_belief(_observation())

    hypothesis = planner.plan(belief, _goal())

    assert hypothesis.option is GrowthOption.RETAIN
    assert hypothesis.target_metric == "incremental_ltv"
    assert len(client.calls) == 1
    assert "secret-user-123" not in client.calls[0]["user"]
    properties = client.calls[0]["schema"]["properties"]
    assert set(properties) == {"option", "rationale", "confidence", "exploration_priority"}
    assert "channel" not in properties
    assert "budget" not in properties
    assert "offer_value" not in properties


def test_low_confidence_proposal_falls_back_to_original_planner() -> None:
    client = FakeClient(_proposal(GrowthOption.RETAIN, confidence=0.20))
    planner = GuardedLLMGrowthPlanner(client, config=LLMPlannerConfig(min_confidence=0.70))

    hypothesis = planner.plan(build_causal_belief(_observation()), _goal())

    assert hypothesis.option is GrowthOption.UPSELL
    audit = planner.audit_snapshot()
    assert audit is not None
    assert audit["accepted"] is False
    assert audit["reason"] == "proposal_low_confidence"


def test_baseline_hard_stop_short_circuits_remote_model() -> None:
    client = FakeClient(_proposal(GrowthOption.UPSELL))
    planner = GuardedLLMGrowthPlanner(client)
    goal = _goal(constraints=_constraints(max_fatigue=0.8))
    belief = build_causal_belief(_observation(fatigue=0.8))

    hypothesis = planner.plan(belief, goal)

    assert hypothesis.option is GrowthOption.HOLDOUT
    assert client.calls == []
    assert planner.audit_snapshot()["reason"] == "baseline_hard_stop"  # type: ignore[index]


def test_provider_failure_opens_circuit_and_preserves_baseline() -> None:
    client = FakeClient(error=TimeoutError("provider timeout"))
    planner = GuardedLLMGrowthPlanner(
        client,
        config=LLMPlannerConfig(max_consecutive_failures=1, circuit_cooldown_seconds=60.0),
    )
    belief = build_causal_belief(_observation())

    first = planner.plan(belief, _goal())
    second = planner.plan(belief, _goal())

    assert first.option is GrowthOption.UPSELL
    assert second.option is GrowthOption.UPSELL
    assert len(client.calls) == 1
    assert planner.audit_snapshot()["reason"] == "circuit_open"  # type: ignore[index]


def test_optional_critic_can_veto_without_selecting_replacement() -> None:
    proposer = FakeClient(_proposal(GrowthOption.RETAIN), provider_name="proposer")
    critic = FakeClient(
        {
            "approved": False,
            "confidence": 0.95,
            "rationale": "The proposal overstates the available evidence.",
            "risk_flags": ["weak_causal_support"],
        },
        provider_name="critic",
    )
    planner = GuardedLLMGrowthPlanner(proposer, critic=critic)

    hypothesis = planner.plan(build_causal_belief(_observation()), _goal())

    assert hypothesis.option is GrowthOption.UPSELL
    audit = planner.audit_snapshot()
    assert audit is not None
    assert audit["reason"] == "critic_veto"
    assert audit["critic_provider"] == "critic"


def test_shadow_mode_logs_candidate_but_returns_baseline() -> None:
    client = FakeClient(_proposal(GrowthOption.RETAIN))
    planner = GuardedLLMGrowthPlanner(client, config=LLMPlannerConfig(shadow_mode=True))

    hypothesis = planner.plan(build_causal_belief(_observation()), _goal())

    assert hypothesis.option is GrowthOption.UPSELL
    audit = planner.audit_snapshot()
    assert audit is not None
    assert audit["reason"] == "shadow_only"
    assert audit["proposed_option"] == GrowthOption.RETAIN.value
    assert audit["returned_option"] == GrowthOption.UPSELL.value


def test_runtime_hash_chain_records_redacted_llm_audit_without_extra_events() -> None:
    client = FakeClient(_proposal(GrowthOption.RETAIN))
    runtime = GrowthEvoRuntime(planner=GuardedLLMGrowthPlanner(client))

    result = runtime.run(_goal(), _observation())

    assert result.event_count == 7
    planned = next(
        event for event in runtime.event_store.events() if event.event_type is EventType.HYPOTHESIS_PLANNED
    )
    audit = planned.payload["planner_audit"]
    assert audit["provider"] == "fake"
    assert audit["model"] == "fake-pinned-v1"
    assert "user" not in audit
    assert "prompt" not in audit
    assert runtime.event_store.verify()
