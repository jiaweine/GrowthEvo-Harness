from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from growthevo.models import CausalBelief, Feedback, GrowthAction, RewardBreakdown


@dataclass(frozen=True, slots=True)
class RewardWeights:
    """Explicit scalarization weights for realized incremental outcomes.

    No business objective is selected by the package. Conversion, LTV,
    retention, direct cost, fatigue and churn-risk deltas may live on different
    units/scales, so the experiment or deployment protocol must provide every
    scalarization coefficient deliberately.

    Epistemic/model uncertainty is intentionally absent. It belongs in policy
    pessimism and promotion evidence, not in an environment reward computed from
    the same realized user outcome.
    """

    conversion: float
    ltv: float
    retention: float
    cost: float
    fatigue: float
    risk: float

    def __post_init__(self) -> None:
        for name, value in (
            ("conversion", self.conversion),
            ("ltv", self.ltv),
            ("retention", self.retention),
            ("cost", self.cost),
            ("fatigue", self.fatigue),
            ("risk", self.risk),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} reward weight must be finite and non-negative")


class CausalRewardModel:
    """Reward treatment incrementality rather than post-treatment raw outcomes."""

    def __init__(self, weights: RewardWeights) -> None:
        self.weights = weights

    def compute(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        feedback: Feedback,
    ) -> RewardBreakdown:
        del belief, action
        w = self.weights
        incremental_conversion = feedback.incremental_conversion
        cost_penalty = w.cost * feedback.cost
        fatigue_penalty = w.fatigue * max(0.0, feedback.fatigue_delta)
        risk_penalty = w.risk * max(0.0, feedback.churn_risk_delta)

        total = (
            w.conversion * incremental_conversion
            + w.ltv * feedback.incremental_ltv
            + w.retention * feedback.retention_delta
            - cost_penalty
            - fatigue_penalty
            - risk_penalty
        )

        return RewardBreakdown(
            incremental_conversion=incremental_conversion,
            incremental_ltv=feedback.incremental_ltv,
            retention=feedback.retention_delta,
            cost_penalty=cost_penalty,
            fatigue_penalty=fatigue_penalty,
            risk_penalty=risk_penalty,
            # Compatibility field: model uncertainty is no longer part of the
            # environment utility and therefore contributes zero by construction.
            uncertainty_penalty=0.0,
            total=total,
        )
