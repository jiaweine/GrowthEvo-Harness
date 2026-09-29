from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("pydantic")

from growthevo.web.decisioning import IdempotencyConflict, ReferenceDecisionEngine
from growthevo.web.product_data import (
    ApprovalDecisionConflict,
    MAX_REFERENCE_CAMPAIGNS,
    ReferenceProductState,
    agent_plan,
)
from growthevo.web.schemas import DecisionRequest


def _request(entity_id: str = "stress-user") -> DecisionRequest:
    return DecisionRequest(
        entity_id=entity_id,
        placement="checkout_banner",
        context={"cart_value": 218, "session_intent": "high", "new_user": True},
        candidate_action_ids=["NO_TREATMENT", "free_shipping_v3", "coupon_10_v2"],
        consent_state=True,
        frequency_remaining=2,
        budget_remaining=50,
        context_freshness_seconds=5,
    )


def test_decision_idempotency_is_atomic_under_concurrent_first_hit() -> None:
    engine = ReferenceDecisionEngine(max_log_size=1_000, max_idempotency_size=128)
    request = _request()

    with ThreadPoolExecutor(max_workers=64) as pool:
        results = list(pool.map(lambda _: engine.decide(request, idempotency_key="burst-one"), range(512)))

    assert len({item["decision_id"] for item in results}) == 1
    assert engine.stats()["recent_decisions"] == 1
    assert engine.stats()["idempotency_keys"] == 1


def test_same_idempotency_key_rejects_different_concurrent_request() -> None:
    engine = ReferenceDecisionEngine(max_log_size=100, max_idempotency_size=32)
    first = _request("user-one")
    second = _request("user-two")
    engine.decide(first, idempotency_key="shared-key")
    with pytest.raises(IdempotencyConflict):
        engine.decide(second, idempotency_key="shared-key")


def test_decision_idempotency_cache_stays_bounded_under_unique_key_pressure() -> None:
    engine = ReferenceDecisionEngine(max_log_size=64, max_idempotency_size=32)

    def run(index: int) -> str:
        return engine.decide(_request(f"user-{index}"), idempotency_key=f"idem-{index}")["decision_id"]

    with ThreadPoolExecutor(max_workers=32) as pool:
        ids = list(pool.map(run, range(256)))

    assert len(set(ids)) == 256
    assert engine.stats() == {
        "recent_decisions": 64,
        "idempotency_keys": 32,
        "max_idempotency_keys": 32,
    }


def test_guardrail_fallback_remains_deterministic_under_pressure() -> None:
    engine = ReferenceDecisionEngine(max_log_size=512)
    request = _request()
    request.consent_state = False

    with ThreadPoolExecutor(max_workers=48) as pool:
        results = list(pool.map(lambda i: engine.decide(request, idempotency_key=f"no-consent-{i}"), range(240)))

    assert all(item["action_id"] == "NO_TREATMENT" for item in results)
    assert all(item["propensity"] == 1.0 for item in results)
    assert all(item["action_distribution"] == {"NO_TREATMENT": 1.0} for item in results)


def test_agent_plan_run_ids_are_unique_under_concurrency() -> None:
    def plan(_: int) -> str:
        return agent_plan("提高新用户首购增量", 500_000, "incremental_first_purchase", ["unsubscribe_rate"])["run_id"]

    with ThreadPoolExecutor(max_workers=32) as pool:
        run_ids = list(pool.map(plan, range(256)))

    assert len(set(run_ids)) == 256


def test_approval_same_decision_retries_are_idempotent() -> None:
    state = ReferenceProductState()

    def approve(_: int) -> dict[str, object] | None:
        return state.decide_approval("apr_281", "approve_5", "concurrent retry")

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(approve, range(128)))

    assert all(result is not None for result in results)
    decided_at = {result["decided_at"] for result in results if result is not None}
    assert len(decided_at) == 1
    assert all(result["status"] == "approve_5" for result in results if result is not None)


def test_approval_conflicting_second_decision_is_rejected() -> None:
    state = ReferenceProductState()
    first = state.decide_approval("apr_281", "approve_5", "first decision")
    assert first is not None
    with pytest.raises(ApprovalDecisionConflict):
        state.decide_approval("apr_281", "reject", "conflicting retry")
    current = next(item for item in state.approvals() if item["id"] == "apr_281")
    assert current["status"] == "approve_5"
    assert current["decision_note"] == "first decision"


def test_reference_campaign_state_is_bounded_under_sustained_parallel_writes() -> None:
    state = ReferenceProductState()
    count = MAX_REFERENCE_CAMPAIGNS + 500

    def create(index: int) -> str:
        return state.create_campaign_draft(
            f"pressure-{index}",
            "bounded reference state",
            "synthetic audience",
            1000.0,
            ["NO_TREATMENT", "free_shipping_v3"],
        )["id"]

    with ThreadPoolExecutor(max_workers=64) as pool:
        ids = list(pool.map(create, range(count)))

    assert len(set(ids)) == count
    stats = state.stats()
    assert stats["campaigns"] == MAX_REFERENCE_CAMPAIGNS
    assert stats["max_campaigns"] == MAX_REFERENCE_CAMPAIGNS
