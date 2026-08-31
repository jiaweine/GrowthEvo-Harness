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


def _normalize_files(files: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in files:
        relative_path = Path(raw)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"evidence path must stay under root: {raw}")
        relative = relative_path.as_posix()
        if relative in {"", "."}:
            raise ValueError("evidence path must name a file")
        if relative in seen:
            raise ValueError(f"duplicate evidence path: {relative}")
        seen.add(relative)
        normalized.append(relative)
    if not normalized:
        raise ValueError("at least one evidence file is required")
    return tuple(sorted(normalized))


def build_manifest(*, root: Path, files: Iterable[str]) -> dict[str, object]:
    root = root.resolve()
    normalized = _normalize_files(files)

    entries: list[dict[str, object]] = []
    total_size = 0
    for relative in normalized:
        relative_path = Path(relative)
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
                "path": relative,
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
    root = root.resolve()
    normalized = _normalize_files(files)
    output = output.resolve()
    if not output.is_relative_to(root):
        raise ValueError("integrity manifest output must stay under root")
    output_relative = output.relative_to(root).as_posix()
    if output_relative in normalized:
        raise ValueError("integrity manifest output must not overwrite an evidence file")

    manifest = build_manifest(root=root, files=normalized)
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
