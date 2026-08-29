from __future__ import annotations

from dataclasses import dataclass
from math import fsum, sqrt
import random
from statistics import NormalDist
from typing import Iterable

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel

from .real_world import RandomizedTargetingResult, evaluate_randomized_targeting


@dataclass(frozen=True, slots=True)
class TargetingBootstrapResult:
    point: RandomizedTargetingResult
    confidence_level: float
    lower_incremental_value: float
    upper_incremental_value: float
    bootstrap_standard_error: float
    replicates: int


@dataclass(frozen=True, slots=True)
class TargetingInferenceResult:
    """Analytic uncertainty for a frozen randomized targeting policy.

    The score vector and its induced top-k treatment set are treated as fixed.
    This is therefore suitable for the final holdout *after* a candidate has been
    selected and frozen.  It is not an uncertainty estimate for model-selection
    search itself.

    The standard error is the usual sample standard error of the Horvitz-Thompson
    policy-minus-treat-none influence terms.  When propensities were estimated on
    an independent training split, the interval is conditional on those frozen
    propensity values; it does not add propensity-estimation uncertainty.
    """

    point: RandomizedTargetingResult
    confidence_level: float
    standard_error: float
    lower_incremental_value: float
    upper_incremental_value: float
    selected_incremental_value: float
    selected_standard_error: float
    lower_selected_incremental_value: float
    upper_selected_incremental_value: float


def _quantile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    low = int(position)
    high = min(len(sorted_values) - 1, low + 1)
    fraction = position - low
    return sorted_values[low] * (1.0 - fraction) + sorted_values[high] * fraction


def infer_randomized_targeting(
    records: Iterable[LoggedTreatmentRecord],
    scores: Iterable[float],
    *,
    selected_fraction: float,
    treatment: Channel = Channel.ADS,
    confidence_level: float = 0.95,
) -> TargetingInferenceResult:
    """Return O(n log n) IPW inference for one already-frozen targeting score.

    Only units in the selected top-score set can make the targeting policy differ
    from treat-none.  For selected unit ``i`` the Horvitz-Thompson difference term
    is

    ``1[A_i=t] Y_i/e_t - 1[A_i=0] Y_i/e_0``.

    The population incremental value is the sample mean of these terms.  Dividing
    by the *realized* selected fraction yields the incremental outcome among the
    selected group, which is useful for top-k uplift reporting without changing
    the underlying randomized policy-value estimand.
    """

    if not 0 < selected_fraction <= 1:
        raise ValueError("selected_fraction must be in (0, 1]")
    if treatment is Channel.NO_TREATMENT:
        raise ValueError("treatment must differ from NO_TREATMENT")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")

    rows = list(records)
    rank_scores = [float(score) for score in scores]
    if not rows or len(rows) != len(rank_scores):
        raise ValueError("records and scores must be non-empty and aligned")
    if len(rows) < 2:
        raise ValueError("analytic targeting inference requires at least two rows")

    point = evaluate_randomized_targeting(
        rows,
        rank_scores,
        selected_fraction=selected_fraction,
        treatment=treatment,
    )
    ranked = sorted(range(len(rows)), key=lambda index: (-rank_scores[index], index))
    selected_count = max(1, int(round(len(rows) * selected_fraction)))
    selected = set(ranked[:selected_count])

    terms: list[float] = []
    for index, row in enumerate(rows):
        if index not in selected:
            terms.append(0.0)
            continue
        if row.action is treatment:
            propensity = row.action_propensities.get(treatment)
            if propensity is None or not 0 < propensity <= 1:
                raise ValueError("selected treated row requires a valid treatment propensity")
            terms.append(row.outcome / propensity)
        elif row.action is Channel.NO_TREATMENT:
            propensity = row.action_propensities.get(Channel.NO_TREATMENT)
            if propensity is None or not 0 < propensity <= 1:
                raise ValueError("selected control row requires a valid control propensity")
            terms.append(-row.outcome / propensity)
        else:
            # A third logged action matches neither the target treatment nor the
            # treat-none comparator and therefore contributes zero to this binary
            # policy contrast.
            terms.append(0.0)

    n = len(terms)
    mean = fsum(terms) / n
    # Keep the inference implementation pinned to the exact policy evaluator.
    if abs(mean - point.incremental_value_vs_none) > 1e-12:
        raise RuntimeError("targeting influence terms disagree with policy-value estimator")
    sample_variance = fsum((value - mean) ** 2 for value in terms) / (n - 1)
    standard_error = sqrt(max(0.0, sample_variance) / n)
    alpha = 1.0 - confidence_level
    critical_value = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    margin = critical_value * standard_error

    realized_fraction = point.selected_fraction
    selected_value = mean / realized_fraction
    selected_standard_error = standard_error / realized_fraction
    selected_margin = critical_value * selected_standard_error
    return TargetingInferenceResult(
        point=point,
        confidence_level=confidence_level,
        standard_error=standard_error,
        lower_incremental_value=mean - margin,
        upper_incremental_value=mean + margin,
        selected_incremental_value=selected_value,
        selected_standard_error=selected_standard_error,
        lower_selected_incremental_value=selected_value - selected_margin,
        upper_selected_incremental_value=selected_value + selected_margin,
    )


def bootstrap_randomized_targeting(
    records: Iterable[LoggedTreatmentRecord],
    scores: Iterable[float],
    *,
    selected_fraction: float,
    treatment: Channel = Channel.ADS,
    replicates: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 17,
) -> TargetingBootstrapResult:
    """Stratified bootstrap interval for a randomized targeting policy.

    Treatment and control observations are resampled separately so each
    replicate preserves the experimental-arm structure instead of allowing a
    small bootstrap sample to accidentally erase one arm. The number of
    replicates is an experiment-protocol choice; the implementation only requires
    the two replicates needed to define a sample variance.

    For multi-million-row final evidence, prefer :func:`infer_randomized_targeting`:
    it evaluates the already-frozen policy once instead of reranking hundreds or
    thousands of bootstrap replicates.
    """

    if replicates < 2:
        raise ValueError("replicates must be at least 2")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")

    rows = list(records)
    rank_scores = [float(score) for score in scores]
    if not rows or len(rows) != len(rank_scores):
        raise ValueError("records and scores must be non-empty and aligned")

    point = evaluate_randomized_targeting(
        rows,
        rank_scores,
        selected_fraction=selected_fraction,
        treatment=treatment,
    )
    treatment_indices = [index for index, row in enumerate(rows) if row.action is treatment]
    control_indices = [
        index for index, row in enumerate(rows) if row.action is Channel.NO_TREATMENT
    ]
    if not treatment_indices or not control_indices:
        raise ValueError("stratified bootstrap requires treatment and control observations")

    rng = random.Random(seed)
    incremental_values: list[float] = []
    for _ in range(replicates):
        sampled_indices = [
            *(rng.choice(treatment_indices) for _ in range(len(treatment_indices))),
            *(rng.choice(control_indices) for _ in range(len(control_indices))),
        ]
        sampled_rows = [rows[index] for index in sampled_indices]
        sampled_scores = [rank_scores[index] for index in sampled_indices]
        result = evaluate_randomized_targeting(
            sampled_rows,
            sampled_scores,
            selected_fraction=selected_fraction,
            treatment=treatment,
        )
        incremental_values.append(result.incremental_value_vs_none)

    center = fsum(incremental_values) / len(incremental_values)
    variance = fsum((value - center) ** 2 for value in incremental_values) / (
        len(incremental_values) - 1
    )
    sorted_values = sorted(incremental_values)
    alpha = 1.0 - confidence_level
    return TargetingBootstrapResult(
        point=point,
        confidence_level=confidence_level,
        lower_incremental_value=_quantile(sorted_values, alpha / 2.0),
        upper_incremental_value=_quantile(sorted_values, 1.0 - alpha / 2.0),
        bootstrap_standard_error=sqrt(max(0.0, variance)),
        replicates=replicates,
    )
