from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from json import dumps
from math import isfinite
from typing import Any, Callable, Iterable, Mapping

from .real_world import KuaiRandInteraction, kuairand_reward


FeatureMap = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HistorySummary:
    """Information available before the current logged interaction."""

    count: int
    reward_sum: float
    click_sum: float
    long_view_sum: float

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.count if self.count else 0.0

    @property
    def click_rate(self) -> float:
        return self.click_sum / self.count if self.count else 0.0

    @property
    def long_view_rate(self) -> float:
        return self.long_view_sum / self.count if self.count else 0.0


StateBuilder = Callable[[KuaiRandInteraction, HistorySummary, FeatureMap], FeatureMap]
RewardFunction = Callable[[KuaiRandInteraction], float]
CandidateSetProvider = Callable[[KuaiRandInteraction, HistorySummary], Iterable[int]]


@dataclass(frozen=True, slots=True)
class OfflineRLTransition:
    """One leakage-aware transition for external offline-RL backends.

    ``trajectory_id`` identifies the real user episode. ``segment_id`` is only
    an export/windowing boundary for sequence models. A segment boundary is a
    truncation, not an environment termination, so Q-learning backends may
    bootstrap from ``next_state`` across it.

    Logging provenance and stable identifiers remain metadata rather than policy
    features. Candidate actions are present only when an experiment protocol
    supplies them; an empty tuple means the log does not identify the decision
    set and must not be interpreted as "the whole item catalog".
    """

    trajectory_id: str
    segment_id: str
    step_index: int
    segment_step_index: int
    state: FeatureMap
    action_id: int
    action_features: FeatureMap
    reward: float
    next_state: FeatureMap
    terminated: bool
    truncated: bool
    user_id: int
    timestamp_ms: int
    random_intervention: bool
    feedback: Mapping[str, float]
    candidate_action_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate_action_ids:
            if len(set(self.candidate_action_ids)) != len(self.candidate_action_ids):
                raise ValueError("candidate_action_ids must be unique")
            if self.action_id not in self.candidate_action_ids:
                raise ValueError("logged action must be present in candidate_action_ids")

    @property
    def done(self) -> bool:
        """Compatibility alias: only a true environment terminal is done."""

        return self.terminated

    @property
    def bootstrap_allowed(self) -> bool:
        return not self.terminated and bool(self.next_state)

    def to_record(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "segment_id": self.segment_id,
            "step_index": self.step_index,
            "segment_step_index": self.segment_step_index,
            "state": dict(self.state),
            "action_id": self.action_id,
            "action_features": dict(self.action_features),
            "candidate_action_ids": list(self.candidate_action_ids),
            "reward": self.reward,
            "next_state": dict(self.next_state),
            "terminated": self.terminated,
            "truncated": self.truncated,
            "done": self.done,
            "bootstrap_allowed": self.bootstrap_allowed,
            "user_id": self.user_id,
            "timestamp_ms": self.timestamp_ms,
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
    def segment_count(self) -> int:
        return len({row.segment_id for row in self.transitions})

    @property
    def action_count(self) -> int:
        return len({row.action_id for row in self.transitions})

    @property
    def random_intervention_rate(self) -> float:
        return sum(row.random_intervention for row in self.transitions) / len(self.transitions)

    @property
    def truncation_rate(self) -> float:
        return sum(row.truncated for row in self.transitions) / len(self.transitions)

    @property
    def candidate_set_coverage(self) -> float:
        return sum(bool(row.candidate_action_ids) for row in self.transitions) / len(self.transitions)

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


def default_kuairand_state_builder(
    row: KuaiRandInteraction,
    history: HistorySummary,
    user_features: FeatureMap,
) -> FeatureMap:
    """Build a default state using only information known before feedback.

    Stable user identifiers are deliberately excluded. Callers that want an ID
    embedding can add it explicitly in a custom ``state_builder`` instead of
    accidentally treating an arbitrary integer identifier as an ordinal feature.
    """

    state: dict[str, Any] = {
        "date": row.date,
        "hourmin": row.hourmin,
        "tab": row.tab,
        "history_count": history.count,
        "prior_mean_reward": history.mean_reward,
        "prior_click_rate": history.click_rate,
        "prior_long_view_rate": history.long_view_rate,
    }
    for key, value in user_features.items():
        state[f"user_feature:{key}"] = value
    return state


def _resolve_reward(
    row: KuaiRandInteraction,
    *,
    reward_function: RewardFunction | None,
    reward_weights: Mapping[str, float] | None,
) -> float:
    if (reward_function is None) == (reward_weights is None):
        raise ValueError("provide exactly one of reward_function or reward_weights")
    if reward_function is not None:
        reward = float(reward_function(row))
    else:
        assert reward_weights is not None
        reward = kuairand_reward(row, weights=reward_weights)
    if not isfinite(reward):
        raise ValueError("reward function must return a finite value")
    return reward


def _candidate_actions(
    row: KuaiRandInteraction,
    history: HistorySummary,
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


def kuairand_to_offline_rl(
    interactions: Iterable[KuaiRandInteraction],
    *,
    reward_function: RewardFunction | None = None,
    reward_weights: Mapping[str, float] | None = None,
    max_steps_per_segment: int = 100,
    user_feature_lookup: Mapping[int, FeatureMap] | None = None,
    action_feature_lookup: Mapping[int, FeatureMap] | None = None,
    state_builder: StateBuilder = default_kuairand_state_builder,
    candidate_provider: CandidateSetProvider | None = None,
) -> OfflineRLDataset:
    """Convert KuaiRand logs into backend-neutral offline-RL transitions.

    Reward scalarization is deliberately not chosen by the adapter. The research
    protocol must supply either an explicit reward function or explicit feedback
    weights. Likewise, candidate sets are exported only when a protocol-defined
    provider can reconstruct a defensible decision set. This prevents CQL/IQL/DT
    comparisons from silently using different negative-action universes.

    Artificial window boundaries do not zero the Bellman bootstrap target.
    """

    if max_steps_per_segment <= 0:
        raise ValueError("max_steps_per_segment must be positive")
    if (reward_function is None) == (reward_weights is None):
        raise ValueError("provide exactly one of reward_function or reward_weights")

    by_user: dict[int, list[KuaiRandInteraction]] = defaultdict(list)
    for row in interactions:
        by_user[row.user_id].append(row)
    if not by_user:
        raise ValueError("at least one KuaiRand interaction is required")

    user_lookup = user_feature_lookup or {}
    action_lookup = action_feature_lookup or {}
    transitions: list[OfflineRLTransition] = []

    for user_id in sorted(by_user):
        rows = sorted(by_user[user_id], key=lambda row: (row.time_ms, row.video_id))
        user_features = user_lookup.get(user_id, {})
        history = HistorySummary(count=0, reward_sum=0.0, click_sum=0.0, long_view_sum=0.0)
        trajectory_id = f"kuairand-user-{user_id}"

        for offset, row in enumerate(rows):
            segment_index = offset // max_steps_per_segment
            segment_step_index = offset % max_steps_per_segment
            segment_id = f"{trajectory_id}-segment-{segment_index}"
            state = dict(state_builder(row, history, user_features))
            candidates = _candidate_actions(row, history, candidate_provider)
            reward = _resolve_reward(
                row,
                reward_function=reward_function,
                reward_weights=reward_weights,
            )

            next_history = HistorySummary(
                count=history.count + 1,
                reward_sum=history.reward_sum + reward,
                click_sum=history.click_sum + row.is_click,
                long_view_sum=history.long_view_sum + row.long_view,
            )
            terminated = offset == len(rows) - 1
            truncated = not terminated and segment_step_index == max_steps_per_segment - 1

            if terminated:
                next_state: dict[str, Any] = {}
            else:
                next_row = rows[offset + 1]
                next_state = dict(state_builder(next_row, next_history, user_features))

            transitions.append(
                OfflineRLTransition(
                    trajectory_id=trajectory_id,
                    segment_id=segment_id,
                    step_index=offset,
                    segment_step_index=segment_step_index,
                    state=state,
                    action_id=row.video_id,
                    action_features=dict(action_lookup.get(row.video_id, {})),
                    candidate_action_ids=candidates,
                    reward=reward,
                    next_state=next_state,
                    terminated=terminated,
                    truncated=truncated,
                    user_id=user_id,
                    timestamp_ms=row.time_ms,
                    random_intervention=row.is_random,
                    feedback=_feedback(row),
                )
            )
            history = next_history

    return OfflineRLDataset(tuple(transitions))
