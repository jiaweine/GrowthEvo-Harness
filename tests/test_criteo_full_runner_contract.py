from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from growthevo.bench.targeting_experiment_plan import load_targeting_experiment_plan


_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "run_criteo_full_locked.py"
_ACCEPTED_RESULT = (
    _ROOT
    / "benchmarks"
    / "targeting"
    / "results"
    / "criteo-v2.1-visit-top10"
    / "7ac26a5a"
    / "locked-result.json"
)
_SPEC = importlib.util.spec_from_file_location("growthevo_full_criteo_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def test_full_criteo_source_is_pinned_to_official_hf_revision_and_digest() -> None:
    assert _RUNNER._SOURCE_COMMIT == "82811785048bb633de2d55c02bab4e57066e6423"
    assert _RUNNER._SOURCE_SHA256 == (
        "2716e1bf0fd157a93b5bf86924d9088419dfbac2022c6cd90030220634f616dc"
    )
    assert _RUNNER._EXPECTED_ROWS == 13_979_592
    assert "criteo/criteo-uplift/resolve/82811785048bb633de2d55c02bab4e57066e6423" in (
        _RUNNER._SOURCE_URL
    )


def test_candidate_config_fingerprint_is_bound_to_v2_plan() -> None:
    config, fingerprint = _RUNNER._load_candidate_config(
        _ROOT / "benchmarks" / "targeting" / "criteo-lgbm-candidates.v1.json"
    )
    plan = load_targeting_experiment_plan(
        _ROOT / "benchmarks" / "targeting" / "criteo-v2.1-visit-top10.v1.json"
    )

    assert fingerprint == "e10eb2fc6552b28109b67cfe075b55fd1d0e8f62"
    assert fingerprint == plan.candidate_config_fingerprint
    assert config["feature_columns"] == [f"f{index}" for index in range(12)]
    assert "exposure" in config["forbidden_columns"]
    assert [candidate["name"] for candidate in config["candidates"]] == [
        "s-lgbm",
        "t-lgbm",
        "x-lgbm",
        "r-lgbm",
        "dr-lgbm",
    ]


def test_canonical_full_criteo_preregistration_matches_accepted_result() -> None:
    plan = load_targeting_experiment_plan(
        _ROOT / "benchmarks" / "targeting" / "criteo-v2.1-visit-top10.v1.json"
    )
    _, candidate_fingerprint = _RUNNER._load_candidate_config(
        _ROOT / "benchmarks" / "targeting" / "criteo-lgbm-candidates.v1.json"
    )
    result = json.loads(_ACCEPTED_RESULT.read_text(encoding="utf-8"))

    assert plan.fingerprint == result["experiment_plan"]["fingerprint"]
    assert plan.fingerprint == result["artifact"]["metrics"]["experiment_plan_fingerprint"]
    assert candidate_fingerprint == result["candidate_config"]["fingerprint"]
    assert candidate_fingerprint == result["artifact"]["metrics"][
        "candidate_config_fingerprint"
    ]


def test_splitmix_scalar_split_is_deterministic_and_leaves_all_three_cohorts() -> None:
    labels = [
        _RUNNER._split_label_value(
            index,
            seed=20260830,
            training_fraction=0.5,
            validation_fraction=0.25,
        )
        for index in range(10_000)
    ]

    assert labels == [
        _RUNNER._split_label_value(
            index,
            seed=20260830,
            training_fraction=0.5,
            validation_fraction=0.25,
        )
        for index in range(10_000)
    ]
    assert set(labels) == {0, 1, 2}
    assert 4_700 <= labels.count(0) <= 5_300
    assert 2_200 <= labels.count(1) <= 2_800
    assert 2_200 <= labels.count(2) <= 2_800


def test_full_plan_freezes_visit_top10_and_train_only_propensity() -> None:
    plan = load_targeting_experiment_plan(
        _ROOT / "benchmarks" / "targeting" / "criteo-v2.1-visit-top10.v1.json"
    )

    assert plan.outcome_definition == "visit"
    assert plan.training_fraction == 0.5
    assert plan.validation_fraction == 0.25
    assert plan.holdout_fraction == 0.25
    assert plan.selected_fraction == 0.1
    assert plan.propensity_protocol == "pooled-training-assignment-share-v1"
    assert plan.score_protocol == "fixed-lightgbm-4.7.0-cate-v1"
