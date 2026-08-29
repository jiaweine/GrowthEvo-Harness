from __future__ import annotations

import argparse
from dataclasses import asdict
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

from growthevo.rl.ope import LoggedBanditRecord

from .locked_evaluation import LockedOPEProtocol, OPECandidate


_ALLOWED_ESTIMATORS = {
    "direct_method",
    "ips",
    "self_normalized_ips",
    "doubly_robust",
    "switch_dr",
    "dr_os",
    "beta_ips",
    "meta_blue",
}


def _json_cluster_identity(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return tuple(_json_cluster_identity(item) for item in value)
    raise ValueError("cluster_id must be a JSON scalar or nested array of scalars")


def _load_ope_jsonl(path: str | Path) -> tuple[LoggedBanditRecord, ...]:
    resolved = Path(path)
    rows: list[LoggedBanditRecord] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid JSON on {resolved}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object on {resolved}:{line_number}")
            try:
                record_id = str(payload["record_id"])
                if not record_id:
                    raise ValueError("record_id cannot be empty")
                rows.append(
                    LoggedBanditRecord(
                        reward=float(payload["reward"]),
                        behavior_propensity=float(payload["behavior_propensity"]),
                        target_action_probability=float(payload["target_action_probability"]),
                        baseline_q=float(payload["baseline_q"]),
                        target_q=float(payload["target_q"]),
                        cluster_id=_json_cluster_identity(payload.get("cluster_id")),
                        record_id=record_id,
                    )
                )
            except KeyError as exc:
                raise ValueError(
                    f"missing required field {exc.args[0]!r} on {resolved}:{line_number}"
                ) from exc
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid OPE row on {resolved}:{line_number}: {exc}") from exc
    if not rows:
        raise ValueError(f"{resolved} produced no OPE records")
    return tuple(rows)


def _load_candidates(path: str | Path) -> tuple[OPECandidate, ...]:
    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid candidate JSON: {resolved}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("candidate JSON must be a non-empty array")

    candidates: list[OPECandidate] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"candidate {index} must be a JSON object")
        estimator = item.get("estimator")
        if estimator not in _ALLOWED_ESTIMATORS:
            raise ValueError(f"candidate {index} has unsupported estimator: {estimator!r}")
        try:
            candidates.append(
                OPECandidate(
                    name=str(item["name"]),
                    estimator=estimator,
                    switch_threshold=(
                        float(item["switch_threshold"])
                        if item.get("switch_threshold") is not None
                        else None
                    ),
                    dr_os_lambda=(
                        float(item["dr_os_lambda"])
                        if item.get("dr_os_lambda") is not None
                        else None
                    ),
                    beta_folds=int(item.get("beta_folds", 5)),
                )
            )
        except KeyError as exc:
            raise ValueError(f"candidate {index} is missing {exc.args[0]!r}") from exc
    return tuple(candidates)


def run_locked_ope_benchmark(
    *,
    tuning_jsonl: str | Path,
    test_jsonl: str | Path,
    candidates_json: str | Path,
    tuning_reference: float,
    test_reference: float,
    benchmark: str,
    dataset: str,
    commit_sha: str,
    output: str | Path,
    support_propensity_floor: float = 1e-3,
) -> dict[str, Any]:
    """Run validation selection followed by exactly one frozen test evaluation.

    The test JSONL is intentionally opened only after ``protocol.tune`` returns.
    This keeps the executable path aligned with the conceptual holdout protocol.
    """

    if not isfinite(tuning_reference) or not isfinite(test_reference):
        raise ValueError("reference values must be finite")
    candidates = _load_candidates(candidates_json)
    tuning_records = _load_ope_jsonl(tuning_jsonl)

    protocol = LockedOPEProtocol(
        candidates,
        support_propensity_floor=support_propensity_floor,
    )
    protocol.tune(tuning_records, reference_value=float(tuning_reference))

    # Deliberately defer even reading the holdout until estimator selection is frozen.
    test_records = _load_ope_jsonl(test_jsonl)
    holdout = protocol.evaluate_once(test_records, reference_value=float(test_reference))
    artifact = protocol.artifact(
        holdout,
        benchmark=benchmark,
        dataset=dataset,
        commit_sha=commit_sha,
    )

    bundle: dict[str, Any] = {
        "schema_version": "growthevo.locked-ope-run.v1",
        "artifact": loads(artifact.to_json()),
        "validation_scores": [
            {
                "candidate": asdict(score.candidate),
                "estimate": score.estimate,
                "reference_value": score.reference_value,
                "absolute_error": score.absolute_error,
                "standard_error": score.standard_error,
                "effective_sample_ratio": score.effective_sample_ratio,
                "support_coverage": score.support_coverage,
                "max_importance_weight": score.max_importance_weight,
            }
            for score in protocol.validation_scores
        ],
    }
    Path(output).write_text(
        dumps(bundle, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select an OPE estimator on validation, then evaluate the frozen winner once on holdout.",
    )
    parser.add_argument("--tuning-jsonl", required=True)
    parser.add_argument("--test-jsonl", required=True)
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--tuning-reference", required=True, type=float)
    parser.add_argument("--test-reference", required=True, type=float)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--support-propensity-floor", type=float, default=1e-3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_locked_ope_benchmark(
        tuning_jsonl=args.tuning_jsonl,
        test_jsonl=args.test_jsonl,
        candidates_json=args.candidates_json,
        tuning_reference=args.tuning_reference,
        test_reference=args.test_reference,
        benchmark=args.benchmark,
        dataset=args.dataset,
        commit_sha=args.commit_sha,
        output=args.output,
        support_propensity_floor=args.support_propensity_floor,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
