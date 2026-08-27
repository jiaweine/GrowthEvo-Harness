from __future__ import annotations

from dataclasses import dataclass, field
from json import dumps
from math import fsum, sqrt
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PlannerTransition:
    """One planner/tool transition prepared for external Agent-RL trainers.

    ``done`` means a true environment terminal. ``truncated`` means the exported
    sequence ended for a bookkeeping reason such as a maximum window length while
    the underlying process can continue. ``credit_boundary`` stops multi-step
    advantage propagation across an attribution/dynamics boundary without
    erasing the critic value of an observed next state.

    ``metadata`` carries provenance that should remain auditable but must not be
    silently exposed as policy observation features, for example a historical
    logging-mechanism indicator or raw user identifier.
    """

    trajectory_id: str
    step_index: int
    action: str
    observation: Mapping[str, Any]
    reward: float
    value_estimate: float = 0.0
    next_value_estimate: float = 0.0
    done: bool = False
    truncated: bool = False
    credit_boundary: bool = False
    legal_action: bool = True
    tool_success: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trajectory_id:
            raise ValueError("trajectory_id cannot be empty")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if not self.action:
            raise ValueError("action cannot be empty")


@dataclass(frozen=True, slots=True)
class PlannerTrainingSample:
    trajectory_id: str
    step_index: int
    action: str
    observation: Mapping[str, Any]
    reward: float
    raw_advantage: float
    advantage: float
    return_target: float
    done: bool
    truncated: bool
    legal_action: bool
    tool_success: bool
    credit_boundary: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PlannerTrainingBatch:
    samples: tuple[PlannerTrainingSample, ...]
    advantage_mean: float
    advantage_std: float
    gamma: float
    gae_lambda: float

    def to_records(self) -> tuple[dict[str, Any], ...]:
        """Return backend-neutral dictionaries suitable for trainer adapters."""

        return tuple(
            {
                "trajectory_id": sample.trajectory_id,
                "step_index": sample.step_index,
                "action": sample.action,
                "observation": dict(sample.observation),
                "reward": sample.reward,
                "raw_advantage": sample.raw_advantage,
                "advantage": sample.advantage,
                "return_target": sample.return_target,
                "done": sample.done,
                "truncated": sample.truncated,
                "legal_action": sample.legal_action,
                "tool_success": sample.tool_success,
                "credit_boundary": sample.credit_boundary,
                "metadata": dict(sample.metadata),
            }
            for sample in self.samples
        )

    def to_jsonl(self) -> str:
        return "\n".join(dumps(record, sort_keys=True) for record in self.to_records())


class TrajectoryTrainerAdapter:
    """Compile event-derived planner transitions into GAE training samples.

    A true terminal controls value bootstrapping. A credit boundary or artificial
    truncation controls eligibility-trace propagation. Truncation therefore keeps
    the next-state value bootstrap but does not propagate later rewards through a
    sequence boundary. This follows the standard distinction between termination
    and time-limit/data-window truncation.
    """

    def __init__(
        self,
        *,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        normalize_advantages: bool = True,
        require_contiguous_steps: bool = True,
    ) -> None:
        if not 0 < gamma <= 1:
            raise ValueError("gamma must be in (0, 1]")
        if not 0 <= gae_lambda <= 1:
            raise ValueError("gae_lambda must be in [0, 1]")
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.normalize_advantages = normalize_advantages
        self.require_contiguous_steps = require_contiguous_steps

    def build(self, transitions: Iterable[PlannerTransition]) -> PlannerTrainingBatch:
        rows = list(transitions)
        if not rows:
            raise ValueError("at least one planner transition is required")

        by_trajectory: dict[str, list[PlannerTransition]] = {}
        for row in rows:
            by_trajectory.setdefault(row.trajectory_id, []).append(row)

        raw_samples: list[tuple[PlannerTransition, float, float]] = []
        for trajectory_id in sorted(by_trajectory):
            trajectory = sorted(by_trajectory[trajectory_id], key=lambda row: row.step_index)
            indices = [row.step_index for row in trajectory]
            if len(indices) != len(set(indices)):
                raise ValueError(f"duplicate step_index in trajectory {trajectory_id!r}")
            if self.require_contiguous_steps and indices:
                expected = list(range(indices[0], indices[0] + len(indices)))
                if indices != expected:
                    raise ValueError(
                        f"non-contiguous step_index in trajectory {trajectory_id!r}; "
                        "split the trajectory or disable contiguous-step validation explicitly"
                    )

            next_advantage = 0.0
            reverse: list[tuple[PlannerTransition, float, float]] = []
            for row in reversed(trajectory):
                value_bootstrap = 0.0 if row.done else 1.0
                trace_continuation = (
                    0.0 if row.done or row.truncated or row.credit_boundary else 1.0
                )
                delta = (
                    row.reward
                    + self.gamma * value_bootstrap * row.next_value_estimate
                    - row.value_estimate
                )
                advantage = (
                    delta
                    + self.gamma * self.gae_lambda * trace_continuation * next_advantage
                )
                return_target = row.value_estimate + advantage
                reverse.append((row, advantage, return_target))
                next_advantage = advantage
            raw_samples.extend(reversed(reverse))

        advantages = [advantage for _, advantage, _ in raw_samples]
        mean = fsum(advantages) / len(advantages)
        if len(advantages) > 1:
            variance = fsum((value - mean) ** 2 for value in advantages) / len(advantages)
            std = sqrt(max(0.0, variance))
        else:
            std = 0.0

        samples: list[PlannerTrainingSample] = []
        for row, raw_advantage, return_target in raw_samples:
            if self.normalize_advantages and std > 1e-12:
                advantage = (raw_advantage - mean) / std
            elif self.normalize_advantages:
                advantage = 0.0
            else:
                advantage = raw_advantage
            samples.append(
                PlannerTrainingSample(
                    trajectory_id=row.trajectory_id,
                    step_index=row.step_index,
                    action=row.action,
                    observation=row.observation,
                    reward=row.reward,
                    raw_advantage=raw_advantage,
                    advantage=advantage,
                    return_target=return_target,
                    done=row.done,
                    truncated=row.truncated,
                    legal_action=row.legal_action,
                    tool_success=row.tool_success,
                    credit_boundary=row.credit_boundary,
                    metadata=row.metadata,
                )
            )

        samples.sort(key=lambda sample: (sample.trajectory_id, sample.step_index))
        return PlannerTrainingBatch(
            samples=tuple(samples),
            advantage_mean=mean,
            advantage_std=std,
            gamma=self.gamma,
            gae_lambda=self.gae_lambda,
        )
