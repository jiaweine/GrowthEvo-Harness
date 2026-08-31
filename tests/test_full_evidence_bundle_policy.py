from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _assert_success_bundle_gate(
    *,
    filename: str,
    verify_step: str,
    upload_step: str,
    required_paths: tuple[str, ...],
) -> None:
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
    before_upload, upload = workflow.split(f"      - name: {upload_step}\n", maxsplit=1)
    _, verify = before_upload.split(f"      - name: {verify_step}\n", maxsplit=1)

    assert "        if: success()\n" in verify
    assert '            test -s "$path"\n' in verify
    assert "        if: always()\n" in upload
    assert "          if-no-files-found: warn\n" in upload

    for path in required_paths:
        assert path in verify, f"{path} is not required by the successful-run evidence gate"
        assert path in upload, f"{path} is not persisted by the evidence upload"


def test_full_criteo_success_requires_complete_core_evidence_bundle() -> None:
    _assert_success_bundle_gate(
        filename="full-criteo-pr-validation.yml",
        verify_step="Verify complete full Criteo evidence bundle",
        upload_step="Upload full Criteo research evidence",
        required_paths=(
            "/tmp/growthevo-full-criteo/dispatch-provenance.json",
            "/tmp/growthevo-full-criteo/accepted-constraints.txt",
            "/tmp/growthevo-full-criteo/runner-environment.txt",
            "/tmp/growthevo-full-criteo/result/source-provenance.json",
            "/tmp/growthevo-full-criteo/result/criteo-v2.1-visit-top10.v1.json",
            "/tmp/growthevo-full-criteo/result/criteo-lgbm-candidates.v1.json",
            "/tmp/growthevo-full-criteo/result/export-manifest.json",
            "/tmp/growthevo-full-criteo/result/locked-result.json",
            "/tmp/growthevo-full-criteo/result/environment.txt",
        ),
    )


def test_full_obd_success_requires_complete_core_evidence_bundle() -> None:
    _assert_success_bundle_gate(
        filename="full-obd-pr-validation.yml",
        verify_step="Verify complete full OBD evidence bundle",
        upload_step="Upload full OBD research evidence",
        required_paths=(
            "/tmp/growthevo-full-obd/dispatch-provenance.json",
            "/tmp/growthevo-full-obd/accepted-constraints.txt",
            "/tmp/growthevo-full-obd/runner-environment.txt",
            "/tmp/growthevo-full-obd/pip-freeze.txt",
            "/tmp/growthevo-full-obd/result/source-provenance.json",
            "/tmp/growthevo-full-obd/result/obd-full-all-random-to-bts.v1.json",
            "/tmp/growthevo-full-obd/result/export/export_manifest.json",
            "/tmp/growthevo-full-obd/result/export/ope_candidates.json",
            "/tmp/growthevo-full-obd/result/locked-result.json",
        ),
    )
