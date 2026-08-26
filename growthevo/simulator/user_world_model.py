from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Mapping

from growthevo.models import CausalBelief, Channel, Feedback, GrowthAction, GrowthOption


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class WorldModelConfig:
    """Explicit assumptions for the reference stochastic user model.

    These are simulator parameters, not universal marketing constants. Production
    experiments should estimate or calibrate them from logged trajectories and
    pass the resulting configuration (or replace the world model entirely).
    """

    fatigue_uplift_penalty: float = 0.25
    touch_fatigue_step: float = 0.08
    churn_fatigue_threshold: float = 0.70
    churn_fatigue_scale: float = 0.05
    retention_uplift_scale: float = 0.20
    default_delay_days: int = 1
    channel_delay_days: Mapping[Channel, int] = field(
        default_factory=lambda: {Channel.EMAIL: 3, Channel.ADS: 3}
    )
    option_min_delay_days: Mapping[GrowthOption, int] = field(
        default_factory=lambda: {GrowthOption.RETAIN: 7, GrowthOption.REACTIVATE: 7}
    )

    def __post_init__(self) -> None:
        if self.fatigue_uplift_penalty < 0:
            raise ValueError("fatigue_uplift_penalty must be non-negative")
        if self.touch_fatigue_step < 0:
            raise ValueError("touch_fatigue_step must be non-negative")
        if not 0 <= self.churn_fatigue_threshold <= 1:
            raise ValueError("churn_fatigue_threshold must be in [0, 1]")
        if self.churn_fatigue_scale < 0:
            raise ValueError("churn_fatigue_scale must be non-negative")
        if self.retention_uplift_scale < 0:
            raise ValueError("retention_uplift_scale must be non-negative")
        if self.default_delay_days < 0:
            raise ValueError("default_delay_days must be non-negative")
        if any(delay < 0 for delay in self.channel_delay_days.values()):
            raise ValueError("channel delay values must be non-negative")
        if any(delay < 0 for delay in self.option_min_delay_days.values()):
            raise ValueError("option delay values must be non-negative")

    def delay_days(self, action: GrowthAction) -> int:
        delay = int(self.channel_delay_days.get(action.channel, self.default_delay_days))
        return max(delay, int(self.option_min_delay_days.get(action.option, 0)))


class UserWorldModel:
    """Small stochastic digital twin for replay and deterministic tests.

    The model outputs both treatment and baseline probabilities. This makes the
    simulator useful for runtime integration without pretending that a sampled
    conversion itself is causal evidence.

    ``GrowthAction.budget`` is treated as the action's complete expected direct
    cost. Offer economics must be compiled into that budget by the policy layer;
    the world model therefore never charges offer value a second time.
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
        direct_cost = action.budget
        incremental_ltv = gross_incremental_ltv
        fatigue_delta = cfg.touch_fatigue_step * action.frequency_cost
        churn_excess = max(
            0.0,
            belief.fatigue + fatigue_delta - cfg.churn_fatigue_threshold,
        )
        churn_risk_delta = churn_excess * cfg.churn_fatigue_scale
        retention_delta = incremental_conversion * cfg.retention_uplift_scale - churn_risk_delta

        return Feedback(
            realized_conversion=realized,
            treatment_conversion_prob=treatment_prob,
            baseline_conversion_prob=baseline,
            incremental_ltv=incremental_ltv,
            retention_delta=retention_delta,
            cost=direct_cost,
            fatigue_delta=fatigue_delta,
            churn_risk_delta=churn_risk_delta,
            delay_days=cfg.delay_days(action),
        )
