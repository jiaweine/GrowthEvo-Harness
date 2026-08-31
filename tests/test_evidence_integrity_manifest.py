from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "write_evidence_integrity_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evidence_integrity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_evidence_integrity_manifest_is_deterministic_and_portable(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "nested").mkdir()
    (tmp_path / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "nested" / "beta.json").write_text('{"beta": 2}\n', encoding="utf-8")

    first = module.build_manifest(root=tmp_path, files=["nested/beta.json", "alpha.txt"])
    second = module.build_manifest(root=tmp_path, files=["alpha.txt", "nested/beta.json"])

    assert first == second
    assert first["schema_version"] == "growthevo.evidence-integrity.v1"
    assert first["hash_algorithm"] == "sha256"
    assert first["file_count"] == 2
    assert [entry["path"] for entry in first["files"]] == ["alpha.txt", "nested/beta.json"]
    assert first["files"][0]["sha256"] == hashlib.sha256(b"alpha\n").hexdigest()
    assert first["files"][0]["size_bytes"] == len(b"alpha\n")
    assert first["total_size_bytes"] == sum(entry["size_bytes"] for entry in first["files"])


def test_evidence_integrity_writer_round_trips_json(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    output = tmp_path / "integrity.json"

    expected = module.write_manifest(root=tmp_path, output=output, files=["result.json"])

    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert output.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.parametrize("bad_path", ["missing.json", "../escape.json", "/tmp/absolute.json"])
def test_evidence_integrity_manifest_rejects_missing_or_out_of_root_paths(
    tmp_path: Path, bad_path: str
) -> None:
    module = _load_module()
    with pytest.raises((FileNotFoundError, ValueError)):
        module.build_manifest(root=tmp_path, files=[bad_path])


def test_evidence_integrity_manifest_rejects_empty_files(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "empty.txt").write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        module.build_manifest(root=tmp_path, files=["empty.txt"])


def test_evidence_integrity_manifest_rejects_duplicate_paths(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        module.build_manifest(root=tmp_path, files=["result.json", "./result.json"])


def test_evidence_integrity_writer_rejects_output_collision(tmp_path: Path) -> None:
    module = _load_module()
    evidence = tmp_path / "result.json"
    evidence.write_text('{"ok": true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="must not overwrite"):
        module.write_manifest(root=tmp_path, output=evidence, files=["result.json"])


def test_evidence_integrity_writer_rejects_output_outside_root(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-integrity.json"
    with pytest.raises(ValueError, match="must stay under root"):
        module.write_manifest(root=tmp_path, output=outside, files=["result.json"])
