from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

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


def test_dev_script_does_not_import_obd_stack_at_module_import_time() -> None:
    # Core CI intentionally does not install numpy/sklearn/obp. Heavy OBD imports
    # belong inside the runtime helpers exercised by the dedicated OBD workflow.
    source = SCRIPT.read_text(encoding="utf-8")
    prefix = source.split("def _position_array", 1)[0]
    assert "import numpy" not in prefix
    assert "from obp" not in prefix
    assert "from sklearn" not in prefix
