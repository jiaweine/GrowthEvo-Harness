from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "growthevo.evidence-integrity.v1"
_CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(*, root: Path, files: Iterable[str]) -> dict[str, object]:
    root = root.resolve()
    normalized = sorted(set(files))
    if not normalized:
        raise ValueError("at least one evidence file is required")

    entries: list[dict[str, object]] = []
    total_size = 0
    for relative in normalized:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"evidence path must stay under root: {relative}")

        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"evidence path escapes root: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"missing evidence file: {relative}")

        size = path.stat().st_size
        if size <= 0:
            raise ValueError(f"evidence file is empty: {relative}")

        total_size += size
        entries.append(
            {
                "path": relative_path.as_posix(),
                "sha256": _sha256(path),
                "size_bytes": size,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "file_count": len(entries),
        "total_size_bytes": total_size,
        "files": entries,
    }


def write_manifest(*, root: Path, output: Path, files: Iterable[str]) -> dict[str, object]:
    manifest = build_manifest(root=root, files=files)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate non-empty evidence files and write a deterministic SHA-256 integrity manifest."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("files", nargs="+")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = write_manifest(root=args.root, output=args.output, files=args.files)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
