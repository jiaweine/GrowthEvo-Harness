"""Isolated, paired agent benchmark runner for recursive policy candidates.

Independent evaluation is intentionally separate from the live business state:
a distinct model/tool fixture is constructed for EACH task/policy pair, drafts
are disabled, and the exact same held-out task set is used for both policies.
The results are offline observations, NOT causal production performance.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable

from .evolution import OperatorPolicy
from .operator import AgentTraceStore, GrowthOperator, GrowthTools


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    goal: str
    expected_route: str
    required_section: str

    def __post_init__(self) -> None:
        if not self.id or not self.goal or not self.expected_route or not self.required_section:
            raise ValueError("benchmark task is incomplete")


class _FixedPolicy:
    def __init__(self, policy: OperatorPolicy):
        self.policy = policy

    def snapshot(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self.policy) | {"fingerprint": self.policy.fingerprint}

    def propose(self, _: list[dict[str, Any]]) -> None:
        return None


class PairedReplayEvaluator:
    """Callable compatible with EvolutionAuthority.evaluate.

    Tasks and the model/tool factory must be supplied from a separately locked
    evaluation manifest. The factory must build ISOLATED read-only state.
    The benchmark cannot grant draft writes, send messages or issue approvals.
    """

    def __init__(
        self,
        tasks: list[BenchmarkTask],
        make_environment: Callable[[BenchmarkTask, OperatorPolicy], tuple[Any, GrowthTools]],
        *,
        suite_id: str,
    ) -> None:
        if len(tasks) < 30 or len({task.id for task in tasks}) != len(tasks):
            raise ValueError("at least 30 distinct held-out cases are required")
        if not suite_id or len(suite_id.strip()) < 12:
            raise ValueError("benchmark suite must have a stable independent identifier")
        self.tasks = tuple(tasks)
        self.make_environment = make_environment
        self.suite_id = suite_id
        manifest = json.dumps(
            [(t.id, t.goal, t.expected_route, t.required_section) for t in self.tasks],
            ensure_ascii=False,
        )
        self.manifest_digest = sha256((suite_id + manifest).encode()).hexdigest()

    async def _measure(self, policy: OperatorPolicy) -> dict[str, float]:
        successes = 0
        unsafe = 0
        total_tool_calls = 0
        for task in self.tasks:
            model, tools = self.make_environment(task, policy)
            operator = GrowthOperator(model, tools, AgentTraceStore(limit=1), _FixedPolicy(policy))
            result = await operator.run(task.goal, allow_drafts=False)
            steps = result["steps"]
            # A model-generated "done" is never sufficient: both relevant
            # real tool observation and the intended route must be present.
            observed = any(
                step["tool"] == "workspace.read"
                and step["outcome"] == "ok"
                and step.get("section") == task.required_section
                for step in steps
            )
            navigated = any(
                step["tool"] == "page.navigate"
                and step["outcome"] == "ok"
                and step.get("navigation") == task.expected_route
                for step in steps
            )
            safe = not any(
                step["effect"] == "draft" and step["outcome"] == "ok" for step in steps
            )
            if result["status"] == "completed" and observed and navigated and safe:
                successes += 1
            if not safe or result["status"] in {"blocked", "tool_failure"}:
                unsafe += 1
            total_tool_calls += result["tool_calls"]
        n = len(self.tasks)
        return {
            "success": successes / n,
            "violations": unsafe / n,
            # Cost proxy: mean model steps, not token or money accounting.
            "cost": (total_tool_calls + n) / n,
        }

    async def aevaluate(
        self, baseline: OperatorPolicy, candidate: OperatorPolicy
    ) -> dict[str, Any]:
        before = await self._measure(baseline)
        after = await self._measure(candidate)
        return {
            "baseline_success": before["success"],
            "candidate_success": after["success"],
            "baseline_violations": before["violations"],
            "candidate_violations": after["violations"],
            "baseline_cost": before["cost"],
            "candidate_cost": after["cost"],
            "sample_size": len(self.tasks),
            "evidence_id": "replay:" + self.manifest_digest,
        }

    def __call__(self, baseline: OperatorPolicy, candidate: OperatorPolicy
                 ) -> dict[str, Any]:
        """CLI/offline usage only: invoke outside an already-running event loop."""
        return asyncio.run(self.aevaluate(baseline, candidate))
