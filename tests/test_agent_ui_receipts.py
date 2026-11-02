from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from growthevo.agent_os import AgentTraceStore, EvolutionAuthority, GrowthOperator
from test_agent_operating_system import FakeModel, finish, make_tools, step
from growthevo.web.product_data import ReferenceProductState


def pending_run(traces):
    model = FakeModel(step("workspace.read", {"section": "campaigns"}),
                      step("page.navigate", {"route": "campaignStudio"}),
                      step("ui.control", {"command": "focus_campaign_name"}), finish())
    return asyncio.run(GrowthOperator(model, make_tools(ReferenceProductState()), traces).run("打开活动草案"))


def test_ui_receipt_is_bound_ordered_idempotent_and_cannot_overwrite_failure():
    traces = AgentTraceStore()
    result = pending_run(traces)
    token, run_id = result["ui_confirmation_token"], result["run_id"]
    assert result["status"] == "awaiting_ui_confirmation"
    assert [action["step_index"] for action in result["ui_actions"]] == [1, 2]
    assert "ui_confirmation_token" not in traces.recent()[0]
    with pytest.raises(KeyError):
        traces.confirm_ui(run_id, "unrelated-token", [])
    with pytest.raises(ValueError):
        traces.confirm_ui(run_id, token, [{"step_index": 2, "status": "confirmed"}])
    receipts = [{"step_index": 1, "status": "confirmed"}, {"step_index": 2, "status": "failed"}]
    with ThreadPoolExecutor(2) as pool:
        reports = list(pool.map(lambda _: traces.confirm_ui(run_id, token, receipts), range(2)))
    assert reports[0] == reports[1]
    assert reports[0]["status"] == "ui_failed"
    assert reports[0]["confirmation_source"] == "browser_reported"
    assert reports[0]["ui_actions"][1]["status"] == "failed"
    with pytest.raises(ValueError, match="overwritten"):
        traces.confirm_ui(run_id, token, [dict(item, status="confirmed") for item in receipts])
    assert traces.recent()[0]["status"] == "ui_failed"


def test_returned_traces_are_detached_and_eviction_revokes_receipt_token():
    traces = AgentTraceStore(limit=1)
    first = pending_run(traces)
    returned = traces.recent()
    returned[0]["steps"].clear()
    assert len(traces.recent()[0]["steps"]) == 3
    second = pending_run(traces)
    with pytest.raises(KeyError):
        traces.confirm_ui(first["run_id"], first["ui_confirmation_token"], [])
    receipts = [{"step_index": 1, "status": "confirmed"}, {"step_index": 2, "status": "confirmed"}]
    confirmed = traces.confirm_ui(second["run_id"], second["ui_confirmation_token"], receipts)
    assert confirmed["status"] == "ui_confirmed"
    assert "evaluation" not in confirmed


def test_evolution_rejects_duplicate_and_old_policy_trace_samples():
    authority = EvolutionAuthority()
    trace = {"run_id": "op_one", "steps": [], "status": "step_limit",
             "policy_fingerprint": authority.active.fingerprint}
    stale = [dict(trace, run_id=f"op_old_{i}", policy_fingerprint="old-policy") for i in range(12)]
    assert authority.readiness([trace] * 8 + stale)["trace_count"] == 1
    assert authority.propose([trace] * 8 + stale) is None
    assert authority.readiness([dict(trace, policy_fingerprint=None)])["trace_count"] == 0


def test_confirmation_api_validates_receipts_and_keeps_pending_on_rejection(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from growthevo.web.app import create_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    app = create_app()
    result = pending_run(app.state.agent_traces)
    path = f'/api/agent/runs/{result["run_id"]}/ui-confirmation'
    body = {"token": result["ui_confirmation_token"], "receipts": [
        {"step_index": 1, "status": "confirmed"}, {"step_index": 2, "status": "confirmed"}]}
    with TestClient(app) as client:
        assert client.post(path, json=dict(body, token="x" * 43)).status_code == 404
        assert client.post(path, json=dict(body, receipts=[body["receipts"][1]])).status_code == 409
        invalid = dict(body, receipts=[{"step_index": True, "status": "confirmed"}])
        assert client.post(path, json=invalid).status_code == 422
        assert client.get("/api/harness/runs").json()[0]["status"] == "awaiting_ui_confirmation"
        assert client.post(path, json=body).json()["status"] == "ui_confirmed"
        assert client.get("/api/harness/runs").json()[0]["confirmation_source"] == "browser_reported"
