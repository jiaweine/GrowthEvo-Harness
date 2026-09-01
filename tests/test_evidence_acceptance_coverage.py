from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "verify_evidence_acceptance.py"


def _load_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("evidence_acceptance", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_acceptance_metadata_must_cover_every_integrity_manifest_file() -> None:
    module = _load_module()
    metadata = {
        "source_artifact_file_sha256": {"locked-result.json": "sha256:" + "a" * 64},
        "persisted_copy_format": {"locked-result.json": "byte-identical source artifact copy"},
    }

    with pytest.raises(ValueError, match="must cover every source integrity-manifest file"):
        module._load_copy_contract(
            metadata,
            expected_names={"locked-result.json", "dispatch-provenance.json"},
        )


def test_acceptance_rejects_duplicate_source_basenames() -> None:
    module = _load_module()
    entries = (
        {"path": "result/environment.txt", "sha256": "a" * 64, "size_bytes": 1},
        {"path": "diagnostics/environment.txt", "sha256": "b" * 64, "size_bytes": 1},
    )

    with pytest.raises(ValueError, match="filenames must be unique"):
        module._manifest_entries_by_filename(entries)
