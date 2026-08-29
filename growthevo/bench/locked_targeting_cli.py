from __future__ import annotations

import argparse
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel

from .locked_evaluation import LockedTargetingProtocol


def _record_from_payload(payload: Mapping[str, Any], *, source: str) -> LoggedTreatmentRecord:
    try:
        unit_id = payload["unit_id"]
        if not isinstance(unit_id, str) or not unit_id:
            raise ValueError("unit_id must be a non-empty JSON string")

        raw_features = payload["features"]
        if not isinstance(raw_features, list) or not raw_features:
            raise ValueError("features must be a non-empty JSON array")
        features = tuple(float(value) for value in raw_features)
        if any(not isfinite(value) for value in features):
            raise ValueError("features must be finite")

        action = Channel(str(payload["action"]))
        raw_propensities = payload["action_propensities"]
        if not isinstance(raw_propensities, dict) or not raw_propensities:
            raise ValueError("action_propensities must be a non-empty JSON object")
        propensities = {
            Channel(str(name)): float(value)
            for name, value in raw_propensities.items()
        }

        group_id = payload.get("group_id")
        if group_id is not None and (not isinstance(group_id, str) or not group_id):
            raise ValueError("group_id must be a non-empty string when provided")

        return LoggedTreatmentRecord(
            unit_id=unit_id,
            features=features,
            action=action,
            outcome=float(payload["outcome"]),
            action_propensities=propensities,
            group_id=group_id,
        )
    except KeyError as exc:
        raise ValueError(f"missing required field {exc.args[0]!r} in {source}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid targeting row in {source}: {exc}") from exc


def _load_tuning_jsonl(
    path: str | Path,
) -> tuple[tuple[LoggedTreatmentRecord, ...], dict[str, tuple[float, ...]]]:
    resolved = Path(path)
    records: list[LoggedTreatmentRecord] = []
    score_rows: list[dict[str, float]] = []
    candidate_names: set[str] | None = None

    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = f"{resolved}:{line_number}"
            try:
                payload = loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid JSON on {source}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object on {source}")
            records.append(_record_from_payload(payload, source=source))

            raw_scores = payload.get("scores")
            if not isinstance(raw_scores, dict) or not raw_scores:
                raise ValueError(f"scores must be a non-empty JSON object on {source}")
            scores: dict[str, float] = {}
            for name, value in raw_scores.items():
                if not isinstance(name, str) or not name:
                    raise ValueError(f"candidate names must be non-empty strings on {source}")
                score = float(value)
                if not isfinite(score):
                    raise ValueError(f"candidate score must be finite on {source}")
                scores[name] = score
            names = set(scores)
            if candidate_names is None:
                candidate_names = names
            elif names != candidate_names:
                raise ValueError("every tuning row must contain the same candidate score set")
            score_rows.append(scores)

    if not records or candidate_names is None:
        raise ValueError(f"{resolved} produced no tuning records")
    candidate_scores = {
        name: tuple(row[name] for row in score_rows)
        for name in sorted(candidate_names)
    }
    return tuple(records), candidate_scores


def _load_test_jsonl(
    path: str | Path,
    *,
    selected_candidate: str,
) -> tuple[tuple[LoggedTreatmentRecord, ...], tuple[float, ...]]:
    resolved = Path(path)
    records: list[LoggedTreatmentRecord] = []
    scores: list[float] = []

    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = f"{resolved}:{line_number}"
            try:
                payload = loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid JSON on {source}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object on {source}")
            declared = payload.get("selected_candidate")
            if declared != selected_candidate:
                raise ValueError(
                    f"holdout row on {source} declares {declared!r}; "
                    f"frozen winner is {selected_candidate!r}"
                )
            try:
                score = float(payload["score"])
            except KeyError as exc:
                raise ValueError(f"missing required field 'score' on {source}") from exc
            if not isfinite(score):
                raise ValueError(f"holdout score must be finite on {source}")
            records.append(_record_from_payload(payload, source=source))
            scores.append(score)

    if not records:
        raise ValueError(f"{resolved} produced no holdout records")
    return tuple(records), tuple(scores)


def run_locked_targeting_benchmark(
    *,
    tuning_jsonl: str | Path,
    test_jsonl: str | Path,
    selected_fraction: float,
    treatment: Channel,
    benchmark: str,
    dataset: str,
    commit_sha: str,
    output: str | Path,
) -> dict[str, Any]:
    """Select a targeting model on randomized validation data, then reveal holdout once."""

    tuning_records, candidate_scores = _load_tuning_jsonl(tuning_jsonl)
    protocol = LockedTargetingProtocol(
        selected_fraction=selected_fraction,
        treatment=treatment,
    )
    selected = protocol.tune(tuning_records, candidate_scores)

    # The holdout is deliberately opened only after the validation winner is frozen.
    test_records, selected_scores = _load_test_jsonl(
        test_jsonl,
        selected_candidate=selected,
    )
    holdout = protocol.evaluate_once(test_records, selected_scores)
    artifact = protocol.artifact(
        holdout,
        benchmark=benchmark,
        dataset=dataset,
        commit_sha=commit_sha,
    )

    bundle: dict[str, Any] = {
        "schema_version": "growthevo.locked-targeting-run.v1",
        "artifact": loads(artifact.to_json()),
        "validation_scores": [
            {
                "candidate_name": score.candidate_name,
                "sample_size": score.result.sample_size,
                "selected_fraction": score.result.selected_fraction,
                "policy_value": score.result.policy_value,
                "treat_none_value": score.result.treat_none_value,
                "treat_all_value": score.result.treat_all_value,
                "incremental_value_vs_none": score.result.incremental_value_vs_none,
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
        description=(
            "Select a randomized-targeting model on validation, then evaluate only "
            "the frozen winner on final holdout."
        ),
    )
    parser.add_argument("--tuning-jsonl", required=True)
    parser.add_argument("--test-jsonl", required=True)
    parser.add_argument("--selected-fraction", required=True, type=float)
    parser.add_argument(
        "--treatment",
        default=Channel.ADS.value,
        choices=[channel.value for channel in Channel if channel is not Channel.NO_TREATMENT],
    )
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_locked_targeting_benchmark(
        tuning_jsonl=args.tuning_jsonl,
        test_jsonl=args.test_jsonl,
        selected_fraction=args.selected_fraction,
        treatment=Channel(args.treatment),
        benchmark=args.benchmark,
        dataset=args.dataset,
        commit_sha=args.commit_sha,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
