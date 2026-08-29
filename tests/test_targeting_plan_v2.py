from __future__ import annotations

import json
from pathlib import Path

import pytest

from growthevo.bench.targeting_experiment_plan import load_targeting_experiment_plan


_FINGERPRINT = "0123456789abcdef0123456789abcdef01234567"


def _v2_plan() -> dict[str, object]:
    return {
        "schema_version": "growthevo.targeting-experiment-plan.v2",
        "benchmark": "criteo-targeting-full-evidence",
        "dataset": "criteo-uplift-v2.1",
        "dataset_source": "fixture:criteo-v2.1:sha256:abc",
        "outcome_definition": "visit",
        "split_strategy": "stable_hash_source_row_v1",
        "training_fraction": 0.5,
        "validation_fraction": 0.25,
        "split_seed": 20260830,
        "treatment": "ads",
        "selected_fraction": 0.1,
        "propensity_protocol": "pooled-training-assignment-share-v1",
        "score_protocol": "fixed-cate-candidate-config-v1",
        "candidate_config_fingerprint": _FINGERPRINT,
        "candidate_names": ["s-lgbm", "t-lgbm", "x-lgbm", "r-lgbm", "dr-lgbm"],
    }


def _manifest() -> dict[str, object]:
    plan = _v2_plan()
    return {
        "schema_version": "growthevo.targeting-export.v2",
        "dataset_source": plan["dataset_source"],
        "outcome_definition": plan["outcome_definition"],
        "split_strategy": plan["split_strategy"],
        "training_fraction": plan["training_fraction"],
        "validation_fraction": plan["validation_fraction"],
        "split_seed": plan["split_seed"],
        "treatment": plan["treatment"],
        "propensity_protocol": plan["propensity_protocol"],
        "score_protocol": plan["score_protocol"],
        "candidate_config_fingerprint": plan["candidate_config_fingerprint"],
        "candidate_names": list(reversed(plan["candidate_names"])),
    }


def _load(tmp_path: Path, payload: dict[str, object]):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_targeting_experiment_plan(path)


def test_v2_plan_binds_training_split_propensity_and_candidate_config(tmp_path: Path) -> None:
    plan = _load(tmp_path, _v2_plan())

    assert plan.training_fraction == pytest.approx(0.5)
    assert plan.validation_fraction == pytest.approx(0.25)
    assert plan.holdout_fraction == pytest.approx(0.25)
    assert plan.split_seed == 20260830
    assert plan.propensity_protocol == "pooled-training-assignment-share-v1"
    assert plan.candidate_config_fingerprint == _FINGERPRINT
    canonical = plan.canonical_payload()
    assert canonical["training_fraction"] == pytest.approx(0.5)
    assert canonical["split_seed"] == 20260830
    assert canonical["candidate_config_fingerprint"] == _FINGERPRINT
    assert len(plan.fingerprint) == 40
    plan.validate_export_manifest(_manifest())


def test_v2_plan_requires_a_nonempty_final_holdout(tmp_path: Path) -> None:
    payload = _v2_plan()
    payload["training_fraction"] = 0.75
    with pytest.raises(ValueError, match="leave a holdout"):
        _load(tmp_path, payload)


def test_v2_plan_rejects_bool_split_seed_and_noncanonical_fingerprint(tmp_path: Path) -> None:
    payload = _v2_plan()
    payload["split_seed"] = True
    with pytest.raises(ValueError, match="split_seed.*JSON integer"):
        _load(tmp_path, payload)

    payload = _v2_plan()
    payload["candidate_config_fingerprint"] = "not-a-digest"
    with pytest.raises(ValueError, match="40-character lowercase hex"):
        _load(tmp_path, payload)


def test_v2_manifest_drift_fails_closed(tmp_path: Path) -> None:
    plan = _load(tmp_path, _v2_plan())

    with pytest.raises(ValueError, match="training_fraction"):
        plan.validate_export_manifest({**_manifest(), "training_fraction": 0.4})
    with pytest.raises(ValueError, match="propensity_protocol"):
        plan.validate_export_manifest(
            {**_manifest(), "propensity_protocol": "full-data-propensity-leak"}
        )
    with pytest.raises(ValueError, match="candidate_config_fingerprint"):
        plan.validate_export_manifest(
            {**_manifest(), "candidate_config_fingerprint": "f" * 40}
        )


def test_v1_plan_remains_byte_contract_compatible(tmp_path: Path) -> None:
    payload = {
        "schema_version": "growthevo.targeting-experiment-plan.v1",
        "benchmark": "legacy-targeting-fixture",
        "dataset": "fixture",
        "dataset_source": "fixture:v1",
        "outcome_definition": "conversion",
        "split_strategy": "stable_hash_unit_id_v1",
        "validation_fraction": 0.5,
        "treatment": "ads",
        "selected_fraction": 0.5,
        "score_protocol": "external-precomputed-cate-scores-v1",
        "candidate_names": ["a", "b"],
    }
    plan = _load(tmp_path, payload)

    assert plan.training_fraction is None
    assert plan.holdout_fraction is None
    assert plan.canonical_payload() == {
        **payload,
        "candidate_names": ["a", "b"],
    }
