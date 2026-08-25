from __future__ import annotations

from dataclasses import dataclass
from math import fsum, sqrt
from typing import Iterable, Literal

from growthevo.models import PolicyEvidence


@dataclass(frozen=True, slots=True)
class LoggedBanditRecord:
    reward: float
    behavior_propensity: float
    target_action_probability: float
    baseline_q: float
    target_q: float

    def __post_init__(self) -> None:
        if not 0 < self.behavior_propensity <= 1:
            raise ValueError("behavior_propensity must be in (0, 1]")
        if not 0 <= self.target_action_probability <= 1:
            raise ValueError("target_action_probability must be in [0, 1]")

    @property
    def importance_weight(self) -> float:
        return self.target_action_probability / self.behavior_propensity


@dataclass(frozen=True, slots=True)
class OPEEstimate:
    """Counterfactual policy-value estimates plus deployment diagnostics.

    ``beta_ips`` uses an estimated optimal additive control variate with
    ``w - 1`` as the zero-mean control. This follows the 2026 SIGIR direction
    that additive baseline corrections can dominate self-normalisation for OPE.

    The estimator remains only as trustworthy as the logged propensities and
    support assumptions. ``effective_sample_size``, ``support_coverage`` and the
    weight-tail diagnostics are therefore first-class outputs rather than debug
    metadata.

    ``support_coverage`` is target-policy-mass weighted: unsupported records are
    weighted by their importance mass rather than counted equally. This prevents
    a small number of extremely high-weight, out-of-support records from being
    hidden by a large number of low-impact supported rows. The unweighted
    ``record_support_coverage`` is retained as a descriptive diagnostic.
    """

    ips: float
    doubly_robust: float
    beta_ips: float
    beta_star: float
    ips_standard_error: float
    dr_standard_error: float
    beta_ips_standard_error: float
    effective_sample_size: float
    effective_sample_ratio: float
    support_coverage: float
    max_importance_weight: float
    weight_coefficient_of_variation: float
    sample_size: int
    record_support_coverage: float = 1.0


def _mean(values: list[float]) -> float:
    return fsum(values) / len(values)


def _standard_error(values: list[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    center = _mean(values)
    sample_variance = fsum((value - center) ** 2 for value in values) / (n - 1)
    return sqrt(max(0.0, sample_variance) / n)


def _sample_covariance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("covariance inputs must have equal length")
    if len(left) <= 1:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    return fsum(
        (l_value - left_mean) * (r_value - right_mean)
        for l_value, r_value in zip(left, right, strict=True)
    ) / (len(left) - 1)


def _sample_variance(values: list[float]) -> float:
    return _sample_covariance(values, values)


def evaluate_policy(
    records: Iterable[LoggedBanditRecord],
    *,
    support_propensity_floor: float = 1e-3,
) -> OPEEstimate:
    """Evaluate a target policy from logged contextual-bandit feedback.

    The implementation deliberately returns multiple estimators instead of
    selecting one silently. Promotion code can compare IPS, DR and beta-IPS and
    abstain when overlap diagnostics indicate unsupported extrapolation.
    """

    if not 0 < support_propensity_floor <= 1:
        raise ValueError("support_propensity_floor must be in (0, 1]")

    rows = list(records)
    if not rows:
        raise ValueError("at least one logged record is required")

    weights = [row.importance_weight for row in rows]
    ips_terms = [weight * row.reward for weight, row in zip(weights, rows, strict=True)]
    dr_terms = [
        row.target_q + weight * (row.reward - row.baseline_q)
        for weight, row in zip(weights, rows, strict=True)
    ]

    # Additive control variate: X = w - E[w] with E[w] = 1 under valid
    # propensities. The population variance-minimising coefficient is
    # Cov(wR, w-1) / Var(w-1); we estimate it from the logged cohort.
    control = [weight - 1.0 for weight in weights]
    control_variance = _sample_variance(control)
    beta_star = (
        _sample_covariance(ips_terms, control) / control_variance
        if control_variance > 1e-15
        else 0.0
    )
    beta_terms = [
        ips_term - beta_star * control_value
        for ips_term, control_value in zip(ips_terms, control, strict=True)
    ]

    n = len(rows)
    weight_sum = fsum(weights)
    squared_weight_sum = fsum(weight * weight for weight in weights)
    ess = (weight_sum * weight_sum / squared_weight_sum) if squared_weight_sum > 0 else 0.0

    weight_mean = _mean(weights)
    weight_std = sqrt(max(0.0, _sample_variance(weights))) if n > 1 else 0.0
    weight_cv = weight_std / weight_mean if abs(weight_mean) > 1e-15 else float("inf")

    support_mask = [
        row.target_action_probability == 0.0
        or row.behavior_propensity >= support_propensity_floor
        for row in rows
    ]
    supported_records = sum(support_mask)
    supported_target_mass = fsum(
        weight
        for weight, supported in zip(weights, support_mask, strict=True)
        if supported
    )
    target_mass_support_coverage = (
        supported_target_mass / weight_sum if weight_sum > 1e-15 else 0.0
    )

    return OPEEstimate(
        ips=_mean(ips_terms),
        doubly_robust=_mean(dr_terms),
        beta_ips=_mean(beta_terms),
        beta_star=beta_star,
        ips_standard_error=_standard_error(ips_terms),
        dr_standard_error=_standard_error(dr_terms),
        beta_ips_standard_error=_standard_error(beta_terms),
        effective_sample_size=ess,
        effective_sample_ratio=ess / n,
        support_coverage=target_mass_support_coverage,
        max_importance_weight=max(weights),
        weight_coefficient_of_variation=weight_cv,
        sample_size=n,
        record_support_coverage=supported_records / n,
    )


def policy_evidence_from_ope(
    estimate: OPEEstimate,
    *,
    baseline_value: float,
    roi: float,
    spend: float,
    fatigue: float,
    churn_risk: float,
    estimator: Literal["beta_ips", "doubly_robust", "ips"] = "beta_ips",
) -> PolicyEvidence:
    """Compile OPE output into the verifier's evidence contract.

    ``beta_ips`` is the default value estimator; DR and plain IPS remain
    explicit choices for ablations and robustness checks.
    """

    if estimator == "beta_ips":
        value = estimate.beta_ips
        standard_error = estimate.beta_ips_standard_error
    elif estimator == "doubly_robust":
        value = estimate.doubly_robust
        standard_error = estimate.dr_standard_error
    elif estimator == "ips":
        value = estimate.ips
        standard_error = estimate.ips_standard_error
    else:  # pragma: no cover - Literal protects typed callers.
        raise ValueError(f"unsupported estimator: {estimator}")

    return PolicyEvidence(
        candidate_value=value,
        baseline_value=baseline_value,
        standard_error=standard_error,
        sample_size=estimate.sample_size,
        effective_sample_size=estimate.effective_sample_size,
        roi=roi,
        spend=spend,
        fatigue=fatigue,
        churn_risk=churn_risk,
        support_coverage=estimate.support_coverage,
        max_importance_weight=estimate.max_importance_weight,
    )
