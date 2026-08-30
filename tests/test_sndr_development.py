from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_sndr_dev.py"
spec = importlib.util.spec_from_file_location("sndr_dev", SCRIPT)
assert spec is not None and spec.loader is not None
sndr_dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sndr_dev
spec.loader.exec_module(sndr_dev)


def test_sndr_matches_dr_when_importance_weights_are_constant_one() -> None:
    rows = tuple(
        LoggedBanditRecord(
            reward=reward,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=baseline,
            target_q=target,
            record_id=f"row-{index}",
        )
        for index, (reward, baseline, target) in enumerate(
            (
                (1.0, 0.2, 0.3),
                (0.0, 0.4, 0.5),
                (1.0, 0.6, 0.7),
                (0.0, 0.1, 0.2),
            )
        )
    )

    estimate, se, mean_weight, correction, influence_mean, method, clusters = sndr_dev.sndr_estimate(rows)
    dr = evaluate_policy(rows)

    assert mean_weight == pytest.approx(1.0)
    assert estimate == pytest.approx(dr.doubly_robust)
    assert se == pytest.approx(dr.dr_standard_error)
    assert correction == pytest.approx(
        sum(row.reward - row.baseline_q for row in rows) / len(rows)
    )
    assert influence_mean == pytest.approx(0.0, abs=1e-15)
    assert method == "iid"
    assert clusters is None


def test_sndr_uses_ratio_normalization_and_delta_influence() -> None:
    rows = (
        LoggedBanditRecord(1.0, 0.5, 0.25, 0.2, 0.3, record_id="a"),  # w=.5
        LoggedBanditRecord(0.0, 0.5, 0.50, 0.4, 0.5, record_id="b"),  # w=1
        LoggedBanditRecord(1.0, 0.5, 0.75, 0.6, 0.7, record_id="c"),  # w=1.5
        LoggedBanditRecord(0.0, 0.5, 1.00, 0.1, 0.2, record_id="d"),  # w=2
    )

    estimate, se, mean_weight, correction, influence_mean, _, _ = sndr_dev.sndr_estimate(rows)

    weights = [0.5, 1.0, 1.5, 2.0]
    q_pi = [0.3, 0.5, 0.7, 0.2]
    residuals = [
        weight * (row.reward - row.baseline_q)
        for weight, row in zip(weights, rows, strict=True)
    ]
    expected_mean_weight = sum(weights) / 4
    expected_correction = (sum(residuals) / 4) / expected_mean_weight
    expected = sum(q_pi) / 4 + expected_correction

    assert mean_weight == pytest.approx(expected_mean_weight)
    assert correction == pytest.approx(expected_correction)
    assert estimate == pytest.approx(expected)
    assert influence_mean == pytest.approx(0.0, abs=1e-15)
    assert se > 0.0


def test_sndr_cluster_standard_error_and_partial_cluster_fail_closed() -> None:
    rows = (
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.2, 0.3, cluster_id="d1", record_id="a"),
        LoggedBanditRecord(0.0, 0.5, 0.5, 0.2, 0.3, cluster_id="d1", record_id="b"),
        LoggedBanditRecord(1.0, 0.5, 0.75, 0.2, 0.3, cluster_id="d2", record_id="c"),
        LoggedBanditRecord(0.0, 0.5, 0.75, 0.2, 0.3, cluster_id="d2", record_id="d"),
    )

    _, se, _, _, _, method, cluster_count = sndr_dev.sndr_estimate(rows)

    assert se >= 0.0
    assert method == "cluster"
    assert cluster_count == 2

    with pytest.raises(ValueError, match="cluster_id"):
        sndr_dev.sndr_estimate(
            (
                rows[0],
                LoggedBanditRecord(0.0, 0.5, 0.5, 0.2, 0.3, record_id="x"),
            )
        )


def test_sndr_requires_positive_importance_mass() -> None:
    rows = (
        LoggedBanditRecord(1.0, 0.5, 0.0, 0.2, 0.3, record_id="a"),
        LoggedBanditRecord(0.0, 0.5, 0.0, 0.2, 0.3, record_id="b"),
    )

    with pytest.raises(ValueError, match="positive finite mean importance weight"):
        sndr_dev.sndr_estimate(rows)
