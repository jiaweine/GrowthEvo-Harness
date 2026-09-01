from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _section(workflow: str, start: str, end: str) -> str:
    return workflow.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def test_full_run_log_is_required_hashed_and_uploaded_for_full_data_evidence() -> None:
    cases = (
        (
            "full-criteo-pr-validation.yml",
            "Verify complete full Criteo evidence bundle",
            "Hash full Criteo core evidence bundle",
            "/tmp/growthevo-full-criteo/full-run.log",
        ),
        (
            "full-obd-pr-validation.yml",
            "Verify complete full OBD evidence bundle",
            "Hash full OBD core evidence bundle",
            "/tmp/growthevo-full-obd/full-run.log",
        ),
    )
    for filename, verify_name, hash_name, absolute_log in cases:
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")

        verify = _section(
            workflow,
            f"      - name: {verify_name}\n",
            f"      - name: {hash_name}\n",
        )
        assert absolute_log in verify
        assert 'test -s "$path"' in verify

        hashed = _section(
            workflow,
            f"      - name: {hash_name}\n",
            "      - name: Upload full ",
        )
        assert "full-run.log" in hashed
        assert "write_evidence_integrity_manifest.py" in hashed

        upload = workflow.split("      - name: Upload full ", maxsplit=1)[1]
        assert absolute_log in upload
