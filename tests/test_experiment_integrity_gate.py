from __future__ import annotations

import pytest

from growthevo.evolution.integrity_gate import (
    BetaBinomialAssignmentEProcess,
    ExperimentIntegrityGate,
    ExperimentIntegritySpec,
    IntegrityGuardedHighPowerPromotionController,
    IntegrityGuardedOnlinePromotionController,
    IntegrityStatus,
)
from growthevo.evolution.online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryMetricSpec,
    CanaryObservation,
    CanaryPlan,
)
from growthevo.evolution.sequential_causal import (
    GroupSequentialSpec,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
)


def _candidate() -> CanaryCandidate:
    return CanaryCandidate(
        name="challenger",
        provider="test",
        model="snapshot-v1",
        contract_fingerprint="contract-v1",
        source_commit_sha="commit-v1",
        source_test_fingerprint="test-v1",
        source_evidence_manifest_fingerprint="evidence-v1",
        promotion_artifact_fingerprint="artifact-v1",
    )


def _base_plan(*, min_observations: int = 50) -> CanaryPlan:
    return CanaryPlan(
        experiment_id="integrity-gate-test",
        candidate_name="challenger",
        candidate_contract_fingerprint="contract-v1",
        source_artifact_fingerprint="artifact-v1",
        metrics=(
            CanaryMetricSpec(
                name="value",
                outcome_min=0.0,
                outcome_max=1.0,
                higher_is_better=True,
                noninferiority_margin=0.0,
            ),
        ),
        primary_metric="value",
        stages=(1.0,),
        challenger_probability=0.5,
        min_observations_per_stage=min_observations,
        ramp_alpha=0.20,
        promotion_alpha=0.20,
        rollback_family_alpha=0.20,
    )


def _integrity_spec() -> ExperimentIntegritySpec:
    return ExperimentIntegritySpec(
        family_alpha=0.10,
        enrollment_alpha=0.05,
        matured_population_alpha=0.05,
        minimum_enrollment_observations=8,
        minimum_matured_observations=8,
        beta_prior_alpha=0.5,
        beta_prior_beta=0.5,
    )


def test_integrity_stream_alphas_cannot_exceed_family_budget() -> None:
    with pytest.raises(ValueError, match="cannot exceed family_alpha"):
        ExperimentIntegritySpec(
            family_alpha=0.01,
            enrollment_alpha=0.007,
            matured_population_alpha=0.007,
        )


def test_beta_binomial_assignment_eprocess_stays_small_for_balanced_split() -> None:
    process = BetaBinomialAssignmentEProcess(
        expected_probability=0.5,
        prior_alpha=0.5,
        prior_beta=0.5,
    )
    for index in range(80):
        process.update(bool(index % 2))
    evidence = process.evidence(alpha=0.01, minimum_observations=8)
    assert evidence.observations == 80
    assert evidence.challenger_share == pytest.approx(0.5)
    assert not evidence.tripped


def test_beta_binomial_assignment_eprocess_detects_extreme_srm() -> None:
    process = BetaBinomialAssignmentEProcess(
        expected_probability=0.5,
        prior_alpha=0.5,
        prior_beta=0.5,
    )
    for _ in range(20):
        process.update(True)
    evidence = process.evidence(alpha=0.01, minimum_observations=8)
    assert evidence.e_value >= evidence.threshold
    assert evidence.tripped


def test_integrity_gate_keeps_enrollment_and_matured_streams_separate() -> None:
    gate = ExperimentIntegrityGate(_base_plan(), _integrity_spec())
    units: list[tuple[str, bool]] = []
    for index in range(16):
        challenger = bool(index % 2)
        unit = f"u-{index}"
        units.append((unit, challenger))
        snapshot = gate.observe_enrollment(unit, assigned_to_challenger=challenger)
        assert snapshot.status is IntegrityStatus.CLEAR
    assert gate.snapshot().enrollment.challenger_share == pytest.approx(0.5)

    challenger_units = [item for item in units if item[1]]
    last = None
    for unit, challenger in challenger_units:
        last = gate.observe_matured_population(unit, assigned_to_challenger=challenger)
    assert last is not None
    assert last.status is IntegrityStatus.BLOCKED
    assert "matured_population_sample_ratio_mismatch" in last.reasons
    assert gate.verify_audit_chain()


def test_duplicate_integrity_records_are_rejected() -> None:
    gate = ExperimentIntegrityGate(_base_plan(), _integrity_spec())
    gate.observe_enrollment("same", assigned_to_challenger=True)
    with pytest.raises(ValueError, match="already been registered for enrollment"):
        gate.observe_enrollment("same", assigned_to_challenger=True)


def _collect_enrollments(controller, *, each_arm: int) -> tuple[list[object], list[object]]:
    challenger: list[object] = []
    control: list[object] = []
    index = 0
    while len(challenger) < each_arm or len(control) < each_arm:
        enrollment = controller.enroll(f"unit-{index}")
        route = enrollment.route
        if route.in_canary:
            target = challenger if route.assigned_to_challenger else control
            if len(target) < each_arm:
                target.append(route)
        index += 1
        if index > 10000:
            raise AssertionError("could not collect balanced deterministic routes")
    return challenger, control


def test_base_wrapper_blocks_biased_matured_population_before_metric_mutation() -> None:
    controller = IntegrityGuardedOnlinePromotionController(
        champion_name="champion",
        candidate=_candidate(),
        plan=_base_plan(min_observations=50),
        integrity_spec=_integrity_spec(),
    )
    controller.start()
    challenger, _ = _collect_enrollments(controller, each_arm=8)

    final = None
    for route in challenger:
        final = controller.observe(
            CanaryObservation(
                analysis_unit_id=route.analysis_unit_id,
                assigned_to_challenger=True,
                assignment_probability=route.challenger_probability,
                traffic_fraction=route.traffic_fraction,
                metrics={"value": 1.0},
            )
        )
    assert final is not None
    assert final.status.value == "rolled_back"
    assert final.decision is CanaryDecision.ROLLBACK
    assert "matured_population_sample_ratio_mismatch" in final.reasons
    # The triggering eighth matured record is blocked before the business metric
    # monitor mutates, so only seven outcomes entered the original controller.
    assert final.canary.total_observations == 7
    assert controller.champion_name == "champion"
    with pytest.raises(RuntimeError, match="integrity gate is blocked"):
        controller.enroll("after-block")


def test_high_power_wrapper_blocks_biased_matured_population_before_group_sequential_update() -> None:
    base = _base_plan(min_observations=20)
    high_power = HighPowerCanaryPlan(
        base_plan=base,
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=64,
            look_fractions=(0.25, 0.5, 0.75, 1.0),
            alpha=0.20,
            spending="obrien_fleming",
            min_arm_observations=4,
        ),
    )
    controller = IntegrityGuardedHighPowerPromotionController(
        champion_name="champion",
        candidate=_candidate(),
        plan=high_power,
        integrity_spec=_integrity_spec(),
    )
    controller.start()
    challenger, _ = _collect_enrollments(controller, each_arm=8)

    final = None
    for ticket in challenger:
        final = controller.observe(
            HighPowerCanaryObservation(
                analysis_unit_id=ticket.analysis_unit_id,
                routing_stage_index=ticket.routing_stage_index,
                assigned_to_challenger=True,
                assignment_probability=ticket.challenger_probability,
                traffic_fraction=ticket.traffic_fraction,
                metrics={"value": 1.0},
            )
        )
    assert final is not None
    assert final.decision is CanaryDecision.ROLLBACK
    assert final.canary.total_observations == 7
    assert controller.controller.monitor.primary_group_sequential.evidence().observations == 7
    assert controller.champion_name == "champion"


def test_balanced_matured_population_does_not_block_integrity_gate() -> None:
    controller = IntegrityGuardedOnlinePromotionController(
        champion_name="champion",
        candidate=_candidate(),
        plan=_base_plan(min_observations=50),
        integrity_spec=_integrity_spec(),
    )
    controller.start()
    challenger, control = _collect_enrollments(controller, each_arm=8)
    ordered = [item for pair in zip(challenger, control) for item in pair]
    final = None
    for route in ordered:
        final = controller.observe(
            CanaryObservation(
                analysis_unit_id=route.analysis_unit_id,
                assigned_to_challenger=route.assigned_to_challenger,
                assignment_probability=route.challenger_probability,
                traffic_fraction=route.traffic_fraction,
                metrics={"value": 0.5},
            )
        )
    assert final is not None
    assert final.integrity.status is IntegrityStatus.CLEAR
    assert final.integrity.matured_population.challenger_share == pytest.approx(0.5)
    assert final.decision is CanaryDecision.HOLD
