from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_obd_locked_ope.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_obd_memory_exporter", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORTER)


def _feedback() -> dict[str, object]:
    return {
        "n_rounds": 2,
        "n_actions": 2,
        "action": [0, 1],
        "position": [0, 1],
        "reward": [1.0, 0.0],
        "pscore": [0.5, 0.25],
        "context": [[1.0], [2.0]],
        "action_context": [[1.0, 0.0], [0.0, 1.0]],
    }


def test_shared_context_free_action_distribution_matches_tiled_semantics() -> None:
    shared = [
        [0.75, 0.20],
        [0.25, 0.80],
    ]
    tiled = [shared, shared]
    q_hat = [
        [[0.20, 0.40], [0.80, 0.60]],
        [[0.30, 0.50], [0.70, 0.90]],
    ]

    shared_rows = _EXPORTER.build_locked_ope_rows(
        _feedback(), shared, q_hat, ["r0", "r1"]
    )
    tiled_rows = _EXPORTER.build_locked_ope_rows(
        _feedback(), tiled, q_hat, ["r0", "r1"]
    )

    assert shared_rows == tiled_rows
    assert shared_rows[0]["target_action_probability"] == pytest.approx(0.75)
    assert shared_rows[1]["target_action_probability"] == pytest.approx(0.80)


def test_compact_q_terms_produce_the_same_locked_rows_as_full_q_tensor() -> None:
    shared = [
        [0.75, 0.20],
        [0.25, 0.80],
    ]
    q_hat = [
        [[0.20, 0.40], [0.80, 0.60]],
        [[0.30, 0.50], [0.70, 0.90]],
    ]
    full_rows = _EXPORTER.build_locked_ope_rows(
        _feedback(), shared, q_hat, ["r0", "r1"]
    )
    baseline_q = [0.20, 0.90]
    target_q = [
        0.75 * 0.20 + 0.25 * 0.80,
        0.20 * 0.50 + 0.80 * 0.90,
    ]

    compact_rows = _EXPORTER.build_locked_ope_rows_from_terms(
        _feedback(), shared, baseline_q, target_q, ["r0", "r1"]
    )

    assert compact_rows == full_rows


def test_compact_q_terms_fail_closed_on_length_drift() -> None:
    with pytest.raises(ValueError, match="compact Q terms"):
        _EXPORTER.build_locked_ope_rows_from_terms(
            _feedback(),
            [[0.5, 0.5], [0.5, 0.5]],
            [0.1],
            [0.2, 0.3],
            ["r0", "r1"],
        )


def test_shared_action_distribution_mass_is_checked_once_per_position() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        _EXPORTER.build_locked_ope_rows_from_terms(
            _feedback(),
            [[0.7, 0.2], [0.5, 0.8]],
            [0.1, 0.2],
            [0.3, 0.4],
            ["r0", "r1"],
        )
