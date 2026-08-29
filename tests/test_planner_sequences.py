from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import (
    kuairand_to_planner_records,
    kuairand_to_planner_transitions,
    load_kuairand,
)
from growthevo.training.trajectory import TrajectoryTrainerAdapter


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "kuairand.csv"
    path.write_text(
        "\n".join(
            [
                "user_id,video_id,time_ms,date,hourmin,tab,is_rand,is_click,is_like,is_follow,is_comment,is_forward,is_hate,long_view,play_time_ms,duration_ms",
                "1,10,1000,20220422,900,1,0,0,0,0,0,0,0,0,1000,9000",
                "1,11,2000,20220422,901,1,1,0,0,0,0,0,0,0,2000,9000",
                "1,12,3000,20220422,902,1,0,1,0,0,0,0,0,1,8000,9000",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _records(tmp_path: Path, **kwargs):
    return kuairand_to_planner_records(
        load_kuairand(_fixture(tmp_path)),
        reward_weights={"is_click": 1.0},
        **kwargs,
    )


def test_planner_state_is_pre_feedback_and_provenance_stays_out_of_observation(tmp_path: Path) -> None:
    first, second, third = _records(tmp_path)

    assert first.transition.observation["prior_click_rate"] == pytest.approx(0.0)
    assert second.transition.observation["prior_click_rate"] == pytest.approx(0.0)
    assert third.transition.observation["prior_click_rate"] == pytest.approx(0.0)
    assert "user_id" not in first.transition.observation
    assert "random_intervention" not in second.transition.observation
    assert second.user_id == 1
    assert second.random_intervention is True
    assert third.transition.done is True


def test_export_window_does_not_change_trainer_credit_semantics(tmp_path: Path) -> None:
    records = _records(tmp_path, max_steps_per_segment=2)

    assert records[1].truncated is True
    assert records[1].segment_id != records[2].segment_id
    assert records[1].transition.trajectory_id == records[2].transition.trajectory_id
    assert [row.transition.step_index for row in records] == [0, 1, 2]
    assert records[1].transition.credit_boundary is False

    batch = TrajectoryTrainerAdapter(
        gamma=1.0,
        gae_lambda=1.0,
        normalize_advantages=False,
    ).build(row.transition for row in records)

    assert [sample.raw_advantage for sample in batch.samples] == pytest.approx([1.0, 1.0, 1.0])


def test_explicit_dynamics_boundary_stops_gae_credit(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        max_steps_per_segment=2,
        credit_boundary_predicate=lambda row, next_row, history: row.video_id == 11,
    )

    assert records[1].truncated is True
    assert records[1].transition.credit_boundary is True

    batch = TrajectoryTrainerAdapter(
        gamma=1.0,
        gae_lambda=1.0,
        normalize_advantages=False,
    ).build(row.transition for row in records)

    assert [sample.raw_advantage for sample in batch.samples] == pytest.approx([0.0, 0.0, 1.0])


def test_candidate_set_is_protocol_defined_and_kept_out_of_observation(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        candidate_provider=lambda row, history: (row.video_id, 100 + history.count),
    )

    assert records[0].candidate_action_ids == (10, 100)
    assert "candidate_action_ids" not in records[0].transition.observation
    assert records[1].to_record()["candidate_action_ids"] == [11, 101]

    with pytest.raises(ValueError, match="contain the logged action"):
        _records(tmp_path, candidate_provider=lambda row, history: (999,))


def test_transition_convenience_api_matches_record_transitions(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    transitions = kuairand_to_planner_transitions(
        rows,
        reward_weights={"is_click": 1.0},
    )

    assert [row.action for row in transitions] == [
        "recommend_video:10",
        "recommend_video:11",
        "recommend_video:12",
    ]
    assert [row.step_index for row in transitions] == [0, 1, 2]
