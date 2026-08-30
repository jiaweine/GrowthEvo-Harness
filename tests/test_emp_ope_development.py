from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from growthevo.rl.ope import LoggedBanditRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_emp_ope_dev.py"
spec = importlib.util.spec_from_file_location("emp_ope_dev", SCRIPT)
assert spec is not None and spec.loader is not None
emp_ope_dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = emp_ope_dev
spec.loader.exec_module(emp_ope_dev)


def test_emp_solver_satisfies_moment_conditions_and_stays_bounded() -> None:
    raw = (
        (0.5, 0.0, 0.2, 0.3),
        (1.0, 1.0, 0.6, 0.5),
        (1.5, 1.0, 0.4, 0.6),
        (2.0, 0.0, 0.1, 0.4),
        (0.75, 1.0, 0.7, 0.55),
        (1.25, 0.0, 0.2, 0.45),
    )
    rows = tuple(
        LoggedBanditRecord(
            reward=reward,
            behavior_propensity=0.5,
            target_action_probability=0.5 * weight,
            baseline_q=baseline_q,
            target_q=target_q,
            record_id=f"row-{index}",
        )
        for index, (weight, reward, baseline_q, target_q) in enumerate(raw)
    )

    estimate, beta, iterations, converged, objective, min_denom, gradient = (
        emp_ope_dev.empirical_likelihood_estimate(rows)
    )

    assert converged
    assert iterations < 50
    assert objective > 0.0
    assert min_denom > 0.0
    assert max(abs(gradient[0]), abs(gradient[1])) < 1e-8
    assert beta != pytest.approx((0.0, 0.0))
    assert min(row.reward for row in rows) <= estimate <= max(row.reward for row in rows)


def test_emp_reduces_to_ips_mean_when_all_controls_are_zero() -> None:
    rows = (
        LoggedBanditRecord(0.0, 0.5, 0.5, 0.0, 0.0, record_id="a"),
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.0, 0.0, record_id="b"),
        LoggedBanditRecord(1.0, 0.5, 0.5, 0.0, 0.0, record_id="c"),
    )

    estimate, beta, _, converged, _, min_denom, gradient = (
        emp_ope_dev.empirical_likelihood_estimate(rows)
    )

    assert converged
    assert beta == pytest.approx((0.0, 0.0))
    assert gradient == pytest.approx((0.0, 0.0))
    assert min_denom == pytest.approx(1.0)
    assert estimate == pytest.approx(2.0 / 3.0)


def test_existing_grid_comparison_keeps_all_current_candidates() -> None:
    rows = tuple(
        LoggedBanditRecord(
            reward=float(index % 2),
            behavior_propensity=0.5,
            target_action_probability=(0.25, 0.5, 0.75, 1.0)[index % 4],
            baseline_q=0.2,
            target_q=0.3,
            record_id=f"row-{index}",
        )
        for index in range(20)
    )

    summaries = emp_ope_dev.existing_candidate_summaries(rows, reference_value=0.5)

    assert set(summaries) == {
        "beta-cf5",
        "dr",
        "ips",
        "snips",
        "switch-5",
        "switch-10",
        "dros-1",
        "dros-10",
        "meta-blue",
    }
