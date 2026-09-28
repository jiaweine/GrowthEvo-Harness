from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ClaimType = Literal["FACT", "ESTIMATE", "INFERENCE", "HYPOTHESIS", "IDEA"]
EvidenceTier = Literal["A", "B", "C", "D"]


class AgentPlanRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    budget_limit: float | None = Field(default=None, ge=0)
    primary_metric: str = "incremental_profit"
    guardrails: list[str] = Field(default_factory=list)


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve_shadow", "approve_1", "approve_5", "approve_25", "reject", "return"]
    note: str = Field(default="", max_length=1000)


class DecisionRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=256)
    placement: str = Field(min_length=1, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)
    candidate_action_ids: list[str] | None = None
    consent_state: bool = True
    frequency_remaining: int = Field(default=1, ge=0)
    budget_remaining: float = Field(default=1000.0, ge=0)
    context_freshness_seconds: int = Field(default=0, ge=0)


class CampaignDraftRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    goal: str = Field(min_length=3, max_length=1000)
    audience: str = Field(min_length=2, max_length=500)
    budget: float = Field(ge=0)
    candidate_action_ids: list[str] = Field(default_factory=lambda: ["NO_TREATMENT", "free_shipping_v3"])
