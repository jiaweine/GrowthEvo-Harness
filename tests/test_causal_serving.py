from __future__ import annotations

import pytest

from growthevo.causal.dr_learner import FittedTreatmentEffect, RidgeRegressor
from growthevo.causal.serving import CausalUpliftServingBridge
from growthevo.models import Channel


def test_serving_bridge_clips_probability_uplift_and_preserves_raw_effect() -> None:
    model = RidgeRegressor(ridge=1e-3).fit(
        [(0.0,), (1.0,), (2.0,)],
        [2.0, 2.0, 2.0],
    )
    fitted = FittedTreatmentEffect(
        treatment=Channel.PUSH,
        control=Channel.NO_TREATMENT,
        model=model,
        residual_scale=0.0,
        sample_size=3,
        overlap_coverage=1.0,
        feature_bounds=((0.0, 2.0),),
    )
    prediction = CausalUpliftServingBridge({Channel.PUSH: fitted}).predict((1.0,))

    assert prediction.raw_channel_effects[Channel.PUSH] == pytest.approx(2.0, abs=1e-3)
    assert prediction.channel_effects[Channel.PUSH] == pytest.approx(1.0)
    assert prediction.clipped_channels == (Channel.PUSH,)
    assert prediction.channel_uncertainty[Channel.PUSH] >= 0.99
