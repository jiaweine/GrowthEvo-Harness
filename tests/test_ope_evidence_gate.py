from __future__ import annotations

import pytest

from growthevo.bench.locked_evaluation import OPECandidate
from growthevo.bench.ope_evidence_gate import (
    EvidenceGatedOPEProtocol,
    OPEEvidenceGate,
)
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


def _well_supported(prefix: str) -> tuple[LoggedBanditRecord, ...]:
    return tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=0.25,
            target_q=0.25,
            record_id=f"{prefix}-{index}",
        )
        for index in range(4)
    )


def _low_ess(prefix: str) -> tuple[LoggedBanditRecord, ...]:
    return (
        LoggedBanditRecord(
            reward=1.0,
            behavior_propensity=0.001,
            target_action_probability=1.0,
            baseline_q=0.2,
            target_q=0.2,
            record_id=f"{prefix}-0",
        ),
        LoggedBanditRecord(0.0, 0.5, 0.0, 0.2, 0.2, record_id=f"{prefix}-1"),
        LoggedBanditRecord(1.0, 0.5, 0.0, 0.2, 0.2, record_id=f"{prefix}-2"),
        LoggedBanditRecord(0.0, 0.5, 0.0, 0.2, 0.2, record_id=f"{prefix}-3"),
    )


def test_default_gate_rejects_model_only_zero_importance_mass() -> None:
    rows = tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=0.0,
            baseline_q=0.2,
            target_q=0.3,
            record_id=f"zero-{index}",
        )
        for index in range(4)
    )
    estimate = evaluate_policy(rows)
    gate = OPEEvidenceGate()

    assert "no_positive_supported_importance_mass" in gate.failures(estimate)

    protocol = EvidenceGatedOPEProtocol([OPECandidate("dm", "direct_method")])
    with pytest.raises(ValueError, match="validation OPE evidence gate failed"):
        protocol.tune(rows, reference_value=0.3)
    assert protocol.selected_candidate is None
    assert protocol.validation_scores == ()


def test_explicit_support_and_ess_thresholds_gate_before_error_selection() -> None:
    weak_support = tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.01,
            target_action_probability=0.01,
            baseline_q=0.25,
            target_q=0.25,
            record_id=f"weak-{index}",
        )
        for index in range(4)
    )
    protocol = EvidenceGatedOPEProtocol(
        [OPECandidate("perfect-looking-dm", "direct_method")],
        support_propensity_floor=0.1,
        evidence_gate=OPEEvidenceGate(min_support_coverage=0.95),
    )

    with pytest.raises(ValueError, match="support_coverage_below_minimum"):
        protocol.tune(weak_support, reference_value=0.25)
    assert protocol.selected_candidate is None

    low_ess = EvidenceGatedOPEProtocol(
        [OPECandidate("ips", "ips")],
        evidence_gate=OPEEvidenceGate(min_effective_sample_ratio=0.5),
    )
    with pytest.raises(ValueError, match="effective_sample_ratio_below_minimum"):
        low_ess.tune(_low_ess("validation-low-ess"), reference_value=0.1)


def test_holdout_gate_failure_still_consumes_the_single_reveal() -> None:
    protocol = EvidenceGatedOPEProtocol(
        [OPECandidate("beta", "beta_ips")],
        evidence_gate=OPEEvidenceGate(
            min_support_coverage=0.95,
            min_effective_sample_ratio=0.5,
        ),
    )
    protocol.tune(_well_supported("validation"), reference_value=0.5)

    with pytest.raises(ValueError, match="holdout OPE evidence gate failed"):
        protocol.evaluate_once(_low_ess("holdout-bad"), reference_value=0.5)

    with pytest.raises(RuntimeError, match="already been revealed"):
        protocol.evaluate_once(_well_supported("different-holdout"), reference_value=0.5)


def test_gate_configuration_changes_protocol_fingerprint() -> None:
    candidates = [OPECandidate("beta", "beta_ips")]
    loose = EvidenceGatedOPEProtocol(
        candidates,
        evidence_gate=OPEEvidenceGate(min_support_coverage=0.5),
    )
    strict = EvidenceGatedOPEProtocol(
        candidates,
        evidence_gate=OPEEvidenceGate(min_support_coverage=0.95),
    )

    assert loose.protocol_fingerprint != strict.protocol_fingerprint


def test_successful_artifact_records_evidence_gate_and_validation_diagnostics() -> None:
    gate = OPEEvidenceGate(
        min_support_coverage=0.95,
        min_effective_sample_ratio=0.5,
    )
    protocol = EvidenceGatedOPEProtocol(
        [OPECandidate("beta", "beta_ips")],
        evidence_gate=gate,
    )
    protocol.tune(_well_supported("validation-ok"), reference_value=0.5)
    holdout = protocol.evaluate_once(
        _well_supported("holdout-ok"),
        reference_value=0.5,
    )
    artifact = protocol.artifact(
        holdout,
        benchmark="unit-ope",
        dataset="synthetic",
        commit_sha="deadbeef",
    )

    assert artifact.protocol_fingerprint == protocol.protocol_fingerprint
    assert artifact.metrics["min_support_coverage"] == pytest.approx(0.95)
    assert artifact.metrics["min_effective_sample_ratio"] == pytest.approx(0.5)
    assert artifact.metrics["validation_support_coverage"] == pytest.approx(1.0)
    assert artifact.metrics["validation_effective_sample_ratio"] == pytest.approx(1.0)
