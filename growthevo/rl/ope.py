from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from typing import Hashable, Iterable, Literal

from growthevo.models import PolicyEvidence


@dataclass(frozen=True, slots=True)
class LoggedBanditRecord:
    reward: float
    behavior_propensity: float
    target_action_probability: float
    baseline_q: float
    target_q: float
    cluster_id: Hashable | None = None

    def __post_init__(self) -> None:
        if not 0 < self.behavior_propensity <= 1:
            raise ValueError("behavior_propensity must be in (0, 1]")
        if not 0 <= self.target_action_probability <= 1:
            raise ValueError("target_action_probability must be in [0, 1]")
        for name, value in (
            ("reward", self.reward),
            ("baseline_q", self.baseline_q),
            ("target_q", self.target_q),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")

    @property
    def importance_weight(self) -> float:
        return self.target_action_probability / self.behavior_propensity


@dataclass(frozen=True, slots=True)
class OPEEstimate:
    """Counterfactual policy-value estimates plus overlap diagnostics.

    Robustness and control-variate coefficients are never silently tuned on the
    evaluation cohort. ``switch_threshold``, ``dr_os_lambda``, and
    ``beta_coefficient`` must be selected on validation data and passed in.
    Missing SWITCH/shrinkage parameters reduce to ordinary DR; a missing beta
    coefficient reduces beta-IPS to ordinary IPS.

    ``beta_star`` is retained only as an evaluation-cohort diagnostic showing
    the variance-minimising empirical coefficient one *would* obtain on this
    cohort. It is deliberately not applied to ``beta_ips`` unless the caller
    explicitly passes a coefficient.

    Standard errors are i.i.d. by default. If every record supplies a
    ``cluster_id``, cluster-robust standard errors are computed from cluster-level
    influence sums. The clustering unit is deliberately supplied by the data
    protocol rather than hard-coded into the estimator.
    """

    direct_method: float
    ips: float
    self_normalized_ips: float
    doubly_robust: float
    switch_dr: float
    dr_os: float
    beta_ips: float
    beta_coefficient: float | None
    beta_star: float
    dm_standard_error: float
    ips_standard_error: float
    snips_standard_error: float
    dr_standard_error: float
    switch_dr_standard_error: float
    dr_os_standard_error: float
    beta_ips_standard_error: float
    standard_error_method: Literal["iid", "cluster"]
    cluster_count: int | None
    switch_threshold: float | None
    dr_os_lambda: float | None
    effective_sample_size: float
    effective_sample_ratio: float
    support_coverage: float
    record_support_coverage: float
    max_importance_weight: float
    mean_importance_weight: float
    importance_weight_normalization_error: float
    weight_coefficient_of_variation: float
    sample_size: int


def _mean(values: list[float]) -> float:
    return fsum(values) / len(values)


def _standard_error(values: list[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    center = _mean(values)
    sample_variance = fsum((value - center) ** 2 for value in values) / (n - 1)
    return sqrt(max(0.0, sample_variance) / n)


def _cluster_standard_error(values: list[float], cluster_ids: list[Hashable]) -> float:
    if len(values) != len(cluster_ids):
        raise ValueError("cluster ids must align with estimator terms")
    clusters = set(cluster_ids)
    cluster_count = len(clusters)
    if cluster_count < 2:
        raise ValueError("cluster-robust standard error requires at least two clusters")
    center = _mean(values)
    cluster_influence = {cluster: 0.0 for cluster in clusters}
    for value, cluster in zip(values, cluster_ids, strict=True):
        cluster_influence[cluster] += value - center
    variance = (
        cluster_count
        / (cluster_count - 1)
        * fsum(total * total for total in cluster_influence.values())
        / (len(values) * len(values))
    )
    return sqrt(max(0.0, variance))


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


def _beta_from_terms(ips_terms: list[float], control: list[float]) -> float:
    control_variance = _sample_variance(control)
    if control_variance <= 1e-15:
        return 0.0
    return _sample_covariance(ips_terms, control) / control_variance


def estimate_beta_coefficient(records: Iterable[LoggedBanditRecord]) -> float:
    """Estimate the additive IPS control-variate coefficient on tuning data."""

    rows = list(records)
    if not rows:
        raise ValueError("at least one logged record is required")
    weights = [row.importance_weight for row in rows]
    ips_terms = [weight * row.reward for weight, row in zip(weights, rows, strict=True)]
    control = [weight - 1.0 for weight in weights]
    return _beta_from_terms(ips_terms, control)


def evaluate_policy(
    records: Iterable[LoggedBanditRecord],
    *,
    support_propensity_floor: float = 1e-3,
    switch_threshold: float | None = None,
    dr_os_lambda: float | None = None,
    beta_coefficient: float | None = None,
) -> OPEEstimate:
    """Evaluate a target policy from logged contextual-bandit feedback.

    The estimator never guesses an independence unit. Leave ``cluster_id`` empty
    for conventional i.i.d. standard errors, or provide it on every record to
    obtain cluster-robust uncertainty under a protocol-defined grouping.
    """

    if not 0 < support_propensity_floor <= 1:
        raise ValueError("support_propensity_floor must be in (0, 1]")
    if switch_threshold is not None and (
        not isfinite(switch_threshold) or switch_threshold <= 0
    ):
        raise ValueError("switch_threshold must be a positive finite value")
    if dr_os_lambda is not None and (
        not isfinite(dr_os_lambda) or dr_os_lambda <= 0
    ):
        raise ValueError("dr_os_lambda must be a positive finite value")
    if beta_coefficient is not None and not isfinite(beta_coefficient):
        raise ValueError("beta_coefficient must be finite when provided")

    rows = list(records)
    if not rows:
        raise ValueError("at least one logged record is required")

    has_cluster = [row.cluster_id is not None for row in rows]
    if any(has_cluster) and not all(has_cluster):
        raise ValueError("cluster_id must be provided for every record or none")
    cluster_ids = [row.cluster_id for row in rows if row.cluster_id is not None]
    if cluster_ids:
        if len(set(cluster_ids)) < 2:
            raise ValueError("cluster-robust standard error requires at least two clusters")
        standard_error_method: Literal["iid", "cluster"] = "cluster"
        cluster_count: int | None = len(set(cluster_ids))

        def standard_error(values: list[float]) -> float:
            return _cluster_standard_error(values, cluster_ids)
    else:
        standard_error_method = "iid"
        cluster_count = None
        standard_error = _standard_error

    weights = [row.importance_weight for row in rows]
    dm_terms = [row.target_q for row in rows]
    ips_terms = [weight * row.reward for weight, row in zip(weights, rows, strict=True)]
    dr_terms = [
        row.target_q + weight * (row.reward - row.baseline_q)
        for weight, row in zip(weights, rows, strict=True)
    ]

    if switch_threshold is None:
        switch_terms = list(dr_terms)
    else:
        switch_terms = [
            row.target_q
            + (
                weight * (row.reward - row.baseline_q)
                if weight <= switch_threshold
                else 0.0
            )
            for weight, row in zip(weights, rows, strict=True)
        ]

    if dr_os_lambda is None:
        shrunk_weights = list(weights)
    else:
        shrunk_weights = [
            dr_os_lambda * weight / (weight * weight + dr_os_lambda)
            for weight in weights
        ]
    dr_os_terms = [
        row.target_q + shrunk * (row.reward - row.baseline_q)
        for shrunk, row in zip(shrunk_weights, rows, strict=True)
    ]

    control = [weight - 1.0 for weight in weights]
    beta_star = _beta_from_terms(ips_terms, control)
    beta_used = 0.0 if beta_coefficient is None else float(beta_coefficient)
    beta_terms = [
        ips_term - beta_used * control_value
        for ips_term, control_value in zip(ips_terms, control, strict=True)
    ]

    n = len(rows)
    weight_sum = fsum(weights)
    squared_weight_sum = fsum(weight * weight for weight in weights)
    ess = (weight_sum * weight_sum / squared_weight_sum) if squared_weight_sum > 0 else 0.0

    if weight_sum > 1e-15:
        self_normalized_ips = fsum(ips_terms) / weight_sum
        mean_weight = weight_sum / n
        snips_influence = [
            weight * (row.reward - self_normalized_ips) / mean_weight
            for weight, row in zip(weights, rows, strict=True)
        ]
        snips_standard_error = standard_error(snips_influence)
    else:
        self_normalized_ips = float("nan")
        snips_standard_error = float("nan")
        mean_weight = 0.0

    weight_std = sqrt(max(0.0, _sample_variance(weights))) if n > 1 else 0.0
    weight_cv = weight_std / mean_weight if abs(mean_weight) > 1e-15 else float("inf")

    support_mask = [
        row.target_action_probability == 0.0
        or row.behavior_propensity >= support_propensity_floor
        for row in rows
    ]
    supported_records = sum(support_mask)
    supported_importance_mass = fsum(
        weight
        for weight, supported in zip(weights, support_mask, strict=True)
        if supported
    )
    support_coverage = (
        supported_importance_mass / weight_sum if weight_sum > 1e-15 else 0.0
    )

    return OPEEstimate(
        direct_method=_mean(dm_terms),
        ips=_mean(ips_terms),
        self_normalized_ips=self_normalized_ips,
        doubly_robust=_mean(dr_terms),
        switch_dr=_mean(switch_terms),
        dr_os=_mean(dr_os_terms),
        beta_ips=_mean(beta_terms),
        beta_coefficient=beta_coefficient,
        beta_star=beta_star,
        dm_standard_error=standard_error(dm_terms),
        ips_standard_error=standard_error(ips_terms),
        snips_standard_error=snips_standard_error,
        dr_standard_error=standard_error(dr_terms),
        switch_dr_standard_error=standard_error(switch_terms),
        dr_os_standard_error=standard_error(dr_os_terms),
        beta_ips_standard_error=standard_error(beta_terms),
        standard_error_method=standard_error_method,
        cluster_count=cluster_count,
        switch_threshold=switch_threshold,
        dr_os_lambda=dr_os_lambda,
        effective_sample_size=ess,
        effective_sample_ratio=ess / n,
        support_coverage=max(0.0, min(1.0, support_coverage)),
        record_support_coverage=supported_records / n,
        max_importance_weight=max(weights),
        mean_importance_weight=mean_weight,
        importance_weight_normalization_error=abs(mean_weight - 1.0),
        weight_coefficient_of_variation=weight_cv,
        sample_size=n,
    )


def policy_evidence_from_ope(
    estimate: OPEEstimate,
    *,
    baseline_value: float,
    roi: float,
    spend: float,
    fatigue: float,
    churn_risk: float,
    estimator: Literal[
        "direct_method",
        "ips",
        "self_normalized_ips",
        "doubly_robust",
        "switch_dr",
        "dr_os",
        "beta_ips",
    ] = "doubly_robust",
) -> PolicyEvidence:
    """Compile OPE output into the verifier's evidence contract."""

    if estimator == "direct_method":
        value = estimate.direct_method
        standard_error = estimate.dm_standard_error
    elif estimator == "ips":
        value = estimate.ips
        standard_error = estimate.ips_standard_error
    elif estimator == "self_normalized_ips":
        value = estimate.self_normalized_ips
        standard_error = estimate.snips_standard_error
    elif estimator == "doubly_robust":
        value = estimate.doubly_robust
        standard_error = estimate.dr_standard_error
    elif estimator == "switch_dr":
        value = estimate.switch_dr
        standard_error = estimate.switch_dr_standard_error
    elif estimator == "dr_os":
        value = estimate.dr_os
        standard_error = estimate.dr_os_standard_error
    elif estimator == "beta_ips":
        value = estimate.beta_ips
        standard_error = estimate.beta_ips_standard_error
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
