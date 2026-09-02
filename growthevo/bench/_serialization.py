"""Internal helpers for strict benchmark JSON parsing and stable serialization."""

from __future__ import annotations

from hashlib import blake2b
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Iterator, Mapping


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize JSON-compatible data using the repository's canonical encoding."""

    return dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint_json(payload: Any) -> str:
    """Return the 160-bit BLAKE2b fingerprint used by benchmark protocols."""

    return blake2b(canonical_json_bytes(payload), digest_size=20).hexdigest()


def load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    """Load one JSON object with consistent benchmark-facing error messages."""

    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid {label} JSON: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    return payload


def iter_jsonl_objects(path: str | Path) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield non-empty JSONL objects together with ``path:line`` source labels."""

    resolved = Path(path)
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = f"{resolved}:{line_number}"
            try:
                payload = loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid JSON on {source}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object on {source}")
            yield payload, source


def required_string(
    payload: Mapping[str, Any],
    key: str,
    *,
    scope: str,
) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{scope} field {key!r} must be a non-empty string")
    return value


def required_number(
    payload: Mapping[str, Any],
    key: str,
    *,
    scope: str,
) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{scope} field {key!r} must be a JSON number")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{scope} field {key!r} must be finite")
    return numeric


def required_int(
    payload: Mapping[str, Any],
    key: str,
    *,
    scope: str,
) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{scope} field {key!r} must be a JSON integer")
    return value


def optional_number(
    payload: Mapping[str, Any],
    key: str,
    *,
    scope: str,
) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{scope} field {key!r} must be a JSON number")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{scope} field {key!r} must be finite")
    return numeric
