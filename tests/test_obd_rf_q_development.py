from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

from growthevo.rl.ope import LoggedBanditRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_obd_rf_q_dev.py"
spec = importlib.util.spec_from_file_location("obd_rf_q_dev", SCRIPT)
assert spec is not None and spec.loader is not None
rf_dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rf_dev
spec.loader.exec_module(rf_dev)


def test_public_meta_ope_random_forest_contract_is_frozen() -> None:
    assert rf_dev._RF_TREES == 150
    assert rf_dev._RF_MAX_DEPTH == 5
    assert rf_dev._RF_FOLDS == 5
    assert rf_dev._RF_RANDOM_STATE == 12345


def test_build_rf_rows_changes_only_q_terms() -> None:
    baseline = (
        LoggedBanditRecord(
            reward=1.0,
            behavior_propensity=0.25,
            target_action_probability=0.6,
            baseline_q=0.1,
            target_q=0.2,
            record_id="a",
        ),
        LoggedBanditRecord(
            reward=0.0,
            behavior_propensity=0.5,
            target_action_probability=0.7,
            baseline_q=0.3,
            target_q=0.4,
            record_id="b",
        ),
    )
    feedback = {
        "n_rounds": 2,
        "n_actions": 2,
        "action": np.asarray([0, 1]),
        "position": np.asarray([0, 0]),
    }
    action_dist = np.asarray([[0.6], [0.4]])
    q_hat = np.asarray(
        [
            [[0.2], [0.8]],
            [[0.4], [0.6]],
        ]
    )

    rows = rf_dev.build_rf_rows(baseline, feedback, action_dist, q_hat)

    assert rows[0].reward == baseline[0].reward
    assert rows[0].behavior_propensity == baseline[0].behavior_propensity
    assert rows[0].target_action_probability == baseline[0].target_action_probability
    assert rows[0].record_id == "a"
    assert rows[0].baseline_q == pytest.approx(0.2)
    assert rows[0].target_q == pytest.approx(0.6 * 0.2 + 0.4 * 0.8)

    assert rows[1].reward == baseline[1].reward
    assert rows[1].behavior_propensity == baseline[1].behavior_propensity
    assert rows[1].target_action_probability == baseline[1].target_action_probability
    assert rows[1].record_id == "b"
    assert rows[1].baseline_q == pytest.approx(0.6)
    assert rows[1].target_q == pytest.approx(0.6 * 0.4 + 0.4 * 0.6)


def test_candidate_grid_contains_exact_current_nine_candidates() -> None:
    rows = tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=0.25 + 0.125 * index,
            baseline_q=0.2,
            target_q=0.3,
            record_id=f"row-{index}",
        )
        for index in range(4)
    )

    grid = rf_dev.candidate_grid(rows, reference=0.5)

    assert set(grid) == {
        "beta-cf5",
        "dr",
        "ips",
        "snips",
        "switch-5",
        "switch-10",
        "dros-1",
        "dros-10",
        "meta-blue",
    }
    assert all(value["absolute_error"] >= 0.0 for value in grid.values())
    assert all(value["standard_error"] >= 0.0 for value in grid.values())
