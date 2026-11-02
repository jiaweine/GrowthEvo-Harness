"""Agent state on the existing PostgreSQL pool; no second database or write path."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from .product_data import campaign_draft_payload

from growthevo.agent_os.journal import ExecutionConflict, assert_lease, draft_fingerprint


class PostgresAgentBackend:
    durability = "postgresql"

    def __init__(self, store: Any):
        self.store = store

    def create(self, scope: str, kind: str, key: str, value: dict[str, Any]) -> None:
        with self.store._pool.connection() as conn:
            row = conn.execute(
                """INSERT INTO growthevo_agent_state (owner_scope, collection, item_id, payload)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING item_id""",
                (scope, kind, key, self.store._jsonb(value)),
            ).fetchone()
            if row is None:
                raise ExecutionConflict("state already exists")

    def get(self, scope: str, kind: str, key: str) -> dict[str, Any]:
        with self.store._pool.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM growthevo_agent_state WHERE owner_scope=%s AND collection=%s AND item_id=%s",
                (scope, kind, key),
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return deepcopy(row["payload"])

    def scan(self, scope: str, kind: str, limit: int) -> list[dict[str, Any]]:
        with self.store._pool.connection() as conn:
            rows = conn.execute(
                """SELECT payload FROM growthevo_agent_state WHERE owner_scope=%s AND collection=%s
                   ORDER BY created_at DESC, item_id DESC LIMIT %s""",
                (scope, kind, max(0, min(limit, 100))),
            ).fetchall()
        return deepcopy([row["payload"] for row in rows])

    def mutate(self, scope: str, kind: str, key: str, change: Callable,
               *, initial: dict[str, Any] | None = None) -> Any:
        with self.store._pool.connection() as conn:
            if initial is not None:
                conn.execute(
                    """INSERT INTO growthevo_agent_state (owner_scope, collection, item_id, payload)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (scope, kind, key, self.store._jsonb(initial)),
                )
            row = conn.execute(
                """SELECT payload
                   FROM growthevo_agent_state WHERE owner_scope=%s AND collection=%s AND item_id=%s FOR UPDATE""",
                (scope, kind, key),
            ).fetchone()
            if row is None:
                raise KeyError(key)
            # Sample the server clock AFTER acquiring the row lock. Waiting for
            # another transaction must not make an expired lease appear live.
            now = conn.execute("SELECT extract(epoch FROM clock_timestamp()) AS server_time").fetchone()
            # change is a short host-owned transition, never an LLM or evaluator.
            value, result = change(deepcopy(row["payload"]), float(now["server_time"]))
            conn.execute(
                """UPDATE growthevo_agent_state SET payload=%s, revision=revision+1, updated_at=now()
                   WHERE owner_scope=%s AND collection=%s AND item_id=%s""",
                (self.store._jsonb(value), scope, kind, key),
            )
        return result

    def draft_once(self, scope: str, run_id: str, lease: str, index: int,
                   arguments: dict[str, Any]) -> dict[str, Any]:
        """Fence the worker, cache the effect and insert the draft in ONE transaction."""
        key = f"{run_id}:{index}"
        with self.store._pool.connection() as conn:
            run = conn.execute(
                """SELECT payload
                   FROM growthevo_agent_state WHERE owner_scope=%s AND collection='runs' AND item_id=%s FOR UPDATE""",
                (scope, run_id),
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            now = conn.execute("SELECT extract(epoch FROM clock_timestamp()) AS server_time").fetchone()
            assert_lease(run["payload"], lease, float(now["server_time"]))
            cached = conn.execute(
                """SELECT payload FROM growthevo_agent_state
                   WHERE owner_scope=%s AND collection='effects' AND item_id=%s""",
                (scope, key),
            ).fetchone()
            if cached is not None:
                if cached["payload"]["fingerprint"] != draft_fingerprint(arguments):
                    raise ExecutionConflict("effect key cannot be reused for different arguments")
                return deepcopy(cached["payload"]["result"])
            # Same shape as the existing product draft, with no external sends.
            item = campaign_draft_payload(**arguments)
            conn.execute("INSERT INTO growthevo_campaigns (id, payload) VALUES (%s, %s)",
                         (item["id"], self.store._jsonb(item)))
            conn.execute(
                """INSERT INTO growthevo_agent_state (owner_scope, collection, item_id, payload)
                   VALUES (%s, 'effects', %s, %s)""",
                (scope, key, self.store._jsonb({"result": item, "fingerprint": draft_fingerprint(arguments)})),
            )
        return deepcopy(item)
