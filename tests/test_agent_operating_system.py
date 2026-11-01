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


def test_shared_campaign_contract_is_dependency_free_and_safe():
    from growthevo.tools.contracts import validated_campaign_draft
    draft = validated_campaign_draft({
        "name": "  Causal holdout  ", "goal": "Incremental profit",
        "audience": "Dormant users", "budget": 200,
        "candidate_action_ids": ["push_reminder", "push_reminder"],
    }, max_budget=300)
    assert draft["name"] == "Causal holdout"
    assert draft["candidate_action_ids"] == ["NO_TREATMENT", "push_reminder"]
    with pytest.raises(ValueError):
        validated_campaign_draft({
            "name": "Safe", "goal": "Incremental profit",
            "audience": "Dormant users", "budget": float("nan"),
            "candidate_action_ids": ["NO_TREATMENT"]
        })
    with pytest.raises(ValueError, match="unknown"):
        validated_campaign_draft({
            "name": "Safe", "goal": "Incremental profit",
            "audience": "Dormant users", "budget": 200,
            "candidate_action_ids": ["arbitrary_outbound_action"]
        })


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
    assert result["status"] == "completed", result["message"]
    assert result["tool_calls"] == 2
    assert result["navigation"] == "campaignStudio"
    assert result["steps"][0]["section"] == "opportunities"
    assert len(traces.recent()) == 1
    assert "section" in model.inputs[1]["previous_steps"][0]["feedback"]
    assert result["durability"] == "process_local"


def test_user_level_decision_data_is_not_exported_to_model():
    tools = make_tools(ReferenceProductState())
    tools.readers["decisions"] = lambda: [
        {"decision_id": "safe-id", "action_id": "NO_TREATMENT",
         "entity_id": "private-customer", "context": {"email": "private@example.com"}}
    ]
    model = FakeModel(step("workspace.read", {"section": "decisions"}), finish())
    result = run(GrowthOperator(model, tools, AgentTraceStore()))
    assert result["status"] == "completed"
    feedback = model.inputs[1]["previous_steps"][0]["feedback"]
    assert "safe-id" in feedback
    assert "private-customer" not in feedback
    assert "private@example.com" not in feedback


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
    assert response["status"] == "completed", response["message"]
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


def test_finishing_without_observing_is_not_claimed_as_completed():
    model = FakeModel(finish("Everything was executed."))
    result = run(GrowthOperator(model, make_tools(ReferenceProductState()),
                                AgentTraceStore()))
    assert result["status"] == "unverified"
    assert result["tool_calls"] == 0
    assert "No workspace operation" in result["message"]


def test_draft_tool_uses_existing_request_validator_and_control_action():
    state = ReferenceProductState()
    draft = {"name": "Checked draft", "goal": "Incremental profit",
             "audience": "Eligible dormant users", "budget": 120,
             "candidate_action_ids": ["push_reminder"]}
    model = FakeModel(step("workspace.read", {"section": "opportunities"}),
                      step("campaign.draft", draft), finish())
    result = run(GrowthOperator(model, make_tools(state), AgentTraceStore()),
                 allow_drafts=True)
    assert result["status"] == "completed"
    assert state.campaigns()[0]["candidate_action_ids"] == [
        "NO_TREATMENT", "push_reminder"
    ]


def test_provider_failure_is_not_silent_success():
    class Broken:
        async def agenerate(self, **kwargs):
            raise RuntimeError("private provider token should not leak")

    result = run(GrowthOperator(Broken(), make_tools(ReferenceProductState()),
                                AgentTraceStore()))
    assert result["status"] == "provider_failure"
    assert not result["steps"]
    assert "private provider token" not in result["message"]


def test_heldout_eval_does_not_lock_live_operator_or_share_mutable_claims():
    from threading import Thread

    authority = EvolutionAuthority()
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": []}
        for i in range(8)
    ])
    assert candidate is not None

    def evaluate_live(baseline, proposal):
        observed = []
        thread = Thread(target=lambda: observed.append(authority.snapshot()),
                        daemon=True)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive(), "held-out replay blocked live policy reads"
        assert observed[0]["fingerprint"] == baseline.fingerprint
        assert authority.candidates()[0]["status"] == "evaluating"
        # Another evaluator may not run the same candidate concurrently.
        with pytest.raises(ValueError, match="already been evaluated"):
            authority.evaluate(candidate.id, lambda a, b: {})
        return {"baseline_success": 0.6, "candidate_success": 0.9,
                "baseline_violations": 0, "candidate_violations": 0,
                "baseline_cost": 1, "candidate_cost": 1.04,
                "sample_size": 40, "evidence_id": "locked-independent-evidence"}

    result = authority.evaluate(candidate.id, evaluate_live)
    assert result.status == "awaiting_shadow_canary"
    assert result.evaluation["candidate_success"] == 0.9


def test_heldout_evaluator_failure_releases_claim_without_fabricated_results():
    authority = EvolutionAuthority()
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": []}
        for i in range(8)
    ])
    assert candidate is not None

    def offline_failure(_baseline, _proposal):
        raise RuntimeError("isolated replay unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        authority.evaluate(candidate.id, offline_failure)
    assert candidate.status == "requires_independent_eval"
    assert candidate.evaluation is None
    assert authority.active.step_budget == 6


def test_heldout_results_are_rejected_if_active_parent_changes_during_replay():
    authority = EvolutionAuthority()
    step_traces = [
        {"run_id": f"op_limited_{i}", "status": "step_limit", "steps": []}
        for i in range(8)
    ]
    candidate = authority.propose(step_traces)
    assert candidate is not None
    read_traces = [
        {"run_id": f"op_observed_{i}", "status": "completed",
         "steps": [{"tool": "workspace.read", "section": "opportunities", "outcome": "ok"}]}
        for i in range(8)
    ]
    second = authority.propose(read_traces)
    assert second is not None

    def metrics(_baseline, _proposal):
        return {"baseline_success": 0.60, "candidate_success": 0.85,
                "baseline_violations": 0, "candidate_violations": 0,
                "baseline_cost": 1, "candidate_cost": 1,
                "sample_size": 40, "evidence_id": "verified-independent-replay"}

    authority.evaluate(second.id, metrics)

    def stale_replay(baseline, proposal):
        assert baseline.step_budget == 6
        assert proposal.step_budget == 7
        authority.promote(second.id, operator_approved=True,
                          shadow_passed=True, canary_passed=True,
                          evidence_reference="separate-human-canary-evidence")
        return metrics(baseline, proposal)

    with pytest.raises(ValueError, match="active policy changed"):
        authority.evaluate(candidate.id, stale_replay)
    assert candidate.status == "stale_evaluation"
    assert candidate.evaluation is None
    assert authority.active.preferred_first_read == "opportunities"


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
    # The descendant actually changes subsequent operator execution budget.
    sections = ("dashboard", "opportunities", "campaigns", "experiments",
                "evidence", "approvals")
    model = FakeModel(*(step("workspace.read", {"section": section}) for section in sections),
                      finish("Completed after six tool observations"))
    updated_operator = GrowthOperator(model, make_tools(ReferenceProductState()),
                                      AgentTraceStore(), authority)
    updated_run = run(updated_operator)
    assert updated_run["status"] == "completed"
    assert updated_run["tool_calls"] == 6
    assert model.inputs[0]["operator_policy"]["preferred_first_read"] == "none"
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


def test_paired_replay_evaluates_actual_agent_loops_and_candidate_budget():
    from growthevo.agent_os.benchmark import BenchmarkTask, PairedReplayEvaluator
    tasks = [
        BenchmarkTask(f"heldout-{i}", f"Inspect opportunities and open experiments {i}",
                      "experiments", "opportunities")
        for i in range(30)
    ]

    def environment(task, policy):
        assert task.required_section == "opportunities"
        del policy
        model = FakeModel(
            step("workspace.read", {"section": "opportunities"}),
            step("workspace.read", {"section": "dashboard"}),
            step("workspace.read", {"section": "campaigns"}),
            step("workspace.read", {"section": "experiments"}),
            step("workspace.read", {"section": "approvals"}),
            step("page.navigate", {"route": "experiments"}),
            finish("Read five sections and requested the required route"),
        )
        return model, make_tools(ReferenceProductState())

    benchmark = PairedReplayEvaluator(
        tasks, environment, suite_id="locked-offline-operator-manifest"
    )
    authority = EvolutionAuthority()
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": []}
        for i in range(8)
    ])
    assert candidate is not None
    metrics = benchmark(authority.active, candidate.proposal)
    assert metrics["baseline_success"] == 0
    assert metrics["candidate_success"] == 1
    assert metrics["candidate_violations"] == 0
    assert metrics["sample_size"] == 30
    assert metrics["evidence_id"].startswith("replay:")
    authority.evaluate(candidate.id, benchmark)
    assert authority.candidates()[0]["status"] == "awaiting_shadow_canary"
    # The offline benchmark alone cannot activate a policy.
    assert authority.active.step_budget == 6
    with pytest.raises(ValueError, match="required"):
        authority.promote(candidate.id, operator_approved=True,
                          shadow_passed=False, canary_passed=False,
                          evidence_reference=metrics["evidence_id"])


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



def test_live_api_executes_real_model_tool_loop(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from growthevo.llm.provider_pool import ProviderFailoverClient, ProviderRoute
    import growthevo.web.app as web_app

    provider = FakeModel(step("workspace.read", {"section": "opportunities"}),
                         step("page.navigate", {"route": "experiments"}),
                         finish("Observed opportunities and opened experiments."))
    provider.provider_name = "fixture"
    provider.model = "pinned-fixture"

    async def close_provider():
        return None

    provider.aclose = close_provider
    pool = ProviderFailoverClient([ProviderRoute("fixture", provider)])
    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "pinned-fixture")
    monkeypatch.setattr(web_app, "build_provider_pool_from_env", lambda: pool)

    with TestClient(web_app.create_app()) as client:
        response = client.post("/api/agent/run", json={
            "goal": "Inspect opportunity evidence and navigate to experiments",
            "allow_draft_writes": False
        })
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["navigation"] == "experiments"
        assert len(response.json()["steps"]) == 2
        traces = client.get("/api/harness/runs").json()
        assert len(traces) == 1
        assert traces[0]["run_id"] == response.json()["run_id"]
        assert client.get("/api/evolution/candidates").json() == []
        assert client.get("/api/evolution/policy").json()["step_budget"] == 6
