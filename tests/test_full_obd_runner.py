from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "run_obd_full_locked.py"
_SPEC = importlib.util.spec_from_file_location("growthevo_full_obd_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def _make_obd_root(root: Path, *, include_target: bool = True) -> Path:
    random_campaign = root / "random" / "all"
    random_campaign.mkdir(parents=True)
    (random_campaign / "all.csv").write_text("x\n", encoding="utf-8")
    (random_campaign / "item_context.csv").write_text("x\n", encoding="utf-8")
    if include_target:
        bts_campaign = root / "bts" / "all"
        bts_campaign.mkdir(parents=True)
        (bts_campaign / "all.csv").write_text("x\n", encoding="utf-8")
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


def test_full_runner_uses_actual_obp_campaign_directory_layout(tmp_path: Path) -> None:
    direct = _make_obd_root(tmp_path / "direct")
    assert _RUNNER._campaign_file(direct, "random", "all") == (
        direct / "random" / "all" / "all.csv"
    )
    assert _RUNNER._item_context_file(direct, "random", "all") == (
        direct / "random" / "all" / "item_context.csv"
    )
    assert _RUNNER._find_obd_root(direct) == direct


def test_find_obd_root_accepts_single_nested_full_root(tmp_path: Path) -> None:
    nested_parent = tmp_path / "nested"
    nested = _make_obd_root(nested_parent / "open_bandit_dataset")
    assert _RUNNER._find_obd_root(nested_parent) == nested


def test_find_obd_root_can_validate_behavior_only_mirror_cache(tmp_path: Path) -> None:
    behavior_only = _make_obd_root(tmp_path / "partial", include_target=False)
    assert (
        _RUNNER._find_obd_root(behavior_only, require_target=False)
        == behavior_only
    )
    with pytest.raises(ValueError, match="full OBD root"):
        _RUNNER._find_obd_root(behavior_only, require_target=True)


def test_find_obd_root_fails_closed_on_ambiguous_extraction(tmp_path: Path) -> None:
    _make_obd_root(tmp_path / "a")
    _make_obd_root(tmp_path / "b")

    with pytest.raises(ValueError, match="exactly one full OBD root"):
        _RUNNER._find_obd_root(tmp_path)


def test_full_mirror_transport_is_pinned_to_obd_v1_revision() -> None:
    assert _RUNNER._HF_DATASET == "zozonext/open-bandit"
    assert _RUNNER._HF_DATA_REVISION == "57a688e"
    behavior_url = _RUNNER._mirror_url("random", "all", "all.csv")
    target_url = _RUNNER._mirror_url("bts", "all", "all.csv")
    assert "/resolve/57a688e/random/all/all.csv" in behavior_url
    assert "/resolve/57a688e/bts/all/all.csv" in target_url


def test_download_budget_fails_before_transfer_when_known_files_do_not_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_RUNNER, "_remote_size", lambda _url: 4 * 1024**3)
    monkeypatch.setattr(
        _RUNNER.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10 * 1024**3, used=0, free=10 * 1024**3),
    )
    downloads = [
        ("https://example.test/a", tmp_path / "a.csv"),
        ("https://example.test/b", tmp_path / "b.csv"),
        ("https://example.test/c", tmp_path / "c.csv"),
    ]

    with pytest.raises(RuntimeError, match="insufficient disk"):
        _RUNNER._assert_download_budget(tmp_path, downloads)


def test_download_budget_counts_existing_cache_as_already_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = tmp_path / "cached.csv"
    cached.write_bytes(b"cached")
    monkeypatch.setattr(_RUNNER, "_remote_size", lambda _url: 3 * 1024**3)
    monkeypatch.setattr(
        _RUNNER.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=8 * 1024**3, used=0, free=8 * 1024**3),
    )
    sizes = _RUNNER._assert_download_budget(
        tmp_path,
        [
            ("https://example.test/cached", cached),
            ("https://example.test/new", tmp_path / "new.csv"),
        ],
    )

    assert sizes["https://example.test/cached"] == len(b"cached")
    assert sizes["https://example.test/new"] == 3 * 1024**3
