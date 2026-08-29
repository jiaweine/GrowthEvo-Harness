from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "run_obd_full_locked.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_full_obd_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def _make_obd_root(root: Path) -> Path:
    (root / "random").mkdir(parents=True)
    (root / "bts").mkdir(parents=True)
    (root / "random" / "all.csv").write_text("x\n", encoding="utf-8")
    (root / "bts" / "all.csv").write_text("x\n", encoding="utf-8")
    (root / "item_context.csv").write_text("x\n", encoding="utf-8")
    return root


def test_full_plan_uses_research_scale_protocol() -> None:
    plan = load_ope_experiment_plan(
        _ROOT / "benchmarks" / "ope" / "obd-full-all-random-to-bts.v1.json"
    )

    assert plan.dataset == "obd-full-all-random-to-bts"
    assert plan.dataset_source.startswith("zozo-research:open-bandit-dataset-full:")
    assert plan.n_sim == 100000
    assert plan.q_model == "logistic"
    assert plan.q_folds == 3
    assert plan.evidence_gate.min_support_coverage == pytest.approx(0.95)
    assert plan.evidence_gate.min_effective_sample_ratio == pytest.approx(0.05)


def test_find_obd_root_accepts_direct_or_single_nested_root(tmp_path: Path) -> None:
    direct = _make_obd_root(tmp_path / "direct")
    assert _RUNNER._find_obd_root(direct) == direct

    nested_parent = tmp_path / "nested"
    nested = _make_obd_root(nested_parent / "open_bandit_dataset")
    assert _RUNNER._find_obd_root(nested_parent) == nested


def test_find_obd_root_fails_closed_on_ambiguous_extraction(tmp_path: Path) -> None:
    _make_obd_root(tmp_path / "a")
    _make_obd_root(tmp_path / "b")

    with pytest.raises(ValueError, match="exactly one"):
        _RUNNER._find_obd_root(tmp_path)
