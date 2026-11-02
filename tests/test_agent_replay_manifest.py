from __future__ import annotations

from hashlib import sha256
import json

import pytest

from growthevo.agent_os.evolution import EvolutionAuthority, OperatorPolicy
from growthevo.agent_os.manifest import LockedReplaySuite
from growthevo.agent_os.operator import SECTIONS
from growthevo.llm.provider_pool import ProviderFailoverClient, ProviderRoute


def manifest_file(tmp_path, **updates):
    payload = {
        "suite_id": "independent-heldout-test-suite",
        "tasks": [{"id": f"heldout-{i}", "goal": f"读取增长机会并打开实验中心，案例 {i}",
                   "expected_route": "experiments", "required_section": "opportunities"} for i in range(30)],
        "workspace": {section: [] for section in SECTIONS},
    }
    payload.update(updates)
    raw = json.dumps(payload, ensure_ascii=False).encode()
    path = tmp_path / "heldout.json"
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest()


class ReplayModel:
    provider_name = "fixture"
    model = "fixture-locked"

    def __init__(self):
        self.calls = 0
        self.closed = False

    def generate(self, **kwargs):
        raise AssertionError("offline replay should use async model calls")

    async def agenerate(self, *, system, user, schema):
        self.calls += 1
        context = json.loads(user)
        # The offline snapshot is empty, independent of reference/live campaigns.
        for previous in context["previous_steps"]:
            feedback = json.loads(previous["feedback"])
            if previous["tool"] == "workspace.read":
                assert feedback["data"] == []
        n = len(context["previous_steps"])
        sections = ["opportunities", "dashboard", "campaigns", "experiments", "approvals"]
        if n < 5:
            tool, args = "workspace.read", {"section": sections[n]}
        elif n == 5:
            tool, args = "page.navigate", {"route": "experiments"}
        else:
            return {"kind": "finish", "tool": "none", "arguments_json": "{}", "message": "离线路由契约检查完成"}
        return {"kind": "tool", "tool": tool, "arguments_json": json.dumps(args), "message": "执行离线检查"}

    async def aclose(self):
        self.closed = True


def pool_for(model):
    return ProviderFailoverClient([ProviderRoute("fixture", model)])


def test_locked_replay_runs_both_policies_on_isolated_snapshot_and_closes_pool(tmp_path):
    path, digest = manifest_file(tmp_path)
    suite = LockedReplaySuite(str(path), digest)
    model = ReplayModel()
    measured = suite.evaluate(OperatorPolicy(), OperatorPolicy(step_budget=7), pool_factory=lambda: pool_for(model))
    assert model.closed
    assert model.calls == 30 * 13
    assert measured["baseline_success"] == 0
    assert measured["candidate_success"] == 1
    assert measured["sample_size"] == 30
    assert measured["evidence_id"] == "replay:" + digest


def test_manifest_rejects_wrong_digest_duplicate_tasks_and_unapproved_routes(tmp_path):
    path, digest = manifest_file(tmp_path)
    with pytest.raises(ValueError, match="digest"):
        LockedReplaySuite(str(path), "0" * 64)
    payload = json.loads(path.read_bytes())
    payload["tasks"][1] = payload["tasks"][0]
    path, digest = manifest_file(tmp_path, tasks=payload["tasks"])
    with pytest.raises(ValueError, match="distinct"):
        LockedReplaySuite(str(path), digest)
    payload["tasks"][0]["expected_route"] = "https://external.example"
    path, digest = manifest_file(tmp_path, tasks=payload["tasks"])
    with pytest.raises(ValueError, match="contract"):
        LockedReplaySuite(str(path), digest)


def test_provider_failure_does_not_become_rejection_and_is_retryable(tmp_path):
    path, digest = manifest_file(tmp_path)
    suite = LockedReplaySuite(str(path), digest)
    authority = EvolutionAuthority()
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": [],
         "policy_fingerprint": authority.active.fingerprint} for i in range(8)])

    class FailedModel(ReplayModel):
        async def agenerate(self, **kwargs):
            raise RuntimeError("provider unavailable")

    model = FailedModel()
    with pytest.raises(RuntimeError):
        authority.evaluate(candidate.id, lambda a, b: suite.evaluate(a, b, pool_factory=lambda: pool_for(model)))
    assert candidate.status == "requires_independent_eval"
    assert candidate.evaluation is None
    assert model.closed


def test_evaluation_api_uses_pinned_suite_and_never_promotes(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "fixture-locked")
    models = []

    def factory():
        model = ReplayModel()
        models.append(model)
        return pool_for(model)

    monkeypatch.setattr(web_app, "build_provider_pool_from_env", factory)
    app = web_app.create_app()
    with TestClient(app) as client:
        assert client.get("/api/evolution/readiness").json()["evaluation_available"] is False
        assert client.post("/api/evolution/candidates/missing/evaluate").status_code == 503
    path, digest = manifest_file(tmp_path)
    monkeypatch.setenv("GROWTHEVO_AGENT_BENCHMARK_PATH", str(path))
    monkeypatch.setenv("GROWTHEVO_AGENT_BENCHMARK_SHA256", digest)
    app = web_app.create_app()
    authority = app.state.evolution_authority
    candidate = authority.propose([
        {"run_id": f"op_{i}", "status": "step_limit", "steps": [],
         "policy_fingerprint": authority.active.fingerprint} for i in range(8)])
    with TestClient(app) as client:
        assert client.get("/api/evolution/readiness").json()["evaluation_available"] is True
        result = client.post(f"/api/evolution/candidates/{candidate.id}/evaluate")
        assert result.status_code == 200, result.text
        assert result.json()["candidate"]["status"] == "awaiting_shadow_canary"
        assert result.json()["evidence_scope"] == "offline_tool_and_route_contracts"
        assert result.json()["promotion_performed"] is False
        assert client.get("/api/evolution/policy").json()["step_budget"] == 6
        assert client.post(f"/api/evolution/candidates/{candidate.id}/evaluate").status_code == 409
    assert all(model.closed for model in models)
