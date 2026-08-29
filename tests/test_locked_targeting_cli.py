from __future__ import annotations

from json import dumps, loads
from pathlib import Path

import pytest

from growthevo.bench.locked_targeting_cli import (
    main,
    run_locked_targeting_benchmark,
)
from growthevo.models import Channel


def _actions() -> tuple[str, ...]:
    return (
        "ads",
        "no_treatment",
        "ads",
        "no_treatment",
        "ads",
        "no_treatment",
        "ads",
        "no_treatment",
    )


def _outcomes() -> tuple[float, ...]:
    return (1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)


def _good_scores() -> tuple[float, ...]:
    return (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0)


def _bad_scores() -> tuple[float, ...]:
    return tuple(reversed(_good_scores()))


def _base_row(prefix: str, index: int) -> dict[str, object]:
    return {
        "unit_id": f"{prefix}-{index}",
        "features": [float(index), float(index % 2)],
        "action": _actions()[index],
        "outcome": _outcomes()[index],
        "action_propensities": {"ads": 0.5, "no_treatment": 0.5},
        "group_id": f"g-{index // 2}",
    }


def _write_tuning(path: Path, *, prefix: str = "tune") -> Path:
    lines = []
    for index in range(8):
        row = _base_row(prefix, index)
        row["scores"] = {
            "good": _good_scores()[index],
            "bad": _bad_scores()[index],
        }
        lines.append(dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_test(
    path: Path,
    *,
    prefix: str = "test",
    declared_candidate: str = "good",
) -> Path:
    lines = []
    for index in range(8):
        row = _base_row(prefix, index)
        row["selected_candidate"] = declared_candidate
        row["score"] = _good_scores()[index]
        lines.append(dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_locked_targeting_cli_writes_validation_and_single_holdout_artifact(tmp_path: Path) -> None:
    tuning = _write_tuning(tmp_path / "tuning.jsonl")
    test = _write_test(tmp_path / "test.jsonl")
    output = tmp_path / "result.json"

    bundle = run_locked_targeting_benchmark(
        tuning_jsonl=tuning,
        test_jsonl=test,
        selected_fraction=0.5,
        treatment=Channel.ADS,
        benchmark="criteo-targeting",
        dataset="criteo-fixture",
        commit_sha="deadbeef",
        output=output,
    )

    assert bundle["artifact"]["selected_candidate"] == "good"
    assert bundle["artifact"]["metrics"]["incremental_value_vs_none"] == pytest.approx(0.5)
    assert len(bundle["validation_scores"]) == 2
    by_name = {row["candidate_name"]: row for row in bundle["validation_scores"]}
    assert by_name["good"]["incremental_value_vs_none"] == pytest.approx(0.5)
    assert by_name["bad"]["incremental_value_vs_none"] == pytest.approx(-0.5)
    assert loads(output.read_text(encoding="utf-8")) == bundle


def test_targeting_cli_entrypoint_uses_same_locked_runner(tmp_path: Path) -> None:
    tuning = _write_tuning(tmp_path / "tuning.jsonl")
    test = _write_test(tmp_path / "test.jsonl")
    output = tmp_path / "result.json"

    exit_code = main(
        [
            "--tuning-jsonl",
            str(tuning),
            "--test-jsonl",
            str(test),
            "--selected-fraction",
            "0.5",
            "--treatment",
            "ads",
            "--benchmark",
            "criteo-targeting",
            "--dataset",
            "criteo-fixture",
            "--commit-sha",
            "deadbeef",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert loads(output.read_text(encoding="utf-8"))["artifact"]["selected_candidate"] == "good"


def test_targeting_cli_rejects_holdout_for_non_winner(tmp_path: Path) -> None:
    tuning = _write_tuning(tmp_path / "tuning.jsonl")
    test = _write_test(tmp_path / "test.jsonl", declared_candidate="bad")

    with pytest.raises(ValueError, match="frozen winner is 'good'"):
        run_locked_targeting_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            selected_fraction=0.5,
            treatment=Channel.ADS,
            benchmark="criteo-targeting",
            dataset="criteo-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )


def test_targeting_cli_rejects_candidate_set_drift_across_validation_rows(tmp_path: Path) -> None:
    tuning = tmp_path / "tuning.jsonl"
    lines = []
    for index in range(8):
        row = _base_row("tune", index)
        row["scores"] = {"good": _good_scores()[index], "bad": _bad_scores()[index]}
        if index == 7:
            row["scores"] = {"good": _good_scores()[index]}
        lines.append(dumps(row))
    tuning.write_text("\n".join(lines) + "\n", encoding="utf-8")
    test = _write_test(tmp_path / "test.jsonl")

    with pytest.raises(ValueError, match="same candidate score set"):
        run_locked_targeting_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            selected_fraction=0.5,
            treatment=Channel.ADS,
            benchmark="criteo-targeting",
            dataset="criteo-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )


def test_targeting_cli_rejects_validation_test_identity_overlap(tmp_path: Path) -> None:
    tuning = _write_tuning(tmp_path / "tuning.jsonl", prefix="same")
    test = _write_test(tmp_path / "test.jsonl", prefix="same")

    with pytest.raises(ValueError, match="identities overlap"):
        run_locked_targeting_benchmark(
            tuning_jsonl=tuning,
            test_jsonl=test,
            selected_fraction=0.5,
            treatment=Channel.ADS,
            benchmark="criteo-targeting",
            dataset="criteo-fixture",
            commit_sha="deadbeef",
            output=tmp_path / "result.json",
        )
