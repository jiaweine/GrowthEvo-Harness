from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .data import build_dashboard_payload
from .decisioning import (
    DecisionInputError,
    IdempotencyConflict,
    ReferenceDecisionEngine,
    action_registry_payload,
)
from .product_data import (
    ApprovalDecisionConflict,
    ReferenceProductState,
    agent_plan,
    evolution_candidates,
    experiments,
    harness_runs,
    opportunities,
)
from .runtime import RuntimeSettings
from .schemas import AgentPlanRequest, ApprovalDecisionRequest, CampaignDraftRequest, DecisionRequest

STATIC_DIR = Path(__file__).with_name("static")
MAX_API_BODY_BYTES = 1_000_000
PRODUCTION_SYSTEM_PATHS = frozenset(
    {
        "/api/health",
        "/api/ready",
        "/api/v1/system/runtime",
        "/api/v1/system/connectors",
        "/api/docs",
        "/api/openapi.json",
    }
)


class ApiBodyLimitMiddleware:
    """Bound API request bodies by bytes actually received, not just headers.

    Content-Length is useful as an early rejection hint but cannot be trusted as
    the sole limit because clients can stream chunked bodies or provide an
    incorrect value. This middleware buffers at most ``max_bytes`` for JSON API
    writes, then replays the bounded body to FastAPI. Oversized/malformed bodies
    fail before validation and the HTTP/1.1 connection is closed so unread bytes
    cannot bleed into a subsequent request.
    """

    def __init__(self, app: Any, max_bytes: int = MAX_API_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send: Any, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"connection", b"close"),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))
        is_api = path == "/api" or path.startswith("/api/")
        if not is_api or method not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        raw_length: bytes | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                raw_length = value
                break
        if raw_length is not None:
            try:
                declared = int(raw_length.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                await self._reject(send, 400, "invalid Content-Length")
                return
            if declared < 0:
                await self._reject(send, 400, "invalid Content-Length")
                return
            if declared > self.max_bytes:
                await self._reject(send, 413, f"API request body exceeds {self.max_bytes} bytes")
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "http.disconnect":
                return
            if message_type != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._reject(send, 413, f"API request body exceeds {self.max_bytes} bytes")
                return
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


def create_app() -> Any:
    """Create the GrowthEvo product surface and versioned API."""
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("GrowthEvo web dependencies are not installed. Install: pip install -e '.[web]'") from exc

    settings = RuntimeSettings.from_env()
    decision_engine = ReferenceDecisionEngine()
    product_state = ReferenceProductState()
    app = FastAPI(
        title="GrowthEvo Growth OS",
        version="1.0",
        description="Agentic causal growth product API. Production side effects remain gated behind explicit connectors and approvals.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.decision_engine = decision_engine
    app.state.product_state = product_state

    # Add the byte limiter before CORS so Starlette's middleware stacking leaves
    # CORS outside it. Rejections from the limiter therefore retain the exact
    # configured Access-Control-Allow-Origin and remain readable by the Pages UI.
    app.add_middleware(ApiBodyLimitMiddleware, max_bytes=MAX_API_BODY_BYTES)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    @app.middleware("http")
    async def runtime_headers(request: Any, call_next: Any) -> Any:
        path = request.url.path
        is_api = path == "/api" or path.startswith("/api/")

        if (
            settings.production
            and not settings.ready
            and is_api
            and path not in PRODUCTION_SYSTEM_PATHS
        ):
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "production runtime is not ready; business APIs are fail-closed",
                    "mode": settings.mode,
                    "environment": settings.environment,
                },
            )
        else:
            response = await call_next(request)

        response.headers["X-GrowthEvo-Mode"] = settings.mode
        response.headers["X-GrowthEvo-Environment"] = settings.environment
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "growthevo-web",
            "api": "v1",
            "mode": settings.mode,
            "environment": settings.environment,
        }

    @app.get("/api/ready", tags=["system"])
    def readiness() -> Any:
        payload = settings.public_payload()
        if not settings.ready:
            return JSONResponse(status_code=503, content={"status": "not_ready", **payload})
        return {"status": "ready", **payload}

    @app.get("/api/v1/system/runtime", tags=["system"])
    def runtime() -> dict[str, object]:
        return settings.public_payload()

    @app.get("/api/v1/system/connectors", tags=["system"])
    def connectors() -> list[dict[str, str]]:
        return settings.connector_states()

    @app.get("/api/dashboard", tags=["compat"])
    @app.get("/api/v1/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        return build_dashboard_payload(product_state)

    @app.get("/api/capabilities", tags=["compat"])
    def capabilities() -> list[dict[str, Any]]:
        return build_dashboard_payload(product_state)["capabilities"]

    @app.get("/api/evidence", tags=["compat"])
    def evidence() -> list[dict[str, Any]]:
        return build_dashboard_payload(product_state)["evidence"]

    @app.get("/api/v1/opportunities", tags=["causal"])
    def opportunity_list() -> list[dict[str, Any]]:
        return opportunities()

    @app.get("/api/v1/campaigns", tags=["campaigns"])
    def campaign_list() -> list[dict[str, Any]]:
        return product_state.campaigns()

    @app.post("/api/v1/campaigns/draft", tags=["campaigns"], status_code=201)
    def campaign_draft(request: CampaignDraftRequest) -> dict[str, Any]:
        return product_state.create_campaign_draft(
            request.name,
            request.goal,
            request.audience,
            request.budget,
            request.candidate_action_ids,
        )

    @app.get("/api/v1/experiments", tags=["experiments"])
    def experiment_list() -> list[dict[str, Any]]:
        return experiments()

    @app.get("/api/v1/approvals", tags=["governance"])
    def approval_list() -> list[dict[str, Any]]:
        return product_state.approvals()

    @app.post("/api/v1/approvals/{approval_id}/decision", tags=["governance"])
    def approval_decision(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
        try:
            result = product_state.decide_approval(approval_id, request.decision, request.note)
        except ApprovalDecisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    def decide(
        request: DecisionRequest,
        idempotency_keys: list[str] | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
    ) -> dict[str, Any]:
        if idempotency_keys is not None and len(idempotency_keys) > 1:
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key must be supplied at most once",
            )

        normalized_key: str | None = None
        if idempotency_keys:
            raw_key = idempotency_keys[0]
            if len(raw_key) > 256:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key must be at most 256 characters",
                )
            normalized_key = raw_key.strip()
            if not normalized_key:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key must contain non-whitespace characters",
                )
        try:
            return decision_engine.decide(request, idempotency_key=normalized_key)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except DecisionInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/decisions/recent", tags=["decisioning"])
    def recent_decisions(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return decision_engine.recent(limit)

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/service-worker.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "service-worker.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    @app.get("/{route:path}", include_in_schema=False)
    def index(route: str = "") -> FileResponse:
        if route == "api" or route.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
