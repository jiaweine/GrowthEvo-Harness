from __future__ import annotations

"""Validation-only development comparator for cross-fitted DR control variates.

This script is intentionally not part of the locked OPE estimator registry.  It
compares ordinary doubly robust OPE against a cross-fitted additive control
variate of the form ``DR - beta * (w - 1)`` on a development/validation cohort.
The coefficient for each held-out fold is estimated only from the other folds.

The construction relies on the usual importance-weight normalization identity
E[w] = 1.  It must therefore be treated as a development candidate until overlap,
propensity provenance, and independent benchmark validation support promotion.
"""

import argparse
from dataclasses import dataclass
from hashlib import blake2b
import json
from math import fsum, isfinite, sqrt
from pathlib import Path
from typing import Any, Hashable, Iterable, Sequence

from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


@dataclass(frozen=True, slots=True)
class BetaDRDevelopmentResult:
    sample_size: int
    beta_folds: int
    fold_betas: tuple[float, ...]
    reference_value: float
    dr_estimate: float
    dr_absolute_error: float
    dr_standard_error: float
    beta_dr_estimate: float
    beta_dr_absolute_error: float
    beta_dr_standard_error: float
    absolute_error_change: float
    standard_error_change: float
    mean_importance_weight: float
    importance_weight_normalization_error: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "growthevo.beta-dr-development.v1",
            "sample_size": self.sample_size,
            "beta_folds": self.beta_folds,
            "fold_betas": list(self.fold_betas),
            "reference_value": self.reference_value,
            "dr_estimate": self.dr_estimate,
            "dr_absolute_error": self.dr_absolute_error,
            "dr_standard_error": self.dr_standard_error,
            "beta_dr_estimate": self.beta_dr_estimate,
            "beta_dr_absolute_error": self.beta_dr_absolute_error,
            "beta_dr_standard_error": self.beta_dr_standard_error,
            "absolute_error_change": self.absolute_error_change,
            "standard_error_change": self.standard_error_change,
            "mean_importance_weight": self.mean_importance_weight,
            "importance_weight_normalization_error": self.importance_weight_normalization_error,
        }


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot take the mean of an empty sequence")
    return fsum(values) / len(values)


def _sample_covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("covariance inputs must align")
    if len(left) <= 1:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    return fsum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    ) / (len(left) - 1)


def _beta(base_terms: Sequence[float], control: Sequence[float]) -> float:
    variance = _sample_covariance(control, control)
    if variance <= 1e-15:
        return 0.0
    return _sample_covariance(base_terms, control) / variance


def _iid_standard_error(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    center = _mean(values)
    variance = fsum((value - center) ** 2 for value in values) / (len(values) - 1)
    return sqrt(max(0.0, variance) / len(values))


def _cluster_standard_error(values: Sequence[float], clusters: Sequence[Hashable]) -> float:
    if len(values) != len(clusters):
        raise ValueError("cluster ids must align with estimator terms")
    unique = set(clusters)
    if len(unique) < 2:
        raise ValueError("cluster-robust standard error requires at least two clusters")
    center = _mean(values)
    influence = {cluster: 0.0 for cluster in unique}
    for value, cluster in zip(values, clusters, strict=True):
        influence[cluster] += value - center
    variance = (
        len(unique)
        / (len(unique) - 1)
        * fsum(total * total for total in influence.values())
        / (len(values) * len(values))
    )
    return sqrt(max(0.0, variance))


def _identity_bytes(value: Any) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return encoded.encode("utf-8")


def _fold_assignments(rows: Sequence[LoggedBanditRecord], folds: int) -> tuple[list[int], int]:
    if folds < 2:
        raise ValueError("beta_folds must be at least 2")
    if len(rows) < 2:
        return [0 for _ in rows], 1

    has_cluster = [row.cluster_id is not None for row in rows]
    if any(has_cluster) and not all(has_cluster):
        raise ValueError("cluster_id must be provided for every record or none")

    if all(has_cluster):
        group_for_row = [row.cluster_id for row in rows]
    else:
        if any(row.record_id is None for row in rows):
            raise ValueError("record_id is required when cluster_id is absent")
        group_for_row = [row.record_id for row in rows]

    unique_groups = list(dict.fromkeys(group_for_row))
    actual_folds = min(folds, len(unique_groups))
    if actual_folds < 2:
        return [0 for _ in rows], 1

    keyed_groups = sorted(
        unique_groups,
        key=lambda group: blake2b(_identity_bytes(group), digest_size=16).digest(),
    )
    group_fold = {
        group: index % actual_folds
        for index, group in enumerate(keyed_groups)
    }
    return [group_fold[group] for group in group_for_row], actual_folds


def cross_fitted_beta_dr_terms(
    rows: Sequence[LoggedBanditRecord],
    *,
    beta_folds: int = 5,
) -> tuple[list[float], tuple[float, ...], int]:
    if not rows:
        raise ValueError("at least one logged record is required")
    weights = [row.importance_weight for row in rows]
    dr_terms = [
        row.target_q + weight * (row.reward - row.baseline_q)
        for row, weight in zip(rows, weights, strict=True)
    ]
    control = [weight - 1.0 for weight in weights]
    assignments, actual_folds = _fold_assignments(rows, beta_folds)
    if actual_folds == 1:
        return list(dr_terms), (0.0,), 1

    result = [0.0 for _ in rows]
    fold_betas: list[float] = []
    for fold in range(actual_folds):
        train_indices = [index for index, assigned in enumerate(assignments) if assigned != fold]
        held_indices = [index for index, assigned in enumerate(assignments) if assigned == fold]
        coefficient = _beta(
            [dr_terms[index] for index in train_indices],
            [control[index] for index in train_indices],
        )
        fold_betas.append(coefficient)
        for index in held_indices:
            result[index] = dr_terms[index] - coefficient * control[index]
    return result, tuple(fold_betas), actual_folds


def compare_beta_dr(
    rows: Sequence[LoggedBanditRecord],
    *,
    reference_value: float,
    beta_folds: int = 5,
) -> BetaDRDevelopmentResult:
    if not rows:
        raise ValueError("at least one logged record is required")
    if not isfinite(reference_value):
        raise ValueError("reference_value must be finite")

    baseline = evaluate_policy(rows, beta_folds=max(2, beta_folds))
    beta_dr_terms, fold_betas, actual_folds = cross_fitted_beta_dr_terms(
        rows,
        beta_folds=beta_folds,
    )
    beta_dr_estimate = _mean(beta_dr_terms)

    clusters = [row.cluster_id for row in rows if row.cluster_id is not None]
    if clusters:
        beta_dr_se = _cluster_standard_error(beta_dr_terms, clusters)
    else:
        beta_dr_se = _iid_standard_error(beta_dr_terms)

    dr_error = abs(baseline.doubly_robust - reference_value)
    beta_dr_error = abs(beta_dr_estimate - reference_value)
    return BetaDRDevelopmentResult(
        sample_size=len(rows),
        beta_folds=actual_folds,
        fold_betas=fold_betas,
        reference_value=float(reference_value),
        dr_estimate=baseline.doubly_robust,
        dr_absolute_error=dr_error,
        dr_standard_error=baseline.dr_standard_error,
        beta_dr_estimate=beta_dr_estimate,
        beta_dr_absolute_error=beta_dr_error,
        beta_dr_standard_error=beta_dr_se,
        absolute_error_change=beta_dr_error - dr_error,
        standard_error_change=beta_dr_se - baseline.dr_standard_error,
        mean_importance_weight=baseline.mean_importance_weight,
        importance_weight_normalization_error=baseline.importance_weight_normalization_error,
    )


def _record(payload: dict[str, Any], *, source: str) -> LoggedBanditRecord:
    try:
        record_id = payload["record_id"]
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("record_id must be a non-empty string")
        cluster_id = payload.get("cluster_id")
        if isinstance(cluster_id, list):
            cluster_id = tuple(cluster_id)
        return LoggedBanditRecord(
            reward=float(payload["reward"]),
            behavior_propensity=float(payload["behavior_propensity"]),
            target_action_probability=float(payload["target_action_probability"]),
            baseline_q=float(payload["baseline_q"]),
            target_q=float(payload["target_q"]),
            cluster_id=cluster_id,
            record_id=record_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid OPE record at {source}: {exc}") from exc


def load_jsonl(path: str | Path) -> tuple[LoggedBanditRecord, ...]:
    resolved = Path(path)
    rows: list[LoggedBanditRecord] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {resolved}:{line_number}")
            rows.append(_record(payload, source=f"{resolved}:{line_number}"))
    if not rows:
        raise ValueError(f"{resolved} produced no OPE records")
    return tuple(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare ordinary DR against cross-fitted DR + (w-1) control variate on validation only."
    )
    parser.add_argument("--validation-jsonl", required=True)
    parser.add_argument("--reference", required=True, type=float)
    parser.add_argument("--beta-folds", default=5, type=int)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = compare_beta_dr(
        load_jsonl(args.validation_jsonl),
        reference_value=args.reference,
        beta_folds=args.beta_folds,
    )
    payload = result.to_dict()
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
