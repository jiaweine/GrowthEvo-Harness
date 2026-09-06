from __future__ import annotations

from dataclasses import replace

import pytest

from growthevo.evolution import (
    CanaryCandidate,
    CanaryMetricSpec,
    CanaryPlan,
    FrozenCUPEDSpec,
    GroupSequentialSpec,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
    HighPowerOnlinePromotionController,
)


def _candidate() -> CanaryCandidate:
    return CanaryCandidate(
        name="candidate",
        provider="openai",
        model="snapshot",
        contract_fingerprint="contract",
        source_commit_sha="commit",
        source_test_fingerprint="holdout",
        source_evidence_manifest_fingerprint="evidence",
        promotion_artifact_fingerprint="artifact",
    )


def _base(*, minimum: int = 2) -> CanaryPlan:
    candidate = _candidate()
    return CanaryPlan(
        experiment_id="atomic-high-power",
        candidate_name=candidate.name,
        candidate_contract_fingerprint=candidate.contract_fingerprint,
        source_artifact_fingerprint=candidate.promotion_artifact_fingerprint,
        metrics=(
            CanaryMetricSpec(
                name="value",
                outcome_min=0.0,
                outcome_max=1.0,
                noninferiority_margin=0.1,
            ),
        ),
        primary_metric="value",
        stages=(1.0,),
        challenger_probability=0.5,
        min_observations_per_stage=minimum,
        ramp_alpha=0.5,
        promotion_alpha=0.2,
        rollback_family_alpha=0.05,
    )


def test_invalid_cuped_observation_does_not_mutate_monitor_state() -> None:
    plan = HighPowerCanaryPlan(
        base_plan=_base(),
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=4,
            look_fractions=(1.0,),
            alpha=0.2,
            min_arm_observations=2,
        ),
        cuped=FrozenCUPEDSpec(
            covariate_name="pre",
            theta=0.5,
            center=0.5,
            covariate_min=0.0,
            covariate_max=1.0,
            source_fingerprint="preperiod",
        ),
    )
    controller = HighPowerOnlinePromotionController(
        champion_name="baseline",
        candidate=_candidate(),
        plan=plan,
    )
    controller.start()
    ticket = controller.enroll("unit-1")
    assert ticket.in_canary is True

    invalid = HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"value": 1.0 if ticket.assigned_to_challenger else 0.0},
        covariates={},
    )

    with pytest.raises(ValueError, match="missing frozen CUPED covariate"):
        controller.observe(invalid)

    assert controller.monitor.snapshot().total_observations == 0
    assert controller.monitor.primary_group_sequential.evidence().observations == 0

    valid = HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"value": 1.0 if ticket.assigned_to_challenger else 0.0},
        covariates={"pre": 0.5},
    )
    controller.observe(valid)
    assert controller.monitor.snapshot().total_observations == 1


def test_expected_final_sample_cannot_be_below_stage_safety_minimum() -> None:
    with pytest.raises(ValueError, match="cannot be below"):
        HighPowerCanaryPlan(
            base_plan=_base(minimum=10),
            group_sequential=GroupSequentialSpec(
                expected_final_stage_observations=8,
                look_fractions=(1.0,),
                alpha=0.2,
                min_arm_observations=2,
            ),
        )


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), 1.1])
def test_mutated_metric_mapping_is_revalidated_before_state_changes(invalid_value) -> None:
    base = _base()
    base = replace(
        base,
        metrics=(*base.metrics, CanaryMetricSpec("cost", 0.0, 1.0)),
        cumulative_cost_metric="cost",
        max_challenger_cumulative_cost=10.0,
    )
    controller = HighPowerOnlinePromotionController(
        champion_name="baseline", candidate=_candidate(),
        plan=HighPowerCanaryPlan(base, GroupSequentialSpec(100)),
    )
    controller.start()
    ticket = controller.enroll("mutable-unit")
    metrics = {"value": 0.5, "cost": 0.1}
    observation = HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics=metrics,
    )
    metrics["cost"] = invalid_value
    before = controller.monitor.snapshot()
    primary_before = controller.monitor.primary_group_sequential.evidence()
    with pytest.raises(ValueError):
        controller.observe(observation)
    assert controller.monitor.snapshot() == before
    assert controller.monitor.primary_group_sequential.evidence() == primary_before
    metrics["cost"] = 0.1
    assert controller.observe(observation).total_observations == 1


def test_cuped_arithmetic_overflow_is_rejected_before_state_changes() -> None:
    cuped = FrozenCUPEDSpec("pre", 1e308, 0.0, -2.0, 2.0, "frozen-reference")
    controller = HighPowerOnlinePromotionController(
        champion_name="baseline", candidate=_candidate(),
        plan=HighPowerCanaryPlan(_base(), GroupSequentialSpec(100), cuped),
    )
    controller.start()
    ticket = controller.enroll("overflow-unit")
    observation = HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"value": 0.5}, covariates={"pre": 2.0},
    )
    before = controller.monitor.snapshot()
    primary_before = controller.monitor.primary_group_sequential.evidence()
    with pytest.raises(ValueError, match="adjusted.*finite"):
        controller.observe(observation)
    assert controller.monitor.snapshot() == before
    assert controller.monitor.primary_group_sequential.evidence() == primary_before
    assert controller.observe(replace(observation, covariates={"pre": 0.0})).total_observations == 1


def test_finite_adjusted_values_cannot_overflow_running_variance() -> None:
    controller = HighPowerOnlinePromotionController(
        champion_name="baseline", candidate=_candidate(),
        plan=HighPowerCanaryPlan(
            _base(), GroupSequentialSpec(100),
            FrozenCUPEDSpec("pre", 1e200, 0.0, 0.0, 1.0, "frozen-reference"),
        ),
    )
    controller.start()
    tickets = []
    for index in range(100):
        ticket = controller.enroll(f"variance-{index}")
        if ticket.assigned_to_challenger:
            tickets.append(ticket)
        if len(tickets) == 2:
            break
    assert len(tickets) == 2
    first = HighPowerCanaryObservation(
        analysis_unit_id=tickets[0].analysis_unit_id, routing_stage_index=0,
        assigned_to_challenger=True, assignment_probability=0.5,
        traffic_fraction=1.0, metrics={"value": 0.5}, covariates={"pre": 1.0},
    )
    controller.observe(first)
    second = replace(first, analysis_unit_id=tickets[1].analysis_unit_id, covariates={"pre": 0.0})
    before = controller.monitor.snapshot()
    primary_before = controller.monitor.primary_group_sequential.evidence()
    with pytest.raises(ValueError, match="running moments"):
        controller.observe(second)
    assert controller.monitor.snapshot() == before
    assert controller.monitor.primary_group_sequential.evidence() == primary_before
    assert controller.observe(replace(second, covariates={"pre": 1.0})).total_observations == 2
