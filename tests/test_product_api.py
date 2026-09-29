from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from growthevo.web.app import create_app


def test_product_api_health_dashboard_and_opportunities() -> None:
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.json()["status"] == "ok"
    assert health.headers["X-GrowthEvo-Mode"]
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["api_version"] == "v1"
    opportunities = client.get("/api/v1/opportunities")
    assert opportunities.status_code == 200
    assert opportunities.json()[0]["evidence_tier"] in {"A", "B", "C", "D"}


def test_runtime_contract_is_public_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    client = TestClient(create_app())
    runtime = client.get("/api/v1/system/runtime").json()
    assert runtime["mode"] == "demo"
    assert runtime["data_mode"] == "synthetic"
    assert runtime["side_effects_enabled"] is False
    assert runtime["execution_mode"] == "reference-only"
    assert runtime["persistence"]["configured"] is False
    assert client.get("/api/ready").status_code == 200


def test_production_readiness_requires_durable_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_runtime_never_exposes_database_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://private_user:private_password@db.example.test:5432/growthevo")
    client = TestClient(create_app())
    response = client.get("/api/ready")
    assert response.status_code == 200
    payload_text = response.text
    assert "private_password" not in payload_text
    assert "private_user" not in payload_text
    assert response.json()["persistence"]["host"] == "db.example.test"


def test_pages_origin_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    origin = "https://jiaweine.github.io"
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", origin)
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/dashboard",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def _decision_request() -> dict[str, object]:
    return {
        "entity_id": "user-api-1",
        "placement": "checkout_banner",
        "context": {"cart_value": 198, "session_intent": "high", "new_user": True},
        "candidate_action_ids": ["NO_TREATMENT", "free_shipping_v3"],
        "consent_state": True,
        "frequency_remaining": 2,
        "budget_remaining": 50,
        "context_freshness_seconds": 10,
    }


def test_product_api_decision_contract() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/decide",
        headers={"Idempotency-Key": "api-test-1"},
        json=_decision_request(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"].startswith("dec_")
    assert 0 < payload["propensity"] <= 1
    assert payload["policy_version"]
    assert payload["engine_mode"] == "reference-contract"


def test_realtime_console_alias_uses_same_decision_contract() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/realtime/decision",
        headers={"Idempotency-Key": "api-test-realtime-1"},
        json=_decision_request(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"].startswith("dec_")
    assert payload["action_id"] in {"NO_TREATMENT", "free_shipping_v3"}
    assert payload["engine_mode"] == "reference-contract"


def test_product_api_agent_and_approval_workflow() -> None:
    client = TestClient(create_app())
    plan = client.post(
        "/api/v1/agent/plan",
        json={"goal": "提升节前新用户首购", "budget_limit": 500000, "guardrails": ["unsubscribe_rate"]},
    )
    assert plan.status_code == 200
    assert plan.json()["next_gate"] == "Shadow preflight"

    approvals = client.get("/api/v1/approvals").json()
    approval_id = approvals[0]["id"]
    result = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve_5", "note": "API test"},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "approve_5"
