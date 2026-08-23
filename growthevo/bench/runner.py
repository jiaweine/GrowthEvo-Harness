from __future__ import annotations

from dataclasses import dataclass
from math import fsum
from typing import Callable

from growthevo.causal.dr_learner import CrossFittedDRLearner, FittedTreatmentEffect
from growthevo.models import Channel

from .synthetic import CATEBenchmarkResult, SyntheticGrowthSample, evaluate_cate, make_synthetic_growth_bandit


PolicyFn = Callable[[tuple[float, ...]], Channel]


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkResult:
    sample_size: int
    policy_value: float
    oracle_value: float
    regret: float
    no_treatment_rate: float


class GrowthAgentBench:
    """Small reproducible benchmark harness with held-out oracle evaluation.

    The benchmark is intentionally synthetic and auditable. It is useful for
    regression testing causal learners and policy logic because the ground-truth
    treatment effects are known. It is not a substitute for Open Bandit/Criteo
    adapters or real randomized experiments.
    """

    def __init__(
        self,
        samples: tuple[SyntheticGrowthSample, ...],
        *,
        train_fraction: float = 0.75,
    ) -> None:
        if len(samples) < 8:
            raise ValueError("benchmark requires at least 8 samples")
        if not 0.5 <= train_fraction < 1.0:
            raise ValueError("train_fraction must be in [0.5, 1)")
        split = int(len(samples) * train_fraction)
        self.train = samples[:split]
        self.test = samples[split:]

    @classmethod
    def synthetic(
        cls,
        sample_size: int = 1200,
        *,
        seed: int = 17,
        outcome_noise: float = 0.02,
        train_fraction: float = 0.75,
    ) -> "GrowthAgentBench":
        return cls(
            make_synthetic_growth_bandit(
                sample_size,
                seed=seed,
                outcome_noise=outcome_noise,
            ),
            train_fraction=train_fraction,
        )

    def fit_cate(
        self,
        *,
        treatment: Channel,
        learner: CrossFittedDRLearner | None = None,
    ) -> tuple[FittedTreatmentEffect, CATEBenchmarkResult]:
        trainer = learner or CrossFittedDRLearner()
        model = trainer.fit(
            (sample.record for sample in self.train),
            treatment=treatment,
        )
        return model, evaluate_cate(model, self.test)

    @staticmethod
    def _oracle_action(sample: SyntheticGrowthSample) -> Channel:
        actions = (Channel.NO_TREATMENT, Channel.PUSH, Channel.EMAIL)
        return max(actions, key=lambda action: (sample.oracle_outcome(action), action.value))

    def evaluate_policy(self, policy: PolicyFn) -> PolicyBenchmarkResult:
        policy_outcomes: list[float] = []
        oracle_outcomes: list[float] = []
        no_treatment = 0
        for sample in self.test:
            action = policy(sample.record.features)
            if action not in {Channel.NO_TREATMENT, Channel.PUSH, Channel.EMAIL}:
                raise ValueError(f"benchmark policy returned unsupported action: {action.value}")
            if action is Channel.NO_TREATMENT:
                no_treatment += 1
            policy_outcomes.append(sample.oracle_outcome(action))
            oracle_outcomes.append(sample.oracle_outcome(self._oracle_action(sample)))

        n = len(self.test)
        policy_value = fsum(policy_outcomes) / n
        oracle_value = fsum(oracle_outcomes) / n
        return PolicyBenchmarkResult(
            sample_size=n,
            policy_value=policy_value,
            oracle_value=oracle_value,
            regret=max(0.0, oracle_value - policy_value),
            no_treatment_rate=no_treatment / n,
        )
