from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import GrowthConstraints, PolicyEvidence, VerificationResult, VerificationStatus


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    z_score: float = 1.96
    min_value_delta: float = 0.0
    min_sample_size: int = 50
    min_effective_sample_size: float = 20.0


class CounterfactualVerifier:
    """Promote only when conservative value and hard constraints are satisfied."""

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()

    def verify(
        self,
        evidence: PolicyEvidence,
        constraints: GrowthConstraints,
    ) -> VerificationResult:
        cfg = self.config
        value_delta = evidence.candidate_value - evidence.baseline_value
        lcb = value_delta - cfg.z_score * max(0.0, evidence.standard_error)

        if (
            evidence.sample_size < cfg.min_sample_size
            or evidence.effective_sample_size < cfg.min_effective_sample_size
        ):
            reasons: list[str] = []
            if evidence.sample_size < cfg.min_sample_size:
                reasons.append("sample_size_below_gate")
            if evidence.effective_sample_size < cfg.min_effective_sample_size:
                reasons.append("effective_sample_size_below_gate")
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                value_delta=value_delta,
                lower_confidence_bound=lcb,
                reasons=tuple(reasons),
            )

        violations: list[str] = []
        if evidence.roi < constraints.min_roi:
            violations.append("roi_constraint_violated")
        if evidence.spend > constraints.max_budget:
            violations.append("budget_constraint_violated")
        if evidence.fatigue > constraints.max_fatigue:
            violations.append("fatigue_constraint_violated")
        if evidence.churn_risk > constraints.max_churn_risk:
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
