from __future__ import annotations

import pytest

from growthevo.causal.dr_learner import FittedTreatmentEffect, RidgeRegressor
from growthevo.causal.serving import CausalUpliftServingBridge
from growthevo.models import Channel, UserObservation


def _fitted(effect: float) -> FittedTreatmentEffect:
    model = RidgeRegressor(ridge=1e-3).fit(
        [(0.0,), (1.0,), (2.0,)],
        [effect, effect, effect],
    )
    return FittedTreatmentEffect(
        treatment=Channel.PUSH,
        control=Channel.NO_TREATMENT,
        model=model,
        residual_scale=0.02,
        sample_size=3,
        overlap_coverage=1.0,
        practical_overlap_coverage=None,
        propensity_clip_fraction=0.0,
        feature_bounds=((0.0, 2.0),),
    )


def test_serving_bridge_clips_probability_uplift_and_preserves_raw_effect() -> None:
    fitted = _fitted(2.0)
    prediction = CausalUpliftServingBridge({Channel.PUSH: fitted}).predict((1.0,))

    assert prediction.raw_channel_effects[Channel.PUSH] == pytest.approx(2.0, abs=1e-3)
    assert prediction.channel_effects[Channel.PUSH] == pytest.approx(1.0)
    assert prediction.clipped_channels == (Channel.PUSH,)
    assert prediction.channel_uncertainty[Channel.PUSH] >= 0.99
    assert prediction.channel_effect_lower_bound == {}


def test_serving_bridge_only_exposes_effect_bound_when_provider_is_injected() -> None:
    fitted = _fitted(0.20)
    bridge = CausalUpliftServingBridge(
        {Channel.PUSH: fitted},
        effect_lower_bound_provider=lambda channel, estimate: estimate.effect - 0.05,
    )
    observation = UserObservation(
        user_id="u",
        natural_conversion=0.1,
        channel_uplift={Channel.PUSH: 0.0},
        uplift_uncertainty=1.0,
        ltv=100.0,
        consented_channels=frozenset({Channel.PUSH}),
    )

    enriched, prediction = bridge.enrich_observation(observation, (1.0,))

    assert prediction.channel_effects[Channel.PUSH] == pytest.approx(0.20, abs=1e-3)
    assert prediction.channel_effect_lower_bound[Channel.PUSH] == pytest.approx(0.15, abs=1e-3)
    assert enriched.channel_effect_lower_bound[Channel.PUSH] == pytest.approx(0.15, abs=1e-3)


def test_serving_bridge_rejects_invalid_lower_bound_above_point_estimate() -> None:
    fitted = _fitted(0.20)
    bridge = CausalUpliftServingBridge(
        {Channel.PUSH: fitted},
        effect_lower_bound_provider=lambda channel, estimate: estimate.effect + 0.01,
    )

    with pytest.raises(ValueError, match="above the point estimate"):
        bridge.predict((1.0,))
