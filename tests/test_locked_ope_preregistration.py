from __future__ import annotations

import json
from pathlib import Path

import pytest

from growthevo.bench.locked_ope_cli import run_locked_ope_benchmark


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_rows(path: Path, prefix: str, rewards: list[float]) -> None:
    rows = [
        {
            "reward": reward,
            "behavior_propensity": 0.5,
            "target_action_probability": 0.5,
            "baseline_q": 0.25,
            "target_q": 0.25,
            "record_id": f"{prefix}-{index}",
            "cluster_id": None,
        }
        for index, reward in enumerate(rewards)
    ]
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _plan() -> dict[str, object]:
    return {
        "schema_version": "growthevo.ope-experiment-plan.v1",
        "benchmark": "unit-ope",
        "dataset": "unit-dataset",
        "dataset_source": "fixture:unit-dataset-v1",
        "campaign": "all",
        "behavior_policy": "random",
        "evaluation_policy": "bts",
        "reward_definition": "click",
        "split_strategy": "paired_chronological_relative_fraction",
        "validation_fraction": 0.5,
        "q_model": "logistic",
        "q_folds": 2,
        "n_sim": 100,
        "random_state": 7,
        "support_propensity_floor": 0.001,
        "evidence_gate": {
            "min_support_coverage": 0.0,
            "min_effective_sample_ratio": 0.0,
            "require_positive_importance_mass": True,
        },
        "candidates": [{"name": "ips", "estimator": "ips"}],
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "growthevo.obd-export.v2",
        "dataset_source": "fixture:unit-dataset-v1",
        "campaign": "all",
        "behavior_policy": "random",
        "evaluation_policy": "bts",
        "reward_definition": "click",
        "split_strategy": "paired_chronological_relative_fraction",
        "validation_fraction": 0.5,
        "q_model": "logistic",
        "q_folds": 2,
        "n_sim": 100,
        "random_state": 7,
    }


def test_preregistration_mismatch_fails_before_validation_file_is_opened(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    plan = tmp_path / "plan.json"
    manifest = tmp_path / "manifest.json"
    _write_json(candidates, [{"name": "ips", "estimator": "ips"}])
    _write_json(plan, _plan())
    _write_json(manifest, {**_manifest(), "n_sim": 101})

    with pytest.raises(ValueError, match="export manifest.*n_sim"):
        run_locked_ope_benchmark(
            tuning_jsonl=tmp_path / "does-not-exist-validation.jsonl",
            test_jsonl=tmp_path / "does-not-exist-holdout.jsonl",
            candidates_json=candidates,
            tuning_reference=0.5,
            test_reference=0.5,
            benchmark="unit-ope",
            dataset="unit-dataset",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
            experiment_plan_json=plan,
            export_manifest_json=manifest,
        )


def test_preregistered_run_binds_plan_manifest_and_locked_evidence(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    plan = tmp_path / "plan.json"
    manifest = tmp_path / "manifest.json"
    tuning = tmp_path / "validation.jsonl"
    holdout = tmp_path / "holdout.jsonl"
    output = tmp_path / "result.json"

    _write_json(candidates, [{"name": "ips", "estimator": "ips"}])
    _write_json(plan, _plan())
    _write_json(manifest, _manifest())
    _write_rows(tuning, "validation", [1.0, 0.0, 1.0, 0.0])
    _write_rows(holdout, "holdout", [1.0, 1.0, 0.0, 0.0])

    result = run_locked_ope_benchmark(
        tuning_jsonl=tuning,
        test_jsonl=holdout,
        candidates_json=candidates,
        tuning_reference=0.5,
        test_reference=0.5,
        benchmark="unit-ope",
        dataset="unit-dataset",
        commit_sha="deadbeef",
        output=output,
        experiment_plan_json=plan,
        export_manifest_json=manifest,
    )

    assert result["schema_version"] == "growthevo.locked-ope-run.v3"
    prereg = result["experiment_plan"]
    assert prereg is not None
    assert len(prereg["fingerprint"]) == 40
    assert len(prereg["export_manifest_fingerprint"]) == 40
    artifact = result["artifact"]
    assert artifact["selected_candidate"] == "ips"
    assert artifact["metrics"]["experiment_plan_fingerprint"] == prereg["fingerprint"]
    assert artifact["metrics"]["export_manifest_fingerprint"] == prereg[
        "export_manifest_fingerprint"
    ]
    assert artifact["metrics"]["dataset_source"] == "fixture:unit-dataset-v1"
    assert artifact["tuning_fingerprint"] != artifact["test_fingerprint"]
