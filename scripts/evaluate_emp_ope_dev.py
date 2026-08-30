from __future__ import annotations

"""Validation-only EMP OPE comparator following Kallus & Uehara (NeurIPS 2019).

The original contextual-bandit implementation uses empirical likelihood with
moment controls ``w - 1`` and ``q_pi - w q_a`` (and a second Q-model control in
their experiments). GrowthEvo's compact locked evidence stores one cross-fitted
Q model, so this development script evaluates the faithful one-Q specialization:

    d_i(beta) = 1 + beta_0 (w_i - 1) + beta_1 (q_pi_i - w_i q_a_i)
    V_EMP = sum_i w_i r_i / d_i / sum_i 1 / d_i

Beta maximizes the empirical mean of log d_i over the positive-denominator
domain. This script is deliberately not part of the locked estimator registry;
it exists only to decide whether a separate, preregistered core integration is
worth pursuing.
"""

import argparse
from dataclasses import dataclass
import json
from math import fsum, isfinite, log
from pathlib import Path
from typing import Any, Iterable, Sequence

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
class EMPDevelopmentResult:
    sample_size: int
    reference_value: float
    beta: tuple[float, float]
    iterations: int
    converged: bool
    objective: float
    min_denominator: float
    weight_moment_residual: float
    q_moment_residual: float
    estimate: float
    absolute_error: float
    reward_min: float
    reward_max: float
    best_existing_candidate: str
    best_existing_absolute_error: float
    absolute_error_change_vs_best: float
    existing_candidates: dict[str, CandidateSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "growthevo.emp-ope-development.v1",
            "sample_size": self.sample_size,
            "reference_value": self.reference_value,
            "beta": list(self.beta),
            "iterations": self.iterations,
            "converged": self.converged,
            "objective": self.objective,
            "min_denominator": self.min_denominator,
            "weight_moment_residual": self.weight_moment_residual,
            "q_moment_residual": self.q_moment_residual,
            "estimate": self.estimate,
            "absolute_error": self.absolute_error,
            "reward_min": self.reward_min,
            "reward_max": self.reward_max,
            "best_existing_candidate": self.best_existing_candidate,
            "best_existing_absolute_error": self.best_existing_absolute_error,
            "absolute_error_change_vs_best": self.absolute_error_change_vs_best,
            "existing_candidates": {
                name: summary.to_dict()
                for name, summary in sorted(self.existing_candidates.items())
            },
        }


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot take the mean of an empty sequence")
    return fsum(values) / len(values)


def _controls(row: LoggedBanditRecord) -> tuple[float, float]:
    weight = row.importance_weight
    return weight - 1.0, row.target_q - weight * row.baseline_q


def _objective_stats(
    controls: Sequence[tuple[float, float]],
    beta: tuple[float, float],
    *,
    min_denominator: float,
) -> tuple[float, tuple[float, float], tuple[tuple[float, float], tuple[float, float]], list[float]] | None:
    denominators = [
        1.0 + beta[0] * control[0] + beta[1] * control[1]
        for control in controls
    ]
    if min(denominators) <= min_denominator:
        return None
    n = len(controls)
    objective = fsum(log(value) for value in denominators) / n
    gradient = (
        fsum(control[0] / denominator for control, denominator in zip(controls, denominators, strict=True)) / n,
        fsum(control[1] / denominator for control, denominator in zip(controls, denominators, strict=True)) / n,
    )
    a00 = fsum(
        control[0] * control[0] / (denominator * denominator)
        for control, denominator in zip(controls, denominators, strict=True)
    ) / n
    a01 = fsum(
        control[0] * control[1] / (denominator * denominator)
        for control, denominator in zip(controls, denominators, strict=True)
    ) / n
    a11 = fsum(
        control[1] * control[1] / (denominator * denominator)
        for control, denominator in zip(controls, denominators, strict=True)
    ) / n
    information = ((a00, a01), (a01, a11))
    return objective, gradient, information, denominators


def solve_emp_beta(
    controls: Sequence[tuple[float, float]],
    *,
    max_iterations: int = 200,
    tolerance: float = 1e-10,
    min_denominator: float = 1e-10,
) -> tuple[tuple[float, float], int, bool, float, list[float], tuple[float, float]]:
    if not controls:
        raise ValueError("at least one empirical-likelihood control is required")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be positive and finite")
    if not isfinite(min_denominator) or min_denominator <= 0:
        raise ValueError("min_denominator must be positive and finite")

    beta = (0.0, 0.0)
    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        stats = _objective_stats(controls, beta, min_denominator=min_denominator)
        if stats is None:  # pragma: no cover - beta=0 starts strictly feasible.
            raise RuntimeError("EMP optimizer left the feasible domain")
        objective, gradient, information, _ = stats
        if max(abs(gradient[0]), abs(gradient[1])) <= tolerance:
            converged = True
            break

        trace = information[0][0] + information[1][1]
        ridge = max(1e-15, abs(trace) * 1e-12)
        a00 = information[0][0] + ridge
        a01 = information[0][1]
        a11 = information[1][1] + ridge
        determinant = a00 * a11 - a01 * a01
        if determinant <= 1e-30:
            break
        step = (
            (gradient[0] * a11 - gradient[1] * a01) / determinant,
            (a00 * gradient[1] - a01 * gradient[0]) / determinant,
        )
        directional_derivative = gradient[0] * step[0] + gradient[1] * step[1]
        scale = 1.0
        accepted = False
        for _ in range(64):
            candidate = (beta[0] + scale * step[0], beta[1] + scale * step[1])
            candidate_stats = _objective_stats(
                controls,
                candidate,
                min_denominator=min_denominator,
            )
            if candidate_stats is not None and candidate_stats[0] >= (
                objective + 1e-4 * scale * directional_derivative
            ):
                beta = candidate
                accepted = True
                break
            scale *= 0.5
        if not accepted:
            break

    final_stats = _objective_stats(controls, beta, min_denominator=min_denominator)
    if final_stats is None:  # pragma: no cover - guarded by line search.
        raise RuntimeError("EMP optimizer produced an infeasible solution")
    objective, gradient, _, denominators = final_stats
    if max(abs(gradient[0]), abs(gradient[1])) <= tolerance:
        converged = True
    return beta, iterations, converged, objective, denominators, gradient


def empirical_likelihood_estimate(
    rows: Sequence[LoggedBanditRecord],
) -> tuple[float, tuple[float, float], int, bool, float, float, tuple[float, float]]:
    if not rows:
        raise ValueError("at least one logged record is required")
    controls = [_controls(row) for row in rows]
    beta, iterations, converged, objective, denominators, gradient = solve_emp_beta(controls)
    inverse_denominators = [1.0 / denominator for denominator in denominators]
    denominator_sum = fsum(inverse_denominators)
    if denominator_sum <= 0:
        raise RuntimeError("EMP normalization mass must be positive")
    numerator = fsum(
        row.importance_weight * row.reward * inverse
        for row, inverse in zip(rows, inverse_denominators, strict=True)
    )
    estimate = numerator / denominator_sum
    return (
        estimate,
        beta,
        iterations,
        converged,
        objective,
        min(denominators),
        gradient,
    )


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


def compare_emp(
    rows: Sequence[LoggedBanditRecord],
    *,
    reference_value: float,
) -> EMPDevelopmentResult:
    if not rows:
        raise ValueError("at least one logged record is required")
    if not isfinite(reference_value):
        raise ValueError("reference_value must be finite")
    estimate, beta, iterations, converged, objective, min_denom, gradient = empirical_likelihood_estimate(rows)
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
    rewards = [row.reward for row in rows]
    return EMPDevelopmentResult(
        sample_size=len(rows),
        reference_value=float(reference_value),
        beta=beta,
        iterations=iterations,
        converged=converged,
        objective=objective,
        min_denominator=min_denom,
        weight_moment_residual=gradient[0],
        q_moment_residual=gradient[1],
        estimate=estimate,
        absolute_error=absolute_error,
        reward_min=min(rewards),
        reward_max=max(rewards),
        best_existing_candidate=best_name,
        best_existing_absolute_error=best_summary.absolute_error,
        absolute_error_change_vs_best=absolute_error - best_summary.absolute_error,
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
        description="Compare the one-Q EMP estimator against the current OPE validation grid."
    )
    parser.add_argument("--validation-jsonl", required=True)
    parser.add_argument("--reference", required=True, type=float)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = compare_emp(load_jsonl(args.validation_jsonl), reference_value=args.reference)
    payload = result.to_dict()
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
