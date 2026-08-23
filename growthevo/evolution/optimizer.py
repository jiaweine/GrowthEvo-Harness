from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from growthevo.evolution.failure_miner import FailureTrace
from growthevo.models import FailureKind, HarnessPatch


EVOLVABLE_COORDINATES = frozenset(
    {
        "planner.hypothesis_template",
        "feature.routing",
        "memory.retrieval_policy",
        "tool.routing",
        "delegation.strategy",
        "policy.exploration_coefficient",
        "reward.short_horizon_shaping",
    }
)

FROZEN_COORDINATES = frozenset(
    {
        "north_star.metric",
        "constraints.consent",
        "constraints.budget_ledger",
        "event_store",
        "verifier",
        "deployment_gate",
        "policy.no_treatment_semantics",
    }
)


@dataclass(frozen=True, slots=True)
class EvolutionConfig:
    exploration_step: float = 0.05
    max_exploration_coefficient: float = 0.50


class HarnessEvolver:
    """Generate declarative one-coordinate patches from typed failures.

    Patches are proposals only. They never directly mutate the runtime and must
    pass replay / shadow verification before promotion.
    """

    def __init__(self, config: EvolutionConfig | None = None) -> None:
        self.config = config or EvolutionConfig()

    def propose(self, failure: FailureTrace, current: dict[str, Any] | None = None) -> HarnessPatch:
        current = current or {}

        if failure.kind is FailureKind.UNCERTAINTY:
            old = float(current.get("policy.exploration_coefficient", 0.10))
            value = min(
                self.config.max_exploration_coefficient,
                old + self.config.exploration_step,
            )
            return self._patch(
                "policy.exploration_coefficient",
                value,
                "Increase controlled exploration because effective evidence is insufficient.",
                failure.kind,
            )

        if failure.kind is FailureKind.ATTRIBUTION:
            return self._patch(
                "reward.short_horizon_shaping",
                {"prefer_incrementality": True, "raw_conversion_credit": 0.0},
                "Reduce proxy reward leakage after counterfactual value failed the promotion gate.",
                failure.kind,
            )

        if failure.kind in {FailureKind.BUDGET, FailureKind.ROI}:
            return self._patch(
                "tool.routing",
                {"prefer_low_cost_channels": True, "require_roi_preview": True},
                "Route candidate actions through lower-cost tools and pre-execution ROI preview.",
                failure.kind,
            )

        if failure.kind is FailureKind.FATIGUE:
            return self._patch(
                "planner.hypothesis_template",
                {"prefer_holdout_when_fatigued": True, "retention_over_conversion": True},
                "Bias semantic planning toward holdout/retention when user-cost failures dominate.",
                failure.kind,
            )

        if failure.kind is FailureKind.DISTRIBUTION_SHIFT:
            return self._patch(
                "feature.routing",
                {"refresh_recent_features": True, "downweight_stale_history": True},
                "Refresh state features after distribution-shift failures.",
                failure.kind,
            )

        return self._patch(
            "memory.retrieval_policy",
            {"retrieve_similar_failures": True, "top_k": 5},
            "Retrieve verified failure precedents before replanning unknown failures.",
            failure.kind,
        )

    @staticmethod
    def validate_coordinate(coordinate: str) -> None:
        if coordinate in FROZEN_COORDINATES:
            raise ValueError(f"frozen coordinate cannot evolve: {coordinate}")
        if coordinate not in EVOLVABLE_COORDINATES:
            raise ValueError(f"unknown evolvable coordinate: {coordinate}")

    def _patch(self, coordinate: str, value: Any, rationale: str, source: FailureKind) -> HarnessPatch:
        self.validate_coordinate(coordinate)
        return HarnessPatch(
            coordinate=coordinate,
            value=value,
            rationale=rationale,
            source_failure=source,
        )
