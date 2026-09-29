from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ClaimType = Literal["FACT", "ESTIMATE", "INFERENCE", "HYPOTHESIS", "IDEA"]
EvidenceTier = Literal["A", "B", "C", "D"]
ActionId = Annotated[str, Field(min_length=1, max_length=128)]
GuardrailName = Annotated[str, Field(min_length=1, max_length=128)]
KNOWN_ACTION_IDS = frozenset(
    {
        "NO_TREATMENT",
        "free_shipping_v3",
        "coupon_10_v2",
        "push_reminder_v4",
        "email_guide_v2",
    }
)


def _validated_action_ids(values: list[str]) -> list[str]:
    deduped = list(dict.fromkeys(values))
    unknown = sorted(set(deduped).difference(KNOWN_ACTION_IDS))
    if unknown:
        raise ValueError(f"unknown candidate_action_ids: {unknown}")
    return deduped


class RequestModel(BaseModel):
    # Safety/governance APIs must fail closed on misspelled contract fields and
    # normalize accidental surrounding whitespace before length validation.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentPlanRequest(RequestModel):
    goal: str = Field(min_length=3, max_length=4000)
    budget_limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    primary_metric: str = Field(default="incremental_profit", min_length=1, max_length=128)
    guardrails: list[GuardrailName] = Field(default_factory=list, max_length=64)


class ApprovalDecisionRequest(RequestModel):
    decision: Literal["approve_shadow", "approve_1", "approve_5", "approve_25", "reject", "return"]
    note: str = Field(min_length=1, max_length=1000)


class DecisionRequest(RequestModel):
    entity_id: str = Field(min_length=1, max_length=256)
    placement: str = Field(min_length=1, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict, max_length=128)
    candidate_action_ids: list[ActionId] | None = Field(default=None, max_length=64)
    consent_state: bool = True
    frequency_remaining: int = Field(default=1, ge=0)
    budget_remaining: float = Field(default=1000.0, ge=0, allow_inf_nan=False)
    context_freshness_seconds: int = Field(default=0, ge=0)

    @field_validator("candidate_action_ids")
    @classmethod
    def validate_candidate_action_ids(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validated_action_ids(value)


class CampaignDraftRequest(RequestModel):
    name: str = Field(min_length=2, max_length=200)
    goal: str = Field(min_length=3, max_length=1000)
    audience: str = Field(min_length=2, max_length=500)
    budget: float = Field(ge=0, allow_inf_nan=False)
    candidate_action_ids: list[ActionId] = Field(
        default_factory=lambda: ["NO_TREATMENT", "free_shipping_v3"],
        max_length=64,
    )

    @field_validator("candidate_action_ids")
    @classmethod
    def validate_campaign_actions(cls, value: list[str]) -> list[str]:
        validated = _validated_action_ids(value)
        if "NO_TREATMENT" not in validated:
            validated.insert(0, "NO_TREATMENT")
        return validated
