from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_obd_locked_ope.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_obd_stream_reference", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORTER)


def test_chunked_target_reference_matches_obp_timestamp_sort_semantics(tmp_path: Path) -> None:
    source = tmp_path / "all.csv"
    frame = pd.DataFrame(
        {
            "timestamp": [
                "2020-01-01 00:00:06",
                "2020-01-01 00:00:01",
                "2020-01-01 00:00:04",
                "2020-01-01 00:00:03",
                "2020-01-01 00:00:02",
                "2020-01-01 00:00:05",
            ],
            "item_id": [2, 0, 1, 2, 1, 0],
            "position": [3, 1, 2, 3, 2, 1],
            "click": [1, 0, 1, 0, 1, 0],
        }
    )
    frame.to_csv(source, index=True)

    validation, holdout, rows = _EXPORTER._target_reference_from_csv(
        source,
        validation_fraction=0.5,
        expected_n_actions=3,
        expected_len_list=3,
        chunksize=2,
    )

    expected = pd.read_csv(source, index_col=0).sort_values("timestamp")
    split = int(len(expected) * 0.5)
    assert rows == len(expected)
    assert validation == pytest.approx(expected["click"].iloc[:split].mean())
    assert holdout == pytest.approx(expected["click"].iloc[split:].mean())


def test_chunked_target_reference_rejects_action_or_slate_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "all.csv"
    pd.DataFrame(
        {
            "timestamp": ["2020-01-01 00:00:01", "2020-01-01 00:00:02"],
            "item_id": [0, 1],
            "position": [1, 2],
            "click": [0, 1],
        }
    ).to_csv(source, index=False)

    with pytest.raises(ValueError, match="action-space"):
        _EXPORTER._target_reference_from_csv(
            source,
            validation_fraction=0.5,
            expected_n_actions=3,
            expected_len_list=2,
            chunksize=1,
        )

    with pytest.raises(ValueError, match="slate length"):
        _EXPORTER._target_reference_from_csv(
            source,
            validation_fraction=0.5,
            expected_n_actions=2,
            expected_len_list=3,
            chunksize=1,
        )
