from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from growthevo.agent_os.durable_evolution import DurableEvolutionAuthority
from growthevo.agent_os.journal import ExecutionConflict
from test_agent_execution_journal import execution_store


def metrics(success=.8):
    return {"baseline_success": .5, "candidate_success": success, "baseline_violations": 0,
            "candidate_violations": 0, "baseline_cost": 1, "candidate_cost": 1,
            "sample_size": 40, "evidence_id": "locked-independent-evidence"}


def traces(authority):
    return [{"run_id": f"op_sample_{i}", "status": "step_limit", "steps": [],
             "policy_fingerprint": authority.snapshot()["fingerprint"]} for i in range(8)]


def test_candidate_archive_evaluation_and_active_policy_survive_reopening(execution_store):
    store = execution_store
    authority = DurableEvolutionAuthority(store.backend, store.scope)
    first = authority.propose(traces(authority))
    assert first is not None
    backend2, _ = store.reopen()
    other = DurableEvolutionAuthority(backend2, store.scope)
    assert other.propose(traces(other)) is None
    assert other.candidates()[0]["id"] == first.id
    other.evaluate(first.id, lambda a, b: metrics())
    assert authority.candidates()[0]["status"] == "awaiting_shadow_canary"
    authority.promote(first.id, operator_approved=True, shadow_passed=True, canary_passed=True,
                      evidence_reference="verified-shadow-canary-reference")
    assert other.snapshot()["step_budget"] == 7
    child = other.propose(traces(other))
    assert child.parent == other.snapshot()["fingerprint"]
    assert child.proposal.step_budget == 8
    assert DurableEvolutionAuthority(backend2, store.scope + "-other").candidates() == []


def test_evaluation_claim_is_shared_without_blocking_policy_reads(execution_store):
    store = execution_store
    first = DurableEvolutionAuthority(store.backend, store.scope)
    backend2, _ = store.reopen()
    other = DurableEvolutionAuthority(backend2, store.scope)
    candidate = first.propose(traces(first))
    started, release = Event(), Event()

    def evaluate(a, b):
        started.set()
        assert release.wait(5)
        return metrics()

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(first.evaluate, candidate.id, evaluate)
        assert started.wait(5)
        try:
            assert other.snapshot()["step_budget"] == 6
            assert other.candidates()[0]["status"] == "evaluating"
            with pytest.raises(ValueError, match="already been evaluated"):
                other.evaluate(candidate.id, lambda a, b: metrics(.9))
        finally:
            release.set()
        future.result(timeout=5)
    assert other.candidates()[0]["evaluation"]["candidate_success"] == .8


def test_evaluator_failure_releases_persistent_claim(execution_store):
    store = execution_store
    authority = DurableEvolutionAuthority(store.backend, store.scope)
    candidate = authority.propose(traces(authority))

    def unavailable(a, b):
        raise RuntimeError("offline worker failed")

    with pytest.raises(RuntimeError):
        authority.evaluate(candidate.id, unavailable)
    restored = DurableEvolutionAuthority(store.backend, store.scope)
    assert restored.candidates()[0]["status"] == "requires_independent_eval"
    assert restored.candidates()[0]["evaluation"] is None
    restored.evaluate(candidate.id, lambda a, b: metrics())
    public = restored.candidates()
    public[0]["evaluation"]["candidate_success"] = 1
    assert restored.candidates()[0]["evaluation"]["candidate_success"] == .8


def test_expired_evaluator_cannot_overwrite_a_replacement_worker(execution_store):
    store = execution_store
    old = DurableEvolutionAuthority(store.backend, store.scope)
    newer = DurableEvolutionAuthority(store.backend, store.scope)
    candidate = old.propose(traces(old))

    def delayed(a, b):
        def expire(state, now):
            state["claims"][candidate.id]["expires_at"] = 0
            return state, None

        store.backend.mutate(store.scope, "evolution", "current", expire)
        newer.evaluate(candidate.id, lambda a, b: metrics(.9))
        return metrics(.7)

    with pytest.raises(ExecutionConflict):
        old.evaluate(candidate.id, delayed)
    assert newer.candidates()[0]["evaluation"]["candidate_success"] == .9
