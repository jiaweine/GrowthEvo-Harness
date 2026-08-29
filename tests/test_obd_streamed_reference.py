from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pd = pytest.importorskip(
    "pandas",
    reason="streamed OBD reference requires optional [obd] dependencies",
)


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_obd_locked_ope.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_obd_stream_reference", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORTER)


def test_chunked_target_reference_handles_mixed_iso8601_precision(tmp_path: Path) -> None:
    source = tmp_path / "all.csv"
    frame = pd.DataFrame(
        {
            "timestamp": [
                "2020-01-01 00:00:06.500000+00:00",
                "2020-01-01 00:00:01+00:00",
                "2020-01-01 00:00:04.250000+00:00",
                "2020-01-01 00:00:03+00:00",
                "2020-01-01 00:00:02.900000+00:00",
                "2020-01-01 00:00:05+00:00",
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

    assert rows == 6
    assert validation == pytest.approx(1.0 / 3.0)
    assert holdout == pytest.approx(2.0 / 3.0)


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
