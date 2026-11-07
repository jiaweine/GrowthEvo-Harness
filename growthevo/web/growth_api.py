"""Validated growth workbench API over the existing FastAPI and PostgreSQL."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .growth_service import GrowthService
from .growth_store import GrowthConflict, GrowthStore


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Profile(Contract):
    id: str = Field(min_length=1, max_length=128)
    segment: str = Field(min_length=1, max_length=64)
    preferred_channel: Literal["web", "email", "push", "sms", "none"]
    consent: StrictBool
    origin: Literal["observed", "simulated"] = "observed"


class Offer(Contract):
    id: str = Field(min_length=1, max_length=128)
    channel: Literal["none", "web", "email", "push", "sms"]
    cost: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    active: StrictBool = True
    origin: Literal["observed", "simulated"] = "observed"


class Asset(Contract):
    id: str = Field(min_length=1, max_length=128)
    offer_id: str = Field(min_length=1, max_length=128)
    channel: Literal["web", "email", "push", "sms"]
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2000)
    origin: Literal["observed", "simulated"] = "observed"


class Event(Contract):
    id: str = Field(min_length=1, max_length=128)
    subject_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    origin: Literal["observed", "simulated"] = "observed"


class Variant(Contract):
    id: str = Field(min_length=1, max_length=64)
    weight: int = Field(ge=1, le=9999)


class Experiment(Contract):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=180)
    status: Literal["draft", "active", "paused"]
    variants: list[Variant] = Field(min_length=2, max_length=8)
    metric: Literal["conversion"] = "conversion"
    origin: Literal["observed", "simulated"] = "observed"

    @model_validator(mode="after")
    def check_allocation(self) -> "Experiment":
        ids = [item.id for item in self.variants]
        if len(set(ids)) != len(ids) or "control" not in ids:
            raise ValueError("distinct variants including control are required")
        if sum(item.weight for item in self.variants) != 10_000:
            raise ValueError("variant weights must total 10000 basis points")
        return self


class JourneyStep(Contract):
    channel: Literal["web", "email", "push", "sms"]
    offer_id: str = Field(min_length=1, max_length=128)
    delay_seconds: int = Field(ge=0, le=30 * 24 * 3600)


class Journey(Contract):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=180)
    trigger: str = Field(min_length=1, max_length=80)
    status: Literal["draft", "active", "paused"]
    steps: list[JourneyStep] = Field(min_length=1, max_length=10)
    origin: Literal["observed", "simulated"] = "observed"


class Subject(Contract):
    subject_id: str = Field(min_length=1, max_length=128)


class Exposure(Subject):
    id: str = Field(min_length=1, max_length=128)


class Metric(Exposure):
    value: int = Field(ge=0, le=1)


class Decision(Subject):
    placement: str = Field(min_length=1, max_length=128)
    decision_key: str = Field(min_length=1, max_length=128)
    budget_remaining: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    frequency_remaining: int = Field(ge=0, le=1000)


class Feedback(Contract):
    id: str = Field(min_length=1, max_length=128)
    success: StrictBool


class Receipt(Contract):
    id: str = Field(min_length=1, max_length=128)
    status: Literal["simulated_delivered", "simulated_failed"]


def build_growth_router(store: GrowthStore | None, *, authenticator: Any,
                        production: bool, simulation: bool) -> Any:
    from fastapi import APIRouter, Depends, Header, HTTPException

    router = APIRouter(prefix="/api/growth", tags=["growth-operations"])

    def current(authorization: str | None = Header(default=None)) -> GrowthService:
        if store is None:
            raise HTTPException(status_code=503, detail="PostgreSQL growth store is required")
        if authenticator is None:
            if production:
                raise HTTPException(status_code=503, detail="authentication required")
            scope = "local-development"
        else:
            from .auth import AuthenticationError, AuthenticationUnavailable
            from growthevo.agent_os.journal import principal_scope
            try:
                claims = authenticator.authenticate_authorization_header(authorization)
                scope = principal_scope(claims)
            except AuthenticationUnavailable as exc:
                raise HTTPException(status_code=503, detail="identity provider unavailable") from exc
            except (AuthenticationError, ValueError) as exc:
                raise HTTPException(status_code=401, detail="valid bearer token required") from exc
        return GrowthService(store, scope, simulation=simulation)

    def apply(func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except GrowthConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def save_object(svc: GrowthService, kind: str, payload: Contract) -> dict[str, Any]:
        data = payload.model_dump()
        if production and data.get("origin") == "simulated":
            raise HTTPException(status_code=422, detail="production cannot accept simulated records")
        if kind == "experiment":
            return apply(svc.experiment, data)
        if kind == "asset":
            offer = svc.store.get(svc.scope, "offer", data["offer_id"])
            if offer is None or offer["channel"] != data["channel"]:
                raise HTTPException(status_code=422, detail="asset must reference same-channel offer")
        if kind == "journey":
            if svc.store.has_journey_jobs(svc.scope, data["id"]):
                previous = svc.store.get(svc.scope, "journey", data["id"])
                if previous != data:
                    raise HTTPException(status_code=409, detail="journey has queued or completed work")
            for step in data["steps"]:
                offer = svc.store.get(svc.scope, "offer", step["offer_id"])
                if offer is None or offer["channel"] != step["channel"]:
                    raise HTTPException(status_code=422, detail="journey step needs an existing same-channel offer")
        return apply(svc.store.put, svc.scope, kind, data)

    @router.get("/overview")
    def overview(svc: GrowthService = Depends(current)) -> dict[str, Any]:
        kinds = ("profile", "offer", "asset", "experiment", "journey", "delivery")
        records = {kind: svc.store.list(svc.scope, kind, limit=500) for kind in kinds}
        return {
            "storage": "postgresql", "scope": "authenticated-principal",
            "counts": {kind: len(items) for kind, items in records.items()},
            "contains_simulated_data": any(
                item.get("origin") == "simulated" for items in records.values() for item in items
            ),
            "count_limit": 500, "outcomes": "observed-only",
        }

    @router.get("/profiles")
    def profiles(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "profile")

    @router.put("/profiles/{subject_id}")
    def put_profile(subject_id: str, request: Profile,
                    svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if subject_id != request.id:
            raise HTTPException(status_code=422, detail="path and profile ID differ")
        return save_object(svc, "profile", request)

    @router.post("/events", status_code=201)
    def add_event(request: Event, svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if production and request.origin == "simulated":
            raise HTTPException(status_code=422, detail="production cannot accept simulated events")
        return apply(svc.event, request.model_dump())

    @router.get("/events")
    def events(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.facts(svc.scope, "event")

    @router.get("/offers")
    def offers(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "offer")

    @router.put("/offers/{offer_id}")
    def put_offer(offer_id: str, request: Offer,
                  svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if offer_id != request.id:
            raise HTTPException(status_code=422, detail="path and offer ID differ")
        return save_object(svc, "offer", request)

    @router.get("/assets")
    def assets(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "asset")

    @router.put("/assets/{asset_id}")
    def put_asset(asset_id: str, request: Asset,
                  svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if asset_id != request.id:
            raise HTTPException(status_code=422, detail="path and asset ID differ")
        return save_object(svc, "asset", request)

    @router.get("/experiments")
    def experiments(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "experiment")

    @router.put("/experiments/{experiment_id}")
    def put_experiment(experiment_id: str, request: Experiment,
                       svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if experiment_id != request.id:
            raise HTTPException(status_code=422, detail="path and experiment ID differ")
        return save_object(svc, "experiment", request)

    @router.post("/experiments/{experiment_id}/assign")
    def assign(experiment_id: str, request: Subject,
               svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.assign, experiment_id, request.subject_id)

    @router.post("/experiments/{experiment_id}/exposures", status_code=201)
    def expose(experiment_id: str, request: Exposure,
               svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.exposure, experiment_id, request.subject_id, request.id)

    @router.post("/experiments/{experiment_id}/metrics", status_code=201)
    def observe_metric(experiment_id: str, request: Metric,
                       svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.metric, experiment_id, request.subject_id, request.id, request.value)

    @router.get("/experiments/{experiment_id}/report")
    def report(experiment_id: str, svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.report, experiment_id)

    @router.get("/journeys")
    def journeys(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "journey")

    @router.put("/journeys/{journey_id}")
    def put_journey(journey_id: str, request: Journey,
                    svc: GrowthService = Depends(current)) -> dict[str, Any]:
        if journey_id != request.id:
            raise HTTPException(status_code=422, detail="path and journey ID differ")
        return save_object(svc, "journey", request)

    @router.get("/journeys/jobs")
    def jobs(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.jobs(svc.scope)

    @router.get("/deliveries")
    def deliveries(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "delivery")

    @router.post("/deliveries/{delivery_id}/receipts", status_code=201)
    def receipt(delivery_id: str, request: Receipt,
                svc: GrowthService = Depends(current)) -> dict[str, Any]:
        delivery = svc.store.get(svc.scope, "delivery", delivery_id)
        if delivery is None or delivery["status"] != "simulated":
            raise HTTPException(status_code=422, detail="only simulated deliveries accept simulated receipts")
        payload = request.model_dump() | {
            "delivery_id": delivery_id, "subject_id": delivery["subject_id"], "origin": "simulated",
        }
        return apply(svc.store.append_fact, svc.scope, "receipt", request.id,
                     delivery["subject_id"], delivery_id, payload)

    @router.post("/decisions", status_code=201)
    def decide(request: Decision, svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.decide, request.model_dump())

    @router.get("/decisions")
    def decisions(svc: GrowthService = Depends(current)) -> list[dict[str, Any]]:
        return svc.store.list(svc.scope, "decision")

    @router.post("/decisions/{decision_id}/feedback", status_code=201)
    def feedback(decision_id: str, request: Feedback,
                 svc: GrowthService = Depends(current)) -> dict[str, Any]:
        return apply(svc.feedback, decision_id, request.id, request.success)

    return router
