"""Operator-configured, digest-pinned offline evaluation. No public metric uploads."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable

from .benchmark import BenchmarkTask, PairedReplayEvaluator
from .evolution import OperatorPolicy
from .operator import GrowthTools, ROUTES, SECTIONS


class LockedReplaySuite:
    """A separately prepared task set and sanitized snapshots, never live product state.

    The file digest is pinned by the deployment owner. That establishes content
    identity, not statistical independence or production promotion authority.
    """

    def __init__(self, path: str, expected_sha256: str):
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("offline evaluation requires a pinned SHA-256 digest")
        with Path(path).open("rb") as handle:
            raw = handle.read(1_000_001)
        if len(raw) > 1_000_000 or sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("offline evaluation manifest size or digest mismatch")
        payload = json.loads(raw)
        if (not isinstance(payload, dict)
            or set(payload) != {"suite_id", "tasks", "workspace"}):
            raise ValueError("invalid offline evaluation manifest")
        suite_id, tasks, workspace = payload["suite_id"], payload["tasks"], payload["workspace"]
        if not isinstance(suite_id, str) or not 12 <= len(suite_id.strip()) <= 128:
            raise ValueError("invalid offline evaluation suite identity")
        if not isinstance(tasks, list) or not 30 <= len(tasks) <= 200:
            raise ValueError("offline evaluation needs 30–200 held-out tasks")
        if not isinstance(workspace, dict) or set(workspace) != SECTIONS:
            raise ValueError("offline evaluation snapshots must cover the declared workspace sections")
        parsed = []
        for task in tasks:
            if (not isinstance(task, dict)
                or set(task) != {"id", "goal", "expected_route", "required_section"}
                or any(not isinstance(value, str) or not value.strip() for value in task.values())
                or len(task["id"]) > 128 or len(task["goal"]) > 4000
                or task["expected_route"] not in ROUTES
                or task["required_section"] not in SECTIONS):
                raise ValueError("invalid offline evaluation task contract")
            parsed.append(BenchmarkTask(**task))
        if len({task.id for task in parsed}) != len(parsed) or len({task.goal for task in parsed}) != len(parsed):
            raise ValueError("offline evaluation tasks must be distinct")
        self.tasks = tuple(parsed)
        self.workspace = deepcopy(workspace)
        self.suite_id = suite_id.strip()
        self.digest = expected_sha256

    def evaluate(self, baseline: OperatorPolicy, candidate: OperatorPolicy, *,
                 pool_factory: Callable[[], Any], timeout_seconds: float = 300) -> dict[str, Any]:
        """Use a fresh provider pool on the evaluation thread's own event loop."""
        async def measure() -> dict[str, Any]:
            from growthevo.llm.configuration import close_provider_pool

            pool = pool_factory()
            try:
                if pool is None:
                    raise RuntimeError("offline evaluation requires an active model")

                def environment(_task: BenchmarkTask, _policy: OperatorPolicy):
                    snapshot = deepcopy(self.workspace)
                    return pool, GrowthTools(
                        readers={section: lambda section=section: deepcopy(snapshot[section])
                                 for section in SECTIONS},
                        product_state=None,
                    )

                evaluator = PairedReplayEvaluator(list(self.tasks), environment, suite_id=self.suite_id)
                result = await asyncio.wait_for(evaluator.aevaluate(baseline, candidate), timeout_seconds)
                # Bind evidence to the full file, including its workspace snapshots.
                result["evidence_id"] = "replay:" + self.digest
                return result
            finally:
                await close_provider_pool(pool)

        return asyncio.run(measure())
