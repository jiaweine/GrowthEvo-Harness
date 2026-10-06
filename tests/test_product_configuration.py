from __future__ import annotations

import argparse

import pytest

pydantic = pytest.importorskip("pydantic")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from growthevo.web.app import MAX_API_BODY_BYTES, create_app
from growthevo.web.cli import (
    _default_graceful_shutdown_seconds,
    _default_limit_concurrency,
    _default_port,
    _default_workers,
    _port,
)
from growthevo.web.decisioning import ACTION_REGISTRY
from growthevo.web.runtime import postgres_pool_config_from_env
from growthevo.web.schemas import ApprovalDecisionRequest, CampaignDraftRequest, DecisionRequest, KNOWN_ACTION_IDS
from scripts.build_pages import normalize_api_base, normalize_oidc_config


def test_pages_api_base_accepts_secure_remote_or_loopback_http_urls() -> None:
    assert normalize_api_base("") == ""
    assert normalize_api_base(" https://api.example.com/root/ ") == "https://api.example.com/root"
    assert normalize_api_base("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    assert normalize_api_base("http://localhost:8765") == "http://localhost:8765"
    for value in ("api.example.com", "javascript:alert(1)", "https://user:secret@example.com", "https://api.example.com?token=secret", "https://api.example.com/#fragment", "https://api.example.com/bad path", "http://api.example.com"):
        with pytest.raises(ValueError):
            normalize_api_base(value)


def test_pages_oidc_config_is_public_pkce_metadata_only() -> None:
    disabled = normalize_oidc_config()
    assert disabled["ENABLED"] is False
    assert disabled["SCOPE"] == "openid profile email"

    enabled = normalize_oidc_config(
        "https://identity.example.test/authorize",
        "https://identity.example.test/token",
        "growthevo-web",
        "growthevo-api",
        "openid profile email",
    )
    assert enabled == {
        "ENABLED": True,
        "AUTHORIZATION_ENDPOINT": "https://identity.example.test/authorize",
        "TOKEN_ENDPOINT": "https://identity.example.test/token",
        "CLIENT_ID": "growthevo-web",
        "AUDIENCE": "growthevo-api",
        "SCOPE": "openid profile email",
    }

    with pytest.raises(ValueError, match="requires authorization endpoint"):
        normalize_oidc_config(
            "https://identity.example.test/authorize",
            None,
            "growthevo-web",
        )
    with pytest.raises(ValueError, match="remote GROWTHEVO_OIDC_TOKEN_ENDPOINT must use https"):
        normalize_oidc_config(
            "https://identity.example.test/authorize",
            "http://identity.example.test/token",
            "growthevo-web",
        )
    with pytest.raises(ValueError, match="must include openid"):
        normalize_oidc_config(
            "https://identity.example.test/authorize",
            "https://identity.example.test/token",
            "growthevo-web",
            scope="profile email",
        )


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


def test_production_capacity_controls_are_explicit_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GROWTHEVO_WEB_WORKERS",
        "GROWTHEVO_HTTP_LIMIT_CONCURRENCY",
        "GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS",
        "GROWTHEVO_DB_POOL_MIN_SIZE",
        "GROWTHEVO_DB_POOL_MAX_SIZE",
        "GROWTHEVO_DB_POOL_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _default_workers() == 1
    assert _default_limit_concurrency() == 512
    assert _default_graceful_shutdown_seconds() == 55
    pool = postgres_pool_config_from_env()
    assert (pool.min_size, pool.max_size, pool.timeout_seconds) == (1, 8, 5.0)

    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    assert _default_workers() == 1

    monkeypatch.setenv("GROWTHEVO_WEB_WORKERS", "2")
    monkeypatch.setenv("GROWTHEVO_HTTP_LIMIT_CONCURRENCY", "768")
    monkeypatch.setenv("GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS", "60")
    monkeypatch.setenv("GROWTHEVO_DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("GROWTHEVO_DB_POOL_MAX_SIZE", "12")
    monkeypatch.setenv("GROWTHEVO_DB_POOL_TIMEOUT_SECONDS", "3.5")
    assert _default_workers() == 2
    assert _default_limit_concurrency() == 768
    assert _default_graceful_shutdown_seconds() == 60
    pool = postgres_pool_config_from_env()
    assert (pool.min_size, pool.max_size, pool.timeout_seconds) == (2, 12, 3.5)

    monkeypatch.setenv("GROWTHEVO_DB_POOL_MIN_SIZE", "20")
    monkeypatch.setenv("GROWTHEVO_DB_POOL_MAX_SIZE", "8")
    with pytest.raises(ValueError, match="MAX_SIZE must be >= GROWTHEVO_DB_POOL_MIN_SIZE"):
        postgres_pool_config_from_env()

    monkeypatch.setenv("GROWTHEVO_WEB_WORKERS", "0")
    with pytest.raises(ValueError, match="GROWTHEVO_WEB_WORKERS"):
        _default_workers()


def test_decision_request_rejects_unknown_safety_fields() -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        DecisionRequest(entity_id="u-extra", placement="checkout", consent_sate=False)
    assert "consent_sate" in str(exc_info.value)
    assert "extra_forbidden" in str(exc_info.value)


def test_decision_request_requires_real_boolean_consent() -> None:
    with pytest.raises(pydantic.ValidationError):
        DecisionRequest(entity_id="u-consent", placement="checkout", consent_state="yes")


def test_decision_request_rejects_non_finite_budget() -> None:
    with pytest.raises(pydantic.ValidationError):
        DecisionRequest(entity_id="u-inf", placement="checkout", budget_remaining=float("inf"))


def test_schema_action_ids_cannot_drift_from_registry() -> None:
    assert KNOWN_ACTION_IDS == frozenset(ACTION_REGISTRY)
    with pytest.raises(pydantic.ValidationError, match="unknown candidate_action_ids"):
        DecisionRequest(entity_id="u-action-typo", placement="checkout", candidate_action_ids=["free_shiping_legacy"])


def test_campaign_draft_always_keeps_no_treatment_control() -> None:
    request = CampaignDraftRequest(name="safe draft", goal="preserve safe control", audience="new users", budget=1000, candidate_action_ids=["free_shipping", "free_shipping"])
    assert request.candidate_action_ids == ["NO_TREATMENT", "free_shipping"]


def test_approval_decisions_require_nonempty_audit_note() -> None:
    with pytest.raises(pydantic.ValidationError):
        ApprovalDecisionRequest(decision="approve_5", note="   ")
    valid = ApprovalDecisionRequest(decision="reject", note="  risk exceeds guardrail  ")
    assert valid.note == "risk exceeds guardrail"


def test_not_ready_production_blocks_business_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("GROWTHEVO_ENV", "test-production")
    client = TestClient(create_app())
    assert client.get("/api/health").status_code == 200
    ready = client.get("/api/ready")
    assert ready.status_code == 503
    assert ready.json()["authentication"]["active"] is False
    assert client.get("/api/system/runtime").status_code == 200
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 503
    assert "fail-closed" in dashboard.json()["detail"]
    decision = client.post("/api/decide", json={"entity_id": "u-prod", "placement": "checkout"})
    assert decision.status_code == 503


def test_auth_configuration_is_not_fake_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("GROWTHEVO_AUTH_ISSUER", "https://identity.example.test")
    client = TestClient(create_app())
    payload = client.get("/api/ready").json()
    assert payload["authentication"] == {"configured": True, "active": False, "backend": "none"}
    connector = next(item for item in payload["connectors"] if item["id"] == "authentication")
    assert connector["state"] == "configured_not_active"


def test_production_cors_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", "http://public.example.test")
    with pytest.raises(ValueError, match="must use https"):
        create_app()
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", "https://public.example.test")
    client = TestClient(create_app())
    response = client.options("/api/dashboard", headers={"Origin": "https://public.example.test", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://public.example.test"


def test_fail_closed_production_response_keeps_exact_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    origin = "https://jiaweine.github.io"
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", origin)
    client = TestClient(create_app())
    response = client.get("/api/dashboard", headers={"Origin": origin})
    assert response.status_code == 503
    assert response.headers.get("access-control-allow-origin") == origin


def test_declared_oversized_api_body_is_rejected_before_parsing() -> None:
    client = TestClient(create_app())
    response = client.post("/api/agent/plan", content=b"{}", headers={"Content-Length": str(MAX_API_BODY_BYTES + 1), "Content-Type": "application/json"})
    assert response.status_code == 413


def test_actual_oversized_body_is_rejected_even_if_declared_length_lies() -> None:
    client = TestClient(create_app())
    body = b"x" * (MAX_API_BODY_BYTES + 1)
    response = client.post("/api/agent/plan", content=body, headers={"Content-Length": "1", "Content-Type": "application/json"})
    assert response.status_code == 413


def test_body_limit_error_keeps_exact_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    origin = "https://jiaweine.github.io"
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", origin)
    client = TestClient(create_app())
    response = client.post("/api/agent/plan", content=b"{}", headers={"Origin": origin, "Content-Length": str(MAX_API_BODY_BYTES + 1), "Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == origin
