from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEAL = ROOT / "benchmarks" / "accepted-evidence-integrity.v1.json"
VERIFIER = ROOT / "scripts" / "verify_accepted_evidence_integrity.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_ACCEPTED_EVIDENCE_PATHS = {
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/criteo-lgbm-candidates.v1.json",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/criteo-v2.1-visit-top10.v1.json",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/environment.txt",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/evidence-metadata.json",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/export-manifest.json",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/locked-result.json",
    "benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/source-provenance.json",
    "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/environment.txt",
    "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/evidence-metadata.json",
    "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/export-manifest.json",
    "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/locked-result.json",
    "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/source-provenance.json",
}


def test_accepted_evidence_seal_covers_exact_machine_readable_evidence() -> None:
    assert VERIFIER.is_file()
    payload = json.loads(SEAL.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "growthevo.accepted-evidence-integrity.v1"
    assert payload["git_object_format"] == "sha1"
    assert [item["name"] for item in payload["evidence_sets"]] == [
        "criteo-v2.1-visit-top10/7ac26a5a",
        "obd-full-all-random-to-bts/7d538cea",
    ]
    sealed_paths = {
        entry["path"]
        for evidence_set in payload["evidence_sets"]
        for entry in evidence_set["files"]
    }
    assert sealed_paths == EXPECTED_ACCEPTED_EVIDENCE_PATHS
    assert all(not path.endswith("/README.md") for path in sealed_paths)


def test_package_ci_fails_closed_on_accepted_evidence_drift() -> None:
    ci = CI.read_text(encoding="utf-8")
    package = ci.split("  package:\n", maxsplit=1)[1].split(
        "  obd-integration:\n", maxsplit=1
    )[0]
    command = "python scripts/verify_accepted_evidence_integrity.py"

    assert "Verify accepted full-data evidence seal" in package
    assert command in package
    assert package.index(command) < package.index("python -m build")
