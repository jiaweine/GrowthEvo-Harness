from __future__ import annotations

from typing import Iterable, Protocol

from growthevo.evolution.failure_miner import FailureMiner
from growthevo.evolution.optimizer import HarnessEvolver
from growthevo.models import (
    CausalBelief,
    EventType,
    Feedback,
    GrowthAction,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
    PolicyEvidence,
    RuntimeResult,
    UserObservation,
    VerificationResult,
)
from growthevo.rl.causal_reward import CausalRewardModel
from growthevo.rl.conformal import ConformalMargins
from growthevo.rl.hierarchical_policy import HierarchicalGrowthPolicy
from growthevo.rl.process_reward import (
    GrowthProcessRewardModel,
    TrajectoryReward,
    TrajectoryStepSignal,
)
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.event_store import EventStore
from growthevo.runtime.legal_action import LegalActionGate
from growthevo.runtime.planner import GrowthHypothesisPlanner
from growthevo.verifier.counterfactual import CounterfactualVerifier


class FeedbackEnvironment(Protocol):
    """Minimal execution-environment contract used by the Runtime."""

    def step(self, belief: CausalBelief, action: GrowthAction) -> Feedback: ...


class GrowthEvoRuntime:
    """Harness for interaction execution and cohort policy verification.

    Execution dependencies are fail-closed. The Runtime does not silently attach
    a synthetic ``UserWorldModel`` or choose a reward scalarization. Callers that
    invoke ``run`` must provide both an environment and a causal reward model.
    Verification-only workflows may omit them and still use ``verify_candidate``.
    """

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        planner: GrowthHypothesisPlanner | None = None,
        policy: HierarchicalGrowthPolicy | None = None,
        legal_gate: LegalActionGate | None = None,
        world_model: FeedbackEnvironment | None = None,
        reward_model: CausalRewardModel | None = None,
        process_reward_model: GrowthProcessRewardModel | None = None,
        verifier: CounterfactualVerifier | None = None,
        failure_miner: FailureMiner | None = None,
        evolver: HarnessEvolver | None = None,
    ) -> None:
        self.event_store = event_store or EventStore()
        self.planner = planner or GrowthHypothesisPlanner()
        self.policy = policy or HierarchicalGrowthPolicy()
        self.legal_gate = legal_gate or LegalActionGate()
        self.world_model = world_model
        self.reward_model = reward_model
        self.process_reward_model = process_reward_model or GrowthProcessRewardModel()
        self.verifier = verifier or CounterfactualVerifier()
        self.failure_miner = failure_miner or FailureMiner()
        self.evolver = evolver or HarnessEvolver()

    def run(self, goal: GrowthGoal, observation: UserObservation) -> RuntimeResult:
        """Execute one user-level decision with explicit environment semantics.

        This method does not pretend that one interaction is enough to promote a
        policy. Cohort-level evidence is evaluated separately by
        :meth:`verify_candidate`, but both phases share the same event stream.
        """

        if self.world_model is None:
            raise RuntimeError(
                "execution environment is not configured; provide world_model explicitly"
            )
        if self.reward_model is None:
            raise RuntimeError(
                "causal reward model is not configured; provide reward_model explicitly"
            )

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

        self._assert_event_integrity()

        return RuntimeResult(
            belief=belief,
            action=action,
            feedback=feedback,
            reward=reward,
            event_count=len(self.event_store),
        )

    def score_planner_trajectory(
        self,
        signals: Iterable[TrajectoryStepSignal],
        *,
        terminal_outcome: float = 0.0,
    ) -> TrajectoryReward:
        """Assign step-level planner credit and persist it beside execution facts."""

        reward = self.process_reward_model.score_trajectory(
            signals,
            terminal_outcome=terminal_outcome,
        )
        self.event_store.append(
            EventType.PROCESS_REWARD_ASSIGNED,
            {"trajectory_reward": reward},
        )
        self._assert_event_integrity()
        return reward

    def verify_candidate(
        self,
        evidence: PolicyEvidence,
        constraints: GrowthConstraints,
        *,
        conformal: ConformalMargins | None = None,
    ) -> VerificationResult:
        """Verify cohort-level candidate-policy evidence and persist the result."""

        result = self.verifier.verify(evidence, constraints, conformal=conformal)
        self.event_store.append(
            EventType.VERIFICATION_COMPLETED,
            {
                "evidence": evidence,
                "conformal": conformal,
                "result": result,
            },
        )

        failure = self.failure_miner.from_verification(result)
        if failure is not None:
            self.event_store.append(EventType.FAILURE_CLASSIFIED, {"failure": failure})
            patch = self.evolver.propose(failure)
            self.event_store.append(EventType.PATCH_PROPOSED, {"patch": patch})

        self._assert_event_integrity()
        return result

    def _assert_event_integrity(self) -> None:
        if not self.event_store.verify():
            raise RuntimeError("event chain integrity verification failed")
