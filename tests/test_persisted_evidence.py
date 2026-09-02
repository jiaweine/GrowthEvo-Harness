from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CRITEO = ROOT / "benchmarks" / "targeting" / "results" / "criteo-v2.1-visit-top10" / "7ac26a5a"
OBD = ROOT / "benchmarks" / "ope" / "results" / "obd-full-all-random-to-bts" / "7d538cea"

CRITEO_MACHINE_BLOBS = {
    "criteo-lgbm-candidates.v1.json": "75bd1f8b55b1b1d292d56e5a225fbf680b0c38e2",
    "criteo-v2.1-visit-top10.v1.json": "3ac7306276c6ea3eb8fd4880556a47b2775fb66c",
    "environment.txt": "df4cc3e611cb0fadc27c23588848a6f71e032a00",
    "evidence-metadata.json": "f70b0a0441a79069f310cd9cda225e120424b636",
    "export-manifest.json": "4d3fb31f355278531e712c615713777abf207dae",
    "locked-result.json": "78d466574b4fdf22f5dacd575df72da767860249",
    "source-provenance.json": "974a2fb5d3a2e3db5588f733301ebbb0b3cafec5",
}

OBD_MACHINE_BLOBS = {
    "environment.txt": "709f941a9e6206392d29a6e9ce58a799f96643fc",
    "evidence-metadata.json": "03a959ca71620f342a7fa1e774179080523dc48f",
    "export-manifest.json": "59d34c7cfb38f341c13af0642d552e2f3a0a1f65",
    "locked-result.json": "26e48927dfb20a4682046139452114c4298128e9",
    "source-provenance.json": "a27c984ae4ab781ac090f1b8a833aa678428a1b2",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    payload = f"blob {len(content)}\0".encode() + content
    return sha1(payload, usedforsecurity=False).hexdigest()


def _assert_machine_evidence_blobs(directory: Path, expected: dict[str, str]) -> None:
    actual = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != "README.md"
    }
    assert actual == set(expected)
    for filename, blob_sha in expected.items():
        assert _git_blob_sha1(directory / filename) == blob_sha


def test_accepted_evidence_machine_records_are_immutable() -> None:
    # These are identities of the persisted repository copies, not the source
    # workflow-artifact SHA256 values. This locks the complete machine record,
    # including compact OBD JSON fields that are not individually asserted below.
    _assert_machine_evidence_blobs(CRITEO, CRITEO_MACHINE_BLOBS)
    _assert_machine_evidence_blobs(OBD, OBD_MACHINE_BLOBS)


def test_criteo_persisted_evidence_is_byte_identical_and_self_consistent() -> None:
    metadata = _json(CRITEO / "evidence-metadata.json")
    expected = {
        "evidence_commit_sha": "7ac26a5aebde2c70e1b43264b89f08dddcff0245",
        "experiment_plan_fingerprint": "28a0ee4516199f2235bc9d52653cc8ab7ec28f5d",
        "candidate_config_fingerprint": "e10eb2fc6552b28109b67cfe075b55fd1d0e8f62",
        "export_manifest_fingerprint": "f765bf351f6b4e2e11fcc464ebd115fddf77520c",
        "protocol_fingerprint": "95a3209a87ad8aa3b7b6d9f3933fade51cb3c9fe",
        "tuning_fingerprint": "dedf85dec29c0f6731a81bcb52d1e3e6db379de4",
        "test_fingerprint": "3b187bd143e729b7d2ee60c8f28c5f438ec61709",
        "workflow_artifact_digest": "sha256:bbdc93a306e532ba6f880dadf409808b65c3dea872a7b41032f4b2e09819ada0",
    }
    for key, value in expected.items():
        assert metadata[key] == value

    for filename, digest in metadata["source_artifact_file_sha256"].items():
        if filename == "full-run.log":
            continue
        assert _sha256(CRITEO / filename) == digest

    result = _json(CRITEO / "locked-result.json")
    artifact = result["artifact"]
    metrics = artifact["metrics"]
    assert artifact["commit_sha"] == expected["evidence_commit_sha"]
    assert artifact["selected_candidate"] == "s-lgbm"
    assert artifact["protocol_fingerprint"] == expected["protocol_fingerprint"]
    assert artifact["tuning_fingerprint"] == expected["tuning_fingerprint"]
    assert artifact["test_fingerprint"] == expected["test_fingerprint"]
    assert result["experiment_plan"]["fingerprint"] == expected["experiment_plan_fingerprint"]
    assert result["candidate_config"]["fingerprint"] == expected["candidate_config_fingerprint"]
    assert metrics["export_manifest_fingerprint"] == expected["export_manifest_fingerprint"]
    assert metrics["sample_size"] == 3_495_070
    assert metrics["incremental_value_vs_none"] == pytest.approx(0.009379102424541465)
    assert metrics["selected_incremental_value"] == pytest.approx(0.09379102424541465)

    validation = {
        row["candidate_name"]: row["incremental_value_vs_none"]
        for row in result["validation_scores"]
    }
    assert max(validation, key=validation.get) == "s-lgbm"

    provenance = _json(CRITEO / "source-provenance.json")
    manifest = _json(CRITEO / "export-manifest.json")
    assert provenance["growth_evo_commit_sha"] == expected["evidence_commit_sha"]
    assert manifest["candidate_config_fingerprint"] == expected["candidate_config_fingerprint"]
    assert manifest["source_rows"] == 13_979_592
    assert manifest["holdout_score_policy"] == "winner-only-after-validation-freeze"


def test_obd_persisted_evidence_is_semantically_locked() -> None:
    metadata = _json(OBD / "evidence-metadata.json")
    expected = {
        "evidence_commit_sha": "7d538cea9698b5f0a48c585eed85e3ae526e5af6",
        "experiment_plan_fingerprint": "4466cd81502843a349e52fc00f1e834e1a28b98b",
        "export_manifest_fingerprint": "9c377a8a69bd158c477c1f789f0e57b150abdbfa",
        "protocol_fingerprint": "b9206804bde8752a88b2a03bbda4b648f648f891",
        "tuning_fingerprint": "3f4698265dc1e1f77003788e8b48e2347b826cf5",
        "test_fingerprint": "d93bdd9361bd9d5d7d6e8552f67b0134600474c1",
        "workflow_artifact_digest": "sha256:b7dbd5afbb331de40b73b5657f7ccdd753ac4c894921dc08dc5d6373c082cc83",
    }
    for key, value in expected.items():
        assert metadata[key] == value

    assert _sha256(OBD / "environment.txt") == metadata["source_artifact_file_sha256"]["environment.txt"]

    result = _json(OBD / "locked-result.json")
    artifact = result["artifact"]
    metrics = artifact["metrics"]
    assert artifact["commit_sha"] == expected["evidence_commit_sha"]
    assert artifact["selected_candidate"] == "ips"
    assert artifact["protocol_fingerprint"] == expected["protocol_fingerprint"]
    assert artifact["tuning_fingerprint"] == expected["tuning_fingerprint"]
    assert artifact["test_fingerprint"] == expected["test_fingerprint"]
    assert result["experiment_plan"]["fingerprint"] == expected["experiment_plan_fingerprint"]
    assert result["experiment_plan"]["export_manifest_fingerprint"] == expected["export_manifest_fingerprint"]
    assert metrics["experiment_plan_fingerprint"] == expected["experiment_plan_fingerprint"]
    assert metrics["export_manifest_fingerprint"] == expected["export_manifest_fingerprint"]
    assert metrics["candidate_count"] == 9
    assert metrics["support_coverage"] == pytest.approx(1.0)
    assert metrics["effective_sample_ratio"] == pytest.approx(0.16123376175710658)
    assert metrics["relative_error"] == pytest.approx(0.09200450319098702)

    validation = {
        row["candidate"]["name"]: row["absolute_error"]
        for row in result["validation_scores"]
    }
    assert min(validation, key=validation.get) == "ips"

    provenance = _json(OBD / "source-provenance.json")
    assert provenance["growth_evo_commit_sha"] == expected["evidence_commit_sha"]


def test_readme_surfaces_only_current_locked_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "**Evidence commit:** `7ac26a5aebde2c70e1b43264b89f08dddcff0245`" in readme
    assert "| Population incremental visit | **+0.93791 pp** |" in readme
    assert "| Selected top-10% incremental visit | **+9.37910 pp** |" in readme

    assert "**Evidence commit:** `7d538cea9698b5f0a48c585eed85e3ae526e5af6`" in readme
    assert "| Final estimate | **0.0045295435** |" in readme
    assert "| Final support coverage | **1.0000** |" in readme
    assert "| Final ESS ratio | **0.16123** |" in readme

    assert "+6.8%" not in readme
    assert "-8.4%" not in readme
