from __future__ import annotations

import math

import pytest

from growthevo.rl import ope as ope_module
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


def test_cluster_robust_uncertainty_and_recsys_meta_blue_are_exposed() -> None:
    rows = [
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.3, 0.4, cluster_id="day-1", record_id="a"),
        LoggedBanditRecord(0.0, 0.5, 0.5, 0.3, 0.4, cluster_id="day-1", record_id="b"),
        LoggedBanditRecord(1.0, 0.25, 0.5, 0.3, 0.4, cluster_id="day-2", record_id="c"),
        LoggedBanditRecord(0.0, 0.75, 0.5, 0.3, 0.4, cluster_id="day-2", record_id="d"),
    ]

    estimate = evaluate_policy(rows, beta_folds=2)

    assert estimate.standard_error_method == "cluster"
    assert estimate.cluster_count == 2
    assert [name for name, _ in estimate.meta_blue_weights] == [
        "beta_ips",
        "self_normalized_ips",
        "doubly_robust",
    ]
    assert "ips" not in {name for name, _ in estimate.meta_blue_weights}
    assert sum(weight for _, weight in estimate.meta_blue_weights) == pytest.approx(1.0)
    assert math.isfinite(estimate.meta_blue)
    assert estimate.meta_blue_standard_error >= 0.0
    assert estimate.mean_importance_weight > 0.0
    assert estimate.importance_weight_normalization_error >= 0.0


def test_meta_blue_uses_cluster_covariance_not_only_cluster_final_se() -> None:
    influences = (
        ("beta_ips", [3.0, 3.0, -3.0, -3.0, 1.0, -1.0]),
        ("self_normalized_ips", [2.0, 2.0, -2.0, -2.0, -1.0, 1.0]),
        ("doubly_robust", [1.0, -1.0, 1.0, -1.0, 0.5, -0.5]),
    )
    iid_covariance = ope_module._covariance_of_means(
        influences,
        cluster_ids=None,
    )
    cluster_covariance = ope_module._covariance_of_means(
        influences,
        cluster_ids=["a", "a", "b", "b", "c", "c"],
    )

    assert cluster_covariance != iid_covariance
    assert ope_module._blue_weights(cluster_covariance) != pytest.approx(
        ope_module._blue_weights(iid_covariance)
    )


def test_meta_blue_drops_snips_when_target_importance_mass_is_zero() -> None:
    rows = [
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=0.0,
            baseline_q=0.2,
            target_q=0.3,
            record_id=f"zero-{index}",
        )
        for index in range(4)
    ]

    estimate = evaluate_policy(rows, beta_folds=2)

    assert math.isnan(estimate.self_normalized_ips)
    assert math.isnan(estimate.snips_standard_error)
    assert [name for name, _ in estimate.meta_blue_weights] == [
        "beta_ips",
        "doubly_robust",
    ]
    assert math.isfinite(estimate.meta_blue)
    assert estimate.support_coverage == pytest.approx(0.0)
    assert estimate.effective_sample_ratio == pytest.approx(0.0)


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
