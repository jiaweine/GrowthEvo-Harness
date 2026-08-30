from __future__ import annotations

"""Validation-only self-normalized doubly robust (SNDR) comparator.

This development script deliberately stays outside GrowthEvo's locked estimator
registry.  It evaluates

    V_SNDR = mean(q_pi) + mean[w * (r - q_a)] / mean(w)

on a validation cohort only, and uses the Delta-method influence function for the
ratio term.  The result is compared against the current nine-candidate OPE grid;
a separate preregistered core integration is warranted only if SNDR improves the
fixed validation winner.
"""

import argparse
from dataclasses import dataclass
import json
from math import fsum, isfinite, sqrt
from pathlib import Path
from typing import Any, Hashable, Iterable, Sequence

from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    estimate: float
    absolute_error: float
    standard_error: float

    def to_dict(self) -> dict[str, float]:
        return {
            "estimate": self.estimate,
            "absolute_error": self.absolute_error,
            "standard_error": self.standard_error,
        }


@dataclass(frozen=True, slots=True)
class SNDRDevelopmentResult:
    sample_size: int
    reference_value: float
    estimate: float
    absolute_error: float
    standard_error: float
    standard_error_method: str
    cluster_count: int | None
    mean_importance_weight: float
    residual_correction: float
    influence_mean: float
    best_existing_candidate: str
    best_existing_absolute_error: float
    absolute_error_change_vs_best: float
    beats_current_best: bool
    existing_candidates: dict[str, CandidateSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "growthevo.sndr-development.v1",
            "sample_size": self.sample_size,
            "reference_value": self.reference_value,
            "estimate": self.estimate,
            "absolute_error": self.absolute_error,
            "standard_error": self.standard_error,
            "standard_error_method": self.standard_error_method,
            "cluster_count": self.cluster_count,
            "mean_importance_weight": self.mean_importance_weight,
            "residual_correction": self.residual_correction,
            "influence_mean": self.influence_mean,
            "best_existing_candidate": self.best_existing_candidate,
            "best_existing_absolute_error": self.best_existing_absolute_error,
            "absolute_error_change_vs_best": self.absolute_error_change_vs_best,
            "beats_current_best": self.beats_current_best,
            "existing_candidates": {
                name: summary.to_dict()
                for name, summary in sorted(self.existing_candidates.items())
            },
        }


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot take the mean of an empty sequence")
    return fsum(values) / len(values)


def _iid_standard_error(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    center = _mean(values)
    variance = fsum((value - center) ** 2 for value in values) / (len(values) - 1)
    return sqrt(max(0.0, variance) / len(values))


def _cluster_standard_error(
    values: Sequence[float],
    cluster_ids: Sequence[Hashable],
) -> float:
    if len(values) != len(cluster_ids):
        raise ValueError("cluster ids must align with influence values")
    clusters = set(cluster_ids)
    if len(clusters) < 2:
        raise ValueError("cluster-robust standard error requires at least two clusters")
    center = _mean(values)
    totals = {cluster: 0.0 for cluster in clusters}
    for value, cluster in zip(values, cluster_ids, strict=True):
        totals[cluster] += value - center
    variance = (
        len(clusters)
        / (len(clusters) - 1)
        * fsum(total * total for total in totals.values())
        / (len(values) * len(values))
    )
    return sqrt(max(0.0, variance))


def sndr_estimate(
    rows: Sequence[LoggedBanditRecord],
) -> tuple[float, float, float, float, str, int | None]:
    """Return SNDR estimate, SE, mean weight, residual correction and SE metadata."""

    if not rows:
        raise ValueError("at least one logged record is required")
    has_cluster = [row.cluster_id is not None for row in rows]
    if any(has_cluster) and not all(has_cluster):
        raise ValueError("cluster_id must be provided for every record or none")

    q_pi = [row.target_q for row in rows]
    weights = [row.importance_weight for row in rows]
    weighted_residuals = [
        weight * (row.reward - row.baseline_q)
        for weight, row in zip(weights, rows, strict=True)
    ]
    mean_q = _mean(q_pi)
    mean_weight = _mean(weights)
    if not isfinite(mean_weight) or mean_weight <= 1e-15:
        raise ValueError("SNDR requires positive finite mean importance weight")
    mean_residual = _mean(weighted_residuals)
    correction = mean_residual / mean_weight
    estimate = mean_q + correction

    # Delta-method influence function for Abar + Bbar/Cbar, where
    # A=q_pi, B=w(r-q_a), and C=w.
    influence = [
        (q_value - mean_q)
        + (residual - mean_residual) / mean_weight
        - (mean_residual / (mean_weight * mean_weight)) * (weight - mean_weight)
        for q_value, residual, weight in zip(q_pi, weighted_residuals, weights, strict=True)
    ]
    influence_mean = _mean(influence)
    cluster_ids = [row.cluster_id for row in rows if row.cluster_id is not None]
    if cluster_ids:
        standard_error = _cluster_standard_error(influence, cluster_ids)
        method = "cluster"
        cluster_count: int | None = len(set(cluster_ids))
    else:
        standard_error = _iid_standard_error(influence)
        method = "iid"
        cluster_count = None
    return estimate, standard_error, mean_weight, correction, influence_mean, method, cluster_count


def _summary(value: float, standard_error: float, reference_value: float) -> CandidateSummary:
    return CandidateSummary(
        estimate=float(value),
        absolute_error=abs(float(value) - reference_value),
        standard_error=float(standard_error),
    )


def existing_candidate_summaries(
    rows: Sequence[LoggedBanditRecord],
    *,
    reference_value: float,
) -> dict[str, CandidateSummary]:
    base = evaluate_policy(
        rows,
        switch_threshold=5.0,
        dr_os_lambda=1.0,
        beta_folds=5,
    )
    switch_10 = evaluate_policy(rows, switch_threshold=10.0, beta_folds=5)
    dros_10 = evaluate_policy(rows, dr_os_lambda=10.0, beta_folds=5)
    return {
        "beta-cf5": _summary(base.beta_ips, base.beta_ips_standard_error, reference_value),
        "dr": _summary(base.doubly_robust, base.dr_standard_error, reference_value),
        "ips": _summary(base.ips, base.ips_standard_error, reference_value),
        "snips": _summary(base.self_normalized_ips, base.snips_standard_error, reference_value),
        "switch-5": _summary(base.switch_dr, base.switch_dr_standard_error, reference_value),
        "switch-10": _summary(switch_10.switch_dr, switch_10.switch_dr_standard_error, reference_value),
        "dros-1": _summary(base.dr_os, base.dr_os_standard_error, reference_value),
        "dros-10": _summary(dros_10.dr_os, dros_10.dr_os_standard_error, reference_value),
        "meta-blue": _summary(base.meta_blue, base.meta_blue_standard_error, reference_value),
    }


def compare_sndr(
    rows: Sequence[LoggedBanditRecord],
    *,
    reference_value: float,
) -> SNDRDevelopmentResult:
    if not rows:
        raise ValueError("at least one logged record is required")
    if not isfinite(reference_value):
        raise ValueError("reference_value must be finite")
    estimate, standard_error, mean_weight, correction, influence_mean, method, cluster_count = sndr_estimate(rows)
    existing = existing_candidate_summaries(rows, reference_value=reference_value)
    best_name, best_summary = min(
        existing.items(),
        key=lambda item: (
            item[1].absolute_error,
            item[1].standard_error,
            item[0],
        ),
    )
    absolute_error = abs(estimate - reference_value)
    return SNDRDevelopmentResult(
        sample_size=len(rows),
        reference_value=float(reference_value),
        estimate=estimate,
        absolute_error=absolute_error,
        standard_error=standard_error,
        standard_error_method=method,
        cluster_count=cluster_count,
        mean_importance_weight=mean_weight,
        residual_correction=correction,
        influence_mean=influence_mean,
        best_existing_candidate=best_name,
        best_existing_absolute_error=best_summary.absolute_error,
        absolute_error_change_vs_best=absolute_error - best_summary.absolute_error,
        beats_current_best=absolute_error < best_summary.absolute_error,
        existing_candidates=existing,
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
        description="Compare SNDR against the current OPE validation grid."
    )
    parser.add_argument("--validation-jsonl", required=True)
    parser.add_argument("--reference", required=True, type=float)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = compare_sndr(load_jsonl(args.validation_jsonl), reference_value=args.reference)
    payload = result.to_dict()
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
