"""Operator and recursive evolution contract tests: no real provider/network needed."""
from __future__ import annotations

import asyncio
import json

import pytest

from growthevo.agent_os import (
    AgentTraceStore, EvolutionAuthority, GrowthOperator, GrowthTools,
)
from growthevo.web.product_data import ReferenceProductState


class FakeModel:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.inputs = []

    async def agenerate(self, *, system, user, schema):
        assert "UNTRUSTED" in system
        assert schema["additionalProperties"] is False
        self.inputs.append(json.loads(user))
        return self.actions.pop(0)


def step(tool, args=None):
    return {"kind": "tool", "tool": tool, "arguments_json": json.dumps(args or {}),
            "message": "use typed capability"}


def finish(message="Task finished"):
    return {"kind": "finish", "tool": "none", "arguments_json": "{}",
            "message": message}


def make_tools(state):
    return GrowthTools(
        readers={key: (lambda key=key: [{"id": "apr_281"}]
                         if key == "approvals" else [{"section": key}])
                 for key in (
                     "dashboard", "opportunities", "campaigns", "experiments",
                     "approvals", "evidence", "actions", "decisions",
                     "harness", "evolution"
                 )},
        product_state=state,
    )


def run(operator, **kwargs):
    return asyncio.run(operator.run("Find an opportunity and navigate", **kwargs))


def test_model_directed_read_navigation_finish_and_trace():
    state = ReferenceProductState()
    traces = AgentTraceStore()
    model = FakeModel(
        step("workspace.read", {"section": "opportunities"}),
        step("page.navigate", {"route": "campaignStudio"}),
        finish("Opened the campaign workspace."),
    )
    operator = GrowthOperator(model, make_tools(state), traces)
    result = run(operator)
    assert result["status"] == "completed"
    assert result["tool_calls"] == 2
    assert result["navigation"] == "campaignStudio"
    assert result["steps"][0]["section"] == "opportunities"
    assert len(traces.recent()) == 1
    assert "section" in model.inputs[1]["previous_steps"][0]["feedback"]
    assert result["durability"] == "process_local"


def test_mutation_needs_consent_and_prior_workspace_observation():
    state = ReferenceProductState()
    args = {"name": "Test", "goal": "Causal profit", "audience": "Dormant",
            "budget": 250, "candidate_action_ids": ["NO_TREATMENT", "push_reminder"]}
    before = len(state.campaigns())
    denied = GrowthOperator(FakeModel(step("workspace.read", {"section": "opportunities"}),
                                      step("campaign.draft", args)),
                            make_tools(state), AgentTraceStore())
    assert run(denied)["status"] == "needs_consent"
    assert len(state.campaigns()) == before

    premature = GrowthOperator(FakeModel(step("campaign.draft", args)),
                               make_tools(state), AgentTraceStore())
    assert run(premature, allow_drafts=True)["status"] == "blocked"
    assert len(state.campaigns()) == before

    allowed = GrowthOperator(FakeModel(step("workspace.read", {"section": "opportunities"}),
                                       step("campaign.draft", args),
                                       finish("Draft created")),
                             make_tools(state), AgentTraceStore())
    response = run(allowed, allow_drafts=True)
    assert response["status"] == "completed"
    assert response["has_draft_write"]
    assert len(state.campaigns()) == before + 1
    assert state.campaigns()[0]["status"] == "Draft"


def test_approval_is_interrupt_only_and_arbitrary_route_denied():
    state = ReferenceProductState()
    gate = GrowthOperator(FakeModel(step("approval.review", {"approval_id": "apr_281"})),
                          make_tools(state), AgentTraceStore())
    result = run(gate)
    assert result["status"] == "needs_approval"
    assert state.approvals()[0]["status"] == "pending"
    assert result["navigation"] == "approvals"

    injection = GrowthOperator(FakeModel(step("page.navigate", {"route": "https://evil.test"})),
                               make_tools(state), AgentTraceStore())
    assert run(injection)["status"] == "blocked"
    invalid = GrowthOperator(FakeModel(step("workspace.read", {"section": "opportunities"}),
                                       step("workspace.read", {"section": "opportunities"})),
                             make_tools(state), AgentTraceStore())
    assert run(invalid)["status"] == "blocked"


def test_provider_failure_is_not_silent_success():
    class Broken:
        async def agenerate(self, **kwargs):
            raise RuntimeError("private provider token should not leak")

    result = run(GrowthOperator(Broken(), make_tools(ReferenceProductState()),
                                AgentTraceStore()))
    assert result["status"] == "provider_failure"
    assert not result["steps"]
    assert "private provider token" not in result["message"]


def test_evolution_archives_descendants_only_after_external_evidence():
    authority = EvolutionAuthority()

    def traces(count):
        return [{"run_id": f"op_real_{i}", "status": "step_limit",
                 "steps": [{"tool": "workspace.read", "section": "opportunities",
                            "outcome": "ok"}]} for i in range(count)]

    first = authority.propose(traces(8))
    assert first is not None
    assert first.parent == authority.active.fingerprint
    assert first.proposal.step_budget == 7
    assert first.status == "requires_independent_eval"
    assert authority.propose(traces(8)) is None
    with pytest.raises(ValueError, match="not a promotable"):
        authority.promote(first.id, operator_approved=True, shadow_passed=True,
                          canary_passed=True, evidence_reference="real-evidence-digest")

    def heldout(baseline, candidate):
        assert candidate.step_budget > baseline.step_budget
        return {"baseline_success": 0.60, "candidate_success": 0.69,
                "baseline_violations": 0.0, "candidate_violations": 0.0,
                "baseline_cost": 1.0, "candidate_cost": 1.03,
                "sample_size": 100, "evidence_id": "independent-holdout-a"}

    authority.evaluate(first.id, heldout)
    with pytest.raises(ValueError, match="required"):
        authority.promote(first.id, operator_approved=False, shadow_passed=True,
                          canary_passed=True, evidence_reference="real-evidence-digest")
    authority.promote(first.id, operator_approved=True, shadow_passed=True,
                      canary_passed=True, evidence_reference="real-evidence-digest")
    second = authority.propose(traces(9))
    assert second is not None
    assert second.parent == first.proposal.fingerprint
    assert second.proposal.step_budget == 8
    assert len(authority.candidates()) == 2


def test_evolution_rejects_unmeasured_or_regressive_changes():
    authority = EvolutionAuthority()
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": []}
        for i in range(8)
    ])
    assert candidate is not None
    with pytest.raises(ValueError, match="insufficient"):
        authority.evaluate(candidate.id, lambda a, b: {
            "baseline_success": .8, "candidate_success": .9,
            "baseline_violations": 0, "candidate_violations": 0,
            "baseline_cost": 1, "candidate_cost": 1.05,
            "sample_size": 10, "evidence_id": "measured-holdout-split"
        })
    assert candidate.status == "requires_independent_eval"
    authority.evaluate(candidate.id, lambda a, b: {
        "baseline_success": .8, "candidate_success": .7,
        "baseline_violations": 0, "candidate_violations": 0,
        "baseline_cost": 1, "candidate_cost": 1,
        "sample_size": 50, "evidence_id": "measured-holdout-split"
    })
    assert candidate.status == "rejected_by_eval"


def test_web_operator_unconfigured_fails_closed(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from growthevo.web.app import create_app

    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    with TestClient(create_app()) as client:
        response = client.post("/api/agent/run", json={"goal": "Find incremental impact"})
        assert response.status_code == 200
        assert response.json()["status"] == "model_unavailable"
        assert response.json()["steps"] == []
        assert any(item["name"] == "workspace.read" for item in client.get("/api/agent/tools").json())
        assert client.post("/api/agent/run", json={
            "goal": "Find incremental impact", "allow_draft_writes": "yes"
        }).status_code == 422
