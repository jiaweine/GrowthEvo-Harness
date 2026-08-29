from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import (
    DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    kuairand_to_offline_rl,
    load_kuairand,
)


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "kuairand.csv"
    path.write_text(
        "\n".join(
            [
                "user_id,video_id,time_ms,date,hourmin,tab,is_rand,is_click,is_like,is_follow,is_comment,is_forward,is_hate,long_view,play_time_ms,duration_ms",
                "1,10,1000,20220422,900,1,0,1,0,0,0,0,0,1,8000,9000",
                "1,11,2000,20220422,901,1,1,0,1,0,0,0,0,0,2000,9000",
                "1,12,3000,20220422,902,1,0,1,0,0,0,0,0,0,5000,9000",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _dataset(rows, **kwargs):
    return kuairand_to_offline_rl(
        rows,
        reward_weights=DEFAULT_KUAIRAND_REWARD_WEIGHTS,
        **kwargs,
    )


def test_offline_rl_requires_explicit_reward_definition(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))

    with pytest.raises(ValueError, match="exactly one"):
        kuairand_to_offline_rl(rows)


def test_offline_rl_state_excludes_logging_mechanism_and_raw_identifier(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = _dataset(rows, max_steps_per_segment=10)

    first, second, third = dataset.transitions
    assert "random_intervention" not in first.state
    assert "user_id" not in first.state
    assert first.user_id == 1
    assert first.random_intervention is False
    assert second.random_intervention is True
    assert first.next_state["prior_click_rate"] == pytest.approx(1.0)
    assert second.state == first.next_state
    assert third.terminated is True
    assert third.done is True
    assert third.next_state == {}
    assert dataset.trajectory_count == 1
    assert dataset.segment_count == 1
    assert dataset.action_count == 3
    assert dataset.random_intervention_rate == pytest.approx(1.0 / 3.0)


def test_offline_rl_segment_boundary_bootstraps_instead_of_faking_terminal(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = _dataset(rows, max_steps_per_segment=2)

    boundary = dataset.transitions[1]
    next_segment = dataset.transitions[2]

    assert boundary.truncated is True
    assert boundary.terminated is False
    assert boundary.done is False
    assert boundary.bootstrap_allowed is True
    assert boundary.next_state == next_segment.state
    assert boundary.trajectory_id == next_segment.trajectory_id
    assert boundary.segment_id != next_segment.segment_id
    assert next_segment.step_index == 2
    assert next_segment.segment_step_index == 0
    assert dataset.trajectory_count == 1
    assert dataset.segment_count == 2
    assert dataset.truncation_rate == pytest.approx(1.0 / 3.0)


def test_offline_rl_export_keeps_multi_feedback_for_analysis(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = _dataset(rows)

    first = dataset.transitions[0]
    assert first.feedback["is_click"] == pytest.approx(1.0)
    assert first.feedback["long_view"] == pytest.approx(1.0)
    assert first.feedback["is_hate"] == pytest.approx(0.0)
    payload = dataset.to_jsonl()
    assert '"action_id": 10' in payload
    assert '"terminated": false' in payload
    assert '"bootstrap_allowed": true' in payload
    assert '"candidate_action_ids": []' in payload


def test_offline_rl_export_accepts_representation_features(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = _dataset(
        rows,
        user_feature_lookup={1: {"activity": "high", "followers": 12}},
        action_feature_lookup={
            10: {"duration_ms": 9000.0, "category": "games"},
            11: {"duration_ms": 9000.0, "category": "music"},
        },
    )

    first, second, _ = dataset.transitions
    assert first.state["user_feature:activity"] == "high"
    assert first.state["user_feature:followers"] == 12
    assert first.action_features["category"] == "games"
    assert second.action_features["category"] == "music"


def test_offline_rl_state_builder_is_injectable(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))

    def build_state(row, history, user_features):
        return {
            "tab": row.tab,
            "history": history.count,
            "profile": user_features.get("profile", "unknown"),
        }

    dataset = _dataset(
        rows,
        user_feature_lookup={1: {"profile": "frequent"}},
        state_builder=build_state,
    )

    assert dataset.transitions[0].state == {
        "tab": 1,
        "history": 0,
        "profile": "frequent",
    }
    assert dataset.transitions[1].state["history"] == 1


def test_offline_rl_candidate_set_is_protocol_defined_and_contains_logged_action(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = _dataset(
        rows,
        candidate_provider=lambda row, history: (row.video_id, 100 + history.count),
    )

    assert dataset.transitions[0].candidate_action_ids == (10, 100)
    assert dataset.transitions[1].candidate_action_ids == (11, 101)
    assert dataset.candidate_set_coverage == pytest.approx(1.0)


def test_offline_rl_rejects_candidate_set_missing_logged_action(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))

    with pytest.raises(ValueError, match="contain the logged action"):
        _dataset(rows, candidate_provider=lambda row, history: (999,))
