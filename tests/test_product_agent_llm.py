from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from growthevo.llm.provider_pool import ProviderFailoverClient, ProviderRoute


class _ProductAgentClient:
    provider_name = "fixture-provider"
    model = "fixture-model"

    def __init__(self, *, fail: bool = False, reported_waiting: int = 0) -> None:
        self.fail = fail
        self.calls = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self.closed = 0
        self.reported_waiting = reported_waiting
        self.runtime_config = SimpleNamespace(max_concurrency=48, max_queue_size=96)

    def generate(self, **_: Any) -> Mapping[str, Any]:
        raise AssertionError("product agent route must use native async generation")

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del system, user
        self.calls += 1
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.003)
            if self.fail:
                raise TimeoutError("private upstream detail")
            properties = schema["properties"]
            if "opportunity_id" in properties:
                return {
                    "opportunity_id": "opp_new_7d",
                    "strategy_title": "验证新用户首购摩擦",
                    "hypothesis": "若首购摩擦是主要阻碍，则受控干预应产生可测的增量利润。",
                    "experiment_direction": "先以 NO_TREATMENT 为 control 做小流量实验，再依据因果证据决定是否扩大。",
                    "confidence": 0.93,
                }
            return {
                "approved": True,
                "confidence": 0.95,
                "rationale": "Proposal is bounded to one workspace opportunity and remains experimental.",
                "risk_flags": [],
            }
        finally:
            self.in_flight -= 1

    def runtime_metrics(self) -> SimpleNamespace:
        return SimpleNamespace(
            in_flight=self.in_flight,
            waiting=self.reported_waiting,
            peak_in_flight=self.peak_in_flight,
            peak_waiting=self.reported_waiting,
            rejected_total=0,
        )

    async def aclose(self) -> None:
        self.closed += 1


def _configured_app(monkeypatch: pytest.MonkeyPatch, route_client: _ProductAgentClient):
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "fixture-model")
    pool = ProviderFailoverClient([ProviderRoute("fixture", route_client)])
    monkeypatch.setattr(web_app, "build_provider_pool_from_env", lambda: pool)
    return web_app.create_app(), pool


def _request(index: int = 0) -> dict[str, Any]:
    return {
        "goal": f"提升节前新用户首购 {index}",
        "budget_limit": 500000,
        "primary_metric": "incremental_profit",
        "guardrails": ["unsubscribe_rate"],
    }


def test_product_agent_uses_async_proposal_and_critic_without_execution_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    route_client = _ProductAgentClient()
    app, _ = _configured_app(monkeypatch, route_client)

    with TestClient(app) as client:
        response = client.post("/api/agent/plan", json=_request())
        assert response.status_code == 200
        payload = response.json()
        assert payload["planner_audit"]["accepted"] is True
        assert payload["planner_audit"]["provider"] == "fixture-provider"
        assert payload["planner_audit"]["critic_provider"] == "fixture-provider"
        assert payload["next_gate"] == "Shadow preflight"
        assert payload["compiled_goal"]["budget_limit"] == 500000
        assert payload["artifacts"][-1]["status"] == "not_submitted"
        assert payload["artifacts"][-2] == {
            "type": "CampaignDraft",
            "title": "5% Canary",
            "status": "awaiting_shadow",
        }
        runtime = client.get("/api/system/runtime").json()
        assert runtime["llm"]["agent_planning"] is True
        assert runtime["llm"]["critic"] is True
        assert runtime["llm"]["metrics"]["provider_attempts_total"] == 2
        assert runtime["llm"]["load_state"] == "ready"
        assert runtime["llm"]["capacity"]["max_concurrency"] == 48
        assert runtime["llm"]["capacity"]["max_queue_size"] == 96
        assert runtime["llm"]["capacity"]["in_flight"] == 0
        assert runtime["llm"]["capacity"]["waiting"] == 0

    assert route_client.closed == 1


def test_runtime_reports_busy_agent_capacity_without_failing_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    route_client = _ProductAgentClient(reported_waiting=5)
    app, _ = _configured_app(monkeypatch, route_client)

    with TestClient(app) as client:
        ready = client.get("/api/ready")
        assert ready.status_code == 200
        llm = ready.json()["llm"]
        assert llm["healthy"] is True
        assert llm["load_state"] == "busy"
        assert llm["capacity"]["waiting"] == 5
        assert llm["capacity"]["busy_routes"] == 1
        assert llm["capacity"]["saturated_routes"] == 0


def test_product_agent_provider_failure_returns_deterministic_plan_and_redacted_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    route_client = _ProductAgentClient(fail=True)
    app, _ = _configured_app(monkeypatch, route_client)

    with TestClient(app) as client:
        response = client.post("/api/agent/plan", json=_request())
        assert response.status_code == 200
        payload = response.json()
        assert payload["claims"][0]["source"] == "Evidence Store / locked bundle"
        assert payload["planner_audit"]["accepted"] is False
        assert payload["planner_audit"]["reason"] == "llm_failure:ProviderUnavailableError"
        assert "private upstream detail" not in response.text
        assert payload["next_gate"] == "Shadow preflight"


def test_agent_endpoint_serves_many_model_plans_concurrently_without_sync_worker_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_client = _ProductAgentClient()
    app, _ = _configured_app(monkeypatch, route_client)

    async def scenario() -> list[Any]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                *(client.post("/api/agent/plan", json=_request(i)) for i in range(48))
            )

    responses = asyncio.run(scenario())
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["planner_audit"]["accepted"] is True for response in responses)
    assert route_client.calls == 96
    assert route_client.peak_in_flight > 1
