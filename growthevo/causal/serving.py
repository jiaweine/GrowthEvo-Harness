from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Callable, Mapping, Sequence

from growthevo.models import Channel, UserObservation

from .dr_learner import CATEEstimate, FittedTreatmentEffect


def _clip_probability_effect(value: float) -> float:
    return max(-1.0, min(1.0, value))


EffectLowerBoundProvider = Callable[[Channel, CATEEstimate], float]
SupportScoreProvider = Callable[[Channel, CATEEstimate], float]


@dataclass(frozen=True, slots=True)
class UpliftServingPrediction:
    raw_channel_effects: Mapping[Channel, float]
    channel_effects: Mapping[Channel, float]
    channel_uncertainty: Mapping[Channel, float]
    channel_support: Mapping[Channel, float]
    model_support_diagnostics: Mapping[Channel, float] = field(default_factory=dict)
    channel_effect_lower_bound: Mapping[Channel, float] = field(default_factory=dict)
    clipped_channels: tuple[Channel, ...] = ()

    @property
    def aggregate_uncertainty(self) -> float:
        if not self.channel_uncertainty:
            return 1.0
        return max(0.0, min(1.0, max(self.channel_uncertainty.values())))

    @property
    def minimum_support(self) -> float:
        if not self.channel_support:
            return 0.0
        return max(0.0, min(1.0, min(self.channel_support.values())))


class CausalUpliftServingBridge:
    """Expose fitted treatment-effect models through the Runtime contract.

    Model residual/extrapolation uncertainty and global overlap diagnostics are
    not deployment guarantees. A caller must explicitly inject:

    * ``effect_lower_bound_provider`` to expose inferential/calibrated effect LCBs;
    * ``support_score_provider`` to expose deployment support for each channel.

    Without a support provider, ``channel_support`` remains empty. Because the
    Runtime treats unknown treatment support as zero, a missing local/support
    protocol cannot silently become full support. ``model_support_diagnostics``
    remains available for analysis without being promoted into the policy gate.
    """

    def __init__(
        self,
        models: Mapping[Channel, FittedTreatmentEffect],
        *,
        effect_lower_bound_provider: EffectLowerBoundProvider | None = None,
        support_score_provider: SupportScoreProvider | None = None,
    ) -> None:
        if not models:
            raise ValueError("at least one treatment-effect model is required")
        if Channel.NO_TREATMENT in models:
            raise ValueError("NO_TREATMENT does not need a treatment-effect model")
        for channel, model in models.items():
            if model.treatment is not channel:
                raise ValueError("model treatment must match its serving channel")
            if model.control is not Channel.NO_TREATMENT:
                raise ValueError("runtime uplift models must use NO_TREATMENT as control")
        self.models = dict(models)
        self.effect_lower_bound_provider = effect_lower_bound_provider
        self.support_score_provider = support_score_provider

    def predict(self, features: Sequence[float]) -> UpliftServingPrediction:
        predictions: dict[Channel, CATEEstimate] = {
            channel: model.predict(features) for channel, model in self.models.items()
        }
        raw_effects = {
            channel: prediction.effect for channel, prediction in predictions.items()
        }
        effects = {
            channel: _clip_probability_effect(prediction.effect)
            for channel, prediction in predictions.items()
        }
        model_support = {
            channel: prediction.support_score for channel, prediction in predictions.items()
        }
        supports: dict[Channel, float] = {}
        if self.support_score_provider is not None:
            for channel, prediction in predictions.items():
                support = float(self.support_score_provider(channel, prediction))
                if not isfinite(support) or not 0.0 <= support <= 1.0:
                    raise ValueError("support-score provider must return a finite value in [0, 1]")
                supports[channel] = support

        uncertainties = {
            channel: max(
                0.0,
                min(
                    1.0,
                    prediction.uncertainty
                    + abs(prediction.effect) * (1.0 - prediction.support_score)
                    + abs(prediction.effect - effects[channel]),
                ),
            )
            for channel, prediction in predictions.items()
        }

        lower_bounds: dict[Channel, float] = {}
        if self.effect_lower_bound_provider is not None:
            for channel, prediction in predictions.items():
                raw_lower = float(self.effect_lower_bound_provider(channel, prediction))
                if not isfinite(raw_lower):
                    raise ValueError("effect lower-bound provider returned a non-finite value")
                lower = _clip_probability_effect(raw_lower)
                if lower > effects[channel] + 1e-12:
                    raise ValueError(
                        "effect lower-bound provider returned a bound above the point estimate"
                    )
                lower_bounds[channel] = lower

        clipped = tuple(
            sorted(
                (
                    channel
                    for channel, prediction in predictions.items()
                    if prediction.effect != effects[channel]
                ),
                key=lambda channel: channel.value,
            )
        )
        return UpliftServingPrediction(
            raw_channel_effects=raw_effects,
            channel_effects=effects,
            channel_uncertainty=uncertainties,
            channel_support=supports,
            model_support_diagnostics=model_support,
            channel_effect_lower_bound=lower_bounds,
            clipped_channels=clipped,
        )

    def enrich_observation(
        self,
        observation: UserObservation,
        features: Sequence[float],
    ) -> tuple[UserObservation, UpliftServingPrediction]:
        prediction = self.predict(features)
        enriched = replace(
            observation,
            channel_uplift=prediction.channel_effects,
            uplift_uncertainty=prediction.aggregate_uncertainty,
            channel_uncertainty=prediction.channel_uncertainty,
            channel_support=prediction.channel_support,
            channel_effect_lower_bound=prediction.channel_effect_lower_bound,
        )
        return enriched, prediction
