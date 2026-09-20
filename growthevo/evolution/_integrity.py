"""Shared canonicalization and identity validators for integrity-sensitive modules."""

from __future__ import annotations

from hashlib import blake2b
import json
from typing import Any


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(payload: Any, *, digest_size: int = 20) -> str:
    return blake2b(_canonical_json(payload), digest_size=digest_size).hexdigest()


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a SHA-256 hex string")
    normalized = value.lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex string")
    return normalized


def _commit_sha(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hexadecimal commit SHA")
    normalized = value.lower()
    if len(normalized) < 7 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{name} must be a hexadecimal commit SHA")
    return normalized
