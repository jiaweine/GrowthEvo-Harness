from __future__ import annotations

import asyncio
import json
import os
from time import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from growthevo.agent_os.durable_evolution import DurableEvolutionAuthority
from growthevo.agent_os.journal import ExecutionConflict, MemoryAgentBackend, RunJournal, principal_scope
from growthevo.agent_os.recovery import RecoverableOperator
from growthevo.web.product_data import ReferenceProductState
from test_agent_operating_system import FakeModel, finish, make_tools, step


@pytest.fixture(params=["memory", "postgres"])
def execution_store(request):
    scope = "journal-test-" + uuid4().hex
    stores = []
    clock = [time()]
    if request.param == "postgres":
        url = os.getenv("GROWTHEVO_TEST_DATABASE_URL", "").strip()
        if not url:
            pytest.skip("GROWTHEVO_TEST_DATABASE_URL is required for durable execution tests")
        from growthevo.web.persistence import PostgresProductState, PostgresStore
        from growthevo.web.agent_persistence import PostgresAgentBackend

        def reopen():
            store = PostgresStore(url, seed_reference=False)
            stores.append(store)
            return PostgresAgentBackend(store), PostgresProductState(store)

        backend, product = reopen()

        def expire(run_id):
            with backend.store._pool.connection() as conn:
                conn.execute("""UPDATE growthevo_agent_state SET payload=jsonb_set(payload,'{lease_until}','0')
                                WHERE owner_scope=%s AND collection='runs' AND item_id=%s""", (scope, run_id))
    else:
        product = ReferenceProductState()
        backend = MemoryAgentBackend(product.create_campaign_draft, clock=lambda: clock[0])

        def reopen():
            return backend, product

        def expire(run_id):
            clock[0] += 121

    yield SimpleNamespace(backend=backend, product=product, scope=scope, expire=expire, reopen=reopen)
    for store in stores:
        store.close()


def operator(model, storage, *, journal=None, backend=None, product=None):
    backend = backend or storage.backend
    journal = journal or RunJournal(backend, storage.scope)
    return RecoverableOperator(model, make_tools(product or storage.product), journal,
                               DurableEvolutionAuthority(backend, storage.scope), journal=journal)


def confirm(journal, result):
    receipts = [{"step_index": action["step_index"], "status": "confirmed"} for action in result["ui_actions"]]
    return journal.confirm_ui(result["run_id"], result["ui_confirmation_token"], receipts)


def test_browser_observation_precedes_next_model_turn_and_round_retries_are_idempotent(execution_store):
    store = execution_store
    journal = RunJournal(store.backend, store.scope)
    model = FakeModel(step("workspace.read", {"section": "campaigns"}),
                      step("ui.control", {"command": "open_search"}),
                      step("ui.control", {"command": "open_date_filter"}), finish("完成"))
    runner = operator(model, store, journal=journal)
    first = asyncio.run(runner.run("private user goal"))
    assert first["status"] == "awaiting_ui_confirmation"
    assert len(model.inputs) == 2
    first_receipt = [{"step_index": 1, "status": "confirmed"}]
    assert confirm(journal, first)["resumable"]
    second = asyncio.run(runner.run("", run_id=first["run_id"]))
    assert second["ui_actions"][0]["target"] == "open_date_filter"
    assert second["ui_confirmation_token"] != first["ui_confirmation_token"]
    assert '"browser_confirmation": "confirmed"' in model.inputs[2]["previous_steps"][-1]["feedback"]
    # An old identical HTTP retry cannot confirm, erase or overwrite the new round.
    retried = journal.confirm_ui(first["run_id"], first["ui_confirmation_token"], first_receipt)
    assert retried["status"] == "awaiting_ui_confirmation"
    assert retried["ui_actions"][0]["target"] == "open_date_filter"
    with pytest.raises(ValueError):
        journal.confirm_ui(first["run_id"], first["ui_confirmation_token"], [{"step_index": 1, "status": "failed"}])
    confirm(journal, second)
    final = asyncio.run(runner.run("", run_id=first["run_id"]))
    assert final["status"] == "completed"
    assert final["tool_calls"] == 3
    public = json.dumps(journal.recent())
    assert "private user goal" not in public
    assert "ui_confirmation_token" not in public
    assert "model_history" not in public
    events = journal.events(first["run_id"])
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert len([event for event in events if event["type"] == "browser_receipt"]) == 2


def test_crash_after_committed_draft_resumes_exact_operation_once(execution_store):
    store = execution_store
    before = len(store.product.campaigns())
    args = {"name": "checkpoint draft", "goal": "验证断点恢复", "audience": "eligible users", "budget": 100,
            "candidate_action_ids": ["NO_TREATMENT", "free_shipping"]}

    class ProcessCrash(BaseException):
        pass

    class CrashJournal(RunJournal):
        def checkpoint(self, run_id, lease, state, trace, event):
            if trace["status"] == "awaiting_ui_confirmation":
                raise ProcessCrash("simulate process exit after the effect transaction committed")
            return super().checkpoint(run_id, lease, state, trace, event)

    journal = CrashJournal(store.backend, store.scope)
    model = FakeModel(step("workspace.read", {"section": "campaigns"}), step("campaign.draft", args))
    with pytest.raises(ProcessCrash):
        asyncio.run(operator(model, store, journal=journal).run("create draft", allow_drafts=True))
    run_id = journal.recent()[0]["run_id"]
    assert len(store.product.campaigns()) == before + 1
    old = store.backend.get(store.scope, "runs", run_id)
    assert old["private"]["pending"]["tool"] == "campaign.draft"
    with pytest.raises(ExecutionConflict):
        journal.claim(run_id, allow_drafts=True)
    store.expire(run_id)
    backend2, product2 = store.reopen()
    restored = RunJournal(backend2, store.scope)
    next_model = FakeModel(finish("草案已保存"))
    recovered_runner = operator(next_model, store, backend=backend2, product=product2, journal=restored)
    recovered = asyncio.run(recovered_runner.run("", run_id=run_id, allow_drafts=True))
    assert recovered["status"] == "awaiting_ui_confirmation"
    assert len(next_model.inputs) == 0
    assert len(product2.campaigns()) == before + 1
    assert recovered["steps"][1]["draft"]["id"] == store.product.campaigns()[0]["id"]
    with pytest.raises(ExecutionConflict):
        store.backend.draft_once(store.scope, run_id, old["lease"], 1, args)
    confirm(restored, recovered)
    result = asyncio.run(recovered_runner.run("", run_id=run_id, allow_drafts=True))
    assert result["status"] == "completed"
    assert len(product2.campaigns()) == before + 1


def test_cancelled_model_request_has_a_recoverable_checkpoint(execution_store):
    store = execution_store
    journal = RunJournal(store.backend, store.scope)

    class WaitingModel:
        async def agenerate(self, **kwargs):
            if not json.loads(kwargs["user"])["previous_steps"]:
                return step("workspace.read", {"section": "campaigns"})
            started.set()
            await asyncio.Event().wait()

    async def interrupt():
        task = asyncio.create_task(operator(WaitingModel(), store, journal=journal).run("interrupted goal"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = asyncio.Event()
    asyncio.run(interrupt())
    trace = journal.recent()[0]
    assert trace["status"] == "interrupted"
    assert trace["tool_calls"] == 1
    resumed = asyncio.run(operator(FakeModel(finish("继续完成")), store).run("", run_id=trace["run_id"]))
    assert resumed["status"] == "completed"
    assert resumed["tool_calls"] == 1


def test_resume_requires_current_draft_consent_without_regenerating_the_operation(execution_store):
    store = execution_store
    before = len(store.product.campaigns())
    model = FakeModel(step("workspace.read", {"section": "campaigns"}), step("campaign.draft", {
        "name": "consent checkpoint", "goal": "验证恢复授权", "audience": "eligible users",
        "budget": 100, "candidate_action_ids": ["NO_TREATMENT", "free_shipping"],
    }))
    runner = operator(model, store)
    paused = asyncio.run(runner.run("prepare a draft"))
    assert paused["status"] == "needs_consent"
    again = asyncio.run(runner.run("", run_id=paused["run_id"]))
    assert again["status"] == "needs_consent"
    assert len(store.product.campaigns()) == before
    assert len(model.inputs) == 2
    accepted = asyncio.run(runner.run("", run_id=paused["run_id"], allow_drafts=True))
    assert accepted["status"] == "awaiting_ui_confirmation"
    assert accepted["tool_calls"] == 2
    assert len(store.product.campaigns()) == before + 1
    assert len(model.inputs) == 2


def test_cached_effect_rejects_different_arguments(execution_store):
    store = execution_store
    journal = RunJournal(store.backend, store.scope)
    _, lease = journal.start("op_effect_identity", {"goal": "effect identity"},
                             {"run_id": "op_effect_identity", "status": "running"})
    args = {"name": "one draft", "goal": "验证幂等", "audience": "eligible users", "budget": 100,
            "candidate_action_ids": ["NO_TREATMENT", "free_shipping"]}
    first = journal.draft_once("op_effect_identity", lease, 0, args)
    assert journal.draft_once("op_effect_identity", lease, 0, args) == first
    with pytest.raises(ExecutionConflict, match="different arguments"):
        journal.draft_once("op_effect_identity", lease, 0, args | {"budget": 200})


def test_analysis_failure_does_not_mask_saved_execution_result(execution_store, monkeypatch):
    store = execution_store
    runner = operator(FakeModel(step("workspace.read", {"section": "campaigns"}), finish("已读取")), store)

    def unavailable(_traces):
        raise RuntimeError("analysis unavailable")

    monkeypatch.setattr(runner.evolution, "propose", unavailable)
    result = asyncio.run(runner.run("read workspace"))
    assert result["status"] == "completed"
    assert RunJournal(store.backend, store.scope).result(result["run_id"])["status"] == "completed"


def test_fencing_cancellation_and_principal_boundaries(execution_store):
    store = execution_store
    journal = RunJournal(store.backend, store.scope)
    state = {"goal": "private goal", "allow_drafts": False}
    _, lease = journal.start("op_fenced", state, {"run_id": "op_fenced", "status": "running", "steps": []})
    other = RunJournal(store.backend, store.scope + "-other")
    with pytest.raises(KeyError):
        other.result("op_fenced")
    with pytest.raises(KeyError):
        other.cancel("op_fenced")
    assert other.recent() == []
    store.expire("op_fenced")
    _, replacement = journal.claim("op_fenced", allow_drafts=False)
    assert replacement != lease
    with pytest.raises(ExecutionConflict):
        journal.checkpoint("op_fenced", lease, state, {"status": "completed"}, "invalid")
    journal.cancel("op_fenced")
    with pytest.raises(ExecutionConflict):
        journal.checkpoint("op_fenced", replacement, state, {"status": "completed"}, "invalid")
    assert journal.result("op_fenced")["status"] == "cancelled"


def test_verified_principal_scope_includes_issuer_and_subject():
    a = principal_scope({"iss": "https://issuer-a", "sub": "one"})
    assert a != principal_scope({"iss": "https://issuer-a", "sub": "two"})
    assert a != principal_scope({"iss": "https://issuer-b", "sub": "one"})
    with pytest.raises(ValueError):
        principal_scope({"sub": "one"})
