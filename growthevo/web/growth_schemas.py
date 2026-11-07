"""Strict request contracts for data-backed growth operations."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from .schemas import RequestModel

Key = str
Channel = Literal["email", "push", "sms", "in_app"]
KEY_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,79}$"


class CustomerInput(RequestModel):
    customer_id: str = Field(pattern=KEY_PATTERN)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=32)
    consent: StrictBool = False


class SegmentInput(RequestModel):
    segment_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=120)
    equals: dict[str, str | int | float | bool] = Field(min_length=1, max_length=12)


class EventInput(RequestModel):
    event_id: str = Field(pattern=KEY_PATTERN)
    customer_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=32)


class CreativeInput(RequestModel):
    creative_id: str = Field(pattern=KEY_PATTERN)
    channel: Channel
    title: str = Field(min_length=2, max_length=150)
    body: str = Field(min_length=2, max_length=2000)


class OfferInput(RequestModel):
    offer_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=150)
    amount: float = Field(ge=0, le=1000000, allow_inf_nan=False)
    max_redemptions: int = Field(ge=1, le=10000000)


class JourneyStepInput(RequestModel):
    channel: Channel
    creative_id: str = Field(pattern=KEY_PATTERN)
    offer_id: str | None = Field(default=None, pattern=KEY_PATTERN)
    delay_seconds: int = Field(ge=0, le=2592000)


class JourneyInput(RequestModel):
    journey_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=150)
    trigger_event: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    segment_id: str | None = Field(default=None, pattern=KEY_PATTERN)
    steps: list[JourneyStepInput] = Field(min_length=1, max_length=8)


class VariantInput(RequestModel):
    key: str = Field(pattern=KEY_PATTERN)
    weight: int = Field(ge=1, le=99, strict=True)


class ExperimentInput(RequestModel):
    experiment_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=150)
    metric_event: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    control: str = Field(pattern=KEY_PATTERN)
    variants: list[VariantInput] = Field(min_length=2, max_length=6)
    window_days: int = Field(default=7, ge=1, le=90)

    @model_validator(mode="after")
    def validate_allocation(self) -> "ExperimentInput":
        keys = [v.key for v in self.variants]
        if len(set(keys)) != len(keys) or self.control not in keys:
            raise ValueError("variants must be unique and include control")
        if sum(v.weight for v in self.variants) != 100:
            raise ValueError("variant weights must sum to 100")
        return self


class ExposureInput(RequestModel):
    customer_id: str = Field(pattern=KEY_PATTERN)
    request_id: str = Field(pattern=KEY_PATTERN)
    surface: str = Field(min_length=2, max_length=100)


class DeliveryReceiptInput(RequestModel):
    provider_event_id: str = Field(pattern=KEY_PATTERN)
    status: Literal["delivered", "failed", "bounced"]
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProcessDueInput(RequestModel):
    limit: int = Field(default=50, ge=1, le=200)
