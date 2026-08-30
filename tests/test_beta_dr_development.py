from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from growthevo.rl.ope import LoggedBanditRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_beta_dr_dev.py"
spec = importlib.util.spec_from_file_location("beta_dr_dev", SCRIPT)
assert spec is not None and spec.loader is not None
beta_dr_dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beta_dr_dev)


def _linear_control_rows() -> tuple[LoggedBanditRecord, ...]:
    weights = (0.5, 1.0, 1.5, 2.0) * 3
    rows = []
    for index, weight in enumerate(weights):
        # With target_q=1 and baseline_q=0 this makes
        # DR_i = 1 + 2 * (w_i - 1), so the optimal additive control is exact.
        reward = 2.0 * (weight - 1.0) / weight
        rows.append(
            LoggedBanditRecord(
                reward=reward,
                behavior_propensity=0.5,
                target_action_probability=0.5 * weight,
                baseline_q=0.0,
                target_q=1.0,
                record_id=f"row-{index}",
            )
        )
    return tuple(rows)


def test_cross_fitted_beta_dr_can_remove_normalization_variance_without_same_fold_fit() -> None:
    rows = _linear_control_rows()

    result = beta_dr_dev.compare_beta_dr(rows, reference_value=1.0, beta_folds=3)

    assert result.beta_folds == 3
    assert result.fold_betas == pytest.approx((2.0, 2.0, 2.0))
    assert result.beta_dr_estimate == pytest.approx(1.0)
    assert result.beta_dr_absolute_error == pytest.approx(0.0)
    assert result.beta_dr_standard_error == pytest.approx(0.0, abs=1e-12)
    assert result.dr_absolute_error > result.beta_dr_absolute_error
    assert result.dr_standard_error > result.beta_dr_standard_error


def test_clustered_cross_fit_keeps_each_cluster_in_one_fold() -> None:
    rows = tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=0.25 + 0.25 * (index % 3),
            baseline_q=0.2,
            target_q=0.3,
            cluster_id=f"day-{index // 2}",
            record_id=f"row-{index}",
        )
        for index in range(8)
    )

    assignments, actual_folds = beta_dr_dev._fold_assignments(rows, 3)

    assert actual_folds == 3
    for cluster in {row.cluster_id for row in rows}:
        cluster_folds = {
            assignments[index]
            for index, row in enumerate(rows)
            if row.cluster_id == cluster
        }
        assert len(cluster_folds) == 1


def test_partial_cluster_ids_fail_closed() -> None:
    rows = (
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.0, 0.0, cluster_id="day-1", record_id="a"),
        LoggedBanditRecord(0.0, 0.5, 0.5, 0.0, 0.0, record_id="b"),
    )

    with pytest.raises(ValueError, match="cluster_id"):
        beta_dr_dev.cross_fitted_beta_dr_terms(rows, beta_folds=2)
