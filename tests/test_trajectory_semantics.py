from __future__ import annotations

import pytest

from growthevo.training.trajectory import PlannerTransition, TrajectoryTrainerAdapter


def test_credit_boundary_stops_trace_but_keeps_next_state_value_bootstrap() -> None:
    batch = TrajectoryTrainerAdapter(
        gamma=0.9,
        gae_lambda=1.0,
        normalize_advantages=False,
    ).build(
        [
            PlannerTransition(
                trajectory_id="trajectory",
                step_index=0,
                action="inspect",
                observation={},
                reward=0.0,
                value_estimate=0.2,
                next_value_estimate=0.5,
                credit_boundary=True,
            ),
            PlannerTransition(
                trajectory_id="trajectory",
                step_index=1,
                action="act",
                observation={},
                reward=1.0,
                value_estimate=0.5,
                next_value_estimate=0.0,
                done=True,
            ),
        ]
    )

    first, second = batch.samples
    assert first.raw_advantage == pytest.approx(0.9 * 0.5 - 0.2)
    assert first.return_target == pytest.approx(0.9 * 0.5)
    assert second.raw_advantage == pytest.approx(0.5)


def test_true_terminal_disables_value_bootstrap() -> None:
    batch = TrajectoryTrainerAdapter(
        gamma=0.9,
        gae_lambda=1.0,
        normalize_advantages=False,
    ).build(
        [
            PlannerTransition(
                trajectory_id="terminal",
                step_index=0,
                action="finish",
                observation={},
                reward=1.0,
                value_estimate=0.3,
                next_value_estimate=100.0,
                done=True,
            )
        ]
    )

    sample = batch.samples[0]
    assert sample.raw_advantage == pytest.approx(0.7)
    assert sample.return_target == pytest.approx(1.0)


def test_non_contiguous_steps_fail_closed_by_default() -> None:
    transitions = [
        PlannerTransition(
            trajectory_id="gap",
            step_index=0,
            action="first",
            observation={},
            reward=0.0,
        ),
        PlannerTransition(
            trajectory_id="gap",
            step_index=2,
            action="third",
            observation={},
            reward=1.0,
            done=True,
        ),
    ]

    with pytest.raises(ValueError, match="non-contiguous"):
        TrajectoryTrainerAdapter().build(transitions)

    batch = TrajectoryTrainerAdapter(
        normalize_advantages=False,
        require_contiguous_steps=False,
    ).build(transitions)
    assert len(batch.samples) == 2
