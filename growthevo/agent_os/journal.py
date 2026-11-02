"""Scoped execution checkpoints. Public traces never contain model context or secrets."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from secrets import token_urlsafe
from threading import RLock
from time import time
from typing import Any, Callable


class ExecutionConflict(ValueError):
    """A worker lost its lease, or a run is already being executed."""


def principal_scope(claims: dict[str, Any]) -> str:
    """Use verified issuer/subject, never a caller-selected tenant header or run ID."""
    if any(not isinstance(claims.get(key), str) or not claims[key].strip() for key in ("iss", "sub")):
        raise ValueError("verified issuer and subject are required")
    return sha256(json.dumps([claims["iss"], claims["sub"]], separators=(",", ":")).encode()).hexdigest()


def draft_fingerprint(arguments: dict[str, Any]) -> str:
    return sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MemoryAgentBackend:
    """Development-only implementation of the same atomic state contract."""

    durability = "process_local"

    def __init__(self, draft_writer: Callable[..., dict[str, Any]], *, clock: Callable[[], float] = time):
        self._lock = RLock()
        self._items: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._draft_writer = draft_writer
        self._clock = clock

    def create(self, scope: str, kind: str, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            identity = (scope, kind, key)
            if identity in self._items:
                raise ExecutionConflict("state already exists")
            if len(self._items) >= 10000:
                raise ExecutionConflict("development state capacity reached")
            self._items[identity] = {"value": deepcopy(value), "created_at": self._clock()}

    def get(self, scope: str, kind: str, key: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._items[(scope, kind, key)]["value"])

    def scan(self, scope: str, kind: str, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = [row for identity, row in self._items.items() if identity[:2] == (scope, kind)]
            rows.sort(key=lambda row: row["created_at"], reverse=True)
            return [deepcopy(row["value"]) for row in rows[:max(0, min(limit, 100))]]

    def mutate(self, scope: str, kind: str, key: str, change: Callable,
               *, initial: dict[str, Any] | None = None) -> Any:
        with self._lock:
            identity = (scope, kind, key)
            if identity not in self._items:
                if initial is None:
                    raise KeyError(key)
                self.create(scope, kind, key, initial)
            row = self._items[identity]
            value, result = change(deepcopy(row["value"]), self._clock())
            row["value"] = deepcopy(value)
            return result

    def draft_once(self, scope: str, run_id: str, lease: str, index: int,
                   arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self._items[(scope, "runs", run_id)]["value"]
            assert_lease(row, lease, self._clock())
            key = (scope, "effects", f"{run_id}:{index}")
            if key not in self._items:
                if len(self._items) >= 10000:
                    raise ExecutionConflict("development state capacity reached")
                result = self._draft_writer(**arguments)
                self.create(scope, "effects", key[2], {"result": result, "fingerprint": draft_fingerprint(arguments)})
            if self._items[key]["value"]["fingerprint"] != draft_fingerprint(arguments):
                raise ExecutionConflict("effect key cannot be reused for different arguments")
            return deepcopy(self._items[key]["value"]["result"])


def assert_lease(row: dict[str, Any], lease: str, now: float) -> None:
    if row.get("lease") != lease or row.get("lease_until", 0) <= now:
        raise ExecutionConflict("execution lease is absent, expired or owned by another worker")


class RunJournal:
    """One authenticated principal's durable runs, bound to a shared backend."""

    LEASE_SECONDS = 120
    MAX_RECOVERIES = 16

    def __init__(self, backend: Any, scope: str):
        self.backend = backend
        self.scope = scope
        self.durability = backend.durability

    @staticmethod
    def _event(row: dict[str, Any], kind: str, now: float) -> None:
        events = row.setdefault("events", [])
        if len(events) >= 256:
            raise ExecutionConflict("execution audit capacity reached")
        events.append({"sequence": len(events), "type": kind, "at": now,
                       "status": row["public"]["status"],
                       "tool_calls": row["public"].get("tool_calls", 0)})

    def start(self, run_id: str, checkpoint: dict[str, Any], trace: dict[str, Any]) -> tuple[dict[str, Any], str]:
        lease = token_urlsafe(32)
        private = deepcopy(checkpoint) | {"ui_token": token_urlsafe(32)}

        def begin(row, now):
            if row:
                raise ExecutionConflict("run already exists")
            row = {"public": deepcopy(trace), "private": private, "lease": lease,
                   "lease_until": now + self.LEASE_SECONDS, "recoveries": 0, "events": []}
            self._event(row, "started", now)
            return row, (deepcopy(private), lease)

        return self.backend.mutate(self.scope, "runs", run_id, begin, initial={})

    def claim(self, run_id: str, *, allow_drafts: bool) -> tuple[dict[str, Any], str] | None:
        lease = token_urlsafe(32)

        def claim(row, now):
            status = row["public"]["status"]
            if status == "running" and row.get("lease_until", 0) > now:
                raise ExecutionConflict("run is already executing")
            if status not in {"running", "interrupted", "provider_failure", "tool_failure", "needs_consent", "ui_confirmed", "ui_failed"}:
                return row, None
            if not row.get("private", {}).get("goal"):
                raise ExecutionConflict("run has no recoverable checkpoint")
            if row.get("recoveries", 0) >= self.MAX_RECOVERIES:
                raise ExecutionConflict("recovery limit reached")
            row["recoveries"] = row.get("recoveries", 0) + 1
            row["private"]["allow_drafts"] = allow_drafts
            row["lease"], row["lease_until"] = lease, now + self.LEASE_SECONDS
            row["public"]["status"] = "running"
            self._event(row, "resumed", now)
            return row, (deepcopy(row["private"]), lease)

        return self.backend.mutate(self.scope, "runs", run_id, claim)

    def checkpoint(self, run_id: str, lease: str, state: dict[str, Any],
                   trace: dict[str, Any], event: str) -> None:
        def save(row, now):
            assert_lease(row, lease, now)
            row["private"] = deepcopy(state)
            row["public"] = deepcopy(trace)
            row["lease_until"] = now + self.LEASE_SECONDS
            if trace["status"] != "running":
                row["lease"], row["lease_until"] = None, 0
            self._event(row, event, now)
            return row, None

        self.backend.mutate(self.scope, "runs", run_id, save)

    async def heartbeat(self, run_id: str, lease: str) -> None:
        def renew(row, now):
            assert_lease(row, lease, now)
            row["lease_until"] = now + self.LEASE_SECONDS
            return row, None

        while True:
            await asyncio.sleep(self.LEASE_SECONDS / 4)
            await asyncio.to_thread(self.backend.mutate, self.scope, "runs", run_id, renew)

    def _public(self, row: dict[str, Any], *, include_token: bool = False) -> dict[str, Any]:
        public = deepcopy(row["public"])
        public["durability"] = self.durability
        has_context = bool(row.get("private", {}).get("goal"))
        public["resumable"] = (has_context and public["status"] in {
            "interrupted", "provider_failure", "tool_failure", "needs_consent", "ui_confirmed", "ui_failed"
        }) or public["status"] == "awaiting_ui_confirmation" or (
            public["status"] == "running" and row.get("lease_until", 0) <= time())
        if include_token and public["status"] in {"awaiting_ui_confirmation", "needs_approval"} and public.get("ui_actions") and not public.get("ui_receipts"):
            public["ui_confirmation_token"] = row["private"].get("ui_token")
        return public

    def result(self, run_id: str) -> dict[str, Any]:
        return self._public(self.backend.get(self.scope, "runs", run_id), include_token=True)

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        return [self._public(row) for row in self.backend.scan(self.scope, "runs", limit)]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return deepcopy(self.backend.get(self.scope, "runs", run_id)["events"])

    def record(self, trace: dict[str, Any], *, confirmation_token: str | None = None) -> None:
        """Compatibility for imported handler traces; no execution context is invented."""
        self.backend.create(self.scope, "runs", trace["run_id"], {
            "public": deepcopy(trace), "private": {"ui_token": confirmation_token},
            "lease": None, "lease_until": 0, "events": [],
        })

    def confirm_ui(self, run_id: str, token: str, receipts: list[dict[str, Any]]) -> dict[str, Any]:
        from .operator import AgentTraceStore

        def confirm(row, now):
            original = row["public"]
            if original["status"] in {"running", "cancelled"}:
                raise ExecutionConflict("browser confirmation must wait for a checkpoint")
            private = row["private"]
            identity = sha256(token.encode()).hexdigest()
            previous = private.get("ui_confirmations", {}).get(identity)
            if previous is not None:
                if previous != receipts:
                    raise ValueError("a recorded UI confirmation cannot be overwritten")
                return row, self._public(row)
            verifier = AgentTraceStore(limit=1)
            verifier.record(original, confirmation_token=private.get("ui_token"))
            row["public"] = verifier.confirm_ui(run_id, token, receipts)
            if original.get("ui_receipts") is None:
                private.setdefault("ui_confirmations", {})[identity] = deepcopy(receipts)
                private["ui_actions"] = deepcopy(row["public"]["ui_actions"])
                private["ui_receipts"] = deepcopy(receipts)
                private["confirmation_source"] = "browser_reported"
                for receipt in receipts:
                    index = receipt["step_index"]
                    if private.get("goal") and index < len(private.get("events", [])):
                        private["events"][index]["ui_confirmation"] = receipt["status"]
                        row["public"]["steps"][index]["ui_confirmation"] = receipt["status"]
                        feedback = json.loads(private["model_history"][index]["feedback"])
                        feedback["browser_confirmation"] = receipt["status"]
                        feedback["confirmation_source"] = "browser_reported"
                        private["model_history"][index]["feedback"] = json.dumps(feedback, ensure_ascii=False)
                self._event(row, "browser_receipt", now)
            return row, self._public(row)

        return self.backend.mutate(self.scope, "runs", run_id, confirm)

    def draft_once(self, run_id: str, lease: str, index: int, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.backend.draft_once(self.scope, run_id, lease, index, arguments)

    def cancel(self, run_id: str) -> dict[str, Any]:
        def cancel(row, now):
            if row["public"]["status"] in {"running", "interrupted", "provider_failure", "tool_failure", "awaiting_ui_confirmation", "needs_consent", "ui_confirmed", "ui_failed"}:
                row["public"]["status"] = "cancelled"
                row["public"]["message"] = "任务已停止。已经发生的草案写入仍保留，请核对执行记录。"
                row["lease"], row["lease_until"] = None, 0
                self._event(row, "cancelled", now)
            return row, self._public(row)

        return self.backend.mutate(self.scope, "runs", run_id, cancel)
