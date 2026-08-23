from __future__ import annotations

from dataclasses import dataclass, replace
from math import fsum
from typing import Mapping, Sequence

from growthevo.models import Channel, UserObservation

from .dr_learner import CATEEstimate, FittedTreatmentEffect


@dataclass(frozen=True, slots=True)
class UpliftServingPrediction:
    channel_effects: Mapping[Channel, float]
    channel_uncertainty: Mapping[Channel, float]
    channel_support: Mapping[Channel, float]

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

    The bridge does not silently turn low support into a confident zero effect.
    Instead it inflates uncertainty as support falls, allowing downstream policy
    logic to abstain while preserving the raw estimated effect for auditability.
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
        effects = {channel: prediction.effect for channel, prediction in predictions.items()}
        supports = {
            channel: prediction.support_score for channel, prediction in predictions.items()
        }
        uncertainties = {
            channel: max(
                0.0,
                prediction.uncertainty
                + abs(prediction.effect) * (1.0 - prediction.support_score),
            )
            for channel, prediction in predictions.items()
        }
        return UpliftServingPrediction(
            channel_effects=effects,
            channel_uncertainty=uncertainties,
            channel_support=supports,
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
        )
        return enriched, prediction
