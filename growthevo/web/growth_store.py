"""Tenant-scoped PostgreSQL records for growth operations.

All related writes share one PostgreSQL transaction. A scope advisory lock serializes
mutations for that scope while preserving the existing product connection pool.
This is deliberately a bounded starting point, not a distributed event bus.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, TypeVar

T = TypeVar("T")

GROWTH_MIGRATION = (
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_records (
        owner_scope TEXT NOT NULL,
        collection TEXT NOT NULL,
        item_id TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, collection, item_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_records_collection_idx
    ON growthevo_growth_records (owner_scope, collection, created_at DESC)
    """,
)


class GrowthConflict(ValueError):
    """A write conflicts with immutable identity or current state."""


class GrowthMissing(LookupError):
    """The requested tenant-scoped object was not found."""


class GrowthTransaction:
    def __init__(self, conn: Any, jsonb: Callable, scope: str):
        self.conn = conn
        self.jsonb = jsonb
        self.scope = scope

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT payload FROM growthevo_growth_records
               WHERE owner_scope=%s AND collection=%s AND item_id=%s""",
            (self.scope, kind, key),
        ).fetchone()
        return deepcopy(row["payload"]) if row is not None else None

    def all(self, kind: str, *, limit: int = 2000) -> list[dict[str, Any]]:
        if not 1 <= limit <= 2000:
            raise ValueError("invalid record scan limit")
        rows = self.conn.execute(
            """SELECT payload FROM growthevo_growth_records
               WHERE owner_scope=%s AND collection=%s
               ORDER BY item_id LIMIT %s""",
            (self.scope, kind, limit + 1),
        ).fetchall()
        if len(rows) > limit:
            raise GrowthConflict("bounded record scan exceeded; pagination required")
        return [deepcopy(row["payload"]) for row in rows]

    def put(self, kind: str, key: str, payload: dict[str, Any], *, new: bool = False) -> None:
        if new:
            row = self.conn.execute(
                """INSERT INTO growthevo_growth_records
                   (owner_scope, collection, item_id, payload)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING RETURNING item_id""",
                (self.scope, kind, key, self.jsonb(payload)),
            ).fetchone()
            if row is None:
                raise GrowthConflict(f"{kind} identity already exists")
        else:
            self.conn.execute(
                """INSERT INTO growthevo_growth_records
                   (owner_scope, collection, item_id, payload)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (owner_scope, collection, item_id)
                   DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()""",
                (self.scope, kind, key, self.jsonb(payload)),
            )


class GrowthStore:
    def __init__(self, product_store: Any):
        self.pool = product_store._pool
        self.jsonb = product_store._jsonb

    def run(self, scope: str, operation: Callable[[GrowthTransaction], T], *,
            write: bool = False) -> T:
        if not scope or len(scope) > 128:
            raise ValueError("invalid principal scope")
        with self.pool.connection() as conn:
            if write:
                # The same scope cannot create duplicate assignments/enrolments
                # concurrently across replicas.
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("growthevo-growth:" + scope,),
                )
            return operation(GrowthTransaction(conn, self.jsonb, scope))

    def ensure_demo(self, scope: str) -> None:
        from .growth_seed import seed_records

        def seed(tx: GrowthTransaction) -> None:
            if tx.get("meta", "demo-seeded") is not None:
                return
            for kind, key, payload in seed_records():
                tx.put(kind, key, payload, new=True)
            tx.put("meta", "demo-seeded", {"source": "synthetic", "seeded": True}, new=True)

        self.run(scope, seed, write=True)

    def scopes_with_jobs(self) -> list[str]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT owner_scope FROM growthevo_growth_records
                   WHERE collection='jobs' AND payload->>'status'='pending'
                   ORDER BY owner_scope LIMIT 100"""
            ).fetchall()
        return [row["owner_scope"] for row in rows]
