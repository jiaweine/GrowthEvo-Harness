from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import CausalBelief, Feedback, GrowthAction, RewardBreakdown


@dataclass(frozen=True, slots=True)
class RewardWeights:
    conversion: float = 1.0
    ltv: float = 0.10
    retention: float = 0.50
    cost: float = 1.0
    fatigue: float = 0.40
    risk: float = 0.50
    uncertainty: float = 0.20


class CausalRewardModel:
    """Reward treatment incrementality, not post-treatment raw outcomes."""

    def __init__(self, weights: RewardWeights | None = None) -> None:
        self.weights = weights or RewardWeights()

    def compute(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        feedback: Feedback,
    ) -> RewardBreakdown:
        w = self.weights
        incremental_conversion = feedback.incremental_conversion
        cost_penalty = w.cost * feedback.cost
        fatigue_penalty = w.fatigue * max(0.0, feedback.fatigue_delta)
        risk_penalty = w.risk * max(0.0, feedback.churn_risk_delta)
        uncertainty_penalty = w.uncertainty * action.uncertainty

        total = (
            w.conversion * incremental_conversion
            + w.ltv * feedback.incremental_ltv
            + w.retention * feedback.retention_delta
            - cost_penalty
            - fatigue_penalty
            - risk_penalty
            - uncertainty_penalty
        )

        return RewardBreakdown(
            incremental_conversion=incremental_conversion,
            incremental_ltv=feedback.incremental_ltv,
            retention=feedback.retention_delta,
            cost_penalty=cost_penalty,
            fatigue_penalty=fatigue_penalty,
            risk_penalty=risk_penalty,
            uncertainty_penalty=uncertainty_penalty,
            total=total,
        )
