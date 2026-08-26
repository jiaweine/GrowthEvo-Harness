from __future__ import annotations

import pytest

from growthevo.rl.process_reward import (
    GrowthProcessRewardModel,
    ProcessRewardWeights,
    ProcessState,
    TrajectoryStepSignal,
)


def test_successful_tool_without_progress_gets_no_default_success_bonus() -> None:
    state = ProcessState(goal_progress=0.4, evidence_quality=0.5, constraint_slack=0.5)
    reward = GrowthProcessRewardModel().score_step(
        TrajectoryStepSignal(
            step_id="uninformative-tool",
            before=state,
            after=state,
            action_entropy=0.2,
            tool_success=True,
        )
    )

    assert reward.tool_credit == pytest.approx(0.0)
    assert reward.observation_credit == pytest.approx(0.0)


def test_success_bonus_is_explicit_experiment_configuration() -> None:
    state = ProcessState(goal_progress=0.4, evidence_quality=0.5, constraint_slack=0.5)
    reward = GrowthProcessRewardModel(
        ProcessRewardWeights(successful_tool_bonus=0.25)
    ).score_step(
        TrajectoryStepSignal(
            step_id="configured-tool-bonus",
            before=state,
            after=state,
            action_entropy=0.2,
            tool_success=True,
        )
    )

    assert reward.tool_credit == pytest.approx(0.25)


def test_failed_tool_remains_penalized() -> None:
    state = ProcessState(goal_progress=0.4, evidence_quality=0.5, constraint_slack=0.5)
    reward = GrowthProcessRewardModel().score_step(
        TrajectoryStepSignal(
            step_id="failed-tool",
            before=state,
            after=state,
            action_entropy=0.2,
            tool_success=False,
        )
    )

    assert reward.tool_credit < 0.0
