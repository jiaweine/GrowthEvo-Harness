from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import (
    evaluate_randomized_targeting,
    kuairand_to_planner_transitions,
    load_criteo_uplift,
    load_kuairand,
    load_open_bandit,
    open_bandit_to_ope,
)
from growthevo.models import Channel
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _criteo_header() -> str:
    return ",".join([*(f"f{i}" for i in range(12)), "treatment", "conversion", "visit", "exposure"])


def _criteo_row(offset: float, treatment: int, conversion: int, visit: int, exposure: int) -> str:
    features = [str(offset + index / 100.0) for index in range(12)]
    return ",".join([*features, str(treatment), str(conversion), str(visit), str(exposure)])


def test_criteo_loader_uses_random_assignment_not_post_treatment_exposure(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "criteo.csv",
        "\n".join(
            [
                _criteo_header(),
                _criteo_row(0.0, 1, 0, 1, 0),
                _criteo_row(1.0, 0, 0, 0, 0),
                _criteo_row(2.0, 1, 1, 1, 1),
                _criteo_row(3.0, 0, 0, 0, 0),
            ]
        ),
    )

    data = load_criteo_uplift(path, outcome="visit")

    assert data.treatment_propensity == pytest.approx(0.5)
    assert data.records[0].action is Channel.ADS
    assert data.records[0].outcome == pytest.approx(1.0)
    assert data.records[0].features == pytest.approx(tuple(i / 100.0 for i in range(12)))
    assert data.records[1].action is Channel.NO_TREATMENT


def test_criteo_randomized_targeting_evaluates_a_policy_not_response_prediction(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "criteo.csv",
        "\n".join(
            [
                _criteo_header(),
                _criteo_row(0.0, 1, 0, 1, 0),
                _criteo_row(1.0, 0, 0, 0, 0),
                _criteo_row(2.0, 1, 0, 1, 1),
                _criteo_row(3.0, 0, 0, 1, 0),
            ]
        ),
    )
    data = load_criteo_uplift(path, outcome="visit")

    result = evaluate_randomized_targeting(
        data.records,
        [4.0, 3.0, 2.0, 1.0],
        selected_fraction=0.5,
    )

    assert result.sample_size == 4
    assert result.selected_fraction == pytest.approx(0.5)
    assert result.policy_value == pytest.approx(0.5)
    assert result.treat_none_value == pytest.approx(0.5)
    assert result.treat_all_value == pytest.approx(1.0)


def test_open_bandit_loader_preserves_logged_propensity(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "bandit.csv",
        "\n".join(
            [
                "timestamp,item_id,position,click,propensity_score,user_feature_0,user-item_affinity_0",
                "2020-01-01 00:00:00,7,1,1,0.25,0.2,0.8",
                "2020-01-01 00:00:01,3,2,0,0.50,0.4,0.1",
            ]
        ),
    )

    rows = load_open_bandit(path)
    ope_rows = open_bandit_to_ope(
        rows,
        target_action_probability=lambda row: 0.5 if row.item_id == 7 else 0.25,
        baseline_q=lambda row: 0.1,
        target_q=lambda row: 0.2,
    )

    assert rows[0].propensity_score == pytest.approx(0.25)
    assert rows[0].context == pytest.approx((0.2, 0.8))
    assert ope_rows[0].behavior_propensity == pytest.approx(0.25)
    assert ope_rows[0].importance_weight == pytest.approx(2.0)


def test_kuairand_sequence_state_does_not_include_current_feedback(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "kuairand.csv",
        "\n".join(
            [
                "user_id,video_id,time_ms,date,hourmin,tab,is_rand,is_click,is_like,is_follow,is_comment,is_forward,is_hate,long_view,play_time_ms,duration_ms",
                "1,10,1000,20220422,900,1,0,1,0,0,0,0,0,1,8000,9000",
                "1,11,2000,20220422,901,1,1,0,1,0,0,0,0,0,2000,9000",
            ]
        ),
    )

    rows = load_kuairand(path)
    transitions = kuairand_to_planner_transitions(rows, max_steps_per_trajectory=10)

    assert transitions[0].observation["prior_click_rate"] == pytest.approx(0.0)
    assert transitions[0].observation["prior_long_view_rate"] == pytest.approx(0.0)
    assert transitions[1].observation["prior_click_rate"] == pytest.approx(1.0)
    assert transitions[1].observation["prior_long_view_rate"] == pytest.approx(1.0)
    assert transitions[1].observation["random_intervention"] is True
    assert transitions[0].reward > transitions[1].reward


def test_switch_and_shrinkage_limit_extreme_importance_residuals() -> None:
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
