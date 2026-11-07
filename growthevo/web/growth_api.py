"""API endpoints for real PostgreSQL-backed growth operations."""
from __future__ import annotations

from hmac import compare_digest
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from growthevo.agent_os.journal import principal_scope

from .growth_channels import ChannelConfigurationError, ChannelWebhook
from .growth_ops import GrowthOperations
from .growth_personalization import ContextualPersonalizer
from .growth_schemas import (
    CreativeInput, CustomerInput, CustomerUpdate, DeliveryReceiptInput, EventInput,
    ExperimentInput, ExposureInput, JourneyInput, OfferInput, ProcessDueInput,
    PersonalizationInput, PersonalizationExposureInput,
    SegmentInput,
)
from .growth_store import GrowthStore


def growth_router(store: GrowthStore | None, *, production: bool,
                  seed_demo: bool) -> APIRouter:
    router = APIRouter(prefix="/api/growth", tags=["growth-operations"])

    def context(request: Request) -> GrowthOperations:
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Growth operations require configured PostgreSQL persistence",
            )
        claims = getattr(request.state, "auth_claims", None)
        if production and claims is None:
            raise HTTPException(status_code=401, detail="verified identity required")
        scope = principal_scope(claims) if claims is not None else "local-development"
        if seed_demo:
            store.ensure_demo(scope)
        return GrowthOperations(store, scope)

    @router.get("/overview")
    def overview(request: Request) -> dict[str, Any]:
        return context(request).overview()

    @router.get("/customers")
    def customers(request: Request) -> list[dict[str, Any]]:
        return context(request).list("customers")

    @router.post("/customers", status_code=201)
    def create_customer(value: CustomerInput, request: Request) -> dict[str, Any]:
        return context(request).create("customers", value.customer_id, value.model_dump(mode="json"))

    @router.post("/customers/{customer_id}/update")
    def update_customer(customer_id: str, value: CustomerUpdate,
                        request: Request) -> dict[str, Any]:
        return context(request).update_customer(customer_id, value.model_dump(mode="json"))

    @router.get("/customers/{customer_id}")
    def profile(customer_id: str, request: Request) -> dict[str, Any]:
        return context(request).profile(customer_id)

    @router.get("/events")
    def events(request: Request) -> list[dict[str, Any]]:
        return context(request).list("events")

    @router.post("/events", status_code=201)
    def ingest(value: EventInput, request: Request) -> dict[str, Any]:
        return context(request).ingest_event(value.model_dump(mode="json"))

    @router.get("/segments")
    def segments(request: Request) -> list[dict[str, Any]]:
        return context(request).list("segments")

    @router.post("/segments", status_code=201)
    def create_segment(value: SegmentInput, request: Request) -> dict[str, Any]:
        return context(request).create("segments", value.segment_id, value.model_dump(mode="json"))

    @router.get("/segments/{segment_id}/preview")
    def segment_preview(segment_id: str, request: Request) -> dict[str, Any]:
        return context(request).segment_preview(segment_id)

    @router.get("/creatives")
    def creatives(request: Request) -> list[dict[str, Any]]:
        return context(request).list("creatives")

    @router.post("/creatives", status_code=201)
    def create_creative(value: CreativeInput, request: Request) -> dict[str, Any]:
        return context(request).create("creatives", value.creative_id, value.model_dump(mode="json"))

    @router.get("/offers")
    def offers(request: Request) -> list[dict[str, Any]]:
        return context(request).list("offers")

    @router.post("/offers", status_code=201)
    def create_offer(value: OfferInput, request: Request) -> dict[str, Any]:
        return context(request).create("offers", value.offer_id, value.model_dump(mode="json"))

    def personalizer(request: Request) -> ContextualPersonalizer:
        operations = context(request)
        return ContextualPersonalizer(operations.store, operations.scope)

    @router.post("/personalization/decide", status_code=201)
    def personalized_decision(value: PersonalizationInput,
                              request: Request) -> dict[str, Any]:
        # A logged decision alone is not a customer exposure or a channel send.
        return personalizer(request).decide(value.model_dump(mode="json"))

    @router.post("/personalization/{request_id}/exposure", status_code=201)
    def confirm_personalization_exposure(
        request_id: str, value: PersonalizationExposureInput, request: Request,
    ) -> dict[str, Any]:
        return personalizer(request).confirm_exposure(request_id, value.surface)

    @router.get("/personalization/metrics")
    def personalization_metrics(request: Request) -> dict[str, Any]:
        return personalizer(request).metrics()

    @router.get("/experiments")
    def experiments(request: Request) -> list[dict[str, Any]]:
        return context(request).list("experiments")

    @router.post("/experiments", status_code=201)
    def create_experiment(value: ExperimentInput, request: Request) -> dict[str, Any]:
        return context(request).create_experiment(value.model_dump(mode="json"))

    @router.post("/experiments/{experiment_id}/exposures", status_code=201)
    def experiment_exposure(experiment_id: str, value: ExposureInput,
                            request: Request) -> dict[str, Any]:
        return context(request).expose(experiment_id, value.model_dump(mode="json"))

    @router.get("/experiments/{experiment_id}/report")
    def experiment_report(experiment_id: str, request: Request) -> dict[str, Any]:
        return context(request).report(experiment_id)

    @router.get("/journeys")
    def journeys(request: Request) -> list[dict[str, Any]]:
        return context(request).list("journeys")

    @router.post("/journeys", status_code=201)
    def create_journey(value: JourneyInput, request: Request) -> dict[str, Any]:
        return context(request).create_journey(value.model_dump(mode="json"))

    @router.post("/journeys/{journey_id}/activate")
    def activate(journey_id: str, request: Request) -> dict[str, Any]:
        return context(request).activate_journey(journey_id)

    @router.post("/journeys/{journey_id}/stop")
    def stop_journey(journey_id: str, request: Request) -> dict[str, Any]:
        return context(request).stop_journey(journey_id)

    @router.get("/journeys/jobs")
    def jobs(request: Request) -> list[dict[str, Any]]:
        return context(request).list("jobs")

    @router.post("/journeys/process")
    def process_due(value: ProcessDueInput, request: Request) -> dict[str, Any]:
        return context(request).process_due(limit=value.limit)

    @router.get("/deliveries")
    def deliveries(request: Request) -> list[dict[str, Any]]:
        return context(request).list("deliveries")

    @router.post("/deliveries/{delivery_id}/submit")
    def submit(delivery_id: str, request: Request,
               channel_submit_token: str | None = Header(
                   default=None, alias="X-Channel-Submit-Token",
               )) -> dict[str, Any]:
        if not production:
            raise HTTPException(status_code=409, detail="real channel submission requires production mode")
        expected = os.getenv("GROWTHEVO_CHANNEL_SUBMIT_SECRET", "")
        if not expected or not channel_submit_token or not compare_digest(expected, channel_submit_token):
            raise HTTPException(status_code=403, detail="separate channel submission authority required")
        try:
            webhook = ChannelWebhook.from_environment()
        except ChannelConfigurationError:
            raise HTTPException(status_code=503, detail="trusted channel adapter is unavailable")
        operations = context(request)
        command = operations.reserve_external_submission(delivery_id)
        accepted = webhook.submit(command)
        return operations.finish_external_submission(
            delivery_id, accepted=accepted,
            reason="gateway accepted; awaiting independent receipt" if accepted
                   else "gateway response uncertain; reconcile before retry",
        )

    @router.post("/deliveries/{delivery_id}/receipt")
    def receipt(delivery_id: str, value: DeliveryReceiptInput, request: Request,
                channel_receipt_token: str | None = Header(
                    default=None, alias="X-Channel-Receipt-Token",
                )) -> dict[str, Any]:
        if production:
            expected = os.getenv("GROWTHEVO_CHANNEL_RECEIPT_SECRET", "")
            if not expected or not channel_receipt_token or not compare_digest(
                expected, channel_receipt_token
            ):
                raise HTTPException(status_code=403, detail="receipt authority required")
        return context(request).record_receipt(
            delivery_id, value.model_dump(mode="json"), permit_simulation=not production,
        )

    return router
