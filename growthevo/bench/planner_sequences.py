from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from growthevo.training.trajectory import PlannerTransition

from .real_world import (
    DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    KuaiRandInteraction,
    kuairand_reward,
)


@dataclass(frozen=True, slots=True)
class KuaiRandHistory:
    count: int = 0
    reward_sum: float = 0.0
    click_sum: float = 0.0
    long_view_sum: float = 0.0

    def advance(self, row: KuaiRandInteraction, reward: float) -> "KuaiRandHistory":
        return KuaiRandHistory(
            count=self.count + 1,
            reward_sum=self.reward_sum + reward,
            click_sum=self.click_sum + row.is_click,
            long_view_sum=self.long_view_sum + row.long_view,
        )


PlannerObservationBuilder = Callable[[KuaiRandInteraction, KuaiRandHistory], Mapping[str, Any]]


def default_planner_observation(
    row: KuaiRandInteraction,
    history: KuaiRandHistory,
) -> Mapping[str, Any]:
    """Build a pre-feedback state without logging-policy provenance or raw IDs."""

    count = history.count
    return {
        "date": row.date,
        "hourmin": row.hourmin,
        "tab": row.tab,
        "history_count": count,
        "prior_mean_reward": history.reward_sum / count if count else 0.0,
        "prior_click_rate": history.click_sum / count if count else 0.0,
        "prior_long_view_rate": history.long_view_sum / count if count else 0.0,
    }


def kuairand_to_planner_transitions(
    interactions: Iterable[KuaiRandInteraction],
    *,
    max_steps_per_trajectory: int | None = None,
    reward_weights: Mapping[str, float] = DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    observation_builder: PlannerObservationBuilder = default_planner_observation,
) -> tuple[PlannerTransition, ...]:
    """Create leakage-aware planner trajectories from KuaiRand logs.

    Full user trajectories are preserved by default. When an explicit maximum
    sequence length is supplied, artificial window endings are marked
    ``truncated=True`` and ``credit_boundary=True`` rather than ``done=True``.
    The raw user id and random-intervention indicator remain in metadata, not the
    policy observation.

    The observation builder is injected so research backends can use learned or
    richer state representations without editing dataset-specific control flow.
    """

    if max_steps_per_trajectory is not None and max_steps_per_trajectory <= 0:
        raise ValueError("max_steps_per_trajectory must be positive when provided")

    by_user: dict[int, list[KuaiRandInteraction]] = defaultdict(list)
    for row in interactions:
        by_user[row.user_id].append(row)
    if not by_user:
        raise ValueError("at least one KuaiRand interaction is required")

    transitions: list[PlannerTransition] = []
    for user_id in sorted(by_user):
        rows = sorted(by_user[user_id], key=lambda row: (row.time_ms, row.video_id))
        history = KuaiRandHistory()

        for offset, row in enumerate(rows):
            if max_steps_per_trajectory is None:
                chunk = 0
                step_index = offset
                chunk_terminal = False
                trajectory_id = f"kuairand-user-{user_id}"
            else:
                chunk = offset // max_steps_per_trajectory
                step_index = offset % max_steps_per_trajectory
                chunk_terminal = step_index == max_steps_per_trajectory - 1
                trajectory_id = f"kuairand-user-{user_id}-chunk-{chunk}"

            reward = kuairand_reward(row, weights=reward_weights)
            true_terminal = offset == len(rows) - 1
            truncated = bool(chunk_terminal and not true_terminal)
            observation = dict(observation_builder(row, history))

            transitions.append(
                PlannerTransition(
                    trajectory_id=trajectory_id,
                    step_index=step_index,
                    action=f"recommend_video:{row.video_id}",
                    observation=observation,
                    reward=reward,
                    done=true_terminal,
                    truncated=truncated,
                    credit_boundary=truncated,
                    legal_action=True,
                    tool_success=True,
                    metadata={
                        "user_id": user_id,
                        "random_intervention": row.is_random,
                        "video_id": row.video_id,
                    },
                )
            )
            history = history.advance(row, reward)

    return tuple(transitions)
