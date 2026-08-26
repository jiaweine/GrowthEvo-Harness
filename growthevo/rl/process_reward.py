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

    ``action_entropy`` is retained as an audit diagnostic. It is deliberately
    not used as a proxy for epistemic uncertainty: a policy can be confidently
    wrong, and directly rewarding low entropy creates an incentive to collapse.

    ``information_need`` is optional and should come from an upstream uncertainty
    or value-of-information model. When omitted, evidence gain is credited
    without an entropy multiplier.
    """

    step_id: str
    before: ProcessState
    after: ProcessState
    action_entropy: float
    tool_success: bool
    information_need: float | None = None
    direct_cost: float = 0.0
    duplicate_evidence: bool = False
    irreversible_side_effect: bool = False

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id cannot be empty")
        _unit("action_entropy", self.action_entropy)
        if self.information_need is not None:
            _unit("information_need", self.information_need)
        if self.direct_cost < 0:
            raise ValueError("direct_cost must be non-negative")


@dataclass(frozen=True, slots=True)
class ProcessRewardWeights:
    goal_potential: float = 1.0
    evidence_potential: float = 0.6
    constraint_potential: float = 0.5
    observation_grounding: float = 0.8
    successful_tool_bonus: float = 0.0
    tool_failure: float = 0.30
    direct_cost: float = 0.20
    duplicate_evidence: float = 0.15
    irreversible_side_effect: float = 1.0
    gamma: float = 0.99

    def __post_init__(self) -> None:
        if not 0 < self.gamma <= 1:
            raise ValueError("gamma must be in (0, 1]")
        for name, value in (
            ("successful_tool_bonus", self.successful_tool_bonus),
            ("tool_failure", self.tool_failure),
            ("direct_cost", self.direct_cost),
            ("duplicate_evidence", self.duplicate_evidence),
            ("irreversible_side_effect", self.irreversible_side_effect),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class ProcessStepReward:
    step_id: str
    potential_delta: float
    observation_credit: float
    information_need_multiplier: float
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

    Useful tool calls earn credit through measurable state or evidence progress,
    not merely because the tool returned successfully. The default success bonus
    is therefore zero; failures remain penalized. A non-zero success bonus is
    available only as an explicit experiment configuration.
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
        information_need = 1.0 if signal.information_need is None else signal.information_need
        observation_credit = w.observation_grounding * information_need * evidence_gain

        tool_credit = w.successful_tool_bonus if signal.tool_success else -w.tool_failure
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
            information_need_multiplier=information_need,
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
