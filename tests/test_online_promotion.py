from __future__ import annotations

from dataclasses import replace

import pytest

from growthevo.bench.llm_evaluation import LockedLLMBenchmarkArtifact
from growthevo.evolution.online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryMetricSpec,
    CanaryObservation,
    CanaryPlan,
    CanaryRouter,
    CanaryStatus,
    OnlineCanaryMonitor,
    OnlinePromotionController,
)


def _artifact(*, eligible: bool = True) -> LockedLLMBenchmarkArtifact:
    return LockedLLMBenchmarkArtifact(
        benchmark="llm-online-canary-test",
        dataset="locked-causal-holdout",
        dataset_source="unit-test",
        commit_sha="deadbeef",
        experiment_plan_fingerprint="plan-fp",
        tuning_fingerprint="validation-fp",
        test_fingerprint="holdout-fp",
        selected_candidate="frontier-candidate",
        promotion_eligible=eligible,
        metrics={
            "provider": "openai",
            "model": "pinned-model-snapshot",
            "contract_fingerprint": "contract-fp",
            "evidence_manifest_fingerprint": "causal-evidence-fp",
            "incremental_lcb": 0.2,
        },
    )


def _candidate() -> CanaryCandidate:
    return CanaryCandidate.from_locked_artifact(_artifact())


def _plan(
    *,
    stages: tuple[float, ...] = (0.05, 0.25),
    min_observations: int = 12,
    include_fatigue: bool = True,
    cost_cap: float | None = None,
) -> CanaryPlan:
    candidate = _candidate()
    metrics = [
        CanaryMetricSpec(
            name="incremental_value",
            outcome_min=0.0,
            outcome_max=1.0,
            higher_is_better=True,
            noninferiority_margin=0.10,
        )
    ]
    if include_fatigue:
        metrics.append(
            CanaryMetricSpec(
                name="fatigue",
                outcome_min=0.0,
                outcome_max=1.0,
                higher_is_better=False,
                noninferiority_margin=0.05,
                absolute_max=0.60,
            )
        )
    if cost_cap is not None:
        metrics.append(
            CanaryMetricSpec(
                name="cost",
                outcome_min=0.0,
                outcome_max=10.0,
                higher_is_better=False,
                noninferiority_margin=0.50,
            )
        )
    return CanaryPlan(
        experiment_id="canary-2026q3",
        candidate_name=candidate.name,
        candidate_contract_fingerprint=candidate.contract_fingerprint,
        source_artifact_fingerprint=candidate.promotion_artifact_fingerprint,
        metrics=tuple(metrics),
        primary_metric="incremental_value",
        stages=stages,
        challenger_probability=0.5,
        min_observations_per_stage=min_observations,
        primary_min_improvement=0.05,
        ramp_alpha=0.10,
        promotion_alpha=0.10,
        rollback_family_alpha=0.05,
        cumulative_cost_metric=("cost" if cost_cap is not None else None),
        max_challenger_cumulative_cost=cost_cap,
    )


def _observation(
    monitor: OnlineCanaryMonitor,
    index: int,
    *,
    positive_primary: bool = True,
    safe_fatigue: bool = True,
    challenger: bool | None = None,
    cost: float = 0.0,
) -> CanaryObservation:
    assigned = bool(index % 2 == 0) if challenger is None else challenger
    if positive_primary:
        primary = 1.0 if assigned else 0.0
    else:
        primary = 0.0 if assigned else 1.0
    metrics: dict[str, float] = {"incremental_value": primary}
    if "fatigue" in monitor._monitors:  # test helper only
        if safe_fatigue:
            metrics["fatigue"] = 0.10 if assigned else 0.30
        else:
            metrics["fatigue"] = 1.00 if assigned else 0.00
    if "cost" in monitor._monitors:  # test helper only
        metrics["cost"] = cost if assigned else 0.0
    return CanaryObservation(
        analysis_unit_id=f"unit-{monitor.stage_index}-{index}-{monitor._total_observations}",
        assigned_to_challenger=assigned,
        assignment_probability=monitor.plan.challenger_probability,
        traffic_fraction=monitor.traffic_fraction,
        metrics=metrics,
    )


def _run_until_transition(
    monitor: OnlineCanaryMonitor,
    *,
    positive_primary: bool = True,
    safe_fatigue: bool = True,
    limit: int = 1000,
) -> CanaryDecision:
    for index in range(limit):
        snapshot = monitor.observe(
            _observation(
                monitor,
                index,
                positive_primary=positive_primary,
                safe_fatigue=safe_fatigue,
            )
        )
        if snapshot.decision is not CanaryDecision.HOLD:
            return snapshot.decision
    raise AssertionError("canary did not reach a transition within the test limit")


def test_candidate_requires_locked_promotion_eligibility() -> None:
    with pytest.raises(ValueError, match="not promotion eligible"):
        CanaryCandidate.from_locked_artifact(_artifact(eligible=False))


def test_candidate_binds_locked_artifact_identity() -> None:
    candidate = _candidate()

    assert candidate.name == "frontier-candidate"
    assert candidate.contract_fingerprint == "contract-fp"
    assert candidate.source_test_fingerprint == "holdout-fp"
    assert candidate.source_evidence_manifest_fingerprint == "causal-evidence-fp"
    assert len(candidate.promotion_artifact_fingerprint) == 64


def test_router_is_monotonic_across_stages_and_keeps_arm_assignment_stable() -> None:
    plan = _plan()
    router = CanaryRouter(plan)
    seen_inside = 0
    for index in range(5000):
        unit = f"routing-unit-{index}"
        early = router.route(unit, stage_index=0)
        later = router.route(unit, stage_index=1)
        if early.in_canary:
            seen_inside += 1
            assert later.in_canary is True
            assert later.assigned_to_challenger is early.assigned_to_challenger
    assert seen_inside > 50


def test_strong_safe_challenger_advances_then_promotes() -> None:
    monitor = OnlineCanaryMonitor(_plan())
    monitor.start()

    assert _run_until_transition(monitor) is CanaryDecision.ADVANCE
    assert monitor.status is CanaryStatus.RUNNING
    assert monitor.stage_index == 1

    assert _run_until_transition(monitor) is CanaryDecision.PROMOTE
    assert monitor.status is CanaryStatus.PROMOTED
    snapshot = monitor.snapshot()
    assert snapshot.total_observations >= 24
    assert snapshot.challenger_observations > 0


def test_primary_harm_triggers_anytime_rollback() -> None:
    monitor = OnlineCanaryMonitor(_plan(include_fatigue=False))
    monitor.start()

    decision = _run_until_transition(
        monitor,
        positive_primary=False,
        limit=1000,
    )

    assert decision is CanaryDecision.ROLLBACK
    assert monitor.status is CanaryStatus.ROLLED_BACK
    assert any("relative_harm_anytime_e" in reason for reason in monitor.snapshot().reasons) is False


def test_guardrail_harm_rolls_back_even_when_primary_is_strong() -> None:
    monitor = OnlineCanaryMonitor(_plan())
    monitor.start()

    decision = _run_until_transition(
        monitor,
        positive_primary=True,
        safe_fatigue=False,
        limit=1000,
    )

    assert decision is CanaryDecision.ROLLBACK
    assert monitor.status is CanaryStatus.ROLLED_BACK


def test_cumulative_cost_cap_is_a_deterministic_kill_switch() -> None:
    monitor = OnlineCanaryMonitor(
        _plan(
            include_fatigue=False,
            cost_cap=5.0,
            min_observations=50,
        )
    )
    monitor.start()

    snapshot = monitor.observe(
        _observation(
            monitor,
            0,
            challenger=True,
            cost=6.0,
        )
    )

    assert snapshot.decision is CanaryDecision.ROLLBACK
    assert snapshot.status is CanaryStatus.ROLLED_BACK
    assert "challenger_cumulative_cost_cap_exceeded" in snapshot.reasons


def test_observation_must_match_preregistered_probability_stage_and_metrics() -> None:
    monitor = OnlineCanaryMonitor(_plan(include_fatigue=False))
    monitor.start()
    valid = _observation(monitor, 0)

    with pytest.raises(ValueError, match="assignment probability"):
        monitor.observe(replace(valid, assignment_probability=0.4))
    with pytest.raises(ValueError, match="traffic fraction"):
        monitor.observe(replace(valid, traffic_fraction=0.2))
    with pytest.raises(ValueError, match="metrics do not match plan"):
        monitor.observe(replace(valid, metrics={"incremental_value": 1.0, "extra": 0.0}))


def test_analysis_unit_can_contribute_only_once() -> None:
    monitor = OnlineCanaryMonitor(_plan(include_fatigue=False))
    monitor.start()
    observation = _observation(monitor, 0)
    monitor.observe(observation)

    with pytest.raises(ValueError, match="already been observed"):
        monitor.observe(observation)


def test_final_stage_requires_fresh_primary_superiority_evidence() -> None:
    plan = _plan(stages=(0.05, 0.25), min_observations=8)
    monitor = OnlineCanaryMonitor(plan)
    monitor.start()

    assert _run_until_transition(monitor) is CanaryDecision.ADVANCE
    primary_evidence = {
        item.name: item for item in monitor.snapshot().metric_evidence
    }["incremental_value"]
    # Superiority is deliberately not accumulated before the final stage.
    assert primary_evidence.primary_superiority_e == pytest.approx(1.0)

    assert _run_until_transition(monitor) is CanaryDecision.PROMOTE


def test_controller_keeps_champion_on_rollback_and_hash_chains_transitions() -> None:
    candidate = _candidate()
    plan = _plan(include_fatigue=False)
    controller = OnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=candidate,
        plan=plan,
    )
    controller.start()

    for index in range(1000):
        snapshot = controller.observe(
            _observation(
                controller.monitor,
                index,
                positive_primary=False,
            )
        )
        if snapshot.decision is CanaryDecision.ROLLBACK:
            break
    else:
        raise AssertionError("expected rollback")

    assert controller.champion_name == "deterministic-baseline"
    assert controller.verify_audit_chain() is True
    kinds = [event.kind for event in controller.events()]
    assert kinds[0] == "challenger_registered"
    assert "canary_started" in kinds
    assert "challenger_rolled_back" in kinds
    # Audit payloads are aggregate-only; raw analysis-unit ids are not persisted.
    assert "analysis_unit_id" not in str(controller.events())


def test_controller_promotes_challenger_only_after_final_online_gate() -> None:
    candidate = _candidate()
    plan = _plan()
    controller = OnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=candidate,
        plan=plan,
    )
    controller.start()

    for index in range(2000):
        snapshot = controller.observe(_observation(controller.monitor, index))
        if snapshot.decision is CanaryDecision.PROMOTE:
            break
    else:
        raise AssertionError("expected promotion")

    assert controller.champion_name == candidate.name
    assert controller.monitor.status is CanaryStatus.PROMOTED
    assert controller.verify_audit_chain() is True
    assert controller.events()[-1].kind == "challenger_promoted"
