from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping, Sequence

from growthevo.models import Channel

from .dr_learner import LoggedTreatmentRecord, Regressor, RegressorFactory, RidgeRegressor


@dataclass(frozen=True, slots=True)
class PairwisePropensityEstimate:
    treatment: Channel
    control: Channel
    propensity: float
    raw_prediction: float
    clipped: bool


@dataclass(frozen=True, slots=True)
class FittedPairwisePropensity:
    """Feature-local approximation of the declared logging policy.

    The target is the pair-normalized logging probability already stored in the
    log, not the realized treatment indicator. This model is therefore a serving
    approximation to ``mu(a|x)`` rather than a replacement for a missing
    propensity score.
    """

    treatment: Channel
    control: Channel
    model: Regressor
    sample_size: int

    def predict(self, features: Sequence[float]) -> PairwisePropensityEstimate:
        raw = float(self.model.predict_one(features))
        if not isfinite(raw):
            raise ValueError("propensity model returned a non-finite prediction")
        propensity = max(0.0, min(1.0, raw))
        return PairwisePropensityEstimate(
            treatment=self.treatment,
            control=self.control,
            propensity=propensity,
            raw_prediction=raw,
            clipped=propensity != raw,
        )


@dataclass(frozen=True, slots=True)
class PropensitySupportProtocol:
    """Explicit practical-overlap interval for deployment serving.

    No universal interval is supplied by the library. The experiment/deployment
    protocol must choose the minimum pairwise probability that it considers
    usable. A binary score is intentional: it says whether the declared overlap
    requirement is met, without inventing a calibrated confidence scale.
    """

    min_pairwise_probability: float

    def __post_init__(self) -> None:
        if not 0 < self.min_pairwise_probability < 0.5:
            raise ValueError("min_pairwise_probability must be in (0, 0.5)")

    def score(self, estimate: PairwisePropensityEstimate) -> float:
        e = estimate.propensity
        return float(
            self.min_pairwise_probability
            <= e
            <= 1.0 - self.min_pairwise_probability
        )


def fit_pairwise_propensity_model(
    records: Iterable[LoggedTreatmentRecord],
    *,
    treatment: Channel,
    control: Channel = Channel.NO_TREATMENT,
    model_factory: RegressorFactory | None = None,
    ridge: float = 1e-3,
) -> FittedPairwisePropensity:
    """Fit a local logging-propensity serving model from recorded probabilities."""

    if treatment is control:
        raise ValueError("treatment and control must differ")
    if ridge <= 0:
        raise ValueError("ridge must be positive")
    rows = [row for row in records if row.action in {treatment, control}]
    if not rows:
        raise ValueError("no treatment/control rows available")

    targets: list[float] = []
    for row in rows:
        p1 = float(row.action_propensities.get(treatment, 0.0))
        p0 = float(row.action_propensities.get(control, 0.0))
        pair_mass = p1 + p0
        if pair_mass <= 0.0:
            raise ValueError("treatment/control propensity mass must be positive")
        targets.append(p1 / pair_mass)

    factory = model_factory or (lambda: RidgeRegressor(ridge))
    model = factory().fit((row.features for row in rows), targets)
    return FittedPairwisePropensity(
        treatment=treatment,
        control=control,
        model=model,
        sample_size=len(rows),
    )


def make_support_score_provider(
    models: Mapping[Channel, FittedPairwisePropensity],
    protocols: Mapping[Channel, PropensitySupportProtocol],
):
    """Create a feature-aware serving provider from explicit local-overlap rules."""

    if not models:
        raise ValueError("at least one pairwise propensity model is required")
    if set(models) != set(protocols):
        raise ValueError("propensity models and support protocols must cover the same channels")

    for channel, model in models.items():
        if channel is Channel.NO_TREATMENT:
            raise ValueError("NO_TREATMENT does not need a treatment support model")
        if model.treatment is not channel or model.control is not Channel.NO_TREATMENT:
            raise ValueError("support model must match channel vs NO_TREATMENT")

    def provider(channel, estimate, features) -> float:
        del estimate
        return protocols[channel].score(models[channel].predict(features))

    return provider
