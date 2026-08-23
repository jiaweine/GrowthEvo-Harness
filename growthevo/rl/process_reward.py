from __future__ import annotations

from dataclasses import dataclass
from math import fsum
from typing import Iterable


def _unit(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ProcessState:
    """Verifier-readable state used for potential-based planner shaping."""

    goal_progress: float
    evidence_quality: float
    constraint_slack: float

    def __post_init__(self) -> None:
        _unit("goal_progress", self.goal_progress)
        _unit("evidence_quality", self.evidence_quality)
        if not -1.0 <= self.constraint_slack <= 1.0:
            raise ValueError("constraint_slack must be in [-1, 1]")


@dataclass(frozen=True, slots=True)
class TrajectoryStepSignal:
    """One planner/tool step with environment-grounded learning signals.

    ``action_entropy`` is normalized to [0, 1]. Low entropy means the planner
    was confident before observing the tool/environment response. Crediting a
    subsequent evidence gain by ``1 - action_entropy`` mirrors the 2026 agentic
    RL direction of learning from observations, rather than rewarding only the
    final answer.
    """

    step_id: str
    before: ProcessState
    after: ProcessState
    action_entropy: float
    tool_success: bool
    direct_cost: float = 0.0
    duplicate_evidence: bool = False
    irreversible_side_effect: bool = False

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id cannot be empty")
        _unit("action_entropy", self.action_entropy)
        if self.direct_cost < 0:
            raise ValueError("direct_cost must be non-negative")


@dataclass(frozen=True, slots=True)
class ProcessRewardWeights:
    goal_potential: float = 1.0
    evidence_potential: float = 0.6
    constraint_potential: float = 0.5
    observation_grounding: float = 0.8
    tool_success: float = 0.10
    tool_failure: float = 0.30
    direct_cost: float = 0.20
    duplicate_evidence: float = 0.15
    irreversible_side_effect: float = 1.0
    gamma: float = 0.99

    def __post_init__(self) -> None:
        if not 0 < self.gamma <= 1:
            raise ValueError("gamma must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ProcessStepReward:
    step_id: str
    potential_delta: float
    observation_credit: float
    tool_credit: float
    cost_penalty: float
    duplicate_penalty: float
    side_effect_penalty: float
    total: float


@dataclass(frozen=True, slots=True)
class TrajectoryReward:
    steps: tuple[ProcessStepReward, ...]
    process_total: float
    terminal_outcome: float
    total: float


class GrowthProcessRewardModel:
    """Fine-grained reward for tool-using growth planners.

    The design combines two signals that are useful for long-horizon agent RL:

    * potential-based progress over goal/evidence/constraint state;
    * observation-grounded credit for informative tool/environment responses.

    It intentionally does not reward verbose reasoning or raw tool count.
    Duplicate evidence, failed tools, irreversible side effects and cost receive
    explicit negative credit.
    """

    def __init__(self, weights: ProcessRewardWeights | None = None) -> None:
        self.weights = weights or ProcessRewardWeights()

    def _potential(self, state: ProcessState) -> float:
        w = self.weights
        return (
            w.goal_potential * state.goal_progress
            + w.evidence_potential * state.evidence_quality
            + w.constraint_potential * state.constraint_slack
        )

    def score_step(self, signal: TrajectoryStepSignal) -> ProcessStepReward:
        w = self.weights
        potential_delta = w.gamma * self._potential(signal.after) - self._potential(signal.before)

        evidence_gain = max(0.0, signal.after.evidence_quality - signal.before.evidence_quality)
        action_confidence = 1.0 - signal.action_entropy
        observation_credit = w.observation_grounding * action_confidence * evidence_gain

        tool_credit = w.tool_success if signal.tool_success else -w.tool_failure
        cost_penalty = w.direct_cost * signal.direct_cost
        duplicate_penalty = w.duplicate_evidence if signal.duplicate_evidence else 0.0
        side_effect_penalty = (
            w.irreversible_side_effect if signal.irreversible_side_effect else 0.0
        )

        total = (
            potential_delta
            + observation_credit
            + tool_credit
            - cost_penalty
            - duplicate_penalty
            - side_effect_penalty
        )
        return ProcessStepReward(
            step_id=signal.step_id,
            potential_delta=potential_delta,
            observation_credit=observation_credit,
            tool_credit=tool_credit,
            cost_penalty=cost_penalty,
            duplicate_penalty=duplicate_penalty,
            side_effect_penalty=side_effect_penalty,
            total=total,
        )

    def score_trajectory(
        self,
        signals: Iterable[TrajectoryStepSignal],
        *,
        terminal_outcome: float = 0.0,
    ) -> TrajectoryReward:
        steps = tuple(self.score_step(signal) for signal in signals)
        if not steps:
            raise ValueError("at least one trajectory step is required")
        process_total = fsum(step.total for step in steps)
        return TrajectoryReward(
            steps=steps,
            process_total=process_total,
            terminal_outcome=terminal_outcome,
            total=process_total + terminal_outcome,
        )
