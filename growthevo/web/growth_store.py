"""PostgreSQL-backed growth workbench facts, objects and scheduled work.

The store is tenant/principal scoped and intentionally separate from synthetic
reference dashboards. This module never silently falls back to in-process data.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

KINDS = frozenset({"profile", "offer", "asset", "experiment", "journey", "decision", "delivery"})
FACT_KINDS = frozenset({"event", "exposure", "metric", "feedback", "receipt"})
UTC = timezone.utc

DDL = (
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_objects (
        owner_scope TEXT NOT NULL,
        kind TEXT NOT NULL,
        object_id TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, kind, object_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_objects_recent_idx
    ON growthevo_growth_objects (owner_scope, kind, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_facts (
        owner_scope TEXT NOT NULL,
        kind TEXT NOT NULL,
        fact_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        related_id TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, kind, fact_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_facts_lookup_idx
    ON growthevo_growth_facts (owner_scope, kind, related_id, occurred_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_facts_subject_idx
    ON growthevo_growth_facts (owner_scope, subject_id, occurred_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_assignments (
        owner_scope TEXT NOT NULL,
        experiment_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        variant TEXT NOT NULL,
        assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, experiment_id, subject_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_assignments_exp_idx
    ON growthevo_growth_assignments (owner_scope, experiment_id, variant)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_jobs (
        owner_scope TEXT NOT NULL,
        job_id TEXT NOT NULL,
        journey_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        due_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        payload JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, job_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS growthevo_growth_jobs_due_idx
    ON growthevo_growth_jobs (status, due_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS growthevo_growth_feedback (
        owner_scope TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        fact_id TEXT NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_scope, decision_id),
        UNIQUE (owner_scope, fact_id)
    )
    """,
)


def fingerprint(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class GrowthConflict(ValueError):
    """Immutable fact or assignment already exists with different content."""


class GrowthStore:
    """Small domain repository on the application's existing PostgreSQL pool."""

    def __init__(self, parent: Any) -> None:
        self.pool = parent._pool
        self.jsonb = parent._jsonb
        with self.pool.connection() as conn:
            for statement in DDL:
                conn.execute(statement)

    def get(self, scope: str, kind: str, object_id: str) -> dict[str, Any] | None:
        if kind not in KINDS:
            raise ValueError("unknown object kind")
        with self.pool.connection() as conn:
            row = conn.execute(
                """SELECT payload FROM growthevo_growth_objects
                WHERE owner_scope=%s AND kind=%s AND object_id=%s""",
                (scope, kind, object_id),
            ).fetchone()
        return deepcopy(row["payload"]) if row else None

    def list(self, scope: str, kind: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if kind not in KINDS:
            raise ValueError("unknown object kind")
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT payload FROM growthevo_growth_objects
                WHERE owner_scope=%s AND kind=%s
                ORDER BY updated_at DESC, object_id LIMIT %s""",
                (scope, kind, min(max(limit, 1), 500)),
            ).fetchall()
        return deepcopy([row["payload"] for row in rows])

    def put(self, scope: str, kind: str, payload: dict[str, Any], *, immutable: bool = False) -> dict[str, Any]:
        if kind not in KINDS or not isinstance(payload.get("id"), str):
            raise ValueError("invalid growth object")
        object_id = payload["id"]
        with self.pool.connection() as conn:
            if immutable:
                conn.execute(
                    """INSERT INTO growthevo_growth_objects (owner_scope,kind,object_id,payload)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (scope, kind, object_id, self.jsonb(payload)),
                )
                current = conn.execute(
                    """SELECT payload FROM growthevo_growth_objects
                    WHERE owner_scope=%s AND kind=%s AND object_id=%s""",
                    (scope, kind, object_id),
                ).fetchone()["payload"]
                if current != payload:
                    raise GrowthConflict("object identifier already has different content")
            else:
                conn.execute(
                    """INSERT INTO growthevo_growth_objects (owner_scope,kind,object_id,payload)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (owner_scope,kind,object_id) DO UPDATE
                    SET payload=EXCLUDED.payload, updated_at=now()""",
                    (scope, kind, object_id, self.jsonb(payload)),
                )
        return deepcopy(payload)

    def append_fact(
        self, scope: str, kind: str, fact_id: str, subject_id: str,
        related_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if kind not in FACT_KINDS:
            raise ValueError("unknown fact kind")
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO growthevo_growth_facts
                (owner_scope,kind,fact_id,subject_id,related_id,payload)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (scope, kind, fact_id, subject_id, related_id, self.jsonb(payload)),
            )
            row = conn.execute(
                """SELECT subject_id,related_id,payload FROM growthevo_growth_facts
                WHERE owner_scope=%s AND kind=%s AND fact_id=%s""",
                (scope, kind, fact_id),
            ).fetchone()
            if (row["subject_id"], row["related_id"], row["payload"]) != (subject_id, related_id, payload):
                raise GrowthConflict("fact identifier reused with different content")
        return deepcopy(payload)

    def facts(self, scope: str, kind: str, *, related_id: str | None = None,
              subject_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if kind not in FACT_KINDS:
            raise ValueError("unknown fact kind")
        predicates = ["owner_scope=%s", "kind=%s"]
        values: list[Any] = [scope, kind]
        if related_id is not None:
            predicates.append("related_id=%s")
            values.append(related_id)
        if subject_id is not None:
            predicates.append("subject_id=%s")
            values.append(subject_id)
        values.append(min(max(limit, 1), 1000))
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM growthevo_growth_facts WHERE "
                + " AND ".join(predicates)
                + " ORDER BY occurred_at DESC, fact_id LIMIT %s", values,
            ).fetchall()
        return deepcopy([r["payload"] for r in rows])

    def assignment(self, scope: str, experiment_id: str, subject_id: str,
                   proposed_variant: str) -> str:
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO growthevo_growth_assignments
                (owner_scope,experiment_id,subject_id,variant)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (scope, experiment_id, subject_id, proposed_variant),
            )
            row = conn.execute(
                """SELECT variant FROM growthevo_growth_assignments
                WHERE owner_scope=%s AND experiment_id=%s AND subject_id=%s""",
                (scope, experiment_id, subject_id),
            ).fetchone()
        return str(row["variant"])

    def assignments(self, scope: str, experiment_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT subject_id,variant FROM growthevo_growth_assignments
                WHERE owner_scope=%s AND experiment_id=%s""",
                (scope, experiment_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_assignments(self, scope: str, experiment_id: str) -> bool:
        with self.pool.connection() as conn:
            return conn.execute(
                """SELECT 1 FROM growthevo_growth_assignments
                WHERE owner_scope=%s AND experiment_id=%s LIMIT 1""",
                (scope, experiment_id),
            ).fetchone() is not None

    def append_feedback_once(self, scope: str, decision_id: str,
                             payload: dict[str, Any]) -> dict[str, Any]:
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO growthevo_growth_feedback
                (owner_scope,decision_id,fact_id,payload)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (scope, decision_id, payload["id"], self.jsonb(payload)),
            )
            row = conn.execute(
                """SELECT payload FROM growthevo_growth_feedback
                WHERE owner_scope=%s AND decision_id=%s""",
                (scope, decision_id),
            ).fetchone()
            if row["payload"] != payload:
                raise GrowthConflict("decision already has a different feedback event")
        return deepcopy(payload)

    def feedback_counts(self, scope: str, cohort: str, origin: str) -> dict[str, tuple[int, int]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT payload->>'action_id' AS action_id,
                    sum(CASE WHEN payload->>'success'='true' THEN 1 ELSE 0 END) AS successes,
                    count(*) AS total
                FROM growthevo_growth_feedback
                WHERE owner_scope=%s AND payload->>'cohort'=%s AND payload->>'origin'=%s
                GROUP BY payload->>'action_id'""",
                (scope, cohort, origin),
            ).fetchall()
        return {row["action_id"]: (int(row["successes"]), int(row["total"])) for row in rows}

    def has_journey_jobs(self, scope: str, journey_id: str) -> bool:
        with self.pool.connection() as conn:
            return conn.execute(
                """SELECT 1 FROM growthevo_growth_jobs
                WHERE owner_scope=%s AND journey_id=%s LIMIT 1""",
                (scope, journey_id),
            ).fetchone() is not None

    def enqueue(self, scope: str, job: dict[str, Any]) -> None:
        document = dict(job)
        document["due_at"] = job["due_at"].isoformat()
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO growthevo_growth_jobs
                (owner_scope,job_id,journey_id,subject_id,event_id,step_index,due_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (scope, job["id"], job["journey_id"], job["subject_id"],
                 job["event_id"], job["step_index"], job["due_at"], self.jsonb(document)),
            )

    def claim_due(self, limit: int = 20) -> list[dict[str, Any]]:
        """Claim once. A crashed processing claim stays visible for manual recovery."""
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT owner_scope,job_id,payload FROM growthevo_growth_jobs
                WHERE status='queued' AND due_at <= now()
                ORDER BY due_at, job_id LIMIT %s FOR UPDATE SKIP LOCKED""",
                (min(max(limit, 1), 50),),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE growthevo_growth_jobs
                    SET status='processing',updated_at=now()
                    WHERE owner_scope=%s AND job_id=%s""",
                    (row["owner_scope"], row["job_id"]),
                )
        return [dict(row["payload"]) | {"owner_scope": row["owner_scope"]} for row in rows]

    def finish_job(self, scope: str, job_id: str, status: str) -> None:
        if status not in {"simulated", "blocked", "failed"}:
            raise ValueError("invalid job status")
        with self.pool.connection() as conn:
            conn.execute(
                """UPDATE growthevo_growth_jobs SET status=%s,updated_at=now()
                WHERE owner_scope=%s AND job_id=%s AND status='processing'""",
                (status, scope, job_id),
            )

    def jobs(self, scope: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT payload,status FROM growthevo_growth_jobs
                WHERE owner_scope=%s ORDER BY due_at DESC LIMIT %s""",
                (scope, min(max(limit, 1), 500)),
            ).fetchall()
        return [dict(row["payload"]) | {"status": row["status"]} for row in rows]


def seed_sample(store: GrowthStore, scope: str) -> None:
    """Explicit non-production sample. All records live in PostgreSQL."""
    for profile in (
        {"id": "sample-alex", "segment": "new", "preferred_channel": "email", "consent": True},
        {"id": "sample-bo", "segment": "cart", "preferred_channel": "push", "consent": True},
        {"id": "sample-chen", "segment": "loyal", "preferred_channel": "email", "consent": False},
    ):
        store.put(scope, "profile", profile | {"origin": "simulated"})
    for offer in (
        {"id": "NO_TREATMENT", "channel": "none", "cost": 0, "active": True},
        {"id": "free_shipping", "channel": "web", "cost": 8, "active": True},
        {"id": "push_reminder", "channel": "push", "cost": 0.08, "active": True},
        {"id": "email_guide", "channel": "email", "cost": 0.03, "active": True},
    ):
        store.put(scope, "offer", offer | {"origin": "simulated"})
    store.put(scope, "asset", {
        "id": "sample-creative", "offer_id": "email_guide", "channel": "email",
        "title": "产品指南", "body": "了解适合你的功能", "origin": "simulated",
    })
    store.put(scope, "experiment", {
        "id": "sample-onboarding", "name": "新客优惠对照实验", "status": "active",
        "variants": [{"id": "control", "weight": 5000}, {"id": "treatment", "weight": 5000}],
        "metric": "conversion", "origin": "simulated",
    })
    store.put(scope, "journey", {
        "id": "sample-cart-journey", "name": "加购提醒旅程", "trigger": "cart_abandoned",
        "status": "active", "steps": [
            {"channel": "push", "offer_id": "push_reminder", "delay_seconds": 0},
            {"channel": "email", "offer_id": "email_guide", "delay_seconds": 3600},
        ], "origin": "simulated",
    })
