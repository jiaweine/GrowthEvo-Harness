from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from growthevo.models import Channel, UserObservation

from .dr_learner import CATEEstimate, FittedTreatmentEffect


def _clip_probability_effect(value: float) -> float:
    return max(-1.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class UpliftServingPrediction:
    raw_channel_effects: Mapping[Channel, float]
    channel_effects: Mapping[Channel, float]
    channel_uncertainty: Mapping[Channel, float]
    channel_support: Mapping[Channel, float]
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
    """Expose fitted treatment-effect models through the Runtime observation contract.

    The bridge preserves channel-specific effect, uncertainty, and support. The
    aggregate uncertainty remains available for legacy consumers, but policies
    can make channel-specific conservative decisions instead of inheriting the
    worst uncertainty from an unrelated action.
    """

    def __init__(self, models: Mapping[Channel, FittedTreatmentEffect]) -> None:
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
        supports = {
            channel: prediction.support_score for channel, prediction in predictions.items()
        }
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
        )
        return enriched, prediction
