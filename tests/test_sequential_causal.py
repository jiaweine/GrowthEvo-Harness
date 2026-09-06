from __future__ import annotations

from dataclasses import replace
from statistics import pvariance

import pytest

from growthevo.evolution.online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryMetricSpec,
    CanaryPlan,
    CanaryStatus,
)
from growthevo.evolution.sequential_causal import (
    FrozenCUPEDSpec,
    GroupSequentialPrimaryMonitor,
    GroupSequentialSpec,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
    HighPowerOnlinePromotionController,
)


def _candidate() -> CanaryCandidate:
    return CanaryCandidate(
        name="frontier-candidate",
        provider="openai",
        model="pinned-model-snapshot",
        contract_fingerprint="contract-fp",
        source_commit_sha="deadbeef",
        source_test_fingerprint="holdout-fp",
        source_evidence_manifest_fingerprint="evidence-fp",
        promotion_artifact_fingerprint="artifact-fp",
    )


def _base_plan(
    *,
    stages: tuple[float, ...] = (1.0,),
    min_observations: int = 4,
) -> CanaryPlan:
    candidate = _candidate()
    return CanaryPlan(
        experiment_id="high-power-2026q3",
        candidate_name=candidate.name,
        candidate_contract_fingerprint=candidate.contract_fingerprint,
        source_artifact_fingerprint=candidate.promotion_artifact_fingerprint,
        metrics=(
            CanaryMetricSpec(
                name="incremental_value",
                outcome_min=0.0,
                outcome_max=1.0,
                higher_is_better=True,
                noninferiority_margin=0.10,
            ),
        ),
        primary_metric="incremental_value",
        stages=stages,
        challenger_probability=0.5,
        min_observations_per_stage=min_observations,
        primary_min_improvement=0.05,
        ramp_alpha=0.50,
        promotion_alpha=0.20,
        rollback_family_alpha=0.05,
    )


def _high_power_plan(
    *,
    stages: tuple[float, ...] = (1.0,),
    expected_final: int = 20,
    looks: tuple[float, ...] = (0.5, 1.0),
    min_observations: int = 4,
    cuped: FrozenCUPEDSpec | None = None,
) -> HighPowerCanaryPlan:
    return HighPowerCanaryPlan(
        base_plan=_base_plan(stages=stages, min_observations=min_observations),
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=expected_final,
            look_fractions=looks,
            alpha=0.20,
            spending="equal",
            min_arm_observations=2,
        ),
        cuped=cuped,
        analysis_unit_name="user",
    )


def _observation_from_ticket(ticket, *, challenger_value: float = 1.0, control_value: float = 0.0, covariates=None):
    value = challenger_value if ticket.assigned_to_challenger else control_value
    return HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"incremental_value": value},
        covariates={} if covariates is None else covariates,
    )


def test_group_sequential_alpha_spending_is_preregistered_and_bounded() -> None:
    spec = GroupSequentialSpec(
        expected_final_stage_observations=400,
        look_fractions=(0.25, 0.50, 0.75, 1.0),
        alpha=0.05,
        spending="obrien_fleming",
    )

    increments = [spec.incremental_alpha(index) for index in range(4)]

    assert spec.look_targets == (100, 200, 300, 400)
    assert all(value >= 0 for value in increments)
    assert sum(increments) == pytest.approx(0.05)
    assert spec.cumulative_alpha(3) == pytest.approx(0.05)


def test_group_sequential_alpha_cannot_weaken_base_promotion_gate() -> None:
    base = _base_plan()
    too_loose = GroupSequentialSpec(
        expected_final_stage_observations=100,
        alpha=0.25,
    )

    with pytest.raises(ValueError, match="cannot exceed base promotion_alpha"):
        HighPowerCanaryPlan(base_plan=base, group_sequential=too_loose)


def test_frozen_cuped_reduces_variance_on_predictive_preexposure_signal() -> None:
    cuped = FrozenCUPEDSpec(
        covariate_name="pre_value",
        theta=0.8,
        center=0.5,
        covariate_min=0.0,
        covariate_max=1.0,
        source_fingerprint="preperiod-v1",
    )
    covariates = [index / 99 for index in range(100)]
    raw = [0.2 + 0.8 * (value - 0.5) + (0.01 if index % 2 else -0.01) for index, value in enumerate(covariates)]
    adjusted = [
        cuped.adjust(outcome, {"pre_value": value})
        for outcome, value in zip(raw, covariates)
    ]

    assert pvariance(adjusted) < pvariance(raw) * 0.01
    assert len(cuped.fingerprint) == 40


def test_cuped_requires_frozen_covariate_and_bounds() -> None:
    cuped = FrozenCUPEDSpec(
        covariate_name="pre_value",
        theta=0.5,
        center=0.5,
        covariate_min=0.0,
        covariate_max=1.0,
        source_fingerprint="preperiod-v1",
    )

    with pytest.raises(ValueError, match="missing frozen CUPED covariate"):
        cuped.adjust(0.5, {})
    with pytest.raises(ValueError, match="outside pre-registered bounds"):
        cuped.adjust(0.5, {"pre_value": 1.1})


def test_primary_monitor_analyzes_only_at_planned_looks() -> None:
    plan = _high_power_plan(expected_final=20, looks=(1.0,))
    monitor = GroupSequentialPrimaryMonitor(plan)

    for index in range(19):
        challenger = index % 2 == 0
        monitor.observe(
            HighPowerCanaryObservation(
                analysis_unit_id=f"unit-{index}",
                routing_stage_index=0,
                assigned_to_challenger=challenger,
                assignment_probability=0.5,
                traffic_fraction=1.0,
                metrics={"incremental_value": 1.0 if challenger else 0.0},
            )
        )

    assert monitor.evidence().looks == ()
    monitor.observe(
        HighPowerCanaryObservation(
            analysis_unit_id="unit-19",
            routing_stage_index=0,
            assigned_to_challenger=False,
            assignment_probability=0.5,
            traffic_fraction=1.0,
            metrics={"incremental_value": 0.0},
        )
    )
    evidence = monitor.evidence()
    assert len(evidence.looks) == 1
    assert evidence.success is True
    assert evidence.looks[0].success is True


def test_high_power_controller_promotes_only_after_planned_primary_look() -> None:
    plan = _high_power_plan(expected_final=20, looks=(1.0,), min_observations=4)
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
    )
    controller.start()

    last = None
    admitted = 0
    for index in range(500):
        ticket = controller.enroll(f"promote-{index}")
        if not ticket.in_canary:
            continue
        admitted += 1
        last = controller.observe(_observation_from_ticket(ticket))
        if admitted < 20:
            assert last.decision is not CanaryDecision.PROMOTE
        if last.decision is CanaryDecision.PROMOTE:
            break

    assert last is not None
    assert last.decision is CanaryDecision.PROMOTE
    assert admitted >= 20
    assert controller.champion_name == "frontier-candidate"
    assert controller.monitor.status is CanaryStatus.PROMOTED
    assert controller.verify_audit_chain() is True


def test_delayed_old_stage_outcome_is_valid_but_does_not_fill_current_stage_quota() -> None:
    plan = _high_power_plan(
        stages=(0.5, 1.0),
        expected_final=20,
        looks=(1.0,),
        min_observations=4,
    )
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
    )
    controller.start()

    delayed = None
    for index in range(1000):
        ticket = controller.enroll(f"stage0-{index}")
        if not ticket.in_canary:
            continue
        if delayed is None:
            delayed = ticket
            continue
        snapshot = controller.observe(_observation_from_ticket(ticket))
        if snapshot.decision is CanaryDecision.ADVANCE:
            break
    else:
        raise AssertionError("stage 0 never advanced")

    assert delayed is not None
    assert controller.monitor.stage_index == 1
    assert controller.monitor.snapshot().stage_observations == 0

    snapshot = controller.observe(_observation_from_ticket(delayed))

    assert snapshot.stage_index == 1
    assert snapshot.stage_observations == 0
    assert snapshot.decision is CanaryDecision.HOLD


def test_delayed_outcome_is_verified_against_original_exposure_stage() -> None:
    plan = _high_power_plan(stages=(0.5, 1.0), min_observations=4)
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
    )
    controller.start()

    ticket = None
    for index in range(1000):
        candidate_ticket = controller.enroll(f"forged-{index}")
        if candidate_ticket.in_canary:
            ticket = candidate_ticket
            break
    assert ticket is not None

    forged = _observation_from_ticket(ticket)
    forged = HighPowerCanaryObservation(
        analysis_unit_id=forged.analysis_unit_id,
        routing_stage_index=forged.routing_stage_index,
        assigned_to_challenger=not forged.assigned_to_challenger,
        assignment_probability=forged.assignment_probability,
        traffic_fraction=forged.traffic_fraction,
        metrics=forged.metrics,
    )

    with pytest.raises(ValueError, match="stable router"):
        controller.observe(forged)


def test_randomization_cluster_can_contribute_only_one_matured_outcome() -> None:
    plan = _high_power_plan(expected_final=20, looks=(1.0,))
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
    )
    controller.start()

    ticket = controller.enroll("user-cluster-7")
    assert ticket.in_canary is True
    observation = _observation_from_ticket(ticket)
    controller.observe(observation)

    with pytest.raises(ValueError, match="already been observed"):
        controller.observe(observation)


def _controller_with_delayed_exposure():
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=_high_power_plan(stages=(0.5, 1.0)),
    )
    controller.start()
    delayed = None
    excluded = None
    for index in range(1000):
        ticket = controller.enroll(f"exposure-boundary-{index}")
        if not ticket.in_canary:
            excluded = ticket
            continue
        if delayed is None:
            delayed = ticket
            continue
        snapshot = controller.observe(_observation_from_ticket(ticket))
        if snapshot.decision is CanaryDecision.ADVANCE:
            assert delayed is not None
            assert excluded is not None
            return controller, delayed, excluded
    raise AssertionError("stage 0 never advanced")


def test_delayed_exposure_cannot_be_relabelled_as_final_stage() -> None:
    controller, delayed, _ = _controller_with_delayed_exposure()
    original = _observation_from_ticket(delayed)
    forged = replace(original, routing_stage_index=1, traffic_fraction=1.0)
    before = controller.monitor.snapshot()
    primary_before = controller.monitor.primary_group_sequential.evidence()
    events_before = controller.events()

    with pytest.raises(ValueError, match="registered exposure stage"):
        controller.observe(forged)

    assert controller.monitor.snapshot() == before
    assert controller.monitor.primary_group_sequential.evidence() == primary_before
    assert controller.events() == events_before

    # Rejection leaves the real delayed outcome retryable and confined to safety.
    accepted = controller.observe(original)
    assert accepted.total_observations == before.total_observations + 1
    assert accepted.stage_observations == 0
    assert controller.monitor.primary_group_sequential.evidence() == primary_before


def test_reenrollment_preserves_first_admitted_exposure_stage() -> None:
    controller, delayed, _ = _controller_with_delayed_exposure()

    assert controller.enroll(delayed.analysis_unit_id) == delayed
    assert controller.route(delayed.analysis_unit_id) == delayed
    accepted = controller.observe(_observation_from_ticket(delayed))
    assert accepted.stage_observations == 0
    assert controller.monitor.primary_group_sequential.evidence().observations == 0
    # Observing a unit must not discard its first-exposure record either.
    assert controller.enroll(delayed.analysis_unit_id) == delayed
    with pytest.raises(ValueError, match="already been observed"):
        controller.observe(_observation_from_ticket(delayed))


def test_previously_excluded_unit_can_first_enroll_in_final_stage() -> None:
    controller, _, excluded = _controller_with_delayed_exposure()

    admitted = controller.enroll(excluded.analysis_unit_id)
    assert admitted.in_canary is True
    assert admitted.routing_stage_index == 1
    assert controller.enroll(excluded.analysis_unit_id) == admitted
    accepted = controller.observe(_observation_from_ticket(admitted))
    assert accepted.stage_observations == 1
    assert controller.monitor.primary_group_sequential.evidence().observations == 1


def test_matching_route_without_enrollment_is_rejected_atomically() -> None:
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=_high_power_plan(),
    )
    controller.start()
    route = controller.router.route("never-enrolled", stage_index=0)
    forged = HighPowerCanaryObservation(
        analysis_unit_id=route.analysis_unit_id,
        routing_stage_index=0,
        assigned_to_challenger=route.assigned_to_challenger,
        assignment_probability=route.challenger_probability,
        traffic_fraction=route.traffic_fraction,
        metrics={"incremental_value": 0.5},
    )
    before = controller.monitor.snapshot()
    primary_before = controller.monitor.primary_group_sequential.evidence()
    events_before = controller.events()

    with pytest.raises(ValueError, match="no registered exposure"):
        controller.observe(forged)

    assert controller.monitor.snapshot() == before
    assert controller.monitor.primary_group_sequential.evidence() == primary_before
    assert controller.events() == events_before
    ticket = controller.enroll(route.analysis_unit_id)
    assert controller.observe(_observation_from_ticket(ticket)).total_observations == 1


def test_high_power_audit_binds_advanced_plan_and_contains_no_raw_outcomes() -> None:
    plan = _high_power_plan()
    controller = HighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
    )

    events = controller.events()
    assert events[0].kind == "challenger_registered"
    assert events[1].kind == "high_power_inference_registered"
    assert events[1].payload["high_power_plan_fingerprint"] == plan.fingerprint
    assert "analysis_unit_id" not in str(events)
    assert "metrics" not in str(events)
    assert controller.verify_audit_chain() is True
