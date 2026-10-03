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
    assert health.json()["api"] == "stable"
    assert health.headers["X-GrowthEvo-Mode"]
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["api_contract"] == "stable"
    opportunities = client.get("/api/opportunities")
    assert opportunities.status_code == 200
    assert opportunities.json()[0]["evidence_tier"] in {"A", "B", "C", "D"}


def test_runtime_contract_is_public_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    client = TestClient(create_app())
    runtime = client.get("/api/system/runtime").json()
    assert runtime["mode"] == "demo"
    assert runtime["data_mode"] == "synthetic"
    assert runtime["side_effects_enabled"] is False
    assert runtime["execution_mode"] == "reference-only"
    assert runtime["persistence"]["configured"] is False
    assert runtime["persistence"]["active"] is False
    assert runtime["persistence"]["backend"] == "reference-memory"
    assert client.get("/api/ready").status_code == 200


def test_invalid_runtime_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "prodution")
    with pytest.raises(ValueError, match="invalid GROWTHEVO_MODE"):
        create_app()


def test_production_readiness_requires_active_durable_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["persistence"]["active"] is False


def test_database_url_is_configuration_not_fake_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://private_user:private_password@db.example.test:5432/growthevo")
    client = TestClient(create_app())
    response = client.get("/api/ready")
    assert response.status_code == 503
    payload_text = response.text
    assert "private_password" not in payload_text
    assert "private_user" not in payload_text
    assert "db.example.test" not in payload_text
    payload = response.json()
    assert payload["persistence"]["configured"] is True
    assert payload["persistence"]["active"] is False
    assert "host" not in payload["persistence"]
    assert payload["persistence"]["backend"] == "reference-memory"
    connector = next(item for item in payload["connectors"] if item["id"] == "persistence")
    assert connector["state"] == "configured_not_active"


def test_pages_origin_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    origin = "https://jiaweine.github.io"
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", origin)
    client = TestClient(create_app())
    response = client.options(
        "/api/dashboard",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_configuration_rejects_wildcards_and_non_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcards"):
        create_app()
    monkeypatch.setenv("GROWTHEVO_CORS_ORIGINS", "https://example.com/path")
    with pytest.raises(ValueError, match="exact http"):
        create_app()


def _decision_request() -> dict[str, object]:
    return {
        "entity_id": "user-api-1",
        "placement": "checkout_banner",
        "context": {"cart_value": 198, "session_intent": "high", "new_user": True},
        "candidate_action_ids": ["NO_TREATMENT", "free_shipping"],
        "consent_state": True,
        "frequency_remaining": 2,
        "budget_remaining": 50,
        "context_freshness_seconds": 10,
    }


def test_product_api_decision_contract() -> None:
    client = TestClient(create_app())
    response = client.post("/api/decide", headers={"Idempotency-Key": "api-test-1"}, json=_decision_request())
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"].startswith("dec_")
    assert 0 < payload["propensity"] <= 1
    assert payload["policy_id"] == "policy_growth_safe"
    assert "policy_version" not in payload
    assert payload["engine_mode"] == "reference-contract"
    assert "NO_TREATMENT" in payload["action_distribution"]


def test_explicit_empty_candidate_list_is_conservative() -> None:
    client = TestClient(create_app())
    body = _decision_request()
    body["candidate_action_ids"] = []
    response = client.post("/api/decide", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["action_id"] == "NO_TREATMENT"
    assert payload["action_distribution"] == {"NO_TREATMENT": 1.0}


def test_idempotency_key_reuse_with_different_request_is_conflict() -> None:
    client = TestClient(create_app())
    first = _decision_request()
    second = _decision_request()
    second["entity_id"] = "different-user"
    headers = {"Idempotency-Key": "same-key-different-payload"}
    assert client.post("/api/decide", headers=headers, json=first).status_code == 200
    conflict = client.post("/api/decide", headers=headers, json=second)
    assert conflict.status_code == 409
    assert "different decision request" in conflict.json()["detail"]


def test_idempotency_key_is_trimmed_and_invalid_values_are_rejected() -> None:
    client = TestClient(create_app())
    body = _decision_request()
    padded = client.post("/api/decide", headers={"Idempotency-Key": "  canonical-key  "}, json=body)
    canonical = client.post("/api/decide", headers={"Idempotency-Key": "canonical-key"}, json=body)
    assert padded.status_code == canonical.status_code == 200
    assert padded.json()["decision_id"] == canonical.json()["decision_id"]
    blank = client.post("/api/decide", headers={"Idempotency-Key": "   "}, json=body)
    assert blank.status_code == 422
    assert "non-whitespace" in blank.json()["detail"]
    too_long = client.post("/api/decide", headers={"Idempotency-Key": "x" * 257}, json=body)
    assert too_long.status_code == 422
    assert "at most 256" in too_long.json()["detail"]


def test_duplicate_idempotency_keys_are_rejected() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/decide",
        headers=[("Idempotency-Key", "duplicate-a"), ("Idempotency-Key", "duplicate-b")],
        json=_decision_request(),
    )
    assert response.status_code == 422
    assert "at most once" in response.json()["detail"]


def test_invalid_decision_context_returns_422_not_500() -> None:
    client = TestClient(create_app())
    body = _decision_request()
    body["context"] = {"cart_value": "not-a-number", "session_intent": "high"}
    response = client.post("/api/decide", json=body)
    assert response.status_code == 422
    assert "context.cart_value" in response.json()["detail"]


def test_realtime_console_alias_uses_same_decision_contract() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/realtime/decision",
        headers={"Idempotency-Key": "api-test-realtime-1"},
        json=_decision_request(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"].startswith("dec_")
    assert payload["action_id"] in {"NO_TREATMENT", "free_shipping"}
    assert payload["engine_mode"] == "reference-contract"


def test_app_factory_isolates_mutable_reference_state() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    decision = first.post("/api/decide", json=_decision_request())
    assert decision.status_code == 200
    assert len(first.get("/api/decisions/recent").json()) == 1
    assert second.get("/api/decisions/recent").json() == []
    draft = first.post(
        "/api/campaigns/draft",
        json={"name": "isolated draft", "goal": "prove app isolation", "audience": "test cohort", "budget": 1000, "candidate_action_ids": ["NO_TREATMENT"]},
    )
    assert draft.status_code == 201
    draft_id = draft.json()["id"]
    assert any(item["id"] == draft_id for item in first.get("/api/campaigns").json())
    assert all(item["id"] != draft_id for item in second.get("/api/campaigns").json())


def test_unknown_api_route_is_real_404_not_spa_html() -> None:
    client = TestClient(create_app())
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "API route not found"


def test_service_worker_is_not_long_cached() -> None:
    client = TestClient(create_app())
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_product_api_agent_and_approval_workflow() -> None:
    client = TestClient(create_app())
    plan = client.post("/api/agent/plan", json={"goal": "提升节前新用户首购", "budget_limit": 500000, "guardrails": ["unsubscribe_rate"]})
    assert plan.status_code == 200
    assert plan.json()["next_gate"] == "Shadow preflight"
    approvals = client.get("/api/approvals").json()
    approval_id = approvals[0]["id"]
    result = client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "approve_5", "note": "API test"})
    assert result.status_code == 200
    first_timestamp = result.json()["decided_at"]
    retry = client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "approve_5", "note": "different retry note"})
    assert retry.status_code == 200
    assert retry.json()["decided_at"] == first_timestamp
    assert retry.json()["decision_note"] == "API test"
    conflict = client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "reject", "note": "late conflict"})
    assert conflict.status_code == 409
