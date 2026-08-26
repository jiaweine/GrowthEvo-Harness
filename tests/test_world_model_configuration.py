from __future__ import annotations

import pytest

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthOption
from growthevo.simulator.user_world_model import UserWorldModel, WorldModelConfig


def _belief(*, fatigue: float = 0.6) -> CausalBelief:
    return CausalBelief(
        user_id="world-user",
        natural_conversion=0.2,
        channel_uplift={Channel.EMAIL: 0.1},
        uplift_uncertainty=0.02,
        ltv=100.0,
        fatigue=fatigue,
        churn_risk=0.1,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=5,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.EMAIL}),
    )


def _action() -> GrowthAction:
    return GrowthAction(
        option=GrowthOption.RETAIN,
        channel=Channel.EMAIL,
        budget=0.2,
        frequency_cost=1.0,
        expected_uplift=0.1,
        uncertainty=0.01,
    )


def test_world_model_delay_assumptions_are_configurable() -> None:
    config = WorldModelConfig(
        default_delay_days=2,
        channel_delay_days={Channel.EMAIL: 4},
        option_min_delay_days={GrowthOption.RETAIN: 9},
    )

    feedback = UserWorldModel(seed=1, config=config).step(_belief(), _action())

    assert feedback.delay_days == 9


def test_world_model_churn_threshold_is_configurable() -> None:
    action = _action()
    conservative = UserWorldModel(
        seed=1,
        config=WorldModelConfig(
            churn_fatigue_threshold=0.5,
            touch_fatigue_step=0.1,
            churn_fatigue_scale=1.0,
        ),
    ).step(_belief(fatigue=0.6), action)
    tolerant = UserWorldModel(
        seed=1,
        config=WorldModelConfig(
            churn_fatigue_threshold=0.9,
            touch_fatigue_step=0.1,
            churn_fatigue_scale=1.0,
        ),
    ).step(_belief(fatigue=0.6), action)

    assert conservative.churn_risk_delta == pytest.approx(0.2)
    assert tolerant.churn_risk_delta == pytest.approx(0.0)


def test_world_model_rejects_invalid_environment_parameters() -> None:
    with pytest.raises(ValueError, match="churn_fatigue_threshold"):
        WorldModelConfig(churn_fatigue_threshold=1.1)
    with pytest.raises(ValueError, match="channel delay"):
        WorldModelConfig(channel_delay_days={Channel.EMAIL: -1})
