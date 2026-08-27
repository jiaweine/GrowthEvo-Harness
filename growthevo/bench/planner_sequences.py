from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Iterable, Mapping

from growthevo.training.trajectory import PlannerTransition

from .real_world import KuaiRandInteraction, kuairand_reward


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
RewardFunction = Callable[[KuaiRandInteraction], float]
CandidateSetProvider = Callable[[KuaiRandInteraction, KuaiRandHistory], Iterable[int]]


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


def _resolve_reward(
    row: KuaiRandInteraction,
    *,
    reward_function: RewardFunction | None,
    reward_weights: Mapping[str, float] | None,
) -> float:
    if (reward_function is None) == (reward_weights is None):
        raise ValueError("provide exactly one of reward_function or reward_weights")
    reward = (
        float(reward_function(row))
        if reward_function is not None
        else kuairand_reward(row, weights=reward_weights or {})
    )
    if not isfinite(reward):
        raise ValueError("reward function must return a finite value")
    return reward


def _candidate_actions(
    row: KuaiRandInteraction,
    history: KuaiRandHistory,
    provider: CandidateSetProvider | None,
) -> tuple[int, ...]:
    if provider is None:
        return ()
    candidates = tuple(int(action_id) for action_id in provider(row, history))
    if not candidates:
        raise ValueError("candidate provider returned an empty decision set")
    if len(set(candidates)) != len(candidates):
        raise ValueError("candidate provider returned duplicate action ids")
    if row.video_id not in candidates:
        raise ValueError("candidate set must contain the logged action")
    return candidates


def kuairand_to_planner_transitions(
    interactions: Iterable[KuaiRandInteraction],
    *,
    reward_function: RewardFunction | None = None,
    reward_weights: Mapping[str, float] | None = None,
    max_steps_per_trajectory: int | None = None,
    observation_builder: PlannerObservationBuilder = default_planner_observation,
    candidate_provider: CandidateSetProvider | None = None,
) -> tuple[PlannerTransition, ...]:
    """Create leakage-aware planner trajectories from KuaiRand logs.

    Full user trajectories are preserved by default. Artificial windows are
    truncations/credit boundaries, not terminals. Reward scalarization and the
    candidate action universe are protocol inputs rather than dataset-adapter
    defaults, so planner/DT experiments cannot silently optimize a different
    objective or action set from CQL/IQL experiments.
    """

    if max_steps_per_trajectory is not None and max_steps_per_trajectory <= 0:
        raise ValueError("max_steps_per_trajectory must be positive when provided")
    if (reward_function is None) == (reward_weights is None):
        raise ValueError("provide exactly one of reward_function or reward_weights")

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

            reward = _resolve_reward(
                row,
                reward_function=reward_function,
                reward_weights=reward_weights,
            )
            candidates = _candidate_actions(row, history, candidate_provider)
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
                        "candidate_action_ids": list(candidates),
                    },
                )
            )
            history = history.advance(row, reward)

    return tuple(transitions)
