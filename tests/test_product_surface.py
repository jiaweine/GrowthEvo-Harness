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
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    runtime_ui = (STATIC / "runtime-ui.js").read_text(encoding="utf-8")
    assert "DOMContentLoaded" not in pages
    assert "document.addEventListener('DOMContentLoaded',init)" in app
    assert "fidelity.css" in styles
    assert "product-pages.css" in styles
    assert "runtime-ui.js" in index
    assert "product-data.js" in index
    assert "product-advanced-data.js" in index
    assert index.index("data.js") < index.index("runtime-ui.js") < index.index("product-data.js")
    assert index.index("product-data.js") < index.index("product-advanced-data.js") < index.index("pages.js") < index.index("app.js")
    assert "不会把 synthetic demo 数据伪装成真实生产数据" in runtime_ui
    assert "Demo Workspace · Synthetic Data" in runtime_ui
    assert "using demo mode because MODE=auto" not in runtime_ui
    assert "/api/ready" in runtime_ui


def test_core_product_workbenches_are_real_routes() -> None:
    pages = (STATIC / "pages.js").read_text(encoding="utf-8")
    product_data = (STATIC / "product-data.js").read_text(encoding="utf-8")
    advanced_data = (STATIC / "product-advanced-data.js").read_text(encoding="utf-8")
    required_functions = (
        "function opportunities()",
        "function campaignStudio()",
        "function experiments()",
        "function execution()",
        "function realtime()",
        "function approvals()",
        "function evolution()",
    )
    for marker in required_functions:
        assert marker in pages
    for route in ("opportunities", "campaignStudio", "experiments", "realtime", "approvals", "evolution"):
        assert route in product_data or route in pages
    assert "NO_TREATMENT" in pages
    assert "propensity" in pages
    assert "Replay" in pages and "Shadow" in pages and "Canary" in pages
    assert "creatives" in advanced_data and "journeys" in advanced_data and "memories" in advanced_data
    assert "models" in advanced_data and "policies" in advanced_data and "entities" in advanced_data


def test_pages_builder_packages_all_product_assets() -> None:
    build_script = (ROOT / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    service_worker = (STATIC / "service-worker.js").read_text(encoding="utf-8")
    for asset in ("product-pages.css", "runtime-ui.js", "product-data.js", "product-advanced-data.js"):
        assert asset in build_script
        assert asset in service_worker
    assert "isApi(url)" in service_worker
    assert "url.origin!==SCOPE.origin||isApi(url)" in service_worker
    assert "hit||caches.match" not in service_worker


def test_mutable_dashboard_fields_are_html_escaped() -> None:
    views = (STATIC / "views.js").read_text(encoding="utf-8")
    dashboard = (STATIC / "dashboard-page.js").read_text(encoding="utf-8")
    assert "${esc(c.name)}" in views
    assert "${esc(c.goal)}" in views
    assert "${esc(c.type)}" in views
    assert "c.population==null?'—'" in views
    assert "${esc(k.label)}" in dashboard
    assert "safeColor" in dashboard
    assert "go('campaignStudio')" in dashboard


def test_agent_composer_calls_real_api_outside_demo() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/agent/plan" in app
    assert "if(useDemo)" in app
    assert "renderApiUnavailable(error)" in app


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
    assert no_consent["action_distribution"] == {"NO_TREATMENT": 1.0}

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
