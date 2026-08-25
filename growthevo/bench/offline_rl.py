from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from json import dumps
from typing import Any, Iterable, Mapping

from .real_world import (
    DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    KuaiRandInteraction,
    kuairand_reward,
)


FeatureMap = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class OfflineRLTransition:
    """One transition for external offline-RL backends.

    ``random_intervention`` records how the logged action was generated. It is
    metadata, not part of the policy state: a learned policy should not obtain a
    feature that only exists because of the historical logging mechanism.

    ``action_id`` preserves the exact logged item. ``action_features`` can carry
    item metadata or a precomputed embedding so large-action methods do not have
    to model millions of video identifiers as an unstructured discrete action
    space.
    """

    trajectory_id: str
    step_index: int
    state: FeatureMap
    action_id: int
    action_features: FeatureMap
    reward: float
    next_state: FeatureMap
    done: bool
    random_intervention: bool
    feedback: Mapping[str, float]

    def to_record(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "step_index": self.step_index,
            "state": dict(self.state),
            "action_id": self.action_id,
            "action_features": dict(self.action_features),
            "reward": self.reward,
            "next_state": dict(self.next_state),
            "done": self.done,
            "random_intervention": self.random_intervention,
            "feedback": dict(self.feedback),
        }


@dataclass(frozen=True, slots=True)
class OfflineRLDataset:
    transitions: tuple[OfflineRLTransition, ...]

    def __post_init__(self) -> None:
        if not self.transitions:
            raise ValueError("offline RL dataset cannot be empty")

    @property
    def trajectory_count(self) -> int:
        return len({row.trajectory_id for row in self.transitions})

    @property
    def action_count(self) -> int:
        return len({row.action_id for row in self.transitions})

    @property
    def random_intervention_rate(self) -> float:
        return sum(row.random_intervention for row in self.transitions) / len(self.transitions)

    def to_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(row.to_record() for row in self.transitions)

    def to_jsonl(self) -> str:
        return "\n".join(dumps(row, sort_keys=True) for row in self.to_records())


def _feedback(row: KuaiRandInteraction) -> dict[str, float]:
    return {
        "is_click": row.is_click,
        "long_view": row.long_view,
        "is_like": row.is_like,
        "is_follow": row.is_follow,
        "is_comment": row.is_comment,
        "is_forward": row.is_forward,
        "is_hate": row.is_hate,
    }


def _history_state(
    row: KuaiRandInteraction,
    *,
    history_count: int,
    prior_reward_sum: float,
    prior_click_sum: float,
    prior_long_view_sum: float,
    user_features: FeatureMap | None = None,
) -> dict[str, Any]:
    """Build a state from information available before current feedback."""

    state: dict[str, Any] = {
        "user_id": row.user_id,
        "date": row.date,
        "hourmin": row.hourmin,
        "tab": row.tab,
        "history_count": history_count,
        "prior_mean_reward": prior_reward_sum / history_count if history_count else 0.0,
        "prior_click_rate": prior_click_sum / history_count if history_count else 0.0,
        "prior_long_view_rate": prior_long_view_sum / history_count if history_count else 0.0,
    }
    if user_features:
        for key, value in user_features.items():
            state[f"user_feature:{key}"] = value
    return state


def kuairand_to_offline_rl(
    interactions: Iterable[KuaiRandInteraction],
    *,
    max_steps_per_trajectory: int = 100,
    reward_weights: Mapping[str, float] = DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    user_feature_lookup: Mapping[int, FeatureMap] | None = None,
    action_feature_lookup: Mapping[int, FeatureMap] | None = None,
) -> OfflineRLDataset:
    """Convert KuaiRand logs into leakage-aware offline-RL transitions.

    The output maps to the common transition interface used by conservative
    Q-learning and implicit Q-learning while also retaining trajectories for
    sequence-modeling baselines. Optional user and item features make the export
    suitable for representation-based policies instead of forcing the enormous
    catalog into a flat discrete-action head.

    Artificial chunk boundaries are terminal for bootstrapping, so
    ``next_state`` is empty at those boundaries.
    """

    if max_steps_per_trajectory <= 0:
        raise ValueError("max_steps_per_trajectory must be positive")

    by_user: dict[int, list[KuaiRandInteraction]] = defaultdict(list)
    for row in interactions:
        by_user[row.user_id].append(row)
    if not by_user:
        raise ValueError("at least one KuaiRand interaction is required")

    transitions: list[OfflineRLTransition] = []
    for user_id in sorted(by_user):
        rows = sorted(by_user[user_id], key=lambda row: (row.time_ms, row.video_id))
        user_features = (user_feature_lookup or {}).get(user_id, {})
        prior_reward_sum = 0.0
        prior_click_sum = 0.0
        prior_long_view_sum = 0.0

        for offset, row in enumerate(rows):
            chunk = offset // max_steps_per_trajectory
            step_index = offset % max_steps_per_trajectory
            history_count = offset
            state = _history_state(
                row,
                history_count=history_count,
                prior_reward_sum=prior_reward_sum,
                prior_click_sum=prior_click_sum,
                prior_long_view_sum=prior_long_view_sum,
                user_features=user_features,
            )
            reward = kuairand_reward(row, weights=reward_weights)

            updated_reward_sum = prior_reward_sum + reward
            updated_click_sum = prior_click_sum + row.is_click
            updated_long_view_sum = prior_long_view_sum + row.long_view
            is_user_terminal = offset == len(rows) - 1
            is_chunk_terminal = step_index == max_steps_per_trajectory - 1
            done = is_user_terminal or is_chunk_terminal

            if done:
                next_state: dict[str, Any] = {}
            else:
                next_row = rows[offset + 1]
                next_state = _history_state(
                    next_row,
                    history_count=history_count + 1,
                    prior_reward_sum=updated_reward_sum,
                    prior_click_sum=updated_click_sum,
                    prior_long_view_sum=updated_long_view_sum,
                    user_features=user_features,
                )

            transitions.append(
                OfflineRLTransition(
                    trajectory_id=f"kuairand-user-{user_id}-chunk-{chunk}",
                    step_index=step_index,
                    state=state,
                    action_id=row.video_id,
                    action_features=dict((action_feature_lookup or {}).get(row.video_id, {})),
                    reward=reward,
                    next_state=next_state,
                    done=done,
                    random_intervention=row.is_random,
                    feedback=_feedback(row),
                )
            )

            prior_reward_sum = updated_reward_sum
            prior_click_sum = updated_click_sum
            prior_long_view_sum = updated_long_view_sum

    return OfflineRLDataset(tuple(transitions))
