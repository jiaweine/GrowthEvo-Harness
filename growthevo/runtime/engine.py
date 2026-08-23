from __future__ import annotations

from growthevo.evolution.failure_miner import FailureMiner
from growthevo.evolution.optimizer import HarnessEvolver
from growthevo.models import (
    EventType,
    GrowthAction,
    GrowthGoal,
    GrowthOption,
    RuntimeResult,
    UserObservation,
)
from growthevo.rl.causal_reward import CausalRewardModel
from growthevo.rl.hierarchical_policy import HierarchicalGrowthPolicy
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.event_store import EventStore
from growthevo.runtime.legal_action import LegalActionGate
from growthevo.runtime.planner import GrowthHypothesisPlanner
from growthevo.simulator.user_world_model import UserWorldModel


class GrowthEvoRuntime:
    """Reference end-to-end harness for one autonomous growth decision."""

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        planner: GrowthHypothesisPlanner | None = None,
        policy: HierarchicalGrowthPolicy | None = None,
        legal_gate: LegalActionGate | None = None,
        world_model: UserWorldModel | None = None,
        reward_model: CausalRewardModel | None = None,
        failure_miner: FailureMiner | None = None,
        evolver: HarnessEvolver | None = None,
    ) -> None:
        self.event_store = event_store or EventStore()
        self.planner = planner or GrowthHypothesisPlanner()
        self.policy = policy or HierarchicalGrowthPolicy()
        self.legal_gate = legal_gate or LegalActionGate()
        self.world_model = world_model or UserWorldModel()
        self.reward_model = reward_model or CausalRewardModel()
        self.failure_miner = failure_miner or FailureMiner()
        self.evolver = evolver or HarnessEvolver()

    def run(self, goal: GrowthGoal, observation: UserObservation) -> RuntimeResult:
        self.event_store.append(EventType.GOAL_COMPILED, {"goal": goal})

        belief = build_causal_belief(observation)
        self.event_store.append(EventType.BELIEF_UPDATED, {"belief": belief})

        hypothesis = self.planner.plan(belief, goal)
        self.event_store.append(EventType.HYPOTHESIS_PLANNED, {"hypothesis": hypothesis})

        proposed = self.policy.select_action(belief, hypothesis, goal.constraints)
        self.event_store.append(EventType.ACTION_PROPOSED, {"action": proposed})

        decision = self.legal_gate.evaluate(belief, proposed, goal.constraints)
        action = proposed
        if decision.allowed:
            self.event_store.append(EventType.ACTION_ALLOWED, {"action": action})
        else:
            self.event_store.append(
                EventType.ACTION_BLOCKED,
                {"action": proposed, "reasons": decision.reasons},
            )
            failure = self.failure_miner.from_action_decision(decision)
            if failure is not None:
                self.event_store.append(EventType.FAILURE_CLASSIFIED, {"failure": failure})
                patch = self.evolver.propose(failure)
                self.event_store.append(EventType.PATCH_PROPOSED, {"patch": patch})

            # Hard-gate failures never trigger an alternative treatment in the
            # same decision step. The safe recovery action is a holdout.
            action = GrowthAction.no_treatment(GrowthOption.HOLDOUT)
            self.event_store.append(
                EventType.ACTION_ALLOWED,
                {"action": action, "recovery": "hard_gate_fallback"},
            )

        feedback = self.world_model.step(belief, action)
        self.event_store.append(EventType.FEEDBACK_OBSERVED, {"feedback": feedback})

        reward = self.reward_model.compute(belief, action, feedback)
        self.event_store.append(EventType.REWARD_ASSIGNED, {"reward": reward})

        if not self.event_store.verify():
            raise RuntimeError("event chain integrity verification failed")

        return RuntimeResult(
            belief=belief,
            action=action,
            feedback=feedback,
            reward=reward,
            event_count=len(self.event_store),
        )
