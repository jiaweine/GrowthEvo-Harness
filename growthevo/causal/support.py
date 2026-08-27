from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
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
    lower_bound: float | None = None
    upper_bound: float | None = None
    calibration_miscoverage: float | None = None
    calibration_size: int = 0

    @property
    def calibrated(self) -> bool:
        return self.lower_bound is not None and self.upper_bound is not None


@dataclass(frozen=True, slots=True)
class FittedPairwisePropensity:
    """Feature-local approximation of the declared logging policy.

    The regression target is the pair-normalized logging probability already
    stored in each row, not the realized treatment indicator. This is a serving
    approximation to ``mu(a|x)`` for contexts where the logging probability is
    unavailable at decision time; it does not manufacture a propensity score for
    datasets that never logged one.

    This fitted model is diagnostic only until calibrated on a disjoint cohort.
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
class CalibratedPairwisePropensity:
    """Split-conformal interval around a fitted logging-propensity model.

    ``error_radius`` is calibrated from absolute propensity residuals on a
    separate calibration cohort. Under the usual split-conformal exchangeability
    assumptions, the interval provides marginal finite-sample coverage for the
    recorded pairwise propensity target. The class deliberately stores the
    calibration size and requested miscoverage so downstream evidence can audit
    how the support decision was produced.
    """

    fitted: FittedPairwisePropensity
    error_radius: float
    miscoverage: float
    calibration_size: int

    def __post_init__(self) -> None:
        if self.error_radius < 0 or self.error_radius > 1:
            raise ValueError("error_radius must be in [0, 1]")
        if not 0 < self.miscoverage < 1:
            raise ValueError("miscoverage must be in (0, 1)")
        if self.calibration_size <= 0:
            raise ValueError("calibration_size must be positive")

    @property
    def treatment(self) -> Channel:
        return self.fitted.treatment

    @property
    def control(self) -> Channel:
        return self.fitted.control

    def predict(self, features: Sequence[float]) -> PairwisePropensityEstimate:
        point = self.fitted.predict(features)
        return PairwisePropensityEstimate(
            treatment=point.treatment,
            control=point.control,
            propensity=point.propensity,
            raw_prediction=point.raw_prediction,
            clipped=point.clipped,
            lower_bound=max(0.0, point.propensity - self.error_radius),
            upper_bound=min(1.0, point.propensity + self.error_radius),
            calibration_miscoverage=self.miscoverage,
            calibration_size=self.calibration_size,
        )


@dataclass(frozen=True, slots=True)
class PropensitySupportProtocol:
    """Explicit practical-overlap interval for deployment serving.

    No universal overlap threshold is supplied by the library. The deployment or
    benchmark protocol chooses ``min_pairwise_probability``. A context is marked
    supported only if the *entire calibrated propensity interval* lies inside the
    practical-overlap region. An uncalibrated point prediction is rejected rather
    than silently promoted into deployment evidence.
    """

    min_pairwise_probability: float

    def __post_init__(self) -> None:
        if not 0 < self.min_pairwise_probability < 0.5:
            raise ValueError("min_pairwise_probability must be in (0, 0.5)")

    def score(self, estimate: PairwisePropensityEstimate) -> float:
        if estimate.lower_bound is None or estimate.upper_bound is None:
            raise ValueError("deployment support requires a calibrated propensity interval")
        return float(
            estimate.lower_bound >= self.min_pairwise_probability
            and estimate.upper_bound <= 1.0 - self.min_pairwise_probability
        )


def _pairwise_target(
    row: LoggedTreatmentRecord,
    *,
    treatment: Channel,
    control: Channel,
) -> float | None:
    p1 = float(row.action_propensities.get(treatment, 0.0))
    p0 = float(row.action_propensities.get(control, 0.0))
    pair_mass = p1 + p0
    if pair_mass <= 0.0:
        return None
    return p1 / pair_mass


def fit_pairwise_propensity_model(
    records: Iterable[LoggedTreatmentRecord],
    *,
    treatment: Channel,
    control: Channel = Channel.NO_TREATMENT,
    model_factory: RegressorFactory | None = None,
    ridge: float = 1e-3,
) -> FittedPairwisePropensity:
    """Fit ``mu(treatment | x, treatment-or-control)`` from logged probabilities.

    All contexts with positive treatment/control probability mass are usable,
    regardless of which action happened to be realized. This avoids discarding
    valid logging-policy supervision in multi-action logs.
    """

    if treatment is control:
        raise ValueError("treatment and control must differ")
    if ridge <= 0:
        raise ValueError("ridge must be positive")

    usable: list[tuple[LoggedTreatmentRecord, float]] = []
    for row in records:
        target = _pairwise_target(row, treatment=treatment, control=control)
        if target is not None:
            usable.append((row, target))
    if not usable:
        raise ValueError("no rows have positive treatment/control propensity mass")

    factory = model_factory or (lambda: RidgeRegressor(ridge))
    model = factory().fit(
        (row.features for row, _ in usable),
        (target for _, target in usable),
    )
    return FittedPairwisePropensity(
        treatment=treatment,
        control=control,
        model=model,
        sample_size=len(usable),
    )


def calibrate_pairwise_propensity_model(
    fitted: FittedPairwisePropensity,
    records: Iterable[LoggedTreatmentRecord],
    *,
    miscoverage: float,
) -> CalibratedPairwisePropensity:
    """Calibrate a split-conformal absolute-residual propensity interval.

    ``records`` must come from a calibration cohort that was not used to fit the
    propensity model or to tune its hyperparameters. The function cannot infer
    cohort provenance, so that split remains an explicit experiment contract.
    """

    if not 0 < miscoverage < 1:
        raise ValueError("miscoverage must be in (0, 1)")

    residuals: list[float] = []
    for row in records:
        target = _pairwise_target(
            row,
            treatment=fitted.treatment,
            control=fitted.control,
        )
        if target is None:
            continue
        prediction = fitted.predict(row.features).propensity
        residuals.append(abs(target - prediction))
    if not residuals:
        raise ValueError("calibration cohort has no positive treatment/control propensity mass")

    residuals.sort()
    rank = ceil((len(residuals) + 1) * (1.0 - miscoverage))
    rank = min(len(residuals), max(1, rank))
    radius = residuals[rank - 1]
    return CalibratedPairwisePropensity(
        fitted=fitted,
        error_radius=radius,
        miscoverage=miscoverage,
        calibration_size=len(residuals),
    )


def make_support_score_provider(
    models: Mapping[Channel, CalibratedPairwisePropensity],
    protocols: Mapping[Channel, PropensitySupportProtocol],
):
    """Create a feature-local, calibrated serving-support provider."""

    if not models:
        raise ValueError("at least one calibrated propensity model is required")
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
