from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from typing import Any

import pytest

TEST_DATABASE_URL = os.getenv("GROWTHEVO_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="GROWTHEVO_TEST_DATABASE_URL is required for PostgreSQL persistence tests",
)


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


def _expired_idempotency_count() -> int:
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT count(*) FROM growthevo_idempotency WHERE expires_at <= now()"
        ).fetchone()
    assert row is not None
    return int(row[0])


def _decision_request(entity_id: str = "postgres-restart-user") -> Any:
    from growthevo.web.schemas import DecisionRequest

    return DecisionRequest(
        entity_id=entity_id,
        placement="checkout_banner",
        context={
            "cart_value": 240,
            "session_intent": "high",
            "new_user": True,
            "abandoned_cart": False,
            "churn_risk": 0.05,
        },
        candidate_action_ids=["NO_TREATMENT", "free_shipping", "coupon_10"],
        consent_state=True,
        frequency_remaining=2,
        budget_remaining=50,
        context_freshness_seconds=5,
    )


def _store(*, seed_reference: bool = True) -> Any:
    from growthevo.web.persistence import PostgresStore

    return PostgresStore(TEST_DATABASE_URL, seed_reference=seed_reference)


def test_postgres_state_and_idempotency_survive_store_restart() -> None:
    from growthevo.web.persistence import PersistentReferenceDecisionEngine, PostgresProductState

    _reset_database()
    store = _store()
    state = PostgresProductState(store)
    engine = PersistentReferenceDecisionEngine(store)

    campaign = state.create_campaign_draft(
        "Durable restart campaign",
        "验证跨进程恢复后的 Campaign 草稿仍存在",
        "postgres-restart-audience",
        1200,
        ["NO_TREATMENT", "free_shipping"],
    )
    approval = state.decide_approval("apr_404", "approve_5", "durable approval")
    assert approval is not None
    assert approval["status"] == "approve_5"
    decision = engine.decide(
        _decision_request(),
        idempotency_key="postgres-restart-key",
    )
    decision_id = decision["decision_id"]
    campaign_id = campaign["id"]
    store.close()

    restarted_store = _store()
    try:
        restarted_state = PostgresProductState(restarted_store)
        restarted_engine = PersistentReferenceDecisionEngine(restarted_store)

        assert any(item["id"] == campaign_id for item in restarted_state.campaigns())
        persisted = next(item for item in restarted_state.approvals() if item["id"] == "apr_404")
        assert persisted["status"] == "approve_5"
        assert persisted["decision_note"] == "durable approval"

        replay = restarted_engine.decide(
            _decision_request(),
            idempotency_key="postgres-restart-key",
        )
        assert replay["decision_id"] == decision_id
        assert any(
            item["decision_id"] == decision_id
            for item in restarted_engine.recent(limit=100)
        )

        from growthevo.web.product_data import ApprovalDecisionConflict

        with pytest.raises(ApprovalDecisionConflict):
            restarted_state.decide_approval(
                "apr_404",
                "reject",
                "must not overwrite",
            )
    finally:
        restarted_store.close()

    counts = _database_counts()
    assert counts["decisions"] == 1
    assert counts["idempotency"] == 1
    assert counts["campaigns"] >= 6
    assert counts["approvals"] == 2


def test_postgres_idempotency_and_approval_are_atomic_across_pools() -> None:
    from growthevo.web.decisioning import IdempotencyConflict
    from growthevo.web.persistence import PersistentReferenceDecisionEngine, PostgresProductState
    from growthevo.web.product_data import ApprovalDecisionConflict

    _reset_database()
    store_a = _store()
    store_b = _store()
    engine_a = PersistentReferenceDecisionEngine(store_a)
    engine_b = PersistentReferenceDecisionEngine(store_b)
    state_a = PostgresProductState(store_a)
    state_b = PostgresProductState(store_b)

    try:
        request = _decision_request("postgres-concurrent-user")

        def decide(index: int) -> str:
            engine = engine_a if index % 2 == 0 else engine_b
            return engine.decide(
                request,
                idempotency_key="postgres-concurrent-key",
            )["decision_id"]

        with ThreadPoolExecutor(max_workers=32) as executor:
            decision_ids = list(executor.map(decide, range(128)))
        assert len(set(decision_ids)) == 1

        with pytest.raises(IdempotencyConflict):
            engine_b.decide(
                _decision_request("postgres-different-user"),
                idempotency_key="postgres-concurrent-key",
            )

        def approval(state: Any, decision: str) -> str:
            try:
                result = state.decide_approval(
                    "apr_404",
                    decision,
                    f"concurrent {decision}",
                )
                assert result is not None
                return "ok"
            except ApprovalDecisionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(approval, state_a, "approve_5"),
                executor.submit(approval, state_b, "reject"),
            ]
            outcomes = sorted(future.result() for future in futures)
        assert outcomes == ["conflict", "ok"]
    finally:
        store_a.close()
        store_b.close()

    counts = _database_counts()
    assert counts["decisions"] == 1
    assert counts["idempotency"] == 1


def test_expired_idempotency_cleanup_is_bounded_and_eventual() -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    from growthevo.web.persistence import IDEMPOTENCY_CLEANUP_BATCH

    _reset_database()
    store = _store(seed_reference=False)
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    live_until = datetime.now(timezone.utc) + timedelta(hours=1)
    try:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO growthevo_idempotency (
                        idempotency_key,
                        request_fingerprint,
                        decision_id,
                        payload,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            f"expired-{index:04d}",
                            f"fingerprint-{index:04d}",
                            f"decision-{index:04d}",
                            Jsonb({"decision_id": f"decision-{index:04d}"}),
                            expired_at,
                        )
                        for index in range(IDEMPOTENCY_CLEANUP_BATCH + 44)
                    ],
                )
                cur.execute(
                    """
                    INSERT INTO growthevo_idempotency (
                        idempotency_key,
                        request_fingerprint,
                        decision_id,
                        payload,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        "live-key",
                        "live-fingerprint",
                        "live-decision",
                        Jsonb({"decision_id": "live-decision"}),
                        live_until,
                    ),
                )

        assert _expired_idempotency_count() == IDEMPOTENCY_CLEANUP_BATCH + 44
        entry = store.get_idempotent("live-key")
        assert entry == ("live-fingerprint", {"decision_id": "live-decision"})
        assert _expired_idempotency_count() == 44

        # A later ordinary idempotency lookup drains the next bounded batch;
        # no cron or unbounded DELETE is required for eventual reclamation.
        entry = store.get_idempotent("live-key")
        assert entry == ("live-fingerprint", {"decision_id": "live-decision"})
        assert _expired_idempotency_count() == 0
    finally:
        store.close()

    assert _database_counts()["idempotency"] == 1


def test_production_postgres_is_durable_but_auth_stays_a_separate_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from growthevo.web.persistence import PostgresProductState
    from growthevo.web.runtime import RuntimeSettings

    _reset_database()
    monkeypatch.setenv("GROWTHEVO_MODE", "production")
    monkeypatch.setenv("GROWTHEVO_ENV", "postgres-ci")
    monkeypatch.setenv("GROWTHEVO_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROWTHEVO_AUTH_ISSUER", raising=False)
    monkeypatch.delenv("GROWTHEVO_AUTH_JWKS_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    store = _store(seed_reference=False)
    try:
        settings = replace(RuntimeSettings.from_env(), persistence_backend=store.backend)
        assert settings.database_configured is True
        assert settings.persistence_active is True
        assert settings.authentication_active is False
        assert settings.ready is False
        assert store.healthy() is True

        # Production migration must not inject synthetic reference Campaigns or
        # Approvals into the durable database.
        state = PostgresProductState(store)
        assert state.campaigns() == []
        assert state.approvals() == []
    finally:
        store.close()

    counts = _database_counts()
    assert counts == {"decisions": 0, "idempotency": 0, "campaigns": 0, "approvals": 0}
