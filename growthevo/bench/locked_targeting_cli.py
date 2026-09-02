from __future__ import annotations

import argparse
from dataclasses import replace
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel

from ._serialization import fingerprint_json, iter_jsonl_objects, load_json_object
from .locked_evaluation import LockedTargetingProtocol
from .targeting_experiment_plan import (
    TargetingExperimentPlan,
    load_targeting_experiment_plan,
)


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

    for payload, source in iter_jsonl_objects(resolved):
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

    for payload, source in iter_jsonl_objects(resolved):
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


def _load_and_validate_plan(
    *,
    experiment_plan_json: str | Path | None,
    export_manifest_json: str | Path | None,
    benchmark: str,
    dataset: str,
    treatment: Channel,
    selected_fraction: float,
) -> tuple[TargetingExperimentPlan | None, dict[str, Any] | None]:
    if (experiment_plan_json is None) != (export_manifest_json is None):
        raise ValueError(
            "experiment_plan_json and export_manifest_json must be provided together"
        )
    if experiment_plan_json is None:
        return None, None
    plan = load_targeting_experiment_plan(experiment_plan_json)
    manifest = load_json_object(
        export_manifest_json,
        label="targeting export manifest",
    )
    plan.validate_runtime_contract(
        benchmark=benchmark,
        dataset=dataset,
        treatment=treatment,
        selected_fraction=selected_fraction,
        candidate_names=plan.candidate_names,
    )
    plan.validate_export_manifest(manifest)
    return plan, manifest


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
    experiment_plan_json: str | Path | None = None,
    export_manifest_json: str | Path | None = None,
) -> dict[str, Any]:
    """Select on randomized validation data, then reveal one frozen holdout."""

    plan, manifest = _load_and_validate_plan(
        experiment_plan_json=experiment_plan_json,
        export_manifest_json=export_manifest_json,
        benchmark=benchmark,
        dataset=dataset,
        treatment=treatment,
        selected_fraction=selected_fraction,
    )

    # Upstream plan/manifest agreement is checked before validation is opened.
    tuning_records, candidate_scores = _load_tuning_jsonl(tuning_jsonl)
    if plan is not None and tuple(sorted(candidate_scores)) != tuple(
        sorted(plan.candidate_names)
    ):
        raise ValueError(
            "validation candidate scores do not match the pre-registered candidate set"
        )

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

    plan_payload: dict[str, Any] | None = None
    if plan is not None and manifest is not None:
        manifest_fingerprint = fingerprint_json(manifest)
        metrics = dict(artifact.metrics)
        metrics.update(
            {
                "experiment_plan_fingerprint": plan.fingerprint,
                "export_manifest_fingerprint": manifest_fingerprint,
                "dataset_source": plan.dataset_source,
                "score_protocol": plan.score_protocol,
            }
        )
        artifact = replace(
            artifact,
            protocol_fingerprint=plan.bind_protocol_fingerprint(
                artifact.protocol_fingerprint
            ),
            metrics=metrics,
        )
        plan_payload = {
            "fingerprint": plan.fingerprint,
            "plan": plan.canonical_payload(),
            "export_manifest_fingerprint": manifest_fingerprint,
        }

    bundle: dict[str, Any] = {
        "schema_version": (
            "growthevo.locked-targeting-run.v2"
            if plan is not None
            else "growthevo.locked-targeting-run.v1"
        ),
        "artifact": loads(artifact.to_json()),
        "experiment_plan": plan_payload,
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
    parser.add_argument("--experiment-plan-json")
    parser.add_argument("--export-manifest-json")
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
        experiment_plan_json=args.experiment_plan_json,
        export_manifest_json=args.export_manifest_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
