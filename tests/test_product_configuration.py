from __future__ import annotations

import argparse

import pytest

pydantic = pytest.importorskip("pydantic")

from growthevo.web.cli import _default_port, _port
from growthevo.web.schemas import DecisionRequest
from scripts.build_pages import normalize_api_base


def test_pages_api_base_accepts_only_absolute_http_urls() -> None:
    assert normalize_api_base("") == ""
    assert normalize_api_base(" https://api.example.com/v1/ ") == "https://api.example.com/v1"
    assert normalize_api_base("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    for value in (
        "api.example.com",
        "javascript:alert(1)",
        "https://user:secret@example.com",
        "https://api.example.com?token=secret",
        "https://api.example.com/#fragment",
        "https://api.example.com/bad path",
    ):
        with pytest.raises(ValueError):
            normalize_api_base(value)


def test_configured_port_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("GROWTHEVO_PORT", raising=False)
    assert _default_port() == 8765

    monkeypatch.setenv("PORT", "9000")
    assert _default_port() == 9000

    monkeypatch.setenv("PORT", "not-a-port")
    with pytest.raises(ValueError, match="invalid PORT"):
        _default_port()

    for value in ("0", "65536", "-1", "abc"):
        with pytest.raises(argparse.ArgumentTypeError):
            _port(value)


def test_decision_request_rejects_unknown_safety_fields() -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        DecisionRequest(
            entity_id="u-extra",
            placement="checkout",
            consent_sate=False,
        )
    assert "consent_sate" in str(exc_info.value)
    assert "extra_forbidden" in str(exc_info.value)


def test_decision_request_rejects_non_finite_budget() -> None:
    with pytest.raises(pydantic.ValidationError):
        DecisionRequest(
            entity_id="u-inf",
            placement="checkout",
            budget_remaining=float("inf"),
        )
