from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import kuairand_to_offline_rl, load_kuairand


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


def test_offline_rl_state_excludes_logging_mechanism(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = kuairand_to_offline_rl(rows, max_steps_per_trajectory=10)

    first, second, third = dataset.transitions
    assert "random_intervention" not in first.state
    assert first.random_intervention is False
    assert second.random_intervention is True
    assert first.next_state["prior_click_rate"] == pytest.approx(1.0)
    assert second.state == first.next_state
    assert third.done is True
    assert third.next_state == {}
    assert dataset.trajectory_count == 1
    assert dataset.action_count == 3
    assert dataset.random_intervention_rate == pytest.approx(1.0 / 3.0)


def test_offline_rl_chunk_boundary_stops_bootstrap(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = kuairand_to_offline_rl(rows, max_steps_per_trajectory=2)

    assert dataset.transitions[1].done is True
    assert dataset.transitions[1].next_state == {}
    assert dataset.transitions[2].trajectory_id.endswith("chunk-1")
    assert dataset.transitions[2].step_index == 0


def test_offline_rl_export_keeps_multi_feedback_for_analysis(tmp_path: Path) -> None:
    rows = load_kuairand(_fixture(tmp_path))
    dataset = kuairand_to_offline_rl(rows)

    first = dataset.transitions[0]
    assert first.feedback["is_click"] == pytest.approx(1.0)
    assert first.feedback["long_view"] == pytest.approx(1.0)
    assert first.feedback["is_hate"] == pytest.approx(0.0)
    assert '"action_id": 10' in dataset.to_jsonl()
