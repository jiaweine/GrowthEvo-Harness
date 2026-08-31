from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "benchmarks" / "ope" / "obd-small-regression-contract.v1.json"
VALIDATOR_PATH = ROOT / "scripts" / "validate_obd_regression_contract.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("obd_regression_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _result_from_contract(contract: dict) -> dict:
    expected = contract["expected"]
    return {
        "schema_version": "growthevo.locked-ope-run.v3",
        "artifact": {
            "dataset": contract["dataset"],
            "selected_candidate": expected["selected_candidate"],
            "protocol_fingerprint": expected["protocol_fingerprint"],
            "tuning_fingerprint": "a" * 40,
            "test_fingerprint": "b" * 40,
            "metrics": {
                "estimator": expected["estimator"],
                "candidate_count": expected["candidate_count"],
                "experiment_plan_fingerprint": expected["experiment_plan_fingerprint"],
                "export_manifest_fingerprint": expected["export_manifest_fingerprint"],
                "support_coverage": expected["support_coverage"],
                "validation_support_coverage": expected["validation_support_coverage"],
                "effective_sample_ratio": expected["effective_sample_ratio"],
                "validation_effective_sample_ratio": expected[
                    "validation_effective_sample_ratio"
                ],
                "estimate": expected["estimate"],
                "standard_error": expected["standard_error"],
                "validation_absolute_error": expected["validation_absolute_error"],
            },
        },
    }


def test_small_obd_regression_contract_is_narrow_and_not_promotion_evidence() -> None:
    contract = _contract()
    assert contract["schema_version"] == "growthevo.obd-regression-contract.v1"
    assert contract["purpose"] == "regression_only_not_promotion_evidence"
    assert set(contract["realization_specific_fields"]) == {
        "tuning_fingerprint",
        "test_fingerprint",
    }
    assert "tuning_fingerprint" not in contract["expected"]
    assert "test_fingerprint" not in contract["expected"]

    tolerances = contract["absolute_tolerances"]
    assert tolerances["support_coverage"] == 0.0
    assert tolerances["validation_support_coverage"] == 0.0
    assert tolerances["effective_sample_ratio"] <= 1e-12
    assert tolerances["validation_effective_sample_ratio"] <= 1e-12
    for name in ("estimate", "standard_error", "validation_absolute_error"):
        assert 0.0 < tolerances[name] <= 1e-6


def test_validator_accepts_observed_host_level_float_variant() -> None:
    validator = _load_validator()
    contract = _contract()
    result = _result_from_contract(contract)

    # Natural hosted-runner realization observed while the dependency, OS,
    # data, plan, support, ESS, and winner identities remained unchanged.
    result["artifact"]["metrics"].update(
        {
            "estimate": 0.0042315911774216865,
            "standard_error": 0.0011956748982700559,
            "validation_absolute_error": 0.0012825687093936632,
        }
    )
    summary = validator.validate_contract(contract, result)
    assert summary["selected_candidate"] == "switch-5"


def test_validator_rejects_structural_or_material_numeric_drift() -> None:
    validator = _load_validator()
    contract = _contract()
    baseline = _result_from_contract(contract)

    changed_winner = deepcopy(baseline)
    changed_winner["artifact"]["selected_candidate"] = "ips"
    with pytest.raises(AssertionError, match="selected_candidate"):
        validator.validate_contract(contract, changed_winner)

    changed_metric = deepcopy(baseline)
    changed_metric["artifact"]["metrics"]["estimate"] += 2e-6
    with pytest.raises(AssertionError, match="estimate"):
        validator.validate_contract(contract, changed_metric)
