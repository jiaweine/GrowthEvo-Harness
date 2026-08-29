from __future__ import annotations

import math

import pytest

from growthevo.rl.ope import (
    LoggedBanditRecord,
    estimate_beta_coefficient,
    evaluate_policy,
)


def test_cross_fitted_beta_ips_keeps_optimal_additive_variance_reduction() -> None:
    rows = [
        LoggedBanditRecord(
            reward=reward,
            behavior_propensity=0.5,
            target_action_probability=target_probability,
            baseline_q=0.0,
            target_q=0.0,
            record_id=f"row-{index}",
        )
        for index, (target_probability, reward) in enumerate(
            (
                (0.25, 0.0),
                (0.50, 1.0),
                (0.75, 4.0 / 3.0),
                (1.00, 1.5),
            )
        )
    ]

    estimate = evaluate_policy(rows, beta_folds=2)

    assert estimate.beta_star == pytest.approx(2.0)
    assert estimate.beta_mode == "cross_fit"
    assert estimate.beta_crossfit_folds == 2
    assert estimate.beta_ips == pytest.approx(1.0)
    assert estimate.beta_ips_standard_error == pytest.approx(0.0, abs=1e-12)
    assert estimate.ips_standard_error > estimate.beta_ips_standard_error


def test_fixed_beta_from_tuning_data_is_supported_for_strict_evaluation_split() -> None:
    tuning = [
        LoggedBanditRecord(0.0, 0.5, 0.25, 0.0, 0.0),
        LoggedBanditRecord(1.0, 0.5, 0.50, 0.0, 0.0),
        LoggedBanditRecord(4.0 / 3.0, 0.5, 0.75, 0.0, 0.0),
        LoggedBanditRecord(1.5, 0.5, 1.00, 0.0, 0.0),
    ]
    beta = estimate_beta_coefficient(tuning)
    evaluation = [
        LoggedBanditRecord(2.0, 0.5, 0.50, 0.0, 0.0),
        LoggedBanditRecord(1.0, 0.5, 1.00, 0.0, 0.0),
    ]

    estimate = evaluate_policy(evaluation, beta_coefficient=beta)

    assert beta == pytest.approx(2.0)
    assert estimate.beta_mode == "fixed"
    assert estimate.beta_crossfit_folds == 0
    assert estimate.beta_coefficient == pytest.approx(2.0)


def test_switch_dr_and_optimistic_shrinkage_limit_extreme_weight_residuals() -> None:
    rows = [
        LoggedBanditRecord(
            reward=1.0,
            behavior_propensity=0.001,
            target_action_probability=1.0,
            baseline_q=0.0,
            target_q=0.2,
        ),
        LoggedBanditRecord(
            reward=0.0,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=0.1,
            target_q=0.2,
        ),
    ]

    estimate = evaluate_policy(rows, switch_threshold=10.0, dr_os_lambda=100.0)

    assert estimate.max_importance_weight == pytest.approx(1000.0)
    assert estimate.doubly_robust > 100.0
    assert estimate.switch_dr < 1.0
    assert estimate.dr_os < 1.0
    assert estimate.switch_dr_standard_error < estimate.dr_standard_error
    assert estimate.dr_os_standard_error < estimate.dr_standard_error


def test_cluster_robust_uncertainty_and_meta_blue_are_exposed() -> None:
    rows = [
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.3, 0.4, cluster_id="day-1", record_id="a"),
        LoggedBanditRecord(0.0, 0.5, 0.5, 0.3, 0.4, cluster_id="day-1", record_id="b"),
        LoggedBanditRecord(1.0, 0.25, 0.5, 0.3, 0.4, cluster_id="day-2", record_id="c"),
        LoggedBanditRecord(0.0, 0.75, 0.5, 0.3, 0.4, cluster_id="day-2", record_id="d"),
    ]

    estimate = evaluate_policy(rows, beta_folds=2)

    assert estimate.standard_error_method == "cluster"
    assert estimate.cluster_count == 2
    assert sum(weight for _, weight in estimate.meta_blue_weights) == pytest.approx(1.0)
    assert math.isfinite(estimate.meta_blue)
    assert estimate.meta_blue_standard_error >= 0.0
    assert estimate.mean_importance_weight > 0.0
    assert estimate.importance_weight_normalization_error >= 0.0


def test_partial_cluster_or_record_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="cluster_id"):
        evaluate_policy(
            [
                LoggedBanditRecord(1.0, 0.5, 0.5, 0.0, 0.0, cluster_id="a"),
                LoggedBanditRecord(0.0, 0.5, 0.5, 0.0, 0.0),
            ]
        )

    with pytest.raises(ValueError, match="record_id"):
        evaluate_policy(
            [
                LoggedBanditRecord(1.0, 0.5, 0.5, 0.0, 0.0, record_id="a"),
                LoggedBanditRecord(0.0, 0.5, 0.5, 0.0, 0.0),
            ],
            beta_folds=2,
        )