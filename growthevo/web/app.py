from __future__ import annotations

from pathlib import Path
from typing import Any

from .data import build_dashboard_payload
from .decisioning import ReferenceDecisionEngine, action_registry_payload
from .product_data import (
    agent_plan,
    approvals,
    campaigns,
    create_campaign_draft,
    decide_approval,
    evolution_candidates,
    experiments,
    harness_runs,
    opportunities,
)
from .schemas import AgentPlanRequest, ApprovalDecisionRequest, CampaignDraftRequest, DecisionRequest

STATIC_DIR = Path(__file__).with_name("static")
_engine = ReferenceDecisionEngine()


def create_app() -> Any:
    """Create the GrowthEvo product surface and versioned API."""
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("GrowthEvo web dependencies are not installed. Install: pip install -e '.[web]'") from exc

    app = FastAPI(
        title="GrowthEvo Growth OS",
        version="1.0",
        description="Agentic causal growth product API. Production side effects remain gated behind explicit connectors and approvals.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "growthevo-web", "api": "v1"}

    @app.get("/api/dashboard", tags=["compat"])
    @app.get("/api/v1/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        return build_dashboard_payload()

    @app.get("/api/capabilities", tags=["compat"])
    def capabilities() -> list[dict[str, Any]]:
        return build_dashboard_payload()["capabilities"]

    @app.get("/api/evidence", tags=["compat"])
    def evidence() -> list[dict[str, Any]]:
        return build_dashboard_payload()["evidence"]

    @app.get("/api/v1/opportunities", tags=["causal"])
    def opportunity_list() -> list[dict[str, Any]]:
        return opportunities()

    @app.get("/api/v1/campaigns", tags=["campaigns"])
    def campaign_list() -> list[dict[str, Any]]:
        return campaigns()

    @app.post("/api/v1/campaigns/draft", tags=["campaigns"], status_code=201)
    def campaign_draft(request: CampaignDraftRequest) -> dict[str, Any]:
        return create_campaign_draft(request.name, request.goal, request.audience, request.budget, request.candidate_action_ids)

    @app.get("/api/v1/experiments", tags=["experiments"])
    def experiment_list() -> list[dict[str, Any]]:
        return experiments()

    @app.get("/api/v1/approvals", tags=["governance"])
    def approval_list() -> list[dict[str, Any]]:
        return approvals()

    @app.post("/api/v1/approvals/{approval_id}/decision", tags=["governance"])
    def approval_decision(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
        result = decide_approval(approval_id, request.decision, request.note)
        if result is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return result

    @app.get("/api/v1/harness/runs", tags=["harness"])
    def runs() -> list[dict[str, Any]]:
        return harness_runs()

    @app.get("/api/v1/evolution/candidates", tags=["evolution"])
    def evolution() -> list[dict[str, Any]]:
        return evolution_candidates()

    @app.post("/api/v1/agent/plan", tags=["agent"])
    def plan(request: AgentPlanRequest) -> dict[str, Any]:
        return agent_plan(request.goal, request.budget_limit, request.primary_metric, request.guardrails)

    @app.get("/api/v1/actions", tags=["decisioning"])
    def actions() -> list[dict[str, Any]]:
        return action_registry_payload()

    @app.post("/api/v1/realtime/decision", tags=["decisioning"], include_in_schema=False)
    @app.post("/api/v1/decide", tags=["decisioning"])
    def decide(request: DecisionRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        return _engine.decide(request, idempotency_key=idempotency_key)

    @app.get("/api/v1/decisions/recent", tags=["decisioning"])
    def recent_decisions(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return _engine.recent(limit)

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/service-worker.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(STATIC_DIR / "service-worker.js", media_type="application/javascript")

    @app.get("/", include_in_schema=False)
    @app.get("/{route:path}", include_in_schema=False)
    def index(route: str = "") -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
