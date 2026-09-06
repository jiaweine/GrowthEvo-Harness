from __future__ import annotations

import pytest

from growthevo.evolution.evidence_lab import (
    BernoulliSequentialScenario,
    MonteCarloAcceptanceGate,
    SequentialEvidenceLabPlan,
    SequentialProtocolCertificate,
    run_sequential_evidence_lab,
)
from growthevo.evolution.online_promotion import CanaryMetricSpec, CanaryPlan
from growthevo.evolution.sequential_causal import GroupSequentialSpec, HighPowerCanaryPlan


def _plan(
    *,
    replications: int = 64,
    expected_n: int = 64,
    seed: int = 17,
    gate: MonteCarloAcceptanceGate | None = None,
) -> SequentialEvidenceLabPlan:
    base = CanaryPlan(
        experiment_id="evidence-lab-test",
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
    high_power = HighPowerCanaryPlan(
        base_plan=base,
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=expected_n,
            look_fractions=(0.25, 0.50, 0.75, 1.0),
            alpha=0.20,
            spending="obrien_fleming",
            min_arm_observations=6,
        ),
    )
    return SequentialEvidenceLabPlan(
        high_power_plan=high_power,
        scenario=BernoulliSequentialScenario(
            name="strong-binary-signal",
            control_rate=0.50,
            benefit_effect=0.45,
            harm_effect=-0.45,
            max_observations=expected_n,
        ),
        replications=replications,
        base_seed=seed,
        gate=gate or MonteCarloAcceptanceGate(
            max_type_i_upper=0.20,
            min_power_lower=0.50,
            min_harm_detection_lower=0.50,
            max_mean_rollback_delay_fraction=0.95,
            confidence_level=0.95,
            minimum_replications=1000,
        ),
    )


def test_lab_is_reproducible_for_same_plan_and_commit() -> None:
    plan = _plan()
    first = run_sequential_evidence_lab(plan, commit_sha="abc123")
    second = run_sequential_evidence_lab(plan, commit_sha="abc123")
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


def test_seed_changes_lab_plan_identity() -> None:
    assert _plan(seed=17).fingerprint != _plan(seed=18).fingerprint


def test_small_monte_carlo_run_is_diagnostic_only() -> None:
    artifact = run_sequential_evidence_lab(_plan(replications=64), commit_sha="abc123")
    assert not artifact.acceptance_passed
    assert "insufficient_monte_carlo_replications" in artifact.acceptance_reasons
    with pytest.raises(ValueError, match="did not pass acceptance"):
        SequentialProtocolCertificate.from_artifact(artifact)


def test_strong_reference_protocol_can_pass_pre_registered_lab_gate() -> None:
    artifact = run_sequential_evidence_lab(
        _plan(replications=1000, expected_n=128),
        commit_sha="abc123",
    )
    assert artifact.acceptance_passed, artifact.acceptance_reasons
    assert artifact.group_sequential.type_i_error.upper <= 0.20
    assert artifact.anytime_eprocess.type_i_error.upper <= 0.20
    assert artifact.group_sequential.power.lower >= 0.50
    assert artifact.anytime_eprocess.power.lower >= 0.50
    assert artifact.anytime_eprocess.harm_detection is not None
    assert artifact.anytime_eprocess.harm_detection.lower >= 0.50
    certificate = SequentialProtocolCertificate.from_artifact(artifact)
    assert certificate.high_power_plan_fingerprint == artifact.high_power_plan_fingerprint
    assert certificate.lab_artifact_fingerprint == artifact.fingerprint


def test_impossibly_tight_type_i_gate_fails_closed() -> None:
    gate = MonteCarloAcceptanceGate(
        max_type_i_upper=0.001,
        min_power_lower=0.0,
        min_harm_detection_lower=0.0,
        max_mean_rollback_delay_fraction=1.0,
        confidence_level=0.95,
        minimum_replications=1000,
    )
    artifact = run_sequential_evidence_lab(
        _plan(replications=1000, expected_n=32, gate=gate),
        commit_sha="abc123",
    )
    assert not artifact.acceptance_passed
    assert any(reason.endswith(":type_i_upper_exceeds_gate") for reason in artifact.acceptance_reasons)


def test_bernoulli_lab_requires_metric_bounds_cover_unit_interval() -> None:
    base = CanaryPlan(
        experiment_id="bounded",
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
        SequentialEvidenceLabPlan(
            high_power_plan=hp,
            scenario=BernoulliSequentialScenario(
                name="bad-bounds",
                control_rate=0.5,
                benefit_effect=0.2,
                harm_effect=-0.2,
                max_observations=32,
            ),
            replications=64,
            base_seed=1,
        )
