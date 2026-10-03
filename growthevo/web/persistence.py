from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from .decisioning import IdempotencyConflict, ReferenceDecisionEngine
from .product_data import (
    APPROVALS,
    CAMPAIGNS,
    ApprovalDecisionConflict,
    ReferenceProductState,
)

UTC = timezone.utc
IDEMPOTENCY_RETENTION = timedelta(days=7)

_DURABLE_CORE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS growthevo_campaigns (
        id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_order BIGINT GENERATED ALWAYS AS IDENTITY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_campaigns_created_order_idx
    ON growthevo_campaigns (created_order DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_approvals (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_order BIGINT GENERATED ALWAYS AS IDENTITY,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_approvals_created_order_idx
    ON growthevo_approvals (created_order DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_decisions (
        decision_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        logged_at TIMESTAMPTZ NOT NULL,
        created_order BIGINT GENERATED ALWAYS AS IDENTITY
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_decisions_logged_at_idx
    ON growthevo_decisions (logged_at DESC, created_order DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_idempotency (
        idempotency_key TEXT PRIMARY KEY,
        request_fingerprint TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_idempotency_expires_at_idx
    ON growthevo_idempotency (expires_at)
    """,
)

_MIGRATIONS = (("durable_core", _DURABLE_CORE_STATEMENTS),)


class PostgresStore:
    """Durable PostgreSQL state for the product surface.

    The store deliberately owns only product/reference state. It does not alter
    the causal/OPE policy implementation. Database initialization is fail-fast:
    when a non-demo runtime advertises a database URL, GrowthEvo either connects,
    migrates and becomes durable, or startup fails instead of silently falling
    back to process memory.
    """

    backend = "postgresql"

    def __init__(
        self,
        database_url: str,
        *,
        seed_reference: bool,
        min_size: int = 1,
        max_size: int = 8,
        timeout_seconds: float = 5.0,
    ) -> None:
        if min_size <= 0 or max_size < min_size:
            raise ValueError("invalid PostgreSQL pool size")
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("GROWTHEVO_DATABASE_URL/DATABASE_URL must be a PostgreSQL URL")
        try:
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - guarded by the web extra/container lock
            raise RuntimeError(
                "PostgreSQL persistence requires the GrowthEvo web dependencies; "
                "install with: pip install -e '.[web]'"
            ) from exc

        self._jsonb = Jsonb
        self._closed = False
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_seconds,
            kwargs={"row_factory": dict_row},
            open=True,
            name="growthevo-product",
        )
        try:
            self._pool.wait(timeout=timeout_seconds)
            self._migrate()
            if seed_reference:
                self._seed_reference_data()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._pool.close()
        self._closed = True

    def healthy(self) -> bool:
        if self._closed:
            return False
        with self._pool.connection() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
        return bool(row and row["ok"] == 1)

    def _migrate(self) -> None:
        with self._pool.connection() as conn:
            # Serializes schema bootstrap across multiple replicas starting at once.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('growthevo_durable_schema'))")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS growthevo_schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for name, statements in _MIGRATIONS:
                exists = conn.execute(
                    "SELECT 1 AS present FROM growthevo_schema_migrations WHERE name = %s",
                    (name,),
                ).fetchone()
                if exists:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO growthevo_schema_migrations (name) VALUES (%s)",
                    (name,),
                )

    def _seed_reference_data(self) -> None:
        # API/reference mode remains immediately explorable, but production calls
        # this store with seed_reference=False so synthetic fixtures never enter a
        # real production database.
        with self._pool.connection() as conn:
            for item in reversed(CAMPAIGNS):
                payload = copy.deepcopy(item)
                conn.execute(
                    """
                    INSERT INTO growthevo_campaigns (id, payload)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (payload["id"], self._jsonb(payload)),
                )
            for item in reversed(APPROVALS):
                payload = copy.deepcopy(item)
                conn.execute(
                    """
                    INSERT INTO growthevo_approvals (id, status, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (payload["id"], payload["status"], self._jsonb(payload)),
                )

    def campaigns(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM growthevo_campaigns ORDER BY created_order DESC"
            ).fetchall()
        return copy.deepcopy([row["payload"] for row in rows])

    def create_campaign_draft(
        self,
        name: str,
        goal: str,
        audience: str,
        budget: float,
        candidate_action_ids: list[str],
    ) -> dict[str, Any]:
        item = {
            "id": f"cmp_{uuid.uuid4().hex[:8]}",
            "name": name,
            "type": "Campaign",
            "status": "Draft",
            "goal": goal,
            "audience": audience,
            "budget": budget,
            "candidate_action_ids": list(candidate_action_ids),
            "population": None,
            "started_at": None,
            "expected_lift": "pending causal evaluation",
            "evidence_tier": "D",
            "mode": "Draft",
        }
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO growthevo_campaigns (id, payload) VALUES (%s, %s)",
                (item["id"], self._jsonb(item)),
            )
        return copy.deepcopy(item)

    def approvals(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM growthevo_approvals ORDER BY created_order DESC"
            ).fetchall()
        return copy.deepcopy([row["payload"] for row in rows])

    def decide_approval(self, approval_id: str, decision: str, note: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT status, payload
                FROM growthevo_approvals
                WHERE id = %s
                FOR UPDATE
                """,
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            current = str(row["status"])
            payload = copy.deepcopy(row["payload"])
            if current == "pending":
                payload["status"] = decision
                payload["decision_note"] = note
                payload["decided_at"] = datetime.now(UTC).isoformat()
                conn.execute(
                    """
                    UPDATE growthevo_approvals
                    SET status = %s, payload = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (decision, self._jsonb(payload), approval_id),
                )
                return copy.deepcopy(payload)
            if current == decision:
                return copy.deepcopy(payload)
            raise ApprovalDecisionConflict(
                f"approval {approval_id!r} is already finalized as {current!r}; "
                f"cannot change it to {decision!r}"
            )

    def product_stats(self) -> dict[str, int]:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM growthevo_campaigns) AS campaigns,
                    (SELECT count(*) FROM growthevo_approvals) AS approvals
                """
            ).fetchone()
        return {
            "campaigns": int(row["campaigns"]),
            "max_campaigns": -1,
            "approvals": int(row["approvals"]),
        }

    def get_idempotent(self, idempotency_key: str) -> tuple[str, dict[str, Any]] | None:
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM growthevo_idempotency WHERE idempotency_key = %s AND expires_at <= now()",
                (idempotency_key,),
            )
            row = conn.execute(
                """
                SELECT request_fingerprint, payload
                FROM growthevo_idempotency
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return str(row["request_fingerprint"]), copy.deepcopy(row["payload"])

    def record_decision(
        self,
        payload: dict[str, Any],
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        stored = copy.deepcopy(payload)
        logged_at = stored["logged_at"]
        with self._pool.connection() as conn:
            if idempotency_key:
                if request_fingerprint is None:
                    raise RuntimeError("idempotent decisions require a request fingerprint")
                conn.execute(
                    "DELETE FROM growthevo_idempotency WHERE idempotency_key = %s AND expires_at <= now()",
                    (idempotency_key,),
                )
                expires_at = datetime.now(UTC) + IDEMPOTENCY_RETENTION
                row = conn.execute(
                    """
                    INSERT INTO growthevo_idempotency (
                        idempotency_key,
                        request_fingerprint,
                        decision_id,
                        payload,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING request_fingerprint, payload
                    """,
                    (
                        idempotency_key,
                        request_fingerprint,
                        stored["decision_id"],
                        self._jsonb(stored),
                        expires_at,
                    ),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        """
                        SELECT request_fingerprint, payload
                        FROM growthevo_idempotency
                        WHERE idempotency_key = %s
                        """,
                        (idempotency_key,),
                    ).fetchone()
                    if row is None:  # pragma: no cover - transaction/concurrency invariant
                        raise RuntimeError("idempotency winner disappeared before it could be read")
                    return str(row["request_fingerprint"]), copy.deepcopy(row["payload"])

            conn.execute(
                """
                INSERT INTO growthevo_decisions (decision_id, payload, logged_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (decision_id) DO NOTHING
                """,
                (stored["decision_id"], self._jsonb(stored), logged_at),
            )
        return request_fingerprint, copy.deepcopy(stored)

    def recent_decisions(self, limit: int) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT payload
                FROM growthevo_decisions
                ORDER BY logged_at DESC, created_order DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return copy.deepcopy([row["payload"] for row in rows])

    def decision_stats(self) -> dict[str, int]:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM growthevo_decisions) AS recent_decisions,
                    (SELECT count(*) FROM growthevo_idempotency WHERE expires_at > now()) AS idempotency_keys
                """
            ).fetchone()
        return {
            "recent_decisions": int(row["recent_decisions"]),
            "idempotency_keys": int(row["idempotency_keys"]),
            "max_idempotency_keys": -1,
            "idempotency_retention_days": int(IDEMPOTENCY_RETENTION.days),
        }


class PostgresProductState(ReferenceProductState):
    """Reference product semantics backed by durable PostgreSQL state."""

    def __init__(self, store: PostgresStore) -> None:
        self._store = store

    def campaigns(self) -> list[dict[str, Any]]:
        return self._store.campaigns()

    def approvals(self) -> list[dict[str, Any]]:
        return self._store.approvals()

    def stats(self) -> dict[str, int]:
        return self._store.product_stats()

    def decide_approval(self, approval_id: str, decision: str, note: str) -> dict[str, Any] | None:
        return self._store.decide_approval(approval_id, decision, note)

    def create_campaign_draft(
        self,
        name: str,
        goal: str,
        audience: str,
        budget: float,
        candidate_action_ids: list[str],
    ) -> dict[str, Any]:
        return self._store.create_campaign_draft(
            name,
            goal,
            audience,
            budget,
            candidate_action_ids,
        )


class PersistentReferenceDecisionEngine(ReferenceDecisionEngine):
    """Existing reference decision semantics with durable recording/idempotency."""

    def __init__(self, store: PostgresStore) -> None:
        super().__init__(max_log_size=1, max_idempotency_size=1)
        self._store = store

    def _cached(
        self,
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        entry = self._store.get_idempotent(idempotency_key)
        if entry is None:
            return None
        stored_fingerprint, payload = entry
        if request_fingerprint != stored_fingerprint:
            raise IdempotencyConflict(
                "Idempotency-Key was already used for a different decision request"
            )
        return copy.deepcopy(payload)

    def _record(
        self,
        payload: dict[str, Any],
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> dict[str, Any]:
        stored_fingerprint, stored = self._store.record_decision(
            payload,
            idempotency_key,
            request_fingerprint,
        )
        if idempotency_key and stored_fingerprint != request_fingerprint:
            raise IdempotencyConflict(
                "Idempotency-Key was already used for a different decision request"
            )
        return copy.deepcopy(stored)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._store.recent_decisions(limit)

    def stats(self) -> dict[str, int]:
        return self._store.decision_stats()
