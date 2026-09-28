from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from growthevo.web.app import create_app


def test_product_api_health_dashboard_and_opportunities() -> None:
    client = TestClient(create_app())
    assert client.get("/api/health").json()["status"] == "ok"
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["api_version"] == "v1"
    opportunities = client.get("/api/v1/opportunities")
    assert opportunities.status_code == 200
    assert opportunities.json()[0]["evidence_tier"] in {"A", "B", "C", "D"}


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
