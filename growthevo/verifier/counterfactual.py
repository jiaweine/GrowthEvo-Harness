from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from growthevo.models import GrowthConstraints, PolicyEvidence, VerificationResult, VerificationStatus
from growthevo.rl.conformal import ConformalMargins


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    """Statistical superiority rule selected by the experiment protocol.

    ``z_score`` has no repository-wide default because the appropriate tail
    probability/confidence rule belongs to the evaluation design. The verifier
    fails closed when no statistical config is supplied.
    """

    z_score: float
    min_value_delta: float = 0.0

    def __post_init__(self) -> None:
        if self.z_score < 0:
            raise ValueError("z_score must be non-negative")


class EvidenceQualityGate(Protocol):
    """Protocol-defined requirements for whether OPE evidence is usable."""

    def gaps(self, evidence: PolicyEvidence) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ThresholdEvidenceGate:
    """Explicit overlap/sample-quality gate with no hidden numerical defaults.

    The thresholds must be chosen from the experiment/deployment protocol. They
    are intentionally not universal constants of GrowthEvo.
    """

    min_sample_size: int
    min_effective_sample_size: float
    min_effective_sample_ratio: float
    min_support_coverage: float
    max_importance_weight: float

    def __post_init__(self) -> None:
        if self.min_sample_size < 0:
            raise ValueError("min_sample_size must be non-negative")
        if self.min_effective_sample_size < 0:
            raise ValueError("min_effective_sample_size must be non-negative")
        if not 0 <= self.min_effective_sample_ratio <= 1:
            raise ValueError("min_effective_sample_ratio must be in [0, 1]")
        if not 0 <= self.min_support_coverage <= 1:
            raise ValueError("min_support_coverage must be in [0, 1]")
        if self.max_importance_weight < 0:
            raise ValueError("max_importance_weight must be non-negative")

    def gaps(self, evidence: PolicyEvidence) -> tuple[str, ...]:
        gaps: list[str] = []
        if evidence.sample_size < self.min_sample_size:
            gaps.append("sample_size_below_gate")
        if evidence.effective_sample_size < self.min_effective_sample_size:
            gaps.append("effective_sample_size_below_gate")
        if evidence.effective_sample_ratio < self.min_effective_sample_ratio:
            gaps.append("effective_sample_ratio_below_gate")
        if evidence.support_coverage < self.min_support_coverage:
            gaps.append("logging_support_below_gate")
        if evidence.max_importance_weight > self.max_importance_weight:
            gaps.append("importance_weight_tail_above_gate")
        return tuple(gaps)


class CounterfactualVerifier:
    """Conservative promotion gate for learned growth policies.

    Statistical superiority, evidence quality, and business constraints are
    separate contracts. GrowthEvo does not embed one global sample-size/overlap
    recipe. A deployment or benchmark must inject both a ``VerifierConfig`` and
    an ``EvidenceQualityGate``; otherwise promotion abstains.
    """

    def __init__(
        self,
        config: VerifierConfig | None = None,
        *,
        evidence_gate: EvidenceQualityGate | None = None,
    ) -> None:
        self.config = config
        self.evidence_gate = evidence_gate

    def verify(
        self,
        evidence: PolicyEvidence,
        constraints: GrowthConstraints,
        *,
        conformal: ConformalMargins | None = None,
    ) -> VerificationResult:
        if evidence.standard_error < 0:
            raise ValueError("standard_error must be non-negative")

        value_delta = evidence.candidate_value - evidence.baseline_value
        missing_protocol: list[str] = []
        if self.config is None:
            missing_protocol.append("statistical_gate_not_configured")
        if self.evidence_gate is None:
            missing_protocol.append("evidence_quality_gate_not_configured")
        if missing_protocol:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                value_delta=value_delta,
                lower_confidence_bound=float("-inf"),
                reasons=tuple(missing_protocol),
            )

        cfg = self.config
        statistical_lcb = value_delta - cfg.z_score * evidence.standard_error
        calibrated_lcb = (
            conformal.value_lcb(value_delta) if conformal is not None else statistical_lcb
        )
        lcb = min(statistical_lcb, calibrated_lcb)

        evidence_gaps = self.evidence_gate.gaps(evidence)
        if evidence_gaps:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                value_delta=value_delta,
                lower_confidence_bound=lcb,
                reasons=evidence_gaps,
            )

        roi_lcb = conformal.roi_lcb(evidence.roi) if conformal is not None else evidence.roi
        spend_ucb = (
            conformal.spend_ucb(evidence.spend) if conformal is not None else evidence.spend
        )
        fatigue_ucb = (
            conformal.fatigue_ucb(evidence.fatigue)
            if conformal is not None
            else evidence.fatigue
        )
        churn_ucb = (
            conformal.churn_risk_ucb(evidence.churn_risk)
            if conformal is not None
            else evidence.churn_risk
        )

        violations: list[str] = []
        if roi_lcb < constraints.min_roi:
            violations.append("roi_constraint_violated")
        if spend_ucb > constraints.max_budget:
            violations.append("budget_constraint_violated")
        if fatigue_ucb > constraints.max_fatigue:
            violations.append("fatigue_constraint_violated")
        if churn_ucb > constraints.max_churn_risk:
            violations.append("churn_risk_constraint_violated")
        if lcb <= cfg.min_value_delta:
            violations.append("value_lcb_not_superior")

        if violations:
            return VerificationResult(
                status=VerificationStatus.FAIL,
                value_delta=value_delta,
                lower_confidence_bound=lcb,
                reasons=tuple(violations),
            )

        return VerificationResult(
            status=VerificationStatus.PASS,
            value_delta=value_delta,
            lower_confidence_bound=lcb,
        )
