from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from growthevo.rl.ope import LoggedBanditRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_obd_mrdr_q_dev.py"
spec = importlib.util.spec_from_file_location("obd_mrdr_q_dev", SCRIPT)
assert spec is not None and spec.loader is not None
mrdr_dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mrdr_dev
spec.loader.exec_module(mrdr_dev)


def test_mrdr_development_contract_changes_only_fitting_objective() -> None:
    assert mrdr_dev._Q_FOLDS == 2
    assert mrdr_dev._RANDOM_STATE == 12345
    assert mrdr_dev._LOGISTIC_C == 1.0
    assert mrdr_dev._LOGISTIC_MAX_ITER == 1000


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

    grid = mrdr_dev.candidate_grid(rows, reference=0.5)

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


def test_dev_script_keeps_heavy_obd_imports_lazy() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    prefix = source.split("def _position_array", 1)[0]
    assert "import numpy" not in prefix
    assert "from obp" not in prefix
    assert "from sklearn" not in prefix
    assert 'fitting_method="mrdr"' in source
