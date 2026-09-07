from __future__ import annotations

from math import isfinite

import pytest

from growthevo.evolution.nonstationary_heavy_tail import (
    ChangingMeanDecision,
    ChangingMeanLowerConfidenceSequence,
    ChangingMeanLowerCSSpec,
    ChangingMeanOffPolicySpec,
    ChangingMeanOffPolicyValueMonitor,
    NonstationaryFloorSpec,
    NonstationaryPositiveMetricMonitor,
)


def _spec(**overrides: object) -> ChangingMeanLowerCSSpec:
    values: dict[str, object] = {
        "mean_upper": 1.0,
        "alpha": 0.05,
        "lambdas": (0.05, 0.1, 0.2, 0.4, 0.7),
        "predictor_pseudocount": 0.5,
    }
    values.update(overrides)
    return ChangingMeanLowerCSSpec(**values)  # type: ignore[arg-type]


def test_spec_fingerprint_binds_mean_alpha_lambda_and_predictor() -> None:
    baseline = _spec()
    assert baseline.fingerprint != _spec(mean_upper=2.0).fingerprint
    assert baseline.fingerprint != _spec(alpha=0.025).fingerprint
    assert baseline.fingerprint != _spec(lambdas=(0.1, 0.2, 0.4)).fingerprint
    assert baseline.fingerprint != _spec(predictor_pseudocount=0.25).fingerprint


def test_empty_sequence_has_zero_lower_bound() -> None:
    cs = ChangingMeanLowerConfidenceSequence(_spec())
    assert cs.lower_bound() == 0.0
    assert cs.snapshot().observations == 0


def test_constant_nonnegative_signal_builds_nontrivial_lower_bound() -> None:
    cs = ChangingMeanLowerConfidenceSequence(_spec())
    for _ in range(100):
        cs.update(0.8)
    lower = cs.lower_bound()
    assert 0.70 < lower < 0.8


def test_changing_mean_targets_running_average_not_stationary_mean() -> None:
    cs = ChangingMeanLowerConfidenceSequence(_spec())
    values = [0.2 if (index // 25) % 2 == 0 else 0.8 for index in range(500)]
    for value in values:
        cs.update(value)
    assert sum(values) / len(values) == pytest.approx(0.5)
    assert 0.43 < cs.lower_bound() < 0.5


def test_observations_may_exceed_conditional_mean_cap() -> None:
    cs = ChangingMeanLowerConfidenceSequence(_spec())
    for _ in range(50):
        cs.update(0.4)
    cs.update(1000.0)
    lower = cs.lower_bound()
    assert isfinite(lower)
    assert 0.0 <= lower <= 1.0


def test_negative_observation_is_rejected() -> None:
    cs = ChangingMeanLowerConfidenceSequence(_spec())
    with pytest.raises(ValueError, match="nonnegative"):
        cs.update(-1e-9)
    assert cs.observations == 0


def test_positive_metric_floor_monitor_supports_absolute_floor_under_drift() -> None:
    monitor = NonstationaryPositiveMetricMonitor(
        experiment_id="drifting-kpi",
        spec=NonstationaryFloorSpec(
            metric_name="engagement",
            confidence_sequence=_spec(),
            floor=0.4,
        ),
    )
    for index in range(500):
        value = 0.2 if (index // 25) % 2 == 0 else 0.8
        snapshot = monitor.update(analysis_unit_id=f"unit-{index}", value=value)
    assert snapshot.decision is ChangingMeanDecision.ABOVE_FLOOR
    assert snapshot.lower > 0.4


def test_floor_monitor_deduplicates_analysis_units() -> None:
    monitor = NonstationaryPositiveMetricMonitor(
        experiment_id="dedupe",
        spec=NonstationaryFloorSpec(
            metric_name="kpi",
            confidence_sequence=_spec(),
            floor=0.1,
        ),
    )
    monitor.update(analysis_unit_id="same", value=0.5)
    with pytest.raises(ValueError, match="already contributed"):
        monitor.update(analysis_unit_id="same", value=0.5)
    assert monitor.cs.observations == 1


def test_off_policy_monitor_allows_unbounded_importance_weight() -> None:
    monitor = ChangingMeanOffPolicyValueMonitor(
        experiment_id="ope",
        spec=ChangingMeanOffPolicySpec(
            confidence_sequence=_spec(),
            reward_upper=1.0,
            value_floor=0.2,
        ),
    )
    monitor.update(observation_id="rare", importance_weight=100.0, reward=1.0)
    snapshot = monitor.snapshot()
    assert isfinite(snapshot.lower)
    assert 0.0 <= snapshot.lower <= 1.0


def test_off_policy_reward_range_is_fail_closed() -> None:
    monitor = ChangingMeanOffPolicyValueMonitor(
        experiment_id="ope-range",
        spec=ChangingMeanOffPolicySpec(confidence_sequence=_spec()),
    )
    with pytest.raises(ValueError, match="reward range"):
        monitor.update(observation_id="bad", importance_weight=1.0, reward=1.1)
    assert monitor.cs.observations == 0


def test_off_policy_duplicate_is_rejected() -> None:
    monitor = ChangingMeanOffPolicyValueMonitor(
        experiment_id="ope-dedupe",
        spec=ChangingMeanOffPolicySpec(confidence_sequence=_spec()),
    )
    monitor.update(observation_id="same", importance_weight=1.0, reward=0.5)
    with pytest.raises(ValueError, match="already contributed"):
        monitor.update(observation_id="same", importance_weight=1.0, reward=0.5)
    assert monitor.cs.observations == 1


def test_off_policy_numeric_overflow_is_atomic() -> None:
    monitor = ChangingMeanOffPolicyValueMonitor(
        experiment_id="ope-overflow",
        spec=ChangingMeanOffPolicySpec(
            confidence_sequence=_spec(mean_upper=2.0),
            reward_upper=2.0,
        ),
    )
    with pytest.raises(ValueError, match="overflowed"):
        monitor.update(
            observation_id="bad",
            importance_weight=1e308,
            reward=2.0,
        )
    assert monitor.cs.observations == 0


def test_off_policy_spec_fingerprint_binds_value_floor() -> None:
    baseline = ChangingMeanOffPolicySpec(
        confidence_sequence=_spec(),
        reward_upper=1.0,
        value_floor=0.1,
    )
    changed = ChangingMeanOffPolicySpec(
        confidence_sequence=_spec(),
        reward_upper=1.0,
        value_floor=0.2,
    )
    assert baseline.fingerprint != changed.fingerprint
