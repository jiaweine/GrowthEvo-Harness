from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

import pytest

from growthevo.llm.agent_planner import AgentPlannerConfig, GuardedLLMAgentPlanner


OPPORTUNITIES = [
    {
        "id": "opp_a",
        "segment": "new users",
        "population": 1000,
        "incremental_lift_pp": 4.2,
        "incremental_value": 120000,
        "confidence": 0.91,
        "support": 0.88,
        "evidence_tier": "A",
        "best_action": "secret executable hint that must not enter model context",
    },
    {
        "id": "opp_b",
        "segment": "dormant members",
        "population": 800,
        "incremental_lift_pp": 2.5,
        "incremental_value": 70000,
        "confidence": 0.80,
        "support": 0.76,
        "evidence_tier": "B",
    },
]


def _baseline() -> dict[str, Any]:
    return {
        "run_id": "run_fixture",
        "status": "proposal_ready",
        "goal": "fixture goal",
        "claims": [{"type": "FACT", "text": "baseline", "source": "baseline"}],
        "artifacts": [{"type": "StrategyProposal", "title": "baseline", "status": "draft"}],
        "compiled_goal": {
            "primary_metric": "incremental_profit",
            "budget_limit": 1000,
            "guardrails": ["unsubscribe_rate"],
        },
        "next_gate": "Shadow preflight",
    }


def _proposal(
    opportunity_id: str = "opp_a",
    *,
    confidence: float = 0.92,
) -> dict[str, Any]:
    return {
        "opportunity_id": opportunity_id,
        "strategy_title": "Validate new-user friction hypothesis",
        "hypothesis": "Reducing one first-purchase friction should create measurable incremental profit.",
        "experiment_direction": "Run a controlled NO_TREATMENT comparison before any expansion.",
        "confidence": confidence,
    }


def _critic(*, approved: bool = True, confidence: float = 0.94) -> dict[str, Any]:
    return {
        "approved": approved,
        "confidence": confidence,
        "rationale": "The proposal is bounded to a workspace opportunity and remains experimental.",
        "risk_flags": [] if approved else ["overclaim"],
    }


class _AsyncClient:
    provider_name = "fixture-provider"
    model = "fixture-model"

    def __init__(self, output: Mapping[str, Any] | None = None) -> None:
        self.output = dict(output or _proposal())
        self.calls: list[dict[str, Any]] = []

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        await asyncio.sleep(0)
        return dict(self.output)


class _CriticClient(_AsyncClient):
    provider_name = "fixture-critic"
    model = "fixture-critic-model"

    def __init__(self, *, approved: bool = True, confidence: float = 0.94) -> None:
        super().__init__(_critic(approved=approved, confidence=confidence))


class _GoalAwareClient(_AsyncClient):
    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        payload = json.loads(user)
        await asyncio.sleep(0.002)
        selected = "opp_a" if str(payload["goal"]).endswith("A") else "opp_b"
        return _proposal(selected, confidence=0.91 if selected == "opp_a" else 0.83)


class _FailingClient(_AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True
        self.block = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        self.calls.append({})
        if self.fail:
            raise TimeoutError("upstream private failure")
        if self.block:
            self.entered.set()
            await self.release.wait()
        return _proposal()


class _CancellableClient(_AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.block = True
        self.entered = asyncio.Event()

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        self.calls.append({})
        if self.block:
            self.entered.set()
            await asyncio.Event().wait()
        return dict(self.output)


async def _run(planner: GuardedLLMAgentPlanner, goal: str = "goal A") -> dict[str, Any]:
    return await planner.plan(
        goal=goal,
        budget_limit=12345,
        primary_metric="incremental_profit",
        guardrails=["unsubscribe_rate"],
        opportunities=OPPORTUNITIES,
        baseline=_baseline(),
    )


def test_agent_model_can_select_only_workspace_opportunity_and_cannot_write_fact_estimate() -> None:
    client = _AsyncClient()
    planner = GuardedLLMAgentPlanner(client)

    result = asyncio.run(_run(planner))

    assert result["claims"][0] == {
        "type": "FACT",
        "text": "Opportunity Map 已登记「new users」，证据等级 A，支持度 88%。",
        "source": "Opportunity Map / opp_a",
    }
    assert result["claims"][1]["type"] == "ESTIMATE"
    assert "+4.2pp" in result["claims"][1]["text"]
    assert "¥120,000" in result["claims"][1]["text"]
    assert result["claims"][2]["type"] == "HYPOTHESIS"
    assert result["claims"][3]["type"] == "IDEA"
    assert result["compiled_goal"] == {
        "primary_metric": "incremental_profit",
        "budget_limit": 12345,
        "guardrails": ["unsubscribe_rate"],
    }
    assert result["next_gate"] == "Shadow preflight"
    assert result["planner_audit"]["accepted"] is True
    assert result["planner_audit"]["provider"] == "fixture-provider"
    assert result["planner_audit"]["model"] == "fixture-model"

    sent = json.loads(client.calls[0]["user"])
    assert "best_action" not in client.calls[0]["user"]
    assert sent["opportunities"][0]["id"] == "opp_a"
    schema = client.calls[0]["schema"]
    assert schema["properties"]["opportunity_id"]["enum"] == ["opp_a", "opp_b"]
    assert "budget_limit" not in schema["properties"]
    assert "guardrails" not in schema["properties"]


def test_low_confidence_and_invalid_opportunity_fail_closed_to_baseline() -> None:
    low = GuardedLLMAgentPlanner(_AsyncClient(_proposal(confidence=0.2)))
    low_result = asyncio.run(_run(low))
    assert low_result["claims"][0]["text"] == "baseline"
    assert low_result["planner_audit"]["reason"] == "proposal_low_confidence"

    unknown = GuardedLLMAgentPlanner(_AsyncClient(_proposal("not-in-workspace")))
    unknown_result = asyncio.run(_run(unknown))
    assert unknown_result["claims"][0]["text"] == "baseline"
    assert unknown_result["planner_audit"]["reason"] == "llm_failure:ValueError"
    assert "upstream" not in json.dumps(unknown_result)


def test_workspace_validation_failure_is_fail_closed_without_calling_model() -> None:
    client = _AsyncClient()
    planner = GuardedLLMAgentPlanner(client)
    malformed = [dict(OPPORTUNITIES[0], support=2.0)]

    async def scenario() -> dict[str, Any]:
        return await planner.plan(
            goal="goal",
            budget_limit=None,
            primary_metric="incremental_profit",
            guardrails=[],
            opportunities=malformed,
            baseline=_baseline(),
        )

    result = asyncio.run(scenario())
    assert result["claims"][0]["text"] == "baseline"
    assert result["planner_audit"]["reason"] == "workspace_invalid:ValueError"
    assert result["planner_audit"]["used_llm"] is False
    assert client.calls == []


def test_critic_can_veto_without_rewriting_or_escalating_plan() -> None:
    proposer = _AsyncClient()
    critic = _CriticClient(approved=False, confidence=0.97)
    planner = GuardedLLMAgentPlanner(proposer, critic=critic)

    result = asyncio.run(_run(planner))

    assert result["claims"][0]["text"] == "baseline"
    assert result["artifacts"][0]["title"] == "baseline"
    assert result["next_gate"] == "Shadow preflight"
    assert result["planner_audit"]["reason"] == "critic_veto"
    assert result["planner_audit"]["provider"] == "fixture-provider"
    assert result["planner_audit"]["critic_provider"] == "fixture-critic"
    assert result["planner_audit"]["critic_confidence"] == 0.97
    assert len(proposer.calls) == len(critic.calls) == 1


def test_concurrent_async_plans_keep_trace_and_selection_request_local() -> None:
    client = _GoalAwareClient()
    planner = GuardedLLMAgentPlanner(client)

    async def one(index: int) -> tuple[str, str, float]:
        suffix = "A" if index % 2 == 0 else "B"
        result = await _run(planner, f"goal {suffix}")
        audit = planner.audit_snapshot()
        assert audit is not None
        return (
            str(result["planner_audit"]["opportunity_id"]),
            str(audit["opportunity_id"]),
            float(audit["confidence"]),
        )

    async def scenario() -> list[tuple[str, str, float]]:
        return await asyncio.gather(*(one(i) for i in range(120)))

    results = asyncio.run(scenario())
    for index, (result_id, audit_id, confidence) in enumerate(results):
        expected = "opp_a" if index % 2 == 0 else "opp_b"
        assert result_id == audit_id == expected
        assert confidence == (0.91 if expected == "opp_a" else 0.83)


def test_cancellation_propagates_and_does_not_poison_next_request() -> None:
    client = _CancellableClient()
    planner = GuardedLLMAgentPlanner(
        client,
        config=AgentPlannerConfig(max_consecutive_failures=1, circuit_cooldown_seconds=60),
    )

    async def cancelled() -> None:
        task = asyncio.create_task(_run(planner))
        await client.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())
    client.block = False
    client.output = _proposal(confidence=0.2)
    result = asyncio.run(_run(planner))

    assert len(client.calls) == 2
    assert result["planner_audit"]["reason"] == "proposal_low_confidence"
    assert result["planner_audit"]["used_llm"] is True


def test_semantic_circuit_uses_single_half_open_probe_under_concurrency() -> None:
    client = _FailingClient()
    planner = GuardedLLMAgentPlanner(
        client,
        config=AgentPlannerConfig(
            max_consecutive_failures=1,
            circuit_cooldown_seconds=0.02,
        ),
    )

    first = asyncio.run(_run(planner))
    assert first["planner_audit"]["reason"] == "llm_failure:TimeoutError"
    assert len(client.calls) == 1

    async def scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        client.fail = False
        client.block = True
        await asyncio.sleep(0.03)
        probe = asyncio.create_task(_run(planner, "probe A"))
        await client.entered.wait()
        burst = await asyncio.gather(*(_run(planner, f"burst {i} A") for i in range(32)))
        assert len(client.calls) == 2
        client.release.set()
        return await probe, burst

    probe_result, burst_results = asyncio.run(scenario())
    assert probe_result["planner_audit"]["accepted"] is True
    assert all(item["planner_audit"]["reason"] == "agent_circuit_open" for item in burst_results)
    assert all(item["planner_audit"]["used_llm"] is False for item in burst_results)
    assert len(client.calls) == 2
