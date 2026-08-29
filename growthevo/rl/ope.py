from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
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
    record_id: str | None = None

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
        if self.record_id is not None and not self.record_id:
            raise ValueError("record_id cannot be empty when provided")

    @property
    def importance_weight(self) -> float:
        return self.target_action_probability / self.behavior_propensity


@dataclass(frozen=True, slots=True)
class OPEEstimate:
    """Counterfactual policy-value estimates plus overlap diagnostics.

    ``beta_ips`` is the frontier additive-control-variate estimator. By default
    its variance-minimising baseline is cross-fitted: each evaluation fold uses a
    beta coefficient estimated without that fold. This removes the O(1/n)
    same-sample bias discussed in the SIGIR 2026 beta*-IPS analysis while keeping
    the lower asymptotic variance of optimal additive correction over SNIPS.

    ``beta_ips_same_sample`` and ``beta_star`` remain diagnostics so experiments
    can reproduce the lower-variance-but-finitely-biased plug-in estimator.

    SWITCH-DR and optimistic DR shrinkage are retained as stress estimators for
    extreme importance weights. Their tuning parameters belong on validation
    data, never the final evaluation split.

    ``meta_blue`` follows the RecSys 2025 Meta-OPE fixed-effects construction
    using complementary beta-IPS, SNIPS, and DR inputs. SNIPS contributes its
    Delta-method influence rather than being treated as an ordinary sample mean,
    and cluster-aware experiments use the same cluster covariance when deriving
    BLUE weights. The resulting uncertainty remains asymptotic, especially when
    nuisance models or ratio estimators dominate finite-sample behaviour.
    """

    direct_method: float
    ips: float
    self_normalized_ips: float
    doubly_robust: float
    switch_dr: float
    dr_os: float
    beta_ips: float
    beta_ips_same_sample: float
    beta_star: float
    beta_mode: Literal["cross_fit", "fixed"]
    beta_crossfit_folds: int
    beta_coefficient: float | None
    meta_blue: float
    meta_blue_weights: tuple[tuple[str, float], ...]
    dm_standard_error: float
    ips_standard_error: float
    snips_standard_error: float
    dr_standard_error: float
    switch_dr_standard_error: float
    dr_os_standard_error: float
    beta_ips_standard_error: float
    beta_ips_same_sample_standard_error: float
    meta_blue_standard_error: float
    standard_error_method: Literal["iid", "cluster"]
    cluster_count: int | None
    switch_threshold: float | None
    dr_os_lambda: float | None
    effective_sample_size: float
    effective_sample_ratio: float
    support_coverage: float
    max_importance_weight: float
    weight_coefficient_of_variation: float
    sample_size: int
    record_support_coverage: float = 1.0
    mean_importance_weight: float = 1.0
    importance_weight_normalization_error: float = 0.0


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
    variance = _sample_variance(control)
    if variance <= 1e-15:
        return 0.0
    return _sample_covariance(ips_terms, control) / variance


def estimate_beta_coefficient(records: Iterable[LoggedBanditRecord]) -> float:
    """Estimate beta* on a tuning cohort for a fixed-baseline evaluation run."""

    rows = list(records)
    if not rows:
        raise ValueError("at least one logged record is required")
    weights = [row.importance_weight for row in rows]
    ips_terms = [weight * row.reward for weight, row in zip(weights, rows, strict=True)]
    control = [weight - 1.0 for weight in weights]
    return _beta_from_terms(ips_terms, control)


def _stable_fold_assignments(rows: list[LoggedBanditRecord], folds: int) -> list[int]:
    if folds < 2:
        raise ValueError("beta_folds must be at least 2")
    actual_folds = min(folds, len(rows))
    if actual_folds < 2:
        return [0 for _ in rows]

    has_id = [row.record_id is not None for row in rows]
    if any(has_id) and not all(has_id):
        raise ValueError("record_id must be provided for every record or none")

    keyed: list[tuple[bytes, int]] = []
    for index, row in enumerate(rows):
        identity = row.record_id if row.record_id is not None else f"input-index:{index}"
        keyed.append((blake2b(identity.encode("utf-8"), digest_size=16).digest(), index))
    keyed.sort()

    assignments = [0 for _ in rows]
    for position, (_, index) in enumerate(keyed):
        assignments[index] = position % actual_folds
    return assignments


def _cross_fitted_beta_terms(
    rows: list[LoggedBanditRecord],
    ips_terms: list[float],
    control: list[float],
    *,
    beta_folds: int,
) -> tuple[list[float], int]:
    if len(rows) < 2:
        return list(ips_terms), 1

    assignments = _stable_fold_assignments(rows, beta_folds)
    actual_folds = max(assignments) + 1
    result = [0.0 for _ in rows]
    for fold in range(actual_folds):
        train_indices = [index for index, assigned in enumerate(assignments) if assigned != fold]
        held_indices = [index for index, assigned in enumerate(assignments) if assigned == fold]
        train_ips = [ips_terms[index] for index in train_indices]
        train_control = [control[index] for index in train_indices]
        beta = _beta_from_terms(train_ips, train_control)
        for index in held_indices:
            result[index] = ips_terms[index] - beta * control[index]
    return result, actual_folds


def _solve_linear_system(matrix: list[list[float]], target: list[float]) -> list[float]:
    n = len(target)
    augmented = [list(row) + [float(rhs)] for row, rhs in zip(matrix, target, strict=True)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-18:
            raise ValueError("meta-OPE covariance matrix is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(n)]


def _covariance_of_means(
    named_influences: tuple[tuple[str, list[float]], ...],
    *,
    cluster_ids: list[Hashable] | None,
) -> list[list[float]]:
    if not named_influences:
        raise ValueError("meta-OPE requires at least one input estimator")
    n = len(named_influences[0][1])
    if n == 0:
        raise ValueError("meta-OPE influence arrays cannot be empty")
    if any(len(values) != n for _, values in named_influences):
        raise ValueError("meta-OPE influence arrays must be aligned")

    width = len(named_influences)
    covariance = [[0.0 for _ in range(width)] for _ in range(width)]
    if cluster_ids is None:
        for left in range(width):
            for right in range(width):
                covariance[left][right] = _sample_covariance(
                    named_influences[left][1], named_influences[right][1]
                ) / n
        return covariance

    if len(cluster_ids) != n:
        raise ValueError("cluster ids must align with meta-OPE influences")
    clusters = set(cluster_ids)
    cluster_count = len(clusters)
    if cluster_count < 2:
        raise ValueError("cluster-aware meta-OPE requires at least two clusters")

    centers = [_mean(values) for _, values in named_influences]
    cluster_sums = {
        cluster: [0.0 for _ in range(width)]
        for cluster in clusters
    }
    for row, cluster in enumerate(cluster_ids):
        for column in range(width):
            cluster_sums[cluster][column] += (
                named_influences[column][1][row] - centers[column]
            )

    factor = cluster_count / (cluster_count - 1) / (n * n)
    for left in range(width):
        for right in range(width):
            covariance[left][right] = factor * fsum(
                totals[left] * totals[right]
                for totals in cluster_sums.values()
            )
    return covariance


def _blue_weights(covariance: list[list[float]]) -> list[float]:
    width = len(covariance)
    if width == 0 or any(len(row) != width for row in covariance):
        raise ValueError("meta-OPE covariance matrix must be non-empty and square")

    regularized = [list(row) for row in covariance]
    trace = fsum(regularized[index][index] for index in range(width))
    ridge = max(1e-15, abs(trace) * 1e-12)
    for index in range(width):
        regularized[index][index] += ridge

    try:
        inverse_times_one = _solve_linear_system(regularized, [1.0] * width)
        denominator = fsum(inverse_times_one)
        if abs(denominator) <= 1e-15:
            raise ValueError("degenerate BLUE normalization")
        return [value / denominator for value in inverse_times_one]
    except ValueError:
        return [1.0 / width for _ in range(width)]


def _meta_blue(
    named_estimators: tuple[tuple[str, float, list[float]], ...],
    *,
    cluster_ids: list[Hashable] | None,
) -> tuple[float, tuple[tuple[str, float], ...], list[float]]:
    if not named_estimators:
        raise ValueError("meta-OPE requires at least one input estimator")
    n = len(named_estimators[0][2])
    if n == 0:
        raise ValueError("meta-OPE influence arrays cannot be empty")
    if any(len(influence) != n for _, _, influence in named_estimators):
        raise ValueError("meta-OPE influence arrays must be aligned")

    named_influences = tuple(
        (name, influence)
        for name, _, influence in named_estimators
    )
    covariance = _covariance_of_means(
        named_influences,
        cluster_ids=cluster_ids,
    )
    weights = _blue_weights(covariance)
    value = fsum(
        weights[index] * named_estimators[index][1]
        for index in range(len(named_estimators))
    )
    combined_influence = [
        fsum(
            weights[column] * named_estimators[column][2][row]
            for column in range(len(named_estimators))
        )
        for row in range(n)
    ]
    return (
        value,
        tuple(
            (named_estimators[index][0], weights[index])
            for index in range(len(named_estimators))
        ),
        combined_influence,
    )


def evaluate_policy(
    records: Iterable[LoggedBanditRecord],
    *,
    support_propensity_floor: float = 1e-3,
    switch_threshold: float | None = None,
    dr_os_lambda: float | None = None,
    beta_coefficient: float | None = None,
    beta_folds: int = 5,
) -> OPEEstimate:
    """Evaluate a target policy from logged contextual-bandit feedback.

    The default flagship estimator is cross-fitted beta*-IPS. Plain IPS, DR,
    SNIPS, SWITCH-DR, DR-OS and RecSys-style correlated BLUE Meta-OPE are
    returned together so estimator disagreement remains visible.
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
    if beta_folds < 2:
        raise ValueError("beta_folds must be at least 2")

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
            + (weight * (row.reward - row.baseline_q) if weight <= switch_threshold else 0.0)
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
    beta_same_sample_terms = [
        ips_term - beta_star * control_value
        for ips_term, control_value in zip(ips_terms, control, strict=True)
    ]

    if beta_coefficient is None:
        beta_terms, actual_beta_folds = _cross_fitted_beta_terms(
            rows,
            ips_terms,
            control,
            beta_folds=beta_folds,
        )
        beta_mode: Literal["cross_fit", "fixed"] = "cross_fit"
        beta_used: float | None = None
    else:
        beta_terms = [
            ips_term - beta_coefficient * control_value
            for ips_term, control_value in zip(ips_terms, control, strict=True)
        ]
        actual_beta_folds = 0
        beta_mode = "fixed"
        beta_used = float(beta_coefficient)

    n = len(rows)
    weight_sum = fsum(weights)
    squared_weight_sum = fsum(weight * weight for weight in weights)
    ess = (weight_sum * weight_sum / squared_weight_sum) if squared_weight_sum > 0 else 0.0

    mean_weight = weight_sum / n
    if weight_sum > 1e-15 and abs(mean_weight) > 1e-15:
        snips = fsum(ips_terms) / weight_sum
        snips_influence = [
            weight * (row.reward - snips) / mean_weight
            for weight, row in zip(weights, rows, strict=True)
        ]
        snips_standard_error = standard_error(snips_influence)
    else:
        snips = float("nan")
        snips_influence = []
        snips_standard_error = float("nan")

    weight_std = sqrt(max(0.0, _sample_variance(weights))) if n > 1 else 0.0
    weight_cv = weight_std / mean_weight if abs(mean_weight) > 1e-15 else float("inf")

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

    beta_value = _mean(beta_terms)
    dr_value = _mean(dr_terms)
    meta_inputs: list[tuple[str, float, list[float]]] = [
        (
            "beta_ips",
            beta_value,
            [value - beta_value for value in beta_terms],
        )
    ]
    if isfinite(snips):
        meta_inputs.append(
            ("self_normalized_ips", snips, snips_influence)
        )
    meta_inputs.append(
        (
            "doubly_robust",
            dr_value,
            [value - dr_value for value in dr_terms],
        )
    )
    meta_value, meta_weights, meta_influence = _meta_blue(
        tuple(meta_inputs),
        cluster_ids=cluster_ids if cluster_ids else None,
    )

    return OPEEstimate(
        direct_method=_mean(dm_terms),
        ips=_mean(ips_terms),
        self_normalized_ips=snips,
        doubly_robust=dr_value,
        switch_dr=_mean(switch_terms),
        dr_os=_mean(dr_os_terms),
        beta_ips=beta_value,
        beta_ips_same_sample=_mean(beta_same_sample_terms),
        beta_star=beta_star,
        beta_mode=beta_mode,
        beta_crossfit_folds=actual_beta_folds,
        beta_coefficient=beta_used,
        meta_blue=meta_value,
        meta_blue_weights=meta_weights,
        dm_standard_error=standard_error(dm_terms),
        ips_standard_error=standard_error(ips_terms),
        snips_standard_error=snips_standard_error,
        dr_standard_error=standard_error(dr_terms),
        switch_dr_standard_error=standard_error(switch_terms),
        dr_os_standard_error=standard_error(dr_os_terms),
        beta_ips_standard_error=standard_error(beta_terms),
        beta_ips_same_sample_standard_error=standard_error(beta_same_sample_terms),
        meta_blue_standard_error=standard_error(meta_influence),
        standard_error_method=standard_error_method,
        cluster_count=cluster_count,
        switch_threshold=switch_threshold,
        dr_os_lambda=dr_os_lambda,
        effective_sample_size=ess,
        effective_sample_ratio=ess / n,
        support_coverage=max(0.0, min(1.0, target_mass_support_coverage)),
        max_importance_weight=max(weights),
        weight_coefficient_of_variation=weight_cv,
        sample_size=n,
        record_support_coverage=supported_records / n,
        mean_importance_weight=mean_weight,
        importance_weight_normalization_error=abs(mean_weight - 1.0),
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
        "meta_blue",
        "beta_ips",
        "doubly_robust",
        "switch_dr",
        "dr_os",
        "self_normalized_ips",
        "ips",
        "direct_method",
    ] = "beta_ips",
) -> PolicyEvidence:
    """Compile OPE output into the verifier's evidence contract.

    Cross-fitted beta*-IPS is the default. ``meta_blue`` remains opt-in because
    its covariance combination and SNIPS component rely on asymptotic inference;
    locked validation should establish its finite-sample suitability before use.
    """

    if estimator == "meta_blue":
        value = estimate.meta_blue
        standard_error = estimate.meta_blue_standard_error
    elif estimator == "beta_ips":
        value = estimate.beta_ips
        standard_error = estimate.beta_ips_standard_error
    elif estimator == "doubly_robust":
        value = estimate.doubly_robust
        standard_error = estimate.dr_standard_error
    elif estimator == "switch_dr":
        value = estimate.switch_dr
        standard_error = estimate.switch_dr_standard_error
    elif estimator == "dr_os":
        value = estimate.dr_os
        standard_error = estimate.dr_os_standard_error
    elif estimator == "self_normalized_ips":
        value = estimate.self_normalized_ips
        standard_error = estimate.snips_standard_error
    elif estimator == "ips":
        value = estimate.ips
        standard_error = estimate.ips_standard_error
    elif estimator == "direct_method":
        value = estimate.direct_method
        standard_error = estimate.dm_standard_error
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
