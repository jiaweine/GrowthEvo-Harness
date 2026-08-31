from __future__ import annotations

"""Validate the regression-only small-OBD contract.

The small Open Bandit Dataset cohort is exhausted for promotion research. This
validator is therefore deliberately limited to CI regression invariants: exact
protocol/selection structure and narrow absolute tolerances for floating
quantities that can vary slightly across GitHub-hosted CPU/BLAS realizations.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping


EXACT_PATHS = {
    "selected_candidate": ("artifact", "selected_candidate"),
    "estimator": ("artifact", "metrics", "estimator"),
    "candidate_count": ("artifact", "metrics", "candidate_count"),
    "experiment_plan_fingerprint": (
        "artifact",
        "metrics",
        "experiment_plan_fingerprint",
    ),
    "export_manifest_fingerprint": (
        "artifact",
        "metrics",
        "export_manifest_fingerprint",
    ),
    "protocol_fingerprint": ("artifact", "protocol_fingerprint"),
}

NUMERIC_PATHS = {
    "support_coverage": ("artifact", "metrics", "support_coverage"),
    "validation_support_coverage": (
        "artifact",
        "metrics",
        "validation_support_coverage",
    ),
    "effective_sample_ratio": (
        "artifact",
        "metrics",
        "effective_sample_ratio",
    ),
    "validation_effective_sample_ratio": (
        "artifact",
        "metrics",
        "validation_effective_sample_ratio",
    ),
    "estimate": ("artifact", "metrics", "estimate"),
    "standard_error": ("artifact", "metrics", "standard_error"),
    "validation_absolute_error": (
        "artifact",
        "metrics",
        "validation_absolute_error",
    ),
}

REALIZATION_SPECIFIC_FIELDS = {"tuning_fingerprint", "test_fingerprint"}


def _get(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise AssertionError(f"missing regression field: {'.'.join(path)}")
        value = value[key]
    return value


def validate_contract(
    contract: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if contract.get("schema_version") != "growthevo.obd-regression-contract.v1":
        raise AssertionError("unexpected OBD regression-contract schema")
    if contract.get("purpose") != "regression_only_not_promotion_evidence":
        raise AssertionError("small OBD contract must remain regression-only")
    if result.get("schema_version") != "growthevo.locked-ope-run.v3":
        raise AssertionError("unexpected locked OPE result schema")

    artifact = result.get("artifact")
    if not isinstance(artifact, Mapping):
        raise AssertionError("locked OPE result is missing artifact")
    if artifact.get("dataset") != contract.get("dataset"):
        raise AssertionError("small OBD regression dataset identity changed")

    expected = contract.get("expected")
    tolerances = contract.get("absolute_tolerances")
    if not isinstance(expected, Mapping) or not isinstance(tolerances, Mapping):
        raise AssertionError("regression contract is missing expected/tolerance maps")

    for name, path in EXACT_PATHS.items():
        actual = _get(result, path)
        if actual != expected.get(name):
            raise AssertionError(
                f"small OBD regression structure changed for {name}: "
                f"expected {expected.get(name)!r}, got {actual!r}"
            )

    for name, path in NUMERIC_PATHS.items():
        actual = float(_get(result, path))
        target = float(expected[name])
        tolerance = float(tolerances[name])
        if not all(math.isfinite(value) for value in (actual, target, tolerance)):
            raise AssertionError(f"non-finite regression value for {name}")
        if tolerance < 0.0:
            raise AssertionError(f"negative regression tolerance for {name}")
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=tolerance):
            raise AssertionError(
                f"small OBD regression metric drifted for {name}: "
                f"expected {target} +/- {tolerance}, got {actual}"
            )

    realized = contract.get("realization_specific_fields")
    if set(realized or ()) != REALIZATION_SPECIFIC_FIELDS:
        raise AssertionError("realization-specific fingerprint policy changed")
    fingerprints = {name: artifact.get(name) for name in REALIZATION_SPECIFIC_FIELDS}
    if any(not isinstance(value, str) or len(value) != 40 for value in fingerprints.values()):
        raise AssertionError("realized tuning/test fingerprints must be 40-char strings")
    if len(set(fingerprints.values())) != len(fingerprints):
        raise AssertionError("tuning and test fingerprints must remain distinct")

    return {
        "dataset": artifact["dataset"],
        "selected_candidate": artifact["selected_candidate"],
        "protocol_fingerprint": artifact["protocol_fingerprint"],
        "numeric_metrics_checked": sorted(NUMERIC_PATHS),
        "realization_specific_fields": sorted(REALIZATION_SPECIFIC_FIELDS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    with args.contract.open(encoding="utf-8") as handle:
        contract = json.load(handle)
    with args.result.open(encoding="utf-8") as handle:
        result = json.load(handle)

    summary = validate_contract(contract, result)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
