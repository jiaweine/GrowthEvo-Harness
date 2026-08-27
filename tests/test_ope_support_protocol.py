from __future__ import annotations

import pytest

from growthevo.rl.ope import (
    LoggedBanditRecord,
    evaluate_policy,
    policy_evidence_from_ope,
)


def _rows() -> list[LoggedBanditRecord]:
    return [
        LoggedBanditRecord(
            reward=1.0,
            behavior_propensity=0.50,
            target_action_probability=0.50,
            baseline_q=0.40,
            target_q=0.40,
        ),
        LoggedBanditRecord(
            reward=0.0,
            behavior_propensity=0.01,
            target_action_probability=0.50,
            baseline_q=0.20,
            target_q=0.30,
        ),
    ]


def _evidence(estimate):
    return policy_evidence_from_ope(
        estimate,
        baseline_value=0.0,
        roi=1.0,
        spend=0.0,
        fatigue=0.0,
        churn_risk=0.0,
    )


def test_ope_without_practical_support_floor_is_inspectable_but_not_promotable() -> None:
    estimate = evaluate_policy(_rows())

    assert estimate.support_propensity_floor is None
    assert estimate.support_coverage == pytest.approx(1.0)
    assert estimate.record_support_coverage == pytest.approx(1.0)
    with pytest.raises(ValueError, match="explicit practical support"):
        _evidence(estimate)


def test_explicit_support_floor_controls_promotion_diagnostics() -> None:
    estimate = evaluate_policy(_rows(), support_propensity_floor=0.05)
    evidence = _evidence(estimate)

    # The second row carries 50x the importance mass of the first and is below
    # the declared practical support floor, so target-policy-mass support is low.
    assert estimate.support_propensity_floor == pytest.approx(0.05)
    assert estimate.record_support_coverage == pytest.approx(0.5)
    assert estimate.support_coverage == pytest.approx(1.0 / 51.0)
    assert evidence.support_coverage == pytest.approx(1.0 / 51.0)
    assert evidence.max_importance_weight == pytest.approx(50.0)


def test_support_floor_is_not_an_importance_weight_clip() -> None:
    low_floor = evaluate_policy(_rows(), support_propensity_floor=0.005)
    high_floor = evaluate_policy(_rows(), support_propensity_floor=0.05)

    assert low_floor.ips == pytest.approx(high_floor.ips)
    assert low_floor.doubly_robust == pytest.approx(high_floor.doubly_robust)
    assert low_floor.max_importance_weight == pytest.approx(high_floor.max_importance_weight)
    assert low_floor.support_coverage > high_floor.support_coverage
