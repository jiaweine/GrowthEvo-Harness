from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from functools import partial
import json
import os
from pathlib import Path
from typing import Any

from growthevo.agent_os import GrowthTools
from growthevo.agent_os.journal import ExecutionConflict, MemoryAgentBackend, RunJournal, principal_scope
from growthevo.agent_os.recovery import RecoverableOperator
from growthevo.agent_os.durable_evolution import DurableEvolutionAuthority
from growthevo.llm.agent_planner import GuardedLLMAgentPlanner
from growthevo.llm.configuration import (
    activation_summary,
    build_provider_pool_from_env,
    close_provider_pool,
    llm_environment_configured,
)

from .growth_store import GrowthConflict, GrowthMissing, GrowthStore
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
from .runtime import RuntimeSettings, postgres_pool_config_from_env
from .schemas import AgentPlanRequest, AgentRunRequest, AgentResumeRequest, AgentUiConfirmation, ApprovalDecisionRequest, CampaignDraftRequest, DecisionRequest

STATIC_DIR = Path(__file__).with_name("static")
MAX_API_BODY_BYTES = 1_000_000
DECISION_IDEMPOTENCY_PATHS = frozenset({"/api/decide", "/api/realtime/decision"})
PRODUCTION_SYSTEM_PATHS = frozenset(
    {
        "/api/health",
        "/api/ready",
        "/api/system/runtime",
        "/api/system/connectors",
        "/api/docs",
        "/api/openapi.json",
    }
)


class ApiBodyLimitMiddleware:
    """Bound API writes and reject ambiguous decision idempotency headers.

    Content-Length is useful as an early rejection hint but cannot be trusted as
    the sole limit because clients can stream chunked bodies or provide an
    incorrect value. This middleware buffers at most ``max_bytes`` for JSON API
    writes, then replays the bounded body to FastAPI. It also rejects duplicate
    ``Idempotency-Key`` headers on decision endpoints before the request reaches
    framework header normalization. Early rejections close the HTTP/1.1
    connection so unread bytes cannot bleed into a subsequent request.
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

        scope_headers = scope.get("headers", [])
        if path in DECISION_IDEMPOTENCY_PATHS:
            idempotency_header_count = sum(
                1 for name, _ in scope_headers if name.lower() == b"idempotency-key"
            )
            if idempotency_header_count > 1:
                await self._reject(send, 422, "Idempotency-Key must be supplied at most once")
                return

        raw_length: bytes | None = None
        for name, value in scope_headers:
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
    """Create the GrowthEvo product surface and stable API."""
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from .growth_api import growth_router
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("GrowthEvo web dependencies are not installed. Install: pip install -e '.[web]'") from exc

    settings = RuntimeSettings.from_env()
    authenticator: Any | None = None
    persistence_store: Any | None = None
    llm_pool: Any | None = None
    agent_planner: GuardedLLMAgentPlanner | None = None

    # Authentication activation requires the complete generic OIDC/JWKS contract.
    # Partial settings remain visible as configured_not_active and production stays
    # fail-closed. Complete settings are fail-fast: the JWKS must be reachable and
    # contain a usable RS256 signing key before the adapter becomes active.
    auth_issuer = os.getenv("GROWTHEVO_AUTH_ISSUER", "").strip()
    auth_jwks_url = os.getenv("GROWTHEVO_AUTH_JWKS_URL", "").strip()
    auth_audience = os.getenv("GROWTHEVO_AUTH_AUDIENCE", "").strip()
    if auth_issuer and auth_jwks_url and auth_audience and not settings.synthetic_data:
        from .auth import OidcJwksAuthenticator

        try:
            authenticator = OidcJwksAuthenticator(
                issuer=auth_issuer,
                jwks_url=auth_jwks_url,
                audience=auth_audience,
                require_https=settings.production,
            )
        except Exception as exc:
            raise RuntimeError("configured OIDC/JWKS authentication could not be initialized") from exc
        settings = replace(settings, auth_backend=authenticator.backend)

    # Demo mode never reaches an external database even if a generic DATABASE_URL
    # leaks into the environment. API/production mode treats a configured database
    # as explicit intent: initialization must succeed or startup fails instead of
    # silently dropping back to process-local state.
    if settings.database_configured and not settings.synthetic_data:
        from .persistence import (
            PersistentReferenceDecisionEngine,
            PostgresProductState,
            PostgresStore,
        )

        database_url = (
            os.getenv("GROWTHEVO_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or ""
        ).strip()
        try:
            pool_config = postgres_pool_config_from_env()
            persistence_store = PostgresStore(
                database_url,
                seed_reference=not settings.production,
                min_size=pool_config.min_size,
                max_size=pool_config.max_size,
                timeout_seconds=pool_config.timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError("configured PostgreSQL persistence could not be initialized") from exc
        settings = replace(settings, persistence_backend=persistence_store.backend)
        decision_engine = PersistentReferenceDecisionEngine(persistence_store)
        product_state = PostgresProductState(persistence_store)
    else:
        decision_engine = ReferenceDecisionEngine()
        product_state = ReferenceProductState()

    growth_store = GrowthStore(persistence_store) if persistence_store is not None else None

    replay_suite = None
    replay_path = os.getenv("GROWTHEVO_AGENT_BENCHMARK_PATH", "").strip()
    replay_digest = os.getenv("GROWTHEVO_AGENT_BENCHMARK_SHA256", "").strip()
    if (replay_path or replay_digest) and not settings.synthetic_data:
        from growthevo.agent_os.manifest import LockedReplaySuite
        try:
            replay_suite = LockedReplaySuite(replay_path, replay_digest)
        except Exception as exc:
            if persistence_store is not None:
                persistence_store.close()
            raise RuntimeError("configured offline evaluation manifest is invalid") from exc


    # Demo is credential-free by contract and never reaches an external model,
    # even if API keys leak into its environment. API/production activation needs
    # a complete Key + explicitly pinned model pair. Build this last so failures
    # can close an already-open persistence store before startup aborts.
    if llm_environment_configured() and not settings.synthetic_data:
        try:
            llm_pool = build_provider_pool_from_env()
        except Exception as exc:
            if persistence_store is not None:
                persistence_store.close()
            raise RuntimeError("configured LLM provider runtime could not be initialized") from exc

    # The same health-aware pool serves proposal and critic calls sequentially.
    # They never race in parallel. The planner itself owns no network resources;
    # provider clients remain process-long and are closed by the app lifespan.
    if llm_pool is not None:
        agent_planner = GuardedLLMAgentPlanner(llm_pool, critic=llm_pool)

    if persistence_store is not None:
        from .agent_persistence import PostgresAgentBackend
        agent_backend = PostgresAgentBackend(persistence_store)
    else:
        agent_backend = MemoryAgentBackend(product_state.create_campaign_draft)

    def execution_context(scope: str):
        traces = RunJournal(agent_backend, scope)
        authority = DurableEvolutionAuthority(agent_backend, scope)
        tools = GrowthTools(
            readers={
                "dashboard": lambda: build_dashboard_payload(product_state),
                "opportunities": opportunities,
                "campaigns": product_state.campaigns,
                "experiments": experiments,
                "approvals": product_state.approvals,
                "evidence": lambda: build_dashboard_payload(product_state)["evidence"],
                "actions": action_registry_payload,
                "decisions": lambda: decision_engine.recent(20),
                "harness": lambda: traces.recent(20),
                "evolution": authority.candidates,
            }, product_state=product_state,
        )
        operator = RecoverableOperator(llm_pool, tools, traces, authority, journal=traces) if llm_pool else None
        return traces, authority, tools, operator

    def authorized_execution(authorization: str | None):
        if authenticator is None:
            if settings.production:
                raise HTTPException(status_code=503, detail="Authenticated production execution is unavailable")
            return execution_context("local-development")
        from .auth import AuthenticationError, AuthenticationUnavailable
        try:
            claims = authenticator.authenticate_authorization_header(authorization)
            scope = principal_scope(claims)
        except AuthenticationUnavailable as exc:
            raise HTTPException(status_code=503, detail="Identity provider is temporarily unavailable") from exc
        except (AuthenticationError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="valid bearer token required") from exc
        return execution_context(scope)

    agent_traces, evolution_authority, operator_tools, agent_operator = execution_context("local-development")

    @asynccontextmanager
    async def lifespan(_: Any):
        worker_task = None
        if (growth_store is not None and
                os.getenv("GROWTHEVO_JOURNEY_WORKER_ENABLED", "").strip().lower()
                in {"1", "true", "yes"}):
            from .growth_worker import run_growth_worker
            worker_task = asyncio.create_task(run_growth_worker(growth_store))
        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            try:
                await close_provider_pool(llm_pool)
            finally:
                if persistence_store is not None:
                    persistence_store.close()

    app = FastAPI(
        title="GrowthEvo Growth OS",
        version="stable",
        description="Agentic causal growth product API. Production side effects remain gated behind explicit connectors and approvals.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(growth_router(
        growth_store, production=settings.production,
        seed_demo=not settings.production and not settings.synthetic_data,
    ))
    app.state.growth_store = growth_store
    app.state.decision_engine = decision_engine
    app.state.product_state = product_state
    app.state.persistence_store = persistence_store
    app.state.authenticator = authenticator
    app.state.llm_pool = llm_pool
    app.state.agent_planner = agent_planner
    app.state.agent_operator = agent_operator
    app.state.agent_traces = agent_traces
    app.state.evolution_authority = evolution_authority
    app.state.runtime_settings = settings

    @app.exception_handler(GrowthMissing)
    async def growth_missing(_request: Any, _error: GrowthMissing):
        return JSONResponse(status_code=404, content={"detail": "growth resource not found"})

    @app.exception_handler(GrowthConflict)
    async def growth_conflict(_request: Any, error: GrowthConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ExecutionConflict)
    async def execution_conflict(_request: Any, _error: ExecutionConflict):
        return JSONResponse(status_code=409, content={"detail": "Execution state changed or is owned by another worker; refresh before retrying"})

    def persistence_healthy() -> bool:
        if persistence_store is None:
            return True
        try:
            return bool(persistence_store.healthy())
        except Exception:
            return False

    def authentication_healthy() -> bool:
        if authenticator is None:
            return True
        try:
            # Readiness must be local and bounded. OIDC initialization already
            # fetched JWKS fail-fast; bearer verification owns later refreshes and
            # returns 503 fail-closed if the IdP is unavailable.
            return bool(authenticator.readiness_healthy())
        except Exception:
            return False

    def runtime_ready() -> bool:
        # LLMs are intentionally not a readiness dependency: the guarded planner
        # fails closed to deterministic policy when every model route is unavailable.
        # Authentication readiness is also local-only so a remote IdP incident
        # cannot turn Render's platform health probe into an instance restart loop.
        return settings.ready and persistence_healthy() and authentication_healthy()

    def runtime_payload() -> dict[str, object]:
        payload = settings.public_payload()
        gateway_configured = False
        if settings.production:
            from .growth_channels import ChannelConfigurationError, ChannelWebhook
            try:
                ChannelWebhook.from_environment()
                gateway_configured = (
                    len(os.getenv("GROWTHEVO_CHANNEL_SUBMIT_SECRET", "")) >= 16
                    and len(os.getenv("GROWTHEVO_CHANNEL_RECEIPT_SECRET", "")) >= 16
                )
            except ChannelConfigurationError:
                pass
        gateway_enabled = bool(gateway_configured and growth_store is not None and runtime_ready())
        payload["side_effects_enabled"] = gateway_enabled
        if gateway_enabled:
            payload["execution_mode"] = "separately-authorized-webhook"
        payload["growth_operations"] = {
            "backend": "postgresql" if growth_store is not None else "unavailable",
            "journey_worker_configured": (
                growth_store is not None
                and os.getenv("GROWTHEVO_JOURNEY_WORKER_ENABLED", "").strip().lower()
                in {"1", "true", "yes"}
            ),
            "channel_gateway_configured": gateway_configured,
            "external_submission_enabled": gateway_enabled,
        }
        persistence_ok = persistence_healthy()
        authentication_ok = authentication_healthy()
        payload["ready"] = bool(settings.ready and persistence_ok and authentication_ok)
        connectors = [dict(item) for item in payload["connectors"]]

        if persistence_store is not None:
            persistence = dict(payload["persistence"])
            persistence["healthy"] = persistence_ok
            payload["persistence"] = persistence
            for connector in connectors:
                if connector.get("id") == "persistence":
                    connector["state"] = "connected" if persistence_ok else "error"

        if authenticator is not None:
            authentication = dict(payload["authentication"])
            authentication["healthy"] = authentication_ok
            payload["authentication"] = authentication
            for connector in connectors:
                if connector.get("id") == "authentication":
                    connector["state"] = "connected" if authentication_ok else "error"

        llm_summary = activation_summary(llm_pool)
        if settings.synthetic_data:
            llm_available_routes = 0
            llm_healthy = True
            llm_state = "demo"
        elif llm_pool is not None:
            route_health = llm_pool.health_snapshot()
            llm_available_routes = sum(
                1 for route in route_health if route.circuit_state != "open"
            )
            llm_healthy = llm_available_routes > 0
            llm_state = "connected" if llm_healthy else "error"
        else:
            llm_available_routes = 0
            llm_healthy = not llm_summary.configured
            llm_state = "configured_not_active" if llm_summary.configured else "unconfigured"

        llm_payload: dict[str, object] = {
            "configured": llm_summary.configured,
            "active": llm_summary.active,
            "backend": llm_summary.backend,
            "route_count": llm_summary.route_count,
            "available_routes": llm_available_routes,
            "healthy": llm_healthy,
            "providers": list(llm_summary.providers),
            "agent_planning": agent_planner is not None,
            "agent_execution": agent_operator is not None,
            "critic": agent_planner is not None,
        }
        if llm_pool is not None:
            llm_payload["metrics"] = asdict(llm_pool.metrics())
            capacity = llm_pool.capacity_snapshot()
            llm_payload["capacity"] = asdict(capacity)
            if llm_available_routes <= 0:
                llm_payload["load_state"] = "safe"
            elif capacity.observed_routes and (
                capacity.waiting > 0 or capacity.saturated_routes > 0
            ):
                llm_payload["load_state"] = "busy"
            elif llm_available_routes < llm_summary.route_count:
                llm_payload["load_state"] = "degraded"
            else:
                llm_payload["load_state"] = "ready"
        else:
            llm_payload["load_state"] = "inactive"
        payload["agent_execution"] = {
            "durability": agent_backend.durability,
            "principal_isolation": authenticator is not None,
            "checkpoint_recovery": True,
            "external_browser": False,
        }
        payload["llm"] = llm_payload
        for connector in connectors:
            if connector.get("id") == "llm":
                connector["label"] = "LLM Provider Pool"
                connector["state"] = llm_state

        if settings.channel_configured:
            for connector in connectors:
                if connector.get("id") == "channels":
                    connector["state"] = (
                        "configured" if gateway_configured else "configured_not_active"
                    )
        payload["connectors"] = connectors
        return payload

    # Add the byte/header limiter before CORS so Starlette's middleware stacking
    # leaves CORS outside it. Rejections therefore retain the exact configured
    # Access-Control-Allow-Origin and remain readable by the Pages UI.
    app.add_middleware(ApiBodyLimitMiddleware, max_bytes=MAX_API_BODY_BYTES)

    @app.middleware("http")
    async def runtime_headers(request: Any, call_next: Any) -> Any:
        path = request.url.path
        method = request.method.upper()
        is_api = path == "/api" or path.startswith("/api/")
        is_production_business_api = (
            settings.production
            and is_api
            and method != "OPTIONS"
            and path not in PRODUCTION_SYSTEM_PATHS
        )
        protected_agent_api = authenticator is not None and method != "OPTIONS" and (
            path.startswith("/api/agent/") or path.startswith("/api/evolution/") or path.startswith("/api/growth/") or path == "/api/harness/runs"
        )

        if is_production_business_api and not runtime_ready():
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "production runtime is not ready; business APIs are fail-closed",
                    "mode": settings.mode,
                    "environment": settings.environment,
                },
            )
        elif is_production_business_api or protected_agent_api:
            from .auth import AuthenticationError, AuthenticationUnavailable

            raw_headers = request.scope.get("headers", [])
            authorization_count = sum(
                1 for name, _ in raw_headers if name.lower() == b"authorization"
            )
            try:
                if authorization_count != 1 or authenticator is None:
                    raise AuthenticationError("authentication required")
                claims = authenticator.authenticate_authorization_header(
                    request.headers.get("authorization")
                )
                request.state.auth_claims = claims
                response = await call_next(request)
            except AuthenticationUnavailable:
                response = JSONResponse(
                    status_code=503,
                    content={
                        "detail": "identity provider is temporarily unavailable; business API is fail-closed",
                        "mode": settings.mode,
                        "environment": settings.environment,
                    },
                )
            except AuthenticationError:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "valid bearer token required"},
                    headers={"WWW-Authenticate": "Bearer"},
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

    # Keep CORS outside authentication/readiness early responses too.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Channel-Receipt-Token", "X-Channel-Submit-Token"],
        )


    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "growthevo-web",
            "api": "stable",
            "mode": settings.mode,
            "environment": settings.environment,
        }

    @app.get("/api/ready", tags=["system"])
    def readiness() -> Any:
        payload = runtime_payload()
        if not payload["ready"]:
            return JSONResponse(status_code=503, content={"status": "not_ready", **payload})
        return {"status": "ready", **payload}

    @app.get("/api/system/runtime", tags=["system"])
    def runtime() -> dict[str, object]:
        return runtime_payload()

    @app.get("/api/system/connectors", tags=["system"])
    def connectors() -> list[dict[str, str]]:
        payload = runtime_payload()
        return payload["connectors"]  # type: ignore[return-value]

    @app.get("/api/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        return build_dashboard_payload(product_state)

    @app.get("/api/capabilities", tags=["dashboard"])
    def capabilities() -> list[dict[str, Any]]:
        return build_dashboard_payload(product_state)["capabilities"]

    @app.get("/api/evidence", tags=["dashboard"])
    def evidence() -> list[dict[str, Any]]:
        return build_dashboard_payload(product_state)["evidence"]

    @app.get("/api/opportunities", tags=["causal"])
    def opportunity_list() -> list[dict[str, Any]]:
        return opportunities()

    @app.get("/api/campaigns", tags=["campaigns"])
    def campaign_list() -> list[dict[str, Any]]:
        return product_state.campaigns()

    @app.post("/api/campaigns/draft", tags=["campaigns"], status_code=201)
    def campaign_draft(request: CampaignDraftRequest) -> dict[str, Any]:
        return product_state.create_campaign_draft(
            request.name,
            request.goal,
            request.audience,
            request.budget,
            request.candidate_action_ids,
        )

    @app.get("/api/experiments", tags=["experiments"])
    def experiment_list() -> list[dict[str, Any]]:
        return experiments()

    @app.get("/api/approvals", tags=["governance"])
    def approval_list() -> list[dict[str, Any]]:
        return product_state.approvals()

    @app.post("/api/approvals/{approval_id}/decision", tags=["governance"])
    def approval_decision(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
        try:
            result = product_state.decide_approval(approval_id, request.decision, request.note)
        except ApprovalDecisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return result

    @app.get("/api/harness/runs", tags=["harness"])
    def runs(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        traces, _, _, _ = authorized_execution(authorization)
        return harness_runs() if settings.synthetic_data else traces.recent(50)

    @app.get("/api/evolution/candidates", tags=["evolution"])
    def evolution(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        _, authority, _, _ = authorized_execution(authorization)
        return evolution_candidates() if settings.synthetic_data else authority.candidates()

    @app.get("/api/evolution/policy", tags=["evolution"])
    def evolution_policy(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _, authority, _, _ = authorized_execution(authorization)
        return authority.snapshot()

    @app.get("/api/evolution/readiness", tags=["evolution"])
    def evolution_readiness(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, authority, _, _ = authorized_execution(authorization)
        if settings.synthetic_data:
            return {
                "mode": "demo", "trace_count": 0, "required_trace_count": 8,
                "step_limit_count": 0, "completed_count": 0,
                "candidate_count": 0, "enough_traces": False,
                "evaluation_runner": "independent_offline_only",
                "promotion": "separate_shadow_canary_and_human_approval",
                "durability": "process_local",
                "evaluation_available": False,
            }
        return authority.readiness(traces.recent(100)) | {
            "mode": "live",
            "evaluation_available": replay_suite is not None and llm_pool is not None,
            "evaluation_suite": replay_suite.suite_id if replay_suite else None,
            "evaluation_digest": replay_suite.digest if replay_suite else None,
        }

    @app.post("/api/evolution/analyze", tags=["evolution"])
    def evolution_analyze(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, authority, _, _ = authorized_execution(authorization)
        if settings.synthetic_data:
            raise HTTPException(status_code=409, detail="Demo traces cannot generate real evolution candidates")
        recent = traces.recent(100)
        candidate = authority.propose(recent)
        return {
            "trace_count": authority.readiness(recent)["trace_count"],
            "candidate_created": candidate is not None,
            "candidate_id": candidate.id if candidate else None,
            "candidate_count": len(authority.candidates()),
            "policy_fingerprint": authority.snapshot()["fingerprint"],
            "evaluation_required": True,
            "durability": agent_backend.durability,
            "created": candidate is not None,
            "candidate": asdict(candidate) if candidate is not None else None,
            "readiness": authority.readiness(recent),
            "candidates": authority.candidates(),
            "next_gate": "independent_offline_evaluation",
            "message": (
                "Created a bounded candidate; independent offline evaluation is required."
                if candidate is not None else
                "No eligible new proposal from the observed runs; no improvement has been claimed."
            ),
        }

    @app.post("/api/evolution/candidates/{candidate_id}/evaluate", tags=["evolution"])
    async def evaluate_candidate(candidate_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, authority, _, _ = authorized_execution(authorization)
        if settings.synthetic_data:
            raise HTTPException(status_code=409, detail="Demo candidates cannot receive real evaluation evidence")
        if replay_suite is None or llm_pool is None:
            raise HTTPException(status_code=503, detail="Independent offline evaluation is not configured")
        if not any(item["id"] == candidate_id for item in authority.candidates()):
            raise HTTPException(status_code=404, detail="candidate not found")
        from starlette.concurrency import run_in_threadpool

        try:
            # Use only server-owned task snapshots and a fresh provider pool.
            # The client cannot submit metrics, callbacks or executable code.
            evaluator = partial(replay_suite.evaluate, pool_factory=build_provider_pool_from_env)
            candidate = await run_in_threadpool(authority.evaluate, candidate_id, evaluator)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Candidate is not eligible or evaluation evidence was rejected") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Offline evaluation failed; no result was accepted. Retry is safe.") from exc
        return {
            "candidate": asdict(candidate), "suite_id": replay_suite.suite_id,
            "evidence_scope": "offline_tool_and_route_contracts",
            "promotion_performed": False,
        }


    @app.get("/api/agent/tools", tags=["agent"])
    def agent_tools() -> list[dict[str, str]]:
        return operator_tools.describe()

    @app.post("/api/agent/run", tags=["agent"])
    async def operate(request: AgentRunRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _, _, _, operator = authorized_execution(authorization)
        if operator is None:
            return {
                "status": "model_unavailable", "steps": [],
                "message": "Autonomous execution needs an active model provider; no actions were run.",
                "navigation": None, "durability": "process_local",
            }
        return await operator.run(
            request.goal,
            allow_drafts=request.allow_draft_writes,
            max_steps=request.max_steps,
        )

    @app.post("/api/agent/runs/{run_id}/ui-confirmation", tags=["agent"])
    def confirm_agent_ui(run_id: str, request: AgentUiConfirmation,
                         authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, _, _, _ = authorized_execution(authorization)
        try:
            return traces.confirm_ui(
                run_id, request.token, [item.model_dump() for item in request.receipts]
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run confirmation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/agent/runs/{run_id}", tags=["agent"])
    def agent_run_detail(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, _, _, _ = authorized_execution(authorization)
        try:
            return traces.result(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/agent/runs/{run_id}/events", tags=["agent"])
    def agent_run_events(run_id: str, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        traces, _, _, _ = authorized_execution(authorization)
        try:
            return traces.events(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/agent/runs/{run_id}/resume", tags=["agent"])
    async def resume_agent_run(run_id: str, request: AgentResumeRequest,
                               authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, _, _, operator = authorized_execution(authorization)
        try:
            previous = traces.result(run_id)
            if operator is None:
                if previous["status"] == "awaiting_ui_confirmation" or not previous["resumable"]:
                    return previous
                raise HTTPException(status_code=503, detail="Resume requires an active model provider")
            return await operator.run("", run_id=run_id, allow_drafts=request.allow_draft_writes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/agent/runs/{run_id}/cancel", tags=["agent"])
    def cancel_agent_run(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        traces, _, _, _ = authorized_execution(authorization)
        try:
            return traces.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/agent/plan", tags=["agent"])
    async def plan(request: AgentPlanRequest) -> dict[str, Any]:
        baseline = agent_plan(
            request.goal,
            request.budget_limit,
            request.primary_metric,
            request.guardrails,
        )
        if agent_planner is None:
            return baseline
        return await agent_planner.plan(
            goal=request.goal,
            budget_limit=request.budget_limit,
            primary_metric=request.primary_metric,
            guardrails=request.guardrails,
            opportunities=opportunities(),
            baseline=baseline,
        )

    @app.get("/api/actions", tags=["decisioning"])
    def actions() -> list[dict[str, Any]]:
        return action_registry_payload()

    @app.post("/api/realtime/decision", tags=["decisioning"], include_in_schema=False)
    @app.post("/api/decide", tags=["decisioning"])
    def decide(
        request: DecisionRequest,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            min_length=1,
            max_length=256,
        ),
    ) -> dict[str, Any]:
        normalized_key: str | None = None
        if idempotency_key is not None:
            normalized_key = idempotency_key.strip()
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

    @app.get("/api/decisions/recent", tags=["decisioning"])
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
