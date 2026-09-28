from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.web.product_data import agent_plan, dashboard_payload, opportunities


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "growthevo" / "web" / "static"


def test_growth_os_dashboard_exposes_incremental_kpis() -> None:
    payload = dashboard_payload()
    ids = {item["id"] for item in payload["kpis"]}
    assert {"incremental_revenue", "incremental_profit", "incremental_roi", "waste_avoided"} <= ids
    assert payload["summary"]["no_treatment_rate"] > 0


def test_opportunity_map_carries_support_and_evidence() -> None:
    rows = opportunities()
    assert rows
    assert all(0 <= item["support"] <= 1 for item in rows)
    assert all(item["evidence_tier"] in {"A", "B", "C", "D"} for item in rows)


def test_agent_plan_separates_claim_types_and_artifacts() -> None:
    result = agent_plan("提高新用户首购增量", 500_000, "incremental_first_purchase", ["unsubscribe_rate"])
    claim_types = {item["type"] for item in result["claims"]}
    artifact_types = {item["type"] for item in result["artifacts"]}
    assert {"FACT", "ESTIMATE", "HYPOTHESIS", "IDEA"} <= claim_types
    assert {"StrategyProposal", "ExperimentDraft", "CampaignDraft", "ApprovalRequest"} <= artifact_types
    assert result["next_gate"] == "Shadow preflight"


def test_browser_bootstrap_runs_after_all_deferred_modules() -> None:
    pages = (STATIC / "pages.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "DOMContentLoaded" not in pages
    assert "document.addEventListener('DOMContentLoaded',init)" in app
    assert "fidelity.css" in styles


def test_optional_decision_engine_contract() -> None:
    pytest.importorskip("pydantic")
    from growthevo.web.decisioning import ACTION_REGISTRY, ReferenceDecisionEngine
    from growthevo.web.schemas import DecisionRequest

    engine = ReferenceDecisionEngine()
    no_consent = engine.decide(
        DecisionRequest(entity_id="u-1", placement="checkout", consent_state=False)
    )
    assert no_consent["action_id"] == "NO_TREATMENT"
    assert no_consent["propensity"] == 1.0

    request = DecisionRequest(
        entity_id="u-2",
        placement="checkout",
        context={"cart_value": 198, "session_intent": "high", "new_user": True},
        candidate_action_ids=["free_shipping_v3"],
        consent_state=True,
        frequency_remaining=2,
        budget_remaining=50,
        context_freshness_seconds=10,
    )
    first = engine.decide(request, idempotency_key="idem-1")
    second = engine.decide(request, idempotency_key="idem-1")
    assert first["decision_id"] == second["decision_id"]
    assert "NO_TREATMENT" in first["action_distribution"]
    assert 0 < first["propensity"] <= 1
    assert ACTION_REGISTRY["NO_TREATMENT"].cost == 0
    assert ACTION_REGISTRY["NO_TREATMENT"].risk_level == "L0"
