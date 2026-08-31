from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _assert_success_bundle_gate(
    *,
    filename: str,
    verify_step: str,
    hash_step: str,
    upload_step: str,
    bundle_root: str,
    required_relative_paths: tuple[str, ...],
) -> None:
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
    before_upload, upload = workflow.split(f"      - name: {upload_step}\n", maxsplit=1)
    before_hash, hash_section = before_upload.split(f"      - name: {hash_step}\n", maxsplit=1)
    _, verify = before_hash.split(f"      - name: {verify_step}\n", maxsplit=1)

    assert "        if: success()\n" in verify
    assert '            test -s "$path"\n' in verify
    assert "        if: success()\n" in hash_section
    assert "python scripts/write_evidence_integrity_manifest.py" in hash_section
    assert f"--root {bundle_root}" in hash_section
    assert f"--output {bundle_root}/evidence-integrity.json" in hash_section
    assert "        if: always()\n" in upload
    assert "          if-no-files-found: warn\n" in upload
    assert f"{bundle_root}/evidence-integrity.json" in upload

    for relative_path in required_relative_paths:
        absolute_path = f"{bundle_root}/{relative_path}"
        assert absolute_path in verify, (
            f"{absolute_path} is not required by the successful-run evidence gate"
        )
        assert relative_path in hash_section, (
            f"{relative_path} is not covered by the successful-run integrity manifest"
        )
        assert absolute_path in upload, f"{absolute_path} is not persisted by the evidence upload"


def test_full_criteo_success_requires_complete_core_evidence_bundle() -> None:
    _assert_success_bundle_gate(
        filename="full-criteo-pr-validation.yml",
        verify_step="Verify complete full Criteo evidence bundle",
        hash_step="Hash full Criteo core evidence bundle",
        upload_step="Upload full Criteo research evidence",
        bundle_root="/tmp/growthevo-full-criteo",
        required_relative_paths=(
            "dispatch-provenance.json",
            "accepted-constraints.txt",
            "runner-environment.txt",
            "result/source-provenance.json",
            "result/criteo-v2.1-visit-top10.v1.json",
            "result/criteo-lgbm-candidates.v1.json",
            "result/export-manifest.json",
            "result/locked-result.json",
            "result/environment.txt",
        ),
    )


def test_full_obd_success_requires_complete_core_evidence_bundle() -> None:
    _assert_success_bundle_gate(
        filename="full-obd-pr-validation.yml",
        verify_step="Verify complete full OBD evidence bundle",
        hash_step="Hash full OBD core evidence bundle",
        upload_step="Upload full OBD research evidence",
        bundle_root="/tmp/growthevo-full-obd",
        required_relative_paths=(
            "dispatch-provenance.json",
            "accepted-constraints.txt",
            "runner-environment.txt",
            "pip-freeze.txt",
            "result/source-provenance.json",
            "result/obd-full-all-random-to-bts.v1.json",
            "result/export/export_manifest.json",
            "result/export/ope_candidates.json",
            "result/locked-result.json",
        ),
    )
