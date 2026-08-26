from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from growthevo.models import CausalBelief, Feedback, GrowthAction, RewardBreakdown


@dataclass(frozen=True, slots=True)
class RewardWeights:
    """Scalarization weights for causal business outcomes.

    The default objective is net incremental value: incremental LTV minus direct
    cost. Conversion and retention are reported as diagnostics but are not also
    rewarded by default because they may be upstream components of LTV. Likewise
    model uncertainty is handled by policy/verifier confidence logic rather than
    being treated as an environment outcome. Alternative business utilities can
    opt into additional terms explicitly.
    """

    conversion: float = 0.0
    ltv: float = 1.0
    retention: float = 0.0
    cost: float = 1.0
    fatigue: float = 0.0
    risk: float = 0.0
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("conversion", self.conversion),
            ("ltv", self.ltv),
            ("retention", self.retention),
            ("cost", self.cost),
            ("fatigue", self.fatigue),
            ("risk", self.risk),
            ("uncertainty", self.uncertainty),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} reward weight must be finite and non-negative")


class CausalRewardModel:
    """Reward treatment incrementality rather than post-treatment raw outcomes."""

    def __init__(self, weights: RewardWeights | None = None) -> None:
        self.weights = weights or RewardWeights()

    def compute(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        feedback: Feedback,
    ) -> RewardBreakdown:
        del belief
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
