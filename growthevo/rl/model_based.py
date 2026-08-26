from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, fsum
from typing import Callable, Iterable, Sequence

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints
from growthevo.rl.causal_reward import CausalRewardModel
from growthevo.simulator.user_world_model import UserWorldModel, WorldModelConfig


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class WorldTransitionConfig:
    fatigue_decay_per_step: float = 0.06
    churn_recovery_per_step: float = 0.01
    retention_to_intent: float = 0.15
    fatigue_uplift_decay: float = 0.20


@dataclass(frozen=True, slots=True)
class StressScenario:
    """Deployment-shift knobs used for conservative world-model stress tests."""

    uplift_multiplier: float = 1.0
    cost_multiplier: float = 1.0
    fatigue_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.uplift_multiplier < 0 or self.cost_multiplier < 0 or self.fatigue_multiplier < 0:
            raise ValueError("stress multipliers must be non-negative")


@dataclass(frozen=True, slots=True)
class RolloutTrace:
    discounted_return: float
    total_cost: float
    max_fatigue: float
    max_churn_risk: float
    violated: bool
    final_belief: CausalBelief


@dataclass(frozen=True, slots=True)
class CandidateRolloutScore:
    candidate_id: str
    mean_return: float
    cvar_return: float
    violation_rate: float
    mean_cost: float
    robust_score: float


class LongHorizonGrowthWorld:
    """State-transition wrapper around a one-step stochastic user model."""

    def __init__(
        self,
        *,
        seed: int,
        world_config: WorldModelConfig | None = None,
        transition_config: WorldTransitionConfig | None = None,
        reward_model: CausalRewardModel | None = None,
    ) -> None:
        self.world = UserWorldModel(seed=seed, config=world_config)
        self.transition_config = transition_config or WorldTransitionConfig()
        self.reward_model = reward_model or CausalRewardModel()

    def transition(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        *,
        stress: StressScenario | None = None,
    ) -> tuple[CausalBelief, float, float]:
        scenario = stress or StressScenario()
        stressed_action = replace(
            action,
            expected_uplift=action.expected_uplift * scenario.uplift_multiplier,
            budget=action.budget * scenario.cost_multiplier,
        )
        feedback = self.world.step(belief, stressed_action)
        reward = self.reward_model.compute(belief, stressed_action, feedback).total

        cfg = self.transition_config
        treated = action.channel is not Channel.NO_TREATMENT
        fatigue = _clip(
            (belief.fatigue + feedback.fatigue_delta * scenario.fatigue_multiplier)
            * (1.0 - cfg.fatigue_decay_per_step)
        )
        churn = _clip(
            belief.churn_risk + feedback.churn_risk_delta - cfg.churn_recovery_per_step
        )
        natural_conversion = _clip(
            belief.natural_conversion + cfg.retention_to_intent * feedback.retention_delta
        )
        uplift_decay = max(0.0, 1.0 - cfg.fatigue_uplift_decay * fatigue)
        channel_uplift = {
            channel: uplift * uplift_decay for channel, uplift in belief.channel_uplift.items()
        }

        next_belief = replace(
            belief,
            natural_conversion=natural_conversion,
            channel_uplift=channel_uplift,
            fatigue=fatigue,
            churn_risk=churn,
            touches_24h=belief.touches_24h + int(treated),
            touches_7d=belief.touches_7d + int(treated),
            spend_to_date=belief.spend_to_date + feedback.cost,
            days_since_last_active=(
                0
                if feedback.realized_conversion
                else belief.days_since_last_active + max(1, feedback.delay_days)
            ),
        )
        return next_belief, reward, feedback.cost

    def rollout(
        self,
        initial_belief: CausalBelief,
        actions: Sequence[GrowthAction],
        constraints: GrowthConstraints,
        *,
        gamma: float = 0.99,
        stress: StressScenario | None = None,
    ) -> RolloutTrace:
        if not actions:
            raise ValueError("rollout requires at least one action")
        if not 0 < gamma <= 1:
            raise ValueError("gamma must be in (0, 1]")

        belief = initial_belief
        discounted_return = 0.0
        total_cost = 0.0
        max_fatigue = belief.fatigue
        max_churn = belief.churn_risk
        violated = False

        for index, action in enumerate(actions):
            belief, reward, cost = self.transition(belief, action, stress=stress)
            discounted_return += (gamma**index) * reward
            total_cost += cost
            max_fatigue = max(max_fatigue, belief.fatigue)
            max_churn = max(max_churn, belief.churn_risk)
            if (
                belief.spend_to_date > constraints.max_budget
                or belief.fatigue > constraints.max_fatigue
                or belief.churn_risk > constraints.max_churn_risk
                or belief.touches_24h > constraints.max_touches_24h
                or belief.touches_7d > constraints.max_touches_7d
            ):
                violated = True

        return RolloutTrace(
            discounted_return=discounted_return,
            total_cost=total_cost,
            max_fatigue=max_fatigue,
            max_churn_risk=max_churn,
            violated=violated,
            final_belief=belief,
        )


WorldFactory = Callable[[int], LongHorizonGrowthWorld]


class RiskSensitiveMPC:
    """Rank open-loop plans with lower-tail return and safety diagnostics.

    Candidate plans are evaluated with common random numbers: every candidate is
    replayed under the same rollout seeds. This reduces Monte Carlo noise in
    pairwise plan comparisons and makes rankings invariant to candidate order.
    The world constructor is injectable so research experiments can use learned
    dynamics, ensembles, or calibrated simulators without modifying the planner.
    """

    def __init__(
        self,
        *,
        rollouts: int = 32,
        cvar_alpha: float = 0.20,
        violation_penalty: float = 2.0,
        gamma: float = 0.99,
        base_seed: int = 101,
        world_factory: WorldFactory | None = None,
    ) -> None:
        if rollouts <= 0:
            raise ValueError("rollouts must be positive")
        if not 0 < cvar_alpha <= 1:
            raise ValueError("cvar_alpha must be in (0, 1]")
        if violation_penalty < 0:
            raise ValueError("violation_penalty must be non-negative")
        if not 0 < gamma <= 1:
            raise ValueError("gamma must be in (0, 1]")
        self.rollouts = rollouts
        self.cvar_alpha = cvar_alpha
        self.violation_penalty = violation_penalty
        self.gamma = gamma
        self.base_seed = base_seed
        self.world_factory = world_factory

    def _make_world(self, seed: int) -> LongHorizonGrowthWorld:
        if self.world_factory is not None:
            return self.world_factory(seed)
        return LongHorizonGrowthWorld(seed=seed)

    def evaluate(
        self,
        initial_belief: CausalBelief,
        candidates: Iterable[tuple[str, Sequence[GrowthAction]]],
        constraints: GrowthConstraints,
        *,
        stress: StressScenario | None = None,
        rollout_seeds: Sequence[int] | None = None,
    ) -> tuple[CandidateRolloutScore, ...]:
        candidate_rows = [(candidate_id, tuple(actions)) for candidate_id, actions in candidates]
        if not candidate_rows:
            raise ValueError("at least one candidate plan is required")
        identifiers = [candidate_id for candidate_id, _ in candidate_rows]
        if any(not candidate_id for candidate_id in identifiers):
            raise ValueError("candidate_id cannot be empty")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidate_id values must be unique")
        if any(not actions for _, actions in candidate_rows):
            raise ValueError("candidate plans cannot be empty")

        if rollout_seeds is None:
            seeds = tuple(self.base_seed + index for index in range(self.rollouts))
        else:
            seeds = tuple(int(seed) for seed in rollout_seeds)
            if not seeds:
                raise ValueError("rollout_seeds cannot be empty")
            if len(set(seeds)) != len(seeds):
                raise ValueError("rollout_seeds must be unique")

        scores: list[CandidateRolloutScore] = []
        for candidate_id, actions in candidate_rows:
            returns: list[float] = []
            costs: list[float] = []
            violations = 0
            for seed in seeds:
                world = self._make_world(seed)
                trace = world.rollout(
                    initial_belief,
                    actions,
                    constraints,
                    gamma=self.gamma,
                    stress=stress,
                )
                returns.append(trace.discounted_return)
                costs.append(trace.total_cost)
                violations += int(trace.violated)

            ordered_returns = sorted(returns)
            tail_n = max(1, ceil(len(ordered_returns) * self.cvar_alpha))
            cvar = fsum(ordered_returns[:tail_n]) / tail_n
            sample_count = len(seeds)
            violation_rate = violations / sample_count
            mean_return = fsum(returns) / sample_count
            mean_cost = fsum(costs) / sample_count
            robust_score = cvar - self.violation_penalty * violation_rate
            scores.append(
                CandidateRolloutScore(
                    candidate_id=candidate_id,
                    mean_return=mean_return,
                    cvar_return=cvar,
                    violation_rate=violation_rate,
                    mean_cost=mean_cost,
                    robust_score=robust_score,
                )
            )

        return tuple(
            sorted(
                scores,
                key=lambda score: (score.robust_score, score.cvar_return, score.mean_return, score.candidate_id),
                reverse=True,
            )
        )
