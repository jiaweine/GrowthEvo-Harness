from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b
import json
from math import exp, inf, isfinite, log, log1p
from typing import Mapping, Sequence


class ChangingMeanDecision(str, Enum):
    HOLD = "hold"
    ABOVE_FLOOR = "above_floor"


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _logmeanexp(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("logmeanexp requires at least one value")
    maximum = max(values)
    if maximum == inf:
        return inf
    return maximum + log(sum(exp(value - maximum) for value in values)) - log(len(values))


def _stable_log1p_lambda_error(lam: float, error: float) -> float:
    """Compute log(1 + lam*error) without overflowing a huge positive product."""

    if error < 0.0:
        product = lam * error
        if product <= -1.0:
            raise ArithmeticError("betting factor became non-positive")
        return log1p(product)
    if error == 0.0:
        return 0.0
    log_product = log(lam) + log(error)
    if log_product < 700.0:
        return log1p(exp(log_product))
    inverse = exp(-log_product) if log_product < 745.0 else 0.0
    return log_product + log1p(inverse)


@dataclass(frozen=True, slots=True)
class ChangingMeanLowerCSSpec:
    """Lower-CS contract for a nonnegative, right-heavy-tailed changing mean.

    The scalar observations may be unbounded. `mean_upper` is a preregistered upper
    bound on each conditional mean, not an observation cap. After normalization by
    that bound, the target is the running average of predictable conditional means.
    """

    mean_upper: float
    alpha: float = 0.05
    lambdas: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.7)
    predictor_pseudocount: float = 0.5
    root_abs_tolerance: float = 1e-10
    root_max_iterations: int = 128

    def __post_init__(self) -> None:
        if not isfinite(float(self.mean_upper)) or self.mean_upper <= 0:
            raise ValueError("mean_upper must be positive and finite")
        if not isfinite(float(self.alpha)) or not 0 < self.alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if not self.lambdas:
            raise ValueError("at least one betting lambda is required")
        if any(not isfinite(float(item)) or not 0 < item < 1 for item in self.lambdas):
            raise ValueError("betting lambdas must be finite and in (0, 1)")
        if len(set(float(item) for item in self.lambdas)) != len(self.lambdas):
            raise ValueError("betting lambdas must be unique")
        if (
            not isfinite(float(self.predictor_pseudocount))
            or self.predictor_pseudocount < 0
        ):
            raise ValueError("predictor_pseudocount must be finite and non-negative")
        if not isfinite(float(self.root_abs_tolerance)) or self.root_abs_tolerance <= 0:
            raise ValueError("root_abs_tolerance must be positive and finite")
        if (
            isinstance(self.root_max_iterations, bool)
            or not isinstance(self.root_max_iterations, int)
            or self.root_max_iterations < 32
        ):
            raise ValueError("root_max_iterations must be an integer >= 32")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.changing-mean-heavy-tail-lcs.v1",
                **asdict(self),
                "target": "running_average_conditional_mean",
                "observation_support": "nonnegative_unbounded",
                "conditional_mean_contract": "zero_to_mean_upper",
                "mixture_weights": "equal_fixed",
            }
        )


@dataclass(frozen=True, slots=True)
class ChangingMeanLowerSnapshot:
    lower: float
    observations: int
    alpha: float
    mean_upper: float
    protocol_fingerprint: str


class ChangingMeanLowerConfidenceSequence:
    """Anytime-valid lower CS for a changing nonnegative heavy-tailed mean.

    Normalize X_t by `mean_upper`, and let p_t be a predictable estimate in [0,1].
    For fixed lambda in (0,1), define e_t = X_t - p_t and

        V_t(lambda) = sum(lambda e_t - log(1 + lambda e_t)).

    For the running average of conditional means `mu_bar_t`, the process

        exp(lambda (sum X_t - t mu_bar_t) - V_t(lambda))

    is a nonnegative supermartingale. This follows because the one-step conditional
    expected multiplier can be written as `(1+a) exp(-a) <= 1`, where
    `a=lambda(E[X_t|F_(t-1)]-p_t)` and positivity is guaranteed by X_t>=0,
    p_t<=1 and lambda<1.

    GrowthEvo uses a fixed equal-weight finite mixture over preregistered lambdas.
    The implementation stores equivalent log-wealth-at-zero sufficient statistics,
    avoiding catastrophic cancellation for very large right-tail observations.
    """

    def __init__(self, spec: ChangingMeanLowerCSSpec) -> None:
        self.spec = spec
        self._observations = 0
        self._sum_normalized = 0.0
        self._log_wealth_at_zero = [0.0 for _ in spec.lambdas]

    @property
    def observations(self) -> int:
        return self._observations

    def update(self, value: float) -> None:
        value = float(value)
        if not isfinite(value) or value < 0:
            raise ValueError("changing-mean lower CS requires a finite nonnegative value")
        normalized = value / self.spec.mean_upper
        if not isfinite(normalized):
            raise ValueError("value normalization overflowed")

        denominator = self._observations + 1.0
        predictor = min(
            1.0,
            (self._sum_normalized + self.spec.predictor_pseudocount) / denominator,
        )
        error = normalized - predictor

        next_scores: list[float] = []
        for current, lam in zip(self._log_wealth_at_zero, self.spec.lambdas):
            log_factor = _stable_log1p_lambda_error(lam, error)
            increment = lam * predictor + log_factor
            updated = current + increment
            if not isfinite(updated):
                raise ValueError("changing-mean log wealth overflowed")
            next_scores.append(updated)

        next_sum = self._sum_normalized + normalized
        if not isfinite(next_sum):
            raise ValueError("running normalized sum overflowed")

        # Atomic state mutation after all numerical checks pass.
        self._log_wealth_at_zero = next_scores
        self._sum_normalized = next_sum
        self._observations += 1

    def log_wealth(self, candidate_mean: float) -> float:
        candidate_mean = float(candidate_mean)
        if not isfinite(candidate_mean):
            raise ValueError("candidate_mean must be finite")
        if candidate_mean < 0 or candidate_mean > self.spec.mean_upper:
            raise ValueError("candidate_mean lies outside the preregistered mean range")
        if not self._observations:
            return 0.0
        normalized_mean = candidate_mean / self.spec.mean_upper
        components = [
            score - lam * self._observations * normalized_mean
            for score, lam in zip(self._log_wealth_at_zero, self.spec.lambdas)
        ]
        return _logmeanexp(components)

    def e_value(self, candidate_mean: float) -> float:
        log_value = self.log_wealth(candidate_mean)
        return inf if log_value >= 709.0 else exp(log_value)

    def lower_bound(self) -> float:
        if not self._observations:
            return 0.0
        threshold = log(1.0 / self.spec.alpha)
        if self.log_wealth(0.0) <= threshold:
            return 0.0
        if self.log_wealth(self.spec.mean_upper) >= threshold:
            return self.spec.mean_upper

        left = 0.0
        right = self.spec.mean_upper
        for _ in range(self.spec.root_max_iterations):
            midpoint = left + (right - left) / 2.0
            if right - left <= self.spec.root_abs_tolerance:
                return midpoint
            if self.log_wealth(midpoint) >= threshold:
                left = midpoint
            else:
                right = midpoint
        return left + (right - left) / 2.0

    def snapshot(self) -> ChangingMeanLowerSnapshot:
        return ChangingMeanLowerSnapshot(
            lower=self.lower_bound(),
            observations=self._observations,
            alpha=self.spec.alpha,
            mean_upper=self.spec.mean_upper,
            protocol_fingerprint=self.spec.fingerprint,
        )


@dataclass(frozen=True, slots=True)
class NonstationaryFloorSpec:
    metric_name: str
    confidence_sequence: ChangingMeanLowerCSSpec
    floor: float

    def __post_init__(self) -> None:
        if not self.metric_name.strip():
            raise ValueError("metric_name cannot be empty")
        if not isfinite(float(self.floor)):
            raise ValueError("floor must be finite")
        if not 0 <= self.floor <= self.confidence_sequence.mean_upper:
            raise ValueError("floor must lie inside the preregistered mean range")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.nonstationary-floor-monitor.v1",
                "metric_name": self.metric_name,
                "confidence_sequence_fingerprint": self.confidence_sequence.fingerprint,
                "floor": self.floor,
            }
        )


@dataclass(frozen=True, slots=True)
class NonstationaryFloorSnapshot:
    decision: ChangingMeanDecision
    lower: float
    floor: float
    observations: int
    protocol_fingerprint: str


class NonstationaryPositiveMetricMonitor:
    """One-sided absolute-floor evidence for a nonnegative changing metric."""

    def __init__(self, *, experiment_id: str, spec: NonstationaryFloorSpec) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id cannot be empty")
        self.experiment_id = experiment_id
        self.spec = spec
        self.cs = ChangingMeanLowerConfidenceSequence(spec.confidence_sequence)
        self._unit_tokens: set[bytes] = set()

    def _token(self, analysis_unit_id: str) -> bytes:
        if not analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        return blake2b(
            f"{self.experiment_id}|changing-mean|{analysis_unit_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    def update(self, *, analysis_unit_id: str, value: float) -> NonstationaryFloorSnapshot:
        token = self._token(analysis_unit_id)
        if token in self._unit_tokens:
            raise ValueError("analysis unit already contributed to changing-mean evidence")
        # CS update is itself atomic on numerical failure; add dedupe token only after.
        self.cs.update(value)
        self._unit_tokens.add(token)
        return self.snapshot()

    def snapshot(self) -> NonstationaryFloorSnapshot:
        lower = self.cs.lower_bound()
        decision = (
            ChangingMeanDecision.ABOVE_FLOOR
            if self.cs.observations and lower > self.spec.floor
            else ChangingMeanDecision.HOLD
        )
        return NonstationaryFloorSnapshot(
            decision=decision,
            lower=lower,
            floor=self.spec.floor,
            observations=self.cs.observations,
            protocol_fingerprint=self.spec.fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ChangingMeanOffPolicySpec:
    """Nonstationary lower-CS contract for importance-weighted bounded reward."""

    confidence_sequence: ChangingMeanLowerCSSpec
    reward_upper: float = 1.0
    value_floor: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(float(self.reward_upper)) or self.reward_upper <= 0:
            raise ValueError("reward_upper must be positive and finite")
        if abs(self.confidence_sequence.mean_upper - self.reward_upper) > 1e-12:
            raise ValueError("off-policy mean_upper must equal reward_upper")
        if not isfinite(float(self.value_floor)) or not 0 <= self.value_floor <= self.reward_upper:
            raise ValueError("value_floor must lie in [0, reward_upper]")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.changing-mean-off-policy-value.v1",
                "confidence_sequence_fingerprint": self.confidence_sequence.fingerprint,
                "reward_upper": self.reward_upper,
                "value_floor": self.value_floor,
                "estimand": "running_average_counterfactual_policy_value",
            }
        )


class ChangingMeanOffPolicyValueMonitor:
    """Lower-bounds a changing counterfactual policy value with unbounded weights.

    Correctness requires each nonnegative importance weight to be the valid
    predictable likelihood ratio for the target policy relative to the logging
    policy. Rewards are bounded, but weights and the product `weight*reward` need
    not be bounded. This class is not a signed treatment-effect estimator.
    """

    def __init__(self, *, experiment_id: str, spec: ChangingMeanOffPolicySpec) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id cannot be empty")
        self.experiment_id = experiment_id
        self.spec = spec
        self.cs = ChangingMeanLowerConfidenceSequence(spec.confidence_sequence)
        self._tokens: set[bytes] = set()

    def _token(self, observation_id: str) -> bytes:
        if not observation_id:
            raise ValueError("observation_id cannot be empty")
        return blake2b(
            f"{self.experiment_id}|changing-ope|{observation_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    def update(
        self,
        *,
        observation_id: str,
        importance_weight: float,
        reward: float,
    ) -> NonstationaryFloorSnapshot:
        weight = float(importance_weight)
        reward = float(reward)
        if not isfinite(weight) or weight < 0:
            raise ValueError("importance_weight must be finite and nonnegative")
        if not isfinite(reward) or not 0 <= reward <= self.spec.reward_upper:
            raise ValueError("reward lies outside the preregistered reward range")
        value = weight * reward
        if not isfinite(value):
            raise ValueError("importance-weighted reward overflowed")

        token = self._token(observation_id)
        if token in self._tokens:
            raise ValueError("off-policy observation already contributed")
        self.cs.update(value)
        self._tokens.add(token)
        return self.snapshot()

    def snapshot(self) -> NonstationaryFloorSnapshot:
        lower = self.cs.lower_bound()
        decision = (
            ChangingMeanDecision.ABOVE_FLOOR
            if self.cs.observations and lower > self.spec.value_floor
            else ChangingMeanDecision.HOLD
        )
        return NonstationaryFloorSnapshot(
            decision=decision,
            lower=lower,
            floor=self.spec.value_floor,
            observations=self.cs.observations,
            protocol_fingerprint=self.spec.fingerprint,
        )
