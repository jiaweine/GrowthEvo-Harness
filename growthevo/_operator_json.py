"""Shared strict JSON validation helpers for the production operator surface."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def _mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _strict_keys(
    payload: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    missing = sorted(required.difference(payload))
    unexpected = sorted(set(payload).difference(allowed))
    if missing:
        raise ValueError(f"{context} is missing required keys: {missing}")
    if unexpected:
        raise ValueError(f"{context} contains unexpected keys: {unexpected}")


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_string(value: Any, *, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context=context)


def _bool(value: Any, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _number(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number")
    converted = float(value)
    if not isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted
