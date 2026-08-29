from __future__ import annotations

from dataclasses import dataclass
from math import fsum, sqrt
import random
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
