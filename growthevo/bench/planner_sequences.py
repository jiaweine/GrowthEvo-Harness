from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Iterable, Mapping

from growthevo.training.trajectory import PlannerTransition

from .real_world import KuaiRandInteraction, kuairand_reward


@dataclass(frozen=True, slots=True)
class KuaiRandHistory:
    """Pre-decision history available before the current logged interaction."""

    count: int = 0
    reward_sum: float = 0.0
    click_sum: float = 0.0
    long_view_sum: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.count if self.count else 0.0

    @property
    def click_rate(self) -> float:
        return self.click_sum / self.count if self.count else 0.0

    @property
    def long_view_rate(self) -> float:
        return self.long_view_sum / self.count if self.count else 0.0

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
CreditBoundaryPredicate = Callable[
    [KuaiRandInteraction, KuaiRandInteraction | None, KuaiRandHistory],
    bool,
]


@dataclass(frozen=True, slots=True)
class KuaiRandPlannerRecord:
    """Planner transition plus dataset/export provenance.

    Window metadata is deliberately separate from ``PlannerTransition``. A
    sequence-model export window is not automatically a dynamics boundary and
    therefore must not silently change GAE/bootstrap targets. Only an explicit
    ``credit_boundary_predicate`` may set ``transition.credit_boundary``.
    """

    transition: PlannerTransition
    segment_id: str
    segment_step_index: int
    truncated: bool
    user_id: int
    video_id: int
    random_intervention: bool
    candidate_action_ids: tuple[int, ...] = ()

    def to_record(self) -> dict[str, Any]:
        row = self.transition
        return {
            "trajectory_id": row.trajectory_id,
            "segment_id": self.segment_id,
            "step_index": row.step_index,
            "segment_step_index": self.segment_step_index,
            "action": row.action,
            "observation": dict(row.observation),
            "reward": row.reward,
            "value_estimate": row.value_estimate,
            "next_value_estimate": row.next_value_estimate,
            "done": row.done,
            "credit_boundary": row.credit_boundary,
            "legal_action": row.legal_action,
            "tool_success": row.tool_success,
            "truncated": self.truncated,
            "user_id": self.user_id,
            "video_id": self.video_id,
            "random_intervention": self.random_intervention,
            "candidate_action_ids": list(self.candidate_action_ids),
        }


def default_planner_observation(
    row: KuaiRandInteraction,
    history: KuaiRandHistory,
) -> Mapping[str, Any]:
    """Build a leakage-aware state from information known before feedback."""

    return {
        "date": row.date,
        "hourmin": row.hourmin,
        "tab": row.tab,
        "history_count": history.count,
        "prior_mean_reward": history.mean_reward,
        "prior_click_rate": history.click_rate,
        "prior_long_view_rate": history.long_view_rate,
    }


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


def kuairand_to_planner_records(
    interactions: Iterable[KuaiRandInteraction],
    *,
    reward_function: RewardFunction | None = None,
    reward_weights: Mapping[str, float] | None = None,
    max_steps_per_segment: int | None = None,
    observation_builder: PlannerObservationBuilder = default_planner_observation,
    candidate_provider: CandidateSetProvider | None = None,
    credit_boundary_predicate: CreditBoundaryPredicate | None = None,
) -> tuple[KuaiRandPlannerRecord, ...]:
    """Create current-main-compatible planner records from KuaiRand logs.

    A real user remains one planner trajectory with a globally increasing
    ``step_index``. Optional segments exist only for external sequence-model
    export and set ``truncated`` metadata; they do not reset trajectory identity
    and do not imply ``credit_boundary``. This avoids both duplicate step indices
    in ``TrajectoryTrainerAdapter`` and accidental loss of bootstrap/GAE credit.

    A protocol that knows a genuine dynamics discontinuity can supply
    ``credit_boundary_predicate``. It observes the current row, next row (or
    ``None`` at terminal), and post-feedback history and may explicitly stop
    local credit propagation after the current transition.
    """

    if max_steps_per_segment is not None and max_steps_per_segment <= 0:
        raise ValueError("max_steps_per_segment must be positive when provided")
    if (reward_function is None) == (reward_weights is None):
        raise ValueError("provide exactly one of reward_function or reward_weights")

    by_user: dict[int, list[KuaiRandInteraction]] = defaultdict(list)
    for row in interactions:
        by_user[row.user_id].append(row)
    if not by_user:
        raise ValueError("at least one KuaiRand interaction is required")

    result: list[KuaiRandPlannerRecord] = []
    for user_id in sorted(by_user):
        rows = sorted(by_user[user_id], key=lambda row: (row.time_ms, row.video_id))
        history = KuaiRandHistory()
        trajectory_id = f"kuairand-user-{user_id}"

        for offset, row in enumerate(rows):
            reward = _resolve_reward(
                row,
                reward_function=reward_function,
                reward_weights=reward_weights,
            )
            candidates = _candidate_actions(row, history, candidate_provider)
            observation = dict(observation_builder(row, history))
            next_history = history.advance(row, reward)
            next_row = rows[offset + 1] if offset + 1 < len(rows) else None
            done = next_row is None

            if max_steps_per_segment is None:
                segment_index = 0
                segment_step_index = offset
                truncated = False
            else:
                segment_index = offset // max_steps_per_segment
                segment_step_index = offset % max_steps_per_segment
                truncated = (
                    not done
                    and segment_step_index == max_steps_per_segment - 1
                )
            segment_id = f"{trajectory_id}-segment-{segment_index}"

            credit_boundary = False
            if not done and credit_boundary_predicate is not None:
                credit_boundary = bool(
                    credit_boundary_predicate(row, next_row, next_history)
                )

            transition = PlannerTransition(
                trajectory_id=trajectory_id,
                step_index=offset,
                action=f"recommend_video:{row.video_id}",
                observation=observation,
                reward=reward,
                done=done,
                credit_boundary=credit_boundary,
                legal_action=True,
                tool_success=True,
            )
            result.append(
                KuaiRandPlannerRecord(
                    transition=transition,
                    segment_id=segment_id,
                    segment_step_index=segment_step_index,
                    truncated=truncated,
                    user_id=user_id,
                    video_id=row.video_id,
                    random_intervention=row.is_random,
                    candidate_action_ids=candidates,
                )
            )
            history = next_history

    return tuple(result)


def kuairand_to_planner_transitions(
    interactions: Iterable[KuaiRandInteraction],
    **kwargs: Any,
) -> tuple[PlannerTransition, ...]:
    """Return only trainer-facing transitions; provenance stays out-of-band."""

    return tuple(
        record.transition
        for record in kuairand_to_planner_records(interactions, **kwargs)
    )
