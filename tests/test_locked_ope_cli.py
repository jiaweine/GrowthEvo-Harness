from __future__ import annotations

from json import dumps, loads
from pathlib import Path

import pytest

from growthevo.bench.locked_ope_cli import main, run_locked_ope_benchmark


def _write_jsonl(path: Path, *, prefix: str, target_q: float) -> Path:
    rewards = (1.0, 0.0, 1.0, 0.0)
    lines = [
        dumps(
            {
                "reward": reward,
                "behavior_propensity": 0.5,
                "target_action_probability": 0.5,
                "baseline_q": target_q,
                "target_q": target_q,
                "record_id": f"{prefix}-{index}",
                "cluster_id": [prefix, index % 2],
            }
        )
        for index, reward in enumerate(rewards)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_candidates(path: Path) -> Path:
    path.write_text(
        dumps(
            [
                {"name": "dm", "estimator": "direct_method"},
                {"name": "ips", "estimator": "ips"},
                {"name": "beta-cf2", "estimator": "beta_ips", "beta_folds": 2},
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_locked_ope_cli_writes_auditable_bundle(tmp_path: Path) -> None:
    tuning = _write_jsonl(tmp_path / "tuning.jsonl", prefix="tune", target_q=0.6)
    test = _write_jsonl(tmp_path / "test.jsonl", prefix="test", target_q=0.7)
    candidates = _write_candidates(tmp_path / "candidates.json")
    output = tmp_path / "result.json"

    bundle = run_locked_ope_benchmark(
        tuning_jsonl=tuning,
        test_jsonl=test,
        candidates_json=candidates,
        tuning_reference=0.6,
        test_reference=0.65,
        benchmark="open-bandit-ope",
        dataset="obd-fixture",
        commit_sha="deadbeef",
        output=output,
    )

    assert bundle["artifact"]["selected_candidate"] == "dm"
    assert bundle["artifact"]["metrics"]["estimate"] == pytest.approx(0.7)
    assert bundle["artifact"]["metrics"]["absolute_error"] == pytest.approx(0.05)
    assert len(bundle["validation_scores"]) == 3
    assert loads(output.read_text(encoding="utf-8")) == bundle


def test_cli_entrypoint_uses_same_locked_runner(tmp_path: Path) -> None:
    tuning = _write_jsonl(tmp_path / "tuning.jsonl", prefix="tune", target_q=0.6)
    test = _write_jsonl(tmp_path / "test.jsonl", prefix="test", target_q=0.7)
    candidates = _write_candidates(tmp_path / "candidates.json")
    output = tmp_path / "result.json"

    exit_code = main(
        [
            "--tuning-jsonl",
            str(tuning),
            "--test-jsonl",
            str(test),
            "--candidates-json",
            str(candidates),
            "--tuning-reference",
            "0.6",
            "--test-reference",
            "0.65",
            "--benchmark",
            "open-bandit-ope",
            "--dataset",
            "obd-fixture",
            "--commit-sha",
            "deadbeef",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert loads(output.read_text(encoding="utf-8"))["artifact"]["selected_candidate"] == "dm"


def test_cli_rejects_unsupported_candidate_before_test_evaluation(tmp_path: Path) -> None:
    tuning = _write_jsonl(tmp_path / "tuning.jsonl", prefix="tune", target_q=0.6)
    test = _write_jsonl(tmp_path / "test.jsonl", prefix="test", target_q=0.7)
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        dumps([{"name": "mystery", "estimator": "magic"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported estimator"):
        run_locked_ope_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            candidates_json=candidates,
            tuning_reference=0.6,
            test_reference=0.65,
            benchmark="open-bandit-ope",
            dataset="obd-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )


def test_cli_rejects_validation_test_identity_overlap(tmp_path: Path) -> None:
    tuning = _write_jsonl(tmp_path / "tuning.jsonl", prefix="same", target_q=0.6)
    test = _write_jsonl(tmp_path / "test.jsonl", prefix="same", target_q=0.7)
    candidates = _write_candidates(tmp_path / "candidates.json")

    with pytest.raises(ValueError, match="identities overlap"):
        run_locked_ope_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            candidates_json=candidates,
            tuning_reference=0.6,
            test_reference=0.65,
            benchmark="open-bandit-ope",
            dataset="obd-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )


def test_cli_requires_real_stable_record_id(tmp_path: Path) -> None:
    tuning = tmp_path / "tuning.jsonl"
    tuning.write_text(
        dumps(
            {
                "reward": 1.0,
                "behavior_propensity": 0.5,
                "target_action_probability": 0.5,
                "baseline_q": 0.5,
                "target_q": 0.5,
                "record_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    test = _write_jsonl(tmp_path / "test.jsonl", prefix="test", target_q=0.7)
    candidates = _write_candidates(tmp_path / "candidates.json")

    with pytest.raises(ValueError, match="record_id"):
        run_locked_ope_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            candidates_json=candidates,
            tuning_reference=0.6,
            test_reference=0.65,
            benchmark="open-bandit-ope",
            dataset="obd-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )
