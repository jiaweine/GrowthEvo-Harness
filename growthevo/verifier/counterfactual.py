from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import GrowthConstraints, PolicyEvidence, VerificationResult, VerificationStatus
from growthevo.rl.conformal import ConformalMargins


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    z_score: float = 1.96
    min_value_delta: float = 0.0
    min_sample_size: int = 50
    min_effective_sample_size: float = 20.0
    min_effective_sample_ratio: float = 0.20
    min_support_coverage: float = 0.95
    max_importance_weight: float = 20.0

    def __post_init__(self) -> None:
        if self.z_score < 0:
            raise ValueError("z_score must be non-negative")
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


class CounterfactualVerifier:
    """Conservative promotion gate for learned growth policies.

    Statistical superiority is necessary but not sufficient. A candidate also
    needs usable logging-policy overlap, enough effective samples, and hard
    business constraints. When split-conformal margins are supplied, the gate
    intersects asymptotic and calibrated bounds and therefore never becomes less
    conservative because of calibration.
    """

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()

    def verify(
        self,
        evidence: PolicyEvidence,
        constraints: GrowthConstraints,
        *,
        conformal: ConformalMargins | None = None,
    ) -> VerificationResult:
        cfg = self.config
        if evidence.standard_error < 0:
            raise ValueError("standard_error must be non-negative")

        value_delta = evidence.candidate_value - evidence.baseline_value
        statistical_lcb = value_delta - cfg.z_score * evidence.standard_error
        calibrated_lcb = (
            conformal.value_lcb(value_delta) if conformal is not None else statistical_lcb
        )
        lcb = min(statistical_lcb, calibrated_lcb)

        evidence_gaps: list[str] = []
        if evidence.sample_size < cfg.min_sample_size:
            evidence_gaps.append("sample_size_below_gate")
        if evidence.effective_sample_size < cfg.min_effective_sample_size:
            evidence_gaps.append("effective_sample_size_below_gate")
        if evidence.effective_sample_ratio < cfg.min_effective_sample_ratio:
            evidence_gaps.append("effective_sample_ratio_below_gate")
        if evidence.support_coverage < cfg.min_support_coverage:
            evidence_gaps.append("logging_support_below_gate")
        if evidence.max_importance_weight > cfg.max_importance_weight:
            evidence_gaps.append("importance_weight_tail_above_gate")

        if evidence_gaps:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                value_delta=value_delta,
                lower_confidence_bound=lcb,
                reasons=tuple(evidence_gaps),
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
