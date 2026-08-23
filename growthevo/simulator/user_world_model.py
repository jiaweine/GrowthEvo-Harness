from __future__ import annotations

from dataclasses import dataclass
import random

from growthevo.models import CausalBelief, Channel, Feedback, GrowthAction


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class WorldModelConfig:
    fatigue_uplift_penalty: float = 0.25
    touch_fatigue_step: float = 0.08
    offer_cost_rate: float = 0.10
    churn_fatigue_scale: float = 0.05
    retention_uplift_scale: float = 0.20


class UserWorldModel:
    """Small stochastic digital twin for replay and deterministic tests.

    The model outputs both treatment and baseline probabilities. This makes the
    simulator useful for runtime integration without pretending that a sampled
    conversion itself is causal evidence.
    """

    def __init__(self, seed: int = 7, config: WorldModelConfig | None = None) -> None:
        self._rng = random.Random(seed)
        self.config = config or WorldModelConfig()

    def step(self, belief: CausalBelief, action: GrowthAction) -> Feedback:
        baseline = _clip(belief.natural_conversion)

        if action.channel is Channel.NO_TREATMENT:
            treatment_prob = baseline
            realized = self._rng.random() < treatment_prob
            return Feedback(
                realized_conversion=realized,
                treatment_conversion_prob=treatment_prob,
                baseline_conversion_prob=baseline,
                incremental_ltv=0.0,
                retention_delta=0.0,
                cost=0.0,
                fatigue_delta=0.0,
                churn_risk_delta=0.0,
                delay_days=0,
            )

        cfg = self.config
        fatigue_penalty = cfg.fatigue_uplift_penalty * belief.fatigue
        effective_uplift = action.expected_uplift * max(0.0, 1.0 - fatigue_penalty)
        treatment_prob = _clip(baseline + effective_uplift)
        realized = self._rng.random() < treatment_prob

        incremental_conversion = treatment_prob - baseline
        gross_incremental_ltv = incremental_conversion * belief.ltv
        direct_cost = action.budget + cfg.offer_cost_rate * action.offer_value
        incremental_ltv = gross_incremental_ltv
        fatigue_delta = cfg.touch_fatigue_step * action.frequency_cost
        churn_risk_delta = max(0.0, belief.fatigue + fatigue_delta - 0.70) * cfg.churn_fatigue_scale
        retention_delta = incremental_conversion * cfg.retention_uplift_scale - churn_risk_delta

        delay_days = 1
        if action.channel in {Channel.EMAIL, Channel.ADS}:
            delay_days = 3
        if action.option.value in {"retain", "reactivate"}:
            delay_days = max(delay_days, 7)

        return Feedback(
            realized_conversion=realized,
            treatment_conversion_prob=treatment_prob,
            baseline_conversion_prob=baseline,
            incremental_ltv=incremental_ltv,
            retention_delta=retention_delta,
            cost=direct_cost,
            fatigue_delta=fatigue_delta,
            churn_risk_delta=churn_risk_delta,
            delay_days=delay_days,
        )
