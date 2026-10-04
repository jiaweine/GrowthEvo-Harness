from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any, Mapping

from growthevo.llm.planner import GuardedLLMGrowthPlanner, LLMPlannerConfig
from growthevo.models import Channel, GrowthConstraints, GrowthGoal, GrowthOption, UserObservation
from growthevo.runtime.belief_state import build_causal_belief


class _ThreadLocalClient:
    provider_name = "thread-local-fixture"
    model = "fixture-v1"

    def __init__(self) -> None:
        self.local = threading.local()

    def set_output(self, option: GrowthOption, confidence: float) -> None:
        self.local.output = {
            "option": option.value,
            "rationale": f"fixture-{option.value}",
            "confidence": confidence,
            "exploration_priority": 0.0,
        }

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del system, user, schema
        return self.local.output


class _FailingClient:
    provider_name = "failing-fixture"
    model = "fixture-v1"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls = 0

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del system, user, schema
        with self.lock:
            self.calls += 1
        raise TimeoutError("fixture timeout")


def _goal() -> GrowthGoal:
    return GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=GrowthConstraints(
            max_budget=100.0,
            min_roi=1.0,
            max_fatigue=0.8,
            max_churn_risk=0.5,
            max_touches_24h=2,
            max_touches_7d=6,
            max_offer_value=20.0,
        ),
    )


def _belief():
    return build_causal_belief(
        UserObservation(
            user_id="redacted-fixture-user",
            natural_conversion=0.20,
            channel_uplift={Channel.PUSH: 0.08, Channel.EMAIL: 0.04},
            uplift_uncertainty=0.05,
            ltv=100.0,
            fatigue=0.10,
            churn_risk=0.10,
            touches_24h=0,
            touches_7d=1,
            spend_to_date=0.0,
            days_since_last_active=0,
            lifecycle_stage="active",
            consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
        )
    )


def test_concurrent_requests_keep_planner_audit_trace_isolated_per_thread() -> None:
    client = _ThreadLocalClient()
    planner = GuardedLLMGrowthPlanner(client)
    barrier = threading.Barrier(24)

    def run(index: int) -> tuple[str, str, float]:
        option = GrowthOption.RETAIN if index % 2 == 0 else GrowthOption.REACTIVATE
        confidence = 0.80 + (index / 1000.0)
        client.set_output(option, confidence)
        hypothesis = planner.plan(_belief(), _goal())
        barrier.wait(timeout=5.0)
        audit = planner.audit_snapshot()
        assert audit is not None
        return hypothesis.option.value, str(audit["proposed_option"]), float(audit["confidence"])

    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(run, range(24)))

    for index, (returned, proposed, confidence) in enumerate(results):
        expected = GrowthOption.RETAIN if index % 2 == 0 else GrowthOption.REACTIVATE
        assert returned == expected.value
        assert proposed == expected.value
        assert confidence == 0.80 + (index / 1000.0)


def test_concurrent_failures_open_one_shared_circuit_without_corrupting_state() -> None:
    client = _FailingClient()
    planner = GuardedLLMGrowthPlanner(
        client,
        config=LLMPlannerConfig(
            max_consecutive_failures=4,
            circuit_cooldown_seconds=60.0,
        ),
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: planner.plan(_belief(), _goal()), range(8)))

    calls_after_wave = client.calls
    assert calls_after_wave >= 4

    # Once the concurrent failure wave has opened the circuit, a later request
    # must fail closed to the deterministic baseline without another provider call.
    hypothesis = planner.plan(_belief(), _goal())
    audit = planner.audit_snapshot()
    assert hypothesis.option is GrowthOption.UPSELL
    assert audit is not None
    assert audit["reason"] == "circuit_open"
    assert client.calls == calls_after_wave
