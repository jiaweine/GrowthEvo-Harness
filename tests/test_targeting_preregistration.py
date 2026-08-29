from __future__ import annotations

import json
from pathlib import Path

import pytest

from growthevo.bench.locked_targeting_cli import run_locked_targeting_benchmark
from growthevo.bench.targeting_experiment_plan import load_targeting_experiment_plan
from growthevo.models import Channel


def _plan() -> dict[str, object]:
    return {
        "schema_version": "growthevo.targeting-experiment-plan.v1",
        "benchmark": "criteo-targeting",
        "dataset": "criteo-fixture",
        "dataset_source": "fixture:criteo-v1",
        "outcome_definition": "conversion",
        "split_strategy": "stable_hash_unit_id_v1",
        "validation_fraction": 0.5,
        "treatment": "ads",
        "selected_fraction": 0.5,
        "score_protocol": "external-precomputed-cate-scores-v1",
        "candidate_names": ["good", "bad"],
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "growthevo.targeting-export.v1",
        "dataset_source": "fixture:criteo-v1",
        "outcome_definition": "conversion",
        "split_strategy": "stable_hash_unit_id_v1",
        "validation_fraction": 0.5,
        "treatment": "ads",
        "score_protocol": "external-precomputed-cate-scores-v1",
        "candidate_names": ["bad", "good"],
    }


def _row(prefix: str, index: int) -> dict[str, object]:
    actions = ("ads", "no_treatment") * 4
    outcomes = (1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)
    return {
        "unit_id": f"{prefix}-{index}",
        "features": [float(index), float(index % 2)],
        "action": actions[index],
        "outcome": outcomes[index],
        "action_propensities": {"ads": 0.5, "no_treatment": 0.5},
        "group_id": f"g-{prefix}-{index // 2}",
    }


def _write_tuning(path: Path) -> None:
    good = (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0)
    bad = tuple(reversed(good))
    rows = []
    for index in range(8):
        row = _row("validation", index)
        row["scores"] = {"good": good[index], "bad": bad[index]}
        rows.append(row)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _write_holdout(path: Path) -> None:
    good = (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0)
    rows = []
    for index in range(8):
        row = _row("holdout", index)
        row["selected_candidate"] = "good"
        row["score"] = good[index]
        rows.append(row)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_targeting_plan_is_strict_about_json_numbers(tmp_path: Path) -> None:
    payload = _plan()
    payload["selected_fraction"] = True
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="selected_fraction.*JSON number"):
        load_targeting_experiment_plan(path)


def test_targeting_manifest_mismatch_fails_before_validation_read(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    manifest = tmp_path / "manifest.json"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    manifest.write_text(
        json.dumps({**_manifest(), "score_protocol": "changed-after-plan"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="score_protocol"):
        run_locked_targeting_benchmark(
            tuning_jsonl=tmp_path / "missing-validation.jsonl",
            test_jsonl=tmp_path / "missing-holdout.jsonl",
            selected_fraction=0.5,
            treatment=Channel.ADS,
            benchmark="criteo-targeting",
            dataset="criteo-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
            experiment_plan_json=plan,
            export_manifest_json=manifest,
        )


def test_targeting_preregistered_run_binds_plan_and_manifest(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    manifest = tmp_path / "manifest.json"
    tuning = tmp_path / "validation.jsonl"
    holdout = tmp_path / "holdout.jsonl"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    _write_tuning(tuning)
    _write_holdout(holdout)

    result = run_locked_targeting_benchmark(
        tuning_jsonl=tuning,
        test_jsonl=holdout,
        selected_fraction=0.5,
        treatment=Channel.ADS,
        benchmark="criteo-targeting",
        dataset="criteo-fixture",
        commit_sha="deadbeef",
        output=tmp_path / "result.json",
        experiment_plan_json=plan,
        export_manifest_json=manifest,
    )

    assert result["schema_version"] == "growthevo.locked-targeting-run.v2"
    prereg = result["experiment_plan"]
    assert prereg is not None
    artifact = result["artifact"]
    assert artifact["selected_candidate"] == "good"
    assert artifact["metrics"]["dataset_source"] == "fixture:criteo-v1"
    assert artifact["metrics"]["score_protocol"] == "external-precomputed-cate-scores-v1"
    assert artifact["metrics"]["experiment_plan_fingerprint"] == prereg["fingerprint"]
    assert artifact["metrics"]["export_manifest_fingerprint"] == prereg[
        "export_manifest_fingerprint"
    ]
