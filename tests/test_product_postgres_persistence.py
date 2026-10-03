from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from typing import Any

import pytest

TEST_DATABASE_URL = os.getenv("GROWTHEVO_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="GROWTHEVO_TEST_DATABASE_URL is required for PostgreSQL persistence tests",
)


def _app_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    # Import the module-level reference app without accidentally binding it to the
    # test database. Individual app factories below receive explicit DB intent.
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    from growthevo.web.app import create_app

    return create_app


def _configure_database(monkeypatch: pytest.MonkeyPatch, *, mode: str = "api") -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", mode)
    monkeypatch.setenv("GROWTHEVO_ENV", "postgres-ci")
    monkeypatch.setenv("GROWTHEVO_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_AUTH_ISSUER", raising=False)
    monkeypatch.delenv("GROWTHEVO_AUTH_JWKS_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)


def _reset_database() -> None:
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            """
            DROP TABLE IF EXISTS
                growthevo_idempotency,
                growthevo_decisions,
                growthevo_approvals,
                growthevo_campaigns,
                growthevo_schema_migrations
            CASCADE
            """
        )


def _database_counts() -> dict[str, int]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM growthevo_decisions) AS decisions,
                (SELECT count(*) FROM growthevo_idempotency) AS idempotency,
                (SELECT count(*) FROM growthevo_campaigns) AS campaigns,
                (SELECT count(*) FROM growthevo_approvals) AS approvals
            """
        ).fetchone()
    assert row is not None
    return {key: int(value) for key, value in row.items()}


def _decision_body(entity_id: str = "postgres-restart-user") -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "placement": "checkout_banner",
        "context": {
            "cart_value": 240,
            "session_intent": "high",
            "new_user": True,
            "abandoned_cart": False,
            "churn_risk": 0.05,
        },
        "candidate_action_ids": ["NO_TREATMENT", "free_shipping", "coupon_10"],
        "consent_state": True,
        "frequency_remaining": 2,
        "budget_remaining": 50,
        "context_freshness_seconds": 5,
    }


def test_postgres_state_and_idempotency_survive_app_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    create_app = _app_factory(monkeypatch)
    _reset_database()
    _configure_database(monkeypatch)

    from fastapi.testclient import TestClient

    campaign_id: str
    decision_id: str
    app = create_app()
    with TestClient(app) as client:
        runtime = client.get("/api/system/runtime")
        assert runtime.status_code == 200
        payload = runtime.json()
        assert payload["persistence"] == {
            "configured": True,
            "active": True,
            "backend": "postgresql",
            "healthy": True,
        }
        assert payload["ready"] is True
        assert TEST_DATABASE_URL not in json.dumps(payload)

        campaign = client.post(
            "/api/campaigns/draft",
            json={
                "name": "Durable restart campaign",
                "goal": "验证跨进程恢复后的 Campaign 草稿仍存在",
                "audience": "postgres-restart-audience",
                "budget": 1200,
                "candidate_action_ids": ["NO_TREATMENT", "free_shipping"],
            },
        )
        assert campaign.status_code == 201
        campaign_id = campaign.json()["id"]

        approval = client.post(
            "/api/approvals/apr_404/decision",
            json={"decision": "approve_5", "note": "durable approval"},
        )
        assert approval.status_code == 200
        assert approval.json()["status"] == "approve_5"

        decision = client.post(
            "/api/decide",
            headers={"Idempotency-Key": "postgres-restart-key"},
            json=_decision_body(),
        )
        assert decision.status_code == 200
        decision_id = decision.json()["decision_id"]

    # A new app factory creates a new connection pool and new Python objects but
    # must recover the same campaign, approval and idempotent decision from DB.
    restarted = create_app()
    with TestClient(restarted) as client:
        campaigns = client.get("/api/campaigns").json()
        assert any(item["id"] == campaign_id for item in campaigns)

        approvals = client.get("/api/approvals").json()
        persisted = next(item for item in approvals if item["id"] == "apr_404")
        assert persisted["status"] == "approve_5"
        assert persisted["decision_note"] == "durable approval"

        replay = client.post(
            "/api/decide",
            headers={"Idempotency-Key": "postgres-restart-key"},
            json=_decision_body(),
        )
        assert replay.status_code == 200
        assert replay.json()["decision_id"] == decision_id

        recent = client.get("/api/decisions/recent?limit=100").json()
        assert any(item["decision_id"] == decision_id for item in recent)

        conflict = client.post(
            "/api/approvals/apr_404/decision",
            json={"decision": "reject", "note": "must not overwrite"},
        )
        assert conflict.status_code == 409

    counts = _database_counts()
    assert counts["decisions"] == 1
    assert counts["idempotency"] == 1
    assert counts["campaigns"] >= 6
    assert counts["approvals"] == 2


def test_postgres_idempotency_and_approval_are_atomic_across_app_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_app = _app_factory(monkeypatch)
    _reset_database()
    _configure_database(monkeypatch)

    from fastapi.testclient import TestClient

    app_a = create_app()
    app_b = create_app()
    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        body = _decision_body("postgres-concurrent-user")

        def decide(index: int) -> tuple[int, str | None]:
            client = client_a if index % 2 == 0 else client_b
            response = client.post(
                "/api/decide",
                headers={"Idempotency-Key": "postgres-concurrent-key"},
                json=body,
            )
            data = response.json()
            return response.status_code, data.get("decision_id")

        with ThreadPoolExecutor(max_workers=32) as executor:
            results = list(executor.map(decide, range(128)))

        assert {status for status, _ in results} == {200}
        assert len({decision_id for _, decision_id in results}) == 1

        different = _decision_body("postgres-different-user")
        conflict = client_b.post(
            "/api/decide",
            headers={"Idempotency-Key": "postgres-concurrent-key"},
            json=different,
        )
        assert conflict.status_code == 409

        def approval(client: TestClient, decision: str) -> int:
            response = client.post(
                "/api/approvals/apr_404/decision",
                json={"decision": decision, "note": f"concurrent {decision}"},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(approval, client_a, "approve_5"),
                executor.submit(approval, client_b, "reject"),
            ]
            statuses = sorted(future.result() for future in futures)
        assert statuses == [200, 409]

    counts = _database_counts()
    assert counts["decisions"] == 1
    assert counts["idempotency"] == 1


def test_production_with_postgres_still_fails_closed_until_auth_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_app = _app_factory(monkeypatch)
    _reset_database()
    _configure_database(monkeypatch, mode="production")

    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        ready = client.get("/api/ready")
        assert ready.status_code == 503
        payload = ready.json()
        assert payload["persistence"]["active"] is True
        assert payload["persistence"]["healthy"] is True
        assert payload["authentication"]["active"] is False
        assert payload["ready"] is False

        # Production migration must not inject synthetic reference campaigns or
        # approvals into the durable database.
        assert app.state.product_state.campaigns() == []
        assert app.state.product_state.approvals() == []

        blocked = client.get("/api/campaigns")
        assert blocked.status_code == 503

    counts = _database_counts()
    assert counts == {"decisions": 0, "idempotency": 0, "campaigns": 0, "approvals": 0}
