from __future__ import annotations

import pytest

from growthevo.evolution.optimizer import HarnessEvolver
from growthevo.models import (
    Channel,
    GrowthAction,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
    PolicyEvidence,
    UserObservation,
    VerificationStatus,
)
from growthevo.rl.hierarchical_policy import HierarchicalGrowthPolicy
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.engine import GrowthEvoRuntime
from growthevo.runtime.event_store import EventStore
from growthevo.runtime.legal_action import LegalActionGate
from growthevo.runtime.planner import GrowthHypothesis
from growthevo.verifier.counterfactual import CounterfactualVerifier


def _observation(**overrides: object) -> UserObservation:
    values: dict[str, object] = {
        "user_id": "u-1",
        "natural_conversion": 0.20,
        "channel_uplift": {Channel.PUSH: 0.08, Channel.EMAIL: 0.04},
        "uplift_uncertainty": 0.05,
        "ltv": 100.0,
        "fatigue": 0.10,
        "churn_risk": 0.10,
        "touches_24h": 0,
        "touches_7d": 1,
        "spend_to_date": 0.0,
        "days_since_last_active": 45,
        "lifecycle_stage": "dormant",
        "consented_channels": frozenset({Channel.PUSH, Channel.EMAIL}),
    }
    values.update(overrides)
    return UserObservation(**values)  # type: ignore[arg-type]


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


def test_low_incremental_value_abstains_even_when_natural_conversion_is_high() -> None:
    belief = build_causal_belief(
        _observation(
            natural_conversion=0.95,
            channel_uplift={Channel.PUSH: 0.001},
            ltv=10.0,
            days_since_last_active=0,
            lifecycle_stage="active",
        )
    )
    hypothesis = GrowthHypothesis(
        option=GrowthOption.UPSELL,
        rationale="test",
        target_metric="incremental_ltv",
    )

    action = HierarchicalGrowthPolicy().select_action(belief, hypothesis, _constraints())

    assert action.channel is Channel.NO_TREATMENT
    assert action.budget == 0
    assert action.expected_uplift == 0


def test_hard_budget_gate_blocks_treatment() -> None:
    belief = build_causal_belief(_observation(spend_to_date=9.5))
    action = GrowthAction(
        option=GrowthOption.REACTIVATE,
        channel=Channel.PUSH,
        budget=1.0,
        expected_uplift=0.08,
        uncertainty=0.05,
    )

    decision = LegalActionGate().evaluate(belief, action, _constraints(max_budget=10.0))

    assert not decision.allowed
    assert "budget_exceeded" in decision.reasons


def test_no_treatment_always_has_zero_direct_cost() -> None:
    action = GrowthAction.no_treatment()
    assert action.channel is Channel.NO_TREATMENT
    assert action.offer_value == 0
    assert action.budget == 0
    assert action.frequency_cost == 0


def test_event_store_hash_chain_verifies() -> None:
    store = EventStore()
    from growthevo.models import EventType

    store.append(EventType.GOAL_COMPILED, {"metric": "incremental_ltv"})
    store.append(EventType.BELIEF_UPDATED, {"user_id": "u-1"})

    assert store.verify()
    assert store.events()[1].previous_hash == store.events()[0].event_hash


def test_doubly_robust_ope_and_effective_sample_size() -> None:
    estimate = evaluate_policy(
        [
            LoggedBanditRecord(
                reward=1.0,
                behavior_propensity=0.5,
                target_action_probability=0.5,
                baseline_q=0.4,
                target_q=0.5,
            ),
            LoggedBanditRecord(
                reward=0.0,
                behavior_propensity=0.5,
                target_action_probability=0.5,
                baseline_q=0.2,
                target_q=0.3,
            ),
        ]
    )

    assert estimate.ips == pytest.approx(0.5)
    assert estimate.doubly_robust == pytest.approx(0.6)
    assert estimate.effective_sample_size == pytest.approx(2.0)


def test_verifier_separates_insufficient_evidence_from_failure() -> None:
    verifier = CounterfactualVerifier()
    evidence = PolicyEvidence(
        candidate_value=1.2,
        baseline_value=1.0,
        standard_error=0.02,
        sample_size=10,
        effective_sample_size=8,
        roi=2.0,
        spend=5.0,
        fatigue=0.2,
        churn_risk=0.1,
    )

    result = verifier.verify(evidence, _constraints())

    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_verifier_requires_value_lcb_and_constraints() -> None:
    verifier = CounterfactualVerifier()
    passing = PolicyEvidence(
        candidate_value=1.3,
        baseline_value=1.0,
        standard_error=0.05,
        sample_size=100,
        effective_sample_size=80,
        roi=2.0,
        spend=5.0,
        fatigue=0.2,
        churn_risk=0.1,
    )
    failing_roi = PolicyEvidence(
        candidate_value=1.3,
        baseline_value=1.0,
        standard_error=0.05,
        sample_size=100,
        effective_sample_size=80,
        roi=0.5,
        spend=5.0,
        fatigue=0.2,
        churn_risk=0.1,
    )

    assert verifier.verify(passing, _constraints()).status is VerificationStatus.PASS
    failed = verifier.verify(failing_roi, _constraints()).status
    assert failed is VerificationStatus.FAIL


def test_evolver_rejects_frozen_coordinates() -> None:
    with pytest.raises(ValueError, match="frozen coordinate"):
        HarnessEvolver.validate_coordinate("verifier")


def test_runtime_executes_and_preserves_event_integrity() -> None:
    runtime = GrowthEvoRuntime()
    goal = GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=_constraints(),
    )

    result = runtime.run(goal, _observation())

    assert result.action.channel is Channel.PUSH
    assert result.action.option is GrowthOption.REACTIVATE
    assert result.feedback.incremental_conversion > 0
    assert result.event_count == 7
    assert runtime.event_store.verify()
