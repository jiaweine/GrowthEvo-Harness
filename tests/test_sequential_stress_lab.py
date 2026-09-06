from __future__ import annotations

import pytest

from growthevo.evolution.evidence_lab import SequentialProtocolCertificate
from growthevo.evolution.online_promotion import CanaryMetricSpec, CanaryPlan
from growthevo.evolution.sequential_causal import GroupSequentialSpec, HighPowerCanaryPlan
from growthevo.evolution.stress_lab import (
    DelayedCensoringStress,
    HeavyTailStress,
    RobustSequentialProtocolCertificate,
    SRMStress,
    SequentialStressSuitePlan,
    run_sequential_stress_suite,
)


def _plan(*, replications: int = 48, seed: int = 29) -> SequentialStressSuitePlan:
    base = CanaryPlan(
        experiment_id="stress-lab-test",
        candidate_name="candidate",
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
        min_observations_per_stage=20,
        primary_min_improvement=0.0,
        ramp_alpha=0.20,
        promotion_alpha=0.20,
        rollback_family_alpha=0.20,
    )
    hp = HighPowerCanaryPlan(
        base_plan=base,
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=96,
            look_fractions=(0.25, 0.50, 0.75, 1.0),
            alpha=0.20,
            spending="obrien_fleming",
            min_arm_observations=6,
        ),
    )
    return SequentialStressSuitePlan(
        high_power_plan=hp,
        replications=replications,
        base_seed=seed,
        censoring=DelayedCensoringStress(
            control_missing_probability=0.02,
            challenger_missing_probability=0.45,
            challenger_success_extra_missing_probability=0.35,
        ),
        srm=SRMStress(
            challenger_logging_probability=0.20,
            control_logging_probability=1.0,
            p_value_threshold=0.001,
        ),
        heavy_tail=HeavyTailStress(
            pareto_shape=1.25,
            scale=1.0,
            draws_per_replication=24,
        ),
    )


def test_stress_suite_is_reproducible() -> None:
    plan = _plan(replications=16)
    first = run_sequential_stress_suite(plan, commit_sha="abc123")
    second = run_sequential_stress_suite(plan, commit_sha="abc123")
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


def test_seed_changes_stress_suite_identity() -> None:
    assert _plan(seed=29).fingerprint != _plan(seed=30).fingerprint


def test_current_protocol_exposes_known_robustness_blockers() -> None:
    artifact = run_sequential_stress_suite(_plan(), commit_sha="abc123")
    assert not artifact.robust_ready
    assert "cluster:repeated_events_require_upstream_cluster_aggregation" in artifact.blockers
    assert (
        "censoring:arm_or_outcome_dependent_missingness_requires_explicit_estimand"
        in artifact.blockers
    )
    assert "heterogeneity:aggregate_success_can_mask_harmed_subgroups" in artifact.blockers


def test_srm_corruption_is_detected_as_integrity_failure() -> None:
    artifact = run_sequential_stress_suite(_plan(replications=64), commit_sha="abc123")
    assert artifact.srm.integrity_blocker_detected
    assert artifact.srm.alarm_rate.estimate > 0.50
    assert artifact.srm.mean_challenger_share < artifact.srm.expected_challenger_share


def test_heavy_tail_outcomes_fail_closed_instead_of_being_clipped() -> None:
    artifact = run_sequential_stress_suite(_plan(replications=8), commit_sha="abc123")
    assert artifact.heavy_tail.out_of_bound_rate.successes > 0
    assert artifact.heavy_tail.fail_closed
    assert artifact.heavy_tail.rejected_out_of_bound_rate.estimate == 1.0


def test_robust_certificate_cannot_be_issued_from_failing_stress_artifact() -> None:
    plan = _plan(replications=8)
    artifact = run_sequential_stress_suite(plan, commit_sha="abc123")
    nominal = SequentialProtocolCertificate(
        commit_sha="abc123",
        high_power_plan_fingerprint=plan.high_power_plan.fingerprint,
        lab_plan_fingerprint="lab",
        lab_artifact_fingerprint="artifact",
        scenario_fingerprint="scenario",
    )
    with pytest.raises(ValueError, match="unresolved robustness blockers"):
        RobustSequentialProtocolCertificate.issue(nominal=nominal, stress=artifact)


def test_binary_stress_suite_requires_unit_interval_metric_support() -> None:
    base = CanaryPlan(
        experiment_id="bad-stress-bounds",
        candidate_name="candidate",
        candidate_contract_fingerprint="contract",
        source_artifact_fingerprint="artifact",
        metrics=(CanaryMetricSpec(name="value", outcome_min=0.2, outcome_max=1.0),),
        primary_metric="value",
        stages=(1.0,),
        min_observations_per_stage=20,
    )
    hp = HighPowerCanaryPlan(
        base_plan=base,
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=32,
            look_fractions=(0.5, 1.0),
            min_arm_observations=4,
        ),
    )
    with pytest.raises(ValueError, match="contain \\[0, 1\\]"):
        SequentialStressSuitePlan(high_power_plan=hp, replications=8, base_seed=1)
