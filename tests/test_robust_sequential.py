from __future__ import annotations

from math import isfinite

import pytest

from growthevo.evolution.robust_sequential import (
    CatoniMixtureConfidenceSequence,
    CatoniMixtureSpec,
    RobustEffectDecision,
    RobustRandomizedEffectMonitor,
    RobustRandomizedEffectSpec,
    catoni_influence,
)


def _cs_spec(**overrides: object) -> CatoniMixtureSpec:
    values: dict[str, object] = {
        "variance_bound": 4.0,
        "alpha": 0.05,
        "lambda_scales": (0.125, 0.25, 0.5, 1.0, 2.0),
    }
    values.update(overrides)
    return CatoniMixtureSpec(**values)  # type: ignore[arg-type]


def _effect_spec(**overrides: object) -> RobustRandomizedEffectSpec:
    values: dict[str, object] = {
        "metric_name": "value",
        "confidence_sequence": _cs_spec(),
        "superiority_margin": 0.0,
        "harm_margin": 0.0,
        "min_propensity": 0.05,
        "higher_is_better": True,
    }
    values.update(overrides)
    return RobustRandomizedEffectSpec(**values)  # type: ignore[arg-type]


def test_catoni_influence_is_odd_and_stable_for_large_finite_values() -> None:
    for value in (0.01, 1.0, 100.0, 1e200):
        positive = catoni_influence(value)
        negative = catoni_influence(-value)
        assert isfinite(positive)
        assert negative == pytest.approx(-positive)


def test_catoni_spec_fingerprint_binds_variance_alpha_and_lambda_grid() -> None:
    baseline = _cs_spec()
    assert baseline.fingerprint != _cs_spec(variance_bound=5.0).fingerprint
    assert baseline.fingerprint != _cs_spec(alpha=0.025).fingerprint
    assert baseline.fingerprint != _cs_spec(lambda_scales=(0.25, 0.5, 1.0)).fingerprint


def test_catoni_confidence_sequence_is_unbounded_before_first_observation() -> None:
    interval = CatoniMixtureConfidenceSequence(_cs_spec()).interval()
    assert interval.lower == float("-inf")
    assert interval.upper == float("inf")
    assert interval.observations == 0


def test_catoni_confidence_sequence_contains_constant_signal() -> None:
    monitor = CatoniMixtureConfidenceSequence(_cs_spec(variance_bound=1.0))
    for _ in range(80):
        monitor.update(2.0)
    interval = monitor.interval()
    assert interval.lower < 2.0 < interval.upper
    assert interval.width < 1.0


def test_catoni_confidence_sequence_accepts_large_unbounded_observation() -> None:
    monitor = CatoniMixtureConfidenceSequence(_cs_spec(variance_bound=100.0))
    monitor.update(1e100)
    interval = monitor.interval()
    assert isfinite(interval.lower)
    assert isfinite(interval.upper)


def test_positive_randomized_effect_eventually_supports_superiority() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="heavy-tail-positive",
        spec=_effect_spec(),
    )
    snapshot = monitor.snapshot()
    assert snapshot.decision is RobustEffectDecision.HOLD

    # With p=0.5, challenger Y=2 contributes +4 and control Y=0 contributes 0.
    # The monitored HT sequence therefore has mean 2 and variance 4.
    for index in range(50):
        challenger = index % 2 == 0
        snapshot = monitor.update(
            analysis_unit_id=f"unit-{index}",
            assigned_to_challenger=challenger,
            assignment_probability=0.5,
            outcome=2.0 if challenger else 0.0,
        )
    assert snapshot.decision is RobustEffectDecision.SUPPORTS_SUPERIORITY
    assert snapshot.lower > 0.0


def test_negative_randomized_effect_eventually_supports_harm() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="heavy-tail-negative",
        spec=_effect_spec(),
    )
    for index in range(50):
        challenger = index % 2 == 0
        snapshot = monitor.update(
            analysis_unit_id=f"unit-{index}",
            assigned_to_challenger=challenger,
            assignment_probability=0.5,
            outcome=0.0 if challenger else 2.0,
        )
    assert snapshot.decision is RobustEffectDecision.SUPPORTS_HARM
    assert snapshot.upper < 0.0


def test_lower_is_better_orients_effect_before_robust_inference() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="latency",
        spec=_effect_spec(higher_is_better=False),
    )
    for index in range(50):
        challenger = index % 2 == 0
        snapshot = monitor.update(
            analysis_unit_id=f"unit-{index}",
            assigned_to_challenger=challenger,
            assignment_probability=0.5,
            outcome=0.0 if challenger else 2.0,
        )
    assert snapshot.decision is RobustEffectDecision.SUPPORTS_SUPERIORITY


def test_duplicate_randomized_unit_is_rejected_without_second_update() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="dedupe",
        spec=_effect_spec(),
    )
    monitor.update(
        analysis_unit_id="same-user",
        assigned_to_challenger=True,
        assignment_probability=0.5,
        outcome=1.0,
    )
    with pytest.raises(ValueError, match="already contributed"):
        monitor.update(
            analysis_unit_id="same-user",
            assigned_to_challenger=True,
            assignment_probability=0.5,
            outcome=1.0,
        )
    assert monitor.observations == 1


def test_propensity_support_floor_is_fail_closed_and_atomic() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="support",
        spec=_effect_spec(min_propensity=0.1),
    )
    with pytest.raises(ValueError, match="support floor"):
        monitor.update(
            analysis_unit_id="unit",
            assigned_to_challenger=True,
            assignment_probability=0.05,
            outcome=1.0,
        )
    assert monitor.observations == 0


def test_ht_numeric_overflow_is_rejected_before_state_mutation() -> None:
    monitor = RobustRandomizedEffectMonitor(
        experiment_id="overflow",
        spec=_effect_spec(min_propensity=0.05),
    )
    with pytest.raises(ValueError, match="overflowed"):
        monitor.update(
            analysis_unit_id="unit",
            assigned_to_challenger=True,
            assignment_probability=0.05,
            outcome=1e308,
        )
    assert monitor.observations == 0


def test_effect_protocol_fingerprint_binds_causal_and_decision_contract() -> None:
    baseline = _effect_spec()
    assert baseline.fingerprint != _effect_spec(superiority_margin=0.1).fingerprint
    assert baseline.fingerprint != _effect_spec(harm_margin=-0.1).fingerprint
    assert baseline.fingerprint != _effect_spec(higher_is_better=False).fingerprint
    assert baseline.fingerprint != _effect_spec(min_propensity=0.1).fingerprint
