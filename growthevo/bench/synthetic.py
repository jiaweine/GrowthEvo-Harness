from __future__ import annotations

from dataclasses import dataclass
from math import fsum, sqrt
import random
from typing import Callable, Mapping

from growthevo.causal.dr_learner import FittedTreatmentEffect, LoggedTreatmentRecord
from growthevo.models import Channel


@dataclass(frozen=True, slots=True)
class SyntheticGrowthSample:
    record: LoggedTreatmentRecord
    baseline_outcome: float
    oracle_effects: Mapping[Channel, float]

    def oracle_outcome(self, action: Channel) -> float:
        return self.baseline_outcome + float(self.oracle_effects.get(action, 0.0))


@dataclass(frozen=True, slots=True)
class CATEBenchmarkResult:
    treatment: Channel
    sample_size: int
    rmse: float
    mae: float
    bias: float
    mean_support_score: float
    mean_uncertainty: float


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _draw_action(rng: random.Random, propensities: Mapping[Channel, float]) -> Channel:
    threshold = rng.random()
    cumulative = 0.0
    for action in (Channel.NO_TREATMENT, Channel.PUSH, Channel.EMAIL):
        cumulative += propensities[action]
        if threshold <= cumulative:
            return action
    return Channel.EMAIL


def make_synthetic_growth_bandit(
    sample_size: int = 1200,
    *,
    seed: int = 17,
    outcome_noise: float = 0.02,
) -> tuple[SyntheticGrowthSample, ...]:
    """Generate logged contextual-bandit data with known heterogeneous effects.

    The fixture intentionally uses context-dependent logging propensities and
    heterogeneous treatment effects, so a learner must handle both confounding
    by observed context and non-uniform overlap. The generator is a benchmark
    oracle only; its synthetic outcomes are never deployment evidence.
    """

    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if outcome_noise < 0:
        raise ValueError("outcome_noise must be non-negative")

    rng = random.Random(seed)
    samples: list[SyntheticGrowthSample] = []
    for index in range(sample_size):
        intent = rng.uniform(-1.0, 1.0)
        fatigue = rng.uniform(-1.0, 1.0)
        features = (intent, fatigue)

        baseline = 0.22 + 0.06 * intent - 0.04 * fatigue
        push_effect = 0.08 + 0.05 * intent - 0.03 * fatigue
        email_effect = 0.045 - 0.02 * intent - 0.01 * fatigue
        oracle_effects = {
            Channel.NO_TREATMENT: 0.0,
            Channel.PUSH: push_effect,
            Channel.EMAIL: email_effect,
        }

        push_probability = 0.30 + 0.08 * intent - 0.04 * fatigue
        email_probability = 0.25 - 0.03 * intent + 0.03 * fatigue
        control_probability = 1.0 - push_probability - email_probability
        propensities = {
            Channel.NO_TREATMENT: control_probability,
            Channel.PUSH: push_probability,
            Channel.EMAIL: email_probability,
        }
        action = _draw_action(rng, propensities)
        mean_outcome = baseline + oracle_effects[action]
        outcome = _clip(mean_outcome + rng.gauss(0.0, outcome_noise))

        record = LoggedTreatmentRecord(
            unit_id=f"synthetic-{index}",
            features=features,
            action=action,
            outcome=outcome,
            action_propensities=propensities,
        )
        samples.append(
            SyntheticGrowthSample(
                record=record,
                baseline_outcome=baseline,
                oracle_effects=oracle_effects,
            )
        )
    return tuple(samples)


def evaluate_cate(
    model: FittedTreatmentEffect,
    samples: tuple[SyntheticGrowthSample, ...],
) -> CATEBenchmarkResult:
    if not samples:
        raise ValueError("samples cannot be empty")

    errors: list[float] = []
    supports: list[float] = []
    uncertainties: list[float] = []
    for sample in samples:
        prediction = model.predict(sample.record.features)
        oracle = float(sample.oracle_effects.get(model.treatment, 0.0)) - float(
            sample.oracle_effects.get(model.control, 0.0)
        )
        errors.append(prediction.effect - oracle)
        supports.append(prediction.support_score)
        uncertainties.append(prediction.uncertainty)

    n = len(errors)
    return CATEBenchmarkResult(
        treatment=model.treatment,
        sample_size=n,
        rmse=sqrt(fsum(error * error for error in errors) / n),
        mae=fsum(abs(error) for error in errors) / n,
        bias=fsum(errors) / n,
        mean_support_score=fsum(supports) / n,
        mean_uncertainty=fsum(uncertainties) / n,
    )


def oracle_policy_value(
    samples: tuple[SyntheticGrowthSample, ...],
    policy: Callable[[tuple[float, ...]], Channel],
) -> float:
    """Evaluate a policy against the synthetic oracle, without sampling noise."""

    if not samples:
        raise ValueError("samples cannot be empty")
    return fsum(
        sample.oracle_outcome(policy(sample.record.features)) for sample in samples
    ) / len(samples)
