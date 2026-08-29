from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_obd_locked_ope.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_obd_exporter", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORTER)


def _feedback() -> dict[str, object]:
    return {
        "n_rounds": 2,
        "n_actions": 2,
        "action": [0, 1],
        "position": [0, 0],
        "reward": [1.0, 0.0],
        "pscore": [0.5, 0.25],
        "context": [[1.0], [2.0]],
        "action_context": [[1.0, 0.0], [0.0, 1.0]],
    }


def test_build_locked_rows_maps_logged_and_target_q_correctly() -> None:
    action_dist = [
        [[0.75], [0.25]],
        [[0.40], [0.60]],
    ]
    q_hat = [
        [[0.20], [0.80]],
        [[0.30], [0.70]],
    ]

    rows = _EXPORTER.build_locked_ope_rows(
        _feedback(),
        action_dist,
        q_hat,
        ["r0", "r1"],
    )

    assert rows[0]["reward"] == pytest.approx(1.0)
    assert rows[0]["behavior_propensity"] == pytest.approx(0.5)
    assert rows[0]["target_action_probability"] == pytest.approx(0.75)
    assert rows[0]["baseline_q"] == pytest.approx(0.20)
    assert rows[0]["target_q"] == pytest.approx(0.75 * 0.20 + 0.25 * 0.80)

    assert rows[1]["target_action_probability"] == pytest.approx(0.60)
    assert rows[1]["baseline_q"] == pytest.approx(0.70)
    assert rows[1]["target_q"] == pytest.approx(0.40 * 0.30 + 0.60 * 0.70)
    assert rows[1]["record_id"] == "r1"
    assert rows[1]["cluster_id"] is None


def test_build_locked_rows_respects_position_dimension() -> None:
    feedback = _feedback()
    feedback["position"] = [1, 0]
    action_dist = [
        [[0.10, 0.70], [0.90, 0.30]],
        [[0.40, 0.20], [0.60, 0.80]],
    ]
    q_hat = [
        [[0.20, 0.40], [0.80, 0.60]],
        [[0.30, 0.50], [0.70, 0.90]],
    ]

    rows = _EXPORTER.build_locked_ope_rows(
        feedback,
        action_dist,
        q_hat,
        ["slot-r0", "slot-r1"],
        cluster_ids=[["day", 1], ["day", 1]],
    )

    assert rows[0]["target_action_probability"] == pytest.approx(0.70)
    assert rows[0]["baseline_q"] == pytest.approx(0.40)
    assert rows[0]["target_q"] == pytest.approx(0.70 * 0.40 + 0.30 * 0.60)
    assert rows[0]["cluster_id"] == ["day", 1]


def test_build_locked_rows_fails_closed_on_invalid_probability_mass() -> None:
    action_dist = [
        [[0.60], [0.60]],
        [[0.40], [0.60]],
    ]
    q_hat = [
        [[0.20], [0.80]],
        [[0.30], [0.70]],
    ]

    with pytest.raises(ValueError, match="sum to 1"):
        _EXPORTER.build_locked_ope_rows(
            _feedback(),
            action_dist,
            q_hat,
            ["r0", "r1"],
        )


def test_build_locked_rows_requires_stable_unique_ids() -> None:
    action_dist = [
        [[0.75], [0.25]],
        [[0.40], [0.60]],
    ]
    q_hat = [
        [[0.20], [0.80]],
        [[0.30], [0.70]],
    ]

    with pytest.raises(ValueError, match="unique"):
        _EXPORTER.build_locked_ope_rows(
            _feedback(),
            action_dist,
            q_hat,
            ["same", "same"],
        )


def test_regression_model_config_preserves_obd_slate_width() -> None:
    action_context = [[1.0, 0.0], [0.0, 1.0]]
    kwargs = _EXPORTER._regression_model_kwargs(
        n_actions=2,
        len_list=3,
        action_context=action_context,
    )

    assert kwargs == {
        "n_actions": 2,
        "len_list": 3,
        "action_context": action_context,
    }

    with pytest.raises(ValueError, match="len_list"):
        _EXPORTER._regression_model_kwargs(
            n_actions=2,
            len_list=0,
            action_context=action_context,
        )


def test_default_candidate_grid_is_predeclared_and_frontier_oriented() -> None:
    candidates = _EXPORTER._default_candidates()
    names = {candidate["name"] for candidate in candidates}
    estimators = {candidate["estimator"] for candidate in candidates}

    assert "beta-cf5" in names
    assert "beta_ips" in estimators
    assert "doubly_robust" in estimators
    assert "switch_dr" in estimators
    assert "dr_os" in estimators
    assert "meta_blue" in estimators


def test_script_import_does_not_require_obp_runtime() -> None:
    # Reaching this test means the module was imported above without importing obp.
    assert callable(_EXPORTER.build_locked_ope_rows)
    assert callable(_EXPORTER.export_obd_pair)
