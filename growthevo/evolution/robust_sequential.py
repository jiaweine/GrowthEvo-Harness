from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b
import json
from math import exp, inf, isfinite, log, sqrt
from typing import Mapping, Sequence


class RobustEffectDecision(str, Enum):
    HOLD = "hold"
    SUPPORTS_SUPERIORITY = "supports_superiority"
    SUPPORTS_HARM = "supports_harm"


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


def _log_one_plus_t_plus_half_t2(t: float) -> float:
    """Stable log(1 + t + t^2/2) for t >= 0."""

    if t < 0 or not isfinite(t):
        raise ValueError("t must be finite and non-negative")
    if t < 1e150:
        return log(1.0 + t + 0.5 * t * t)
    # Avoid squaring very large finite values. For large t,
    # 1 + t + t^2/2 = t^2 * (1/t^2 + 1/t + 1/2).
    inverse = 1.0 / t
    return 2.0 * log(t) + log(0.5 + inverse + inverse * inverse)


def catoni_influence(value: float) -> float:
    """Odd Catoni influence satisfying the standard exponential envelope.

    phi(x) = log(1 + x + x^2/2) for x >= 0 and
             -log(1 - x + x^2/2) for x < 0.

    The implementation remains finite for every finite IEEE-754 input.
    """

    value = float(value)
    if not isfinite(value):
        raise ValueError("Catoni influence requires a finite value")
    if value >= 0:
        return _log_one_plus_t_plus_half_t2(value)
    return -_log_one_plus_t_plus_half_t2(-value)


@dataclass(frozen=True, slots=True)
class CatoniConfidenceInterval:
    lower: float
    upper: float
    observations: int
    alpha: float
    variance_bound: float

    @property
    def width(self) -> float:
        return self.upper - self.lower


@dataclass(frozen=True, slots=True)
class CatoniMixtureSpec:
    """Pre-registered finite-variance heavy-tail confidence-sequence contract.

    `variance_bound` is an upper bound on the conditional central variance of the
    scalar sequence being monitored. The conditional mean is assumed constant.
    Positive lambda values are expressed as dimensionless scales divided by the
    standard-deviation bound so the protocol identity is stable across units.
    """

    variance_bound: float
    alpha: float = 0.05
    lambda_scales: tuple[float, ...] = (0.125, 0.25, 0.5, 1.0, 2.0)
    root_abs_tolerance: float = 1e-9
    root_rel_tolerance: float = 1e-10
    root_max_iterations: int = 256

    def __post_init__(self) -> None:
        if not isfinite(float(self.variance_bound)) or self.variance_bound <= 0:
            raise ValueError("variance_bound must be positive and finite")
        if not isfinite(float(self.alpha)) or not 0 < self.alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if not self.lambda_scales:
            raise ValueError("at least one lambda scale is required")
        if any(not isfinite(float(item)) or item <= 0 for item in self.lambda_scales):
            raise ValueError("lambda scales must be positive and finite")
        if len(set(float(item) for item in self.lambda_scales)) != len(self.lambda_scales):
            raise ValueError("lambda scales must be unique")
        if (
            not isfinite(float(self.root_abs_tolerance))
            or self.root_abs_tolerance <= 0
        ):
            raise ValueError("root_abs_tolerance must be positive and finite")
        if (
            not isfinite(float(self.root_rel_tolerance))
            or self.root_rel_tolerance <= 0
        ):
            raise ValueError("root_rel_tolerance must be positive and finite")
        if (
            isinstance(self.root_max_iterations, bool)
            or not isinstance(self.root_max_iterations, int)
            or self.root_max_iterations < 32
        ):
            raise ValueError("root_max_iterations must be an integer >= 32")

    @property
    def lambdas(self) -> tuple[float, ...]:
        sigma = sqrt(self.variance_bound)
        return tuple(float(scale) / sigma for scale in self.lambda_scales)

    @property
    def side_alpha(self) -> float:
        return self.alpha / 2.0

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.catoni-mixture-cs.v1",
                **asdict(self),
                "assumption": "constant_conditional_mean_known_conditional_variance_bound",
                "two_sided_allocation": "alpha_over_2_per_side",
                "mixture_weights": "equal",
            }
        )


class CatoniMixtureConfidenceSequence:
    """Anytime-valid heavy-tail CS under a frozen conditional-variance bound.

    For a candidate mean `mu` and positive predictable lambda, Catoni's envelope
    gives the point-parameter supermartingales

        exp(sum phi(lambda * (X_t - mu)) - lambda^2 * v * t / 2)

    and its sign-reversed counterpart whenever the true conditional mean equals
    `mu` and conditional variance is bounded by `v`. A fixed convex mixture over
    pre-registered lambdas remains a supermartingale. Inverting both one-sided
    mixture tests with alpha/2 yields a two-sided confidence sequence.

    This reference implementation intentionally stores the scalar monitored
    sequence to make inversion auditable. It does not claim the approximate
    sufficient-statistic optimizations used by more specialized robust-CS systems.
    """

    def __init__(self, spec: CatoniMixtureSpec) -> None:
        self.spec = spec
        self._observations: list[float] = []

    @property
    def observations(self) -> int:
        return len(self._observations)

    def update(self, value: float) -> None:
        value = float(value)
        if not isfinite(value):
            raise ValueError("robust confidence sequence requires finite observations")
        self._observations.append(value)

    def _component_log_e(self, mean: float, lam: float, *, lower: bool) -> float:
        total = 0.0
        for value in self._observations:
            influenced = catoni_influence(lam * (value - mean))
            total += influenced if lower else -influenced
        total -= 0.5 * lam * lam * self.spec.variance_bound * self.observations
        return total

    def log_e_value(self, mean: float, *, lower: bool) -> float:
        mean = float(mean)
        if not isfinite(mean):
            raise ValueError("candidate mean must be finite")
        if not self._observations:
            return 0.0
        logs = [
            self._component_log_e(mean, lam, lower=lower)
            for lam in self.spec.lambdas
        ]
        return _logmeanexp(logs)

    def e_value(self, mean: float, *, lower: bool) -> float:
        log_value = self.log_e_value(mean, lower=lower)
        return inf if log_value >= 709.0 else exp(log_value)

    def _root(self, *, lower: bool) -> float:
        if not self._observations:
            return -inf if lower else inf
        threshold = log(1.0 / self.spec.side_alpha)

        def objective(candidate: float) -> float:
            return self.log_e_value(candidate, lower=lower) - threshold

        ordered = sorted(self._observations)
        center = ordered[len(ordered) // 2]
        sigma = sqrt(self.spec.variance_bound)
        scale = max(sigma, 1.0, abs(center) * 1e-12)

        left = center - scale
        right = center + scale
        left_value = objective(left)
        right_value = objective(right)

        # For the lower e-process the objective decreases with candidate mean;
        # for the upper e-process it increases. Expand until the crossing is
        # bracketed. All observations are finite, and Catoni's logarithmic tails
        # keep the objective numerically stable for very large magnitudes.
        for _ in range(self.spec.root_max_iterations):
            if lower:
                if left_value >= 0.0 and right_value <= 0.0:
                    break
                if left_value < 0.0:
                    scale *= 2.0
                    left = center - scale
                    if not isfinite(left):
                        left = -1.7976931348623157e308
                    left_value = objective(left)
                if right_value > 0.0:
                    scale *= 2.0
                    right = center + scale
                    if not isfinite(right):
                        right = 1.7976931348623157e308
                    right_value = objective(right)
            else:
                if left_value <= 0.0 and right_value >= 0.0:
                    break
                if left_value > 0.0:
                    scale *= 2.0
                    left = center - scale
                    if not isfinite(left):
                        left = -1.7976931348623157e308
                    left_value = objective(left)
                if right_value < 0.0:
                    scale *= 2.0
                    right = center + scale
                    if not isfinite(right):
                        right = 1.7976931348623157e308
                    right_value = objective(right)
        else:
            raise ArithmeticError("failed to bracket Catoni confidence-sequence root")

        for _ in range(self.spec.root_max_iterations):
            midpoint = left + (right - left) / 2.0
            midpoint_value = objective(midpoint)
            tolerance = self.spec.root_abs_tolerance + self.spec.root_rel_tolerance * max(
                1.0, abs(midpoint)
            )
            if right - left <= tolerance:
                return midpoint
            if lower:
                if midpoint_value >= 0.0:
                    left = midpoint
                else:
                    right = midpoint
            else:
                if midpoint_value <= 0.0:
                    left = midpoint
                else:
                    right = midpoint
        return left + (right - left) / 2.0

    def interval(self) -> CatoniConfidenceInterval:
        if not self._observations:
            return CatoniConfidenceInterval(
                lower=-inf,
                upper=inf,
                observations=0,
                alpha=self.spec.alpha,
                variance_bound=self.spec.variance_bound,
            )
        lower = self._root(lower=True)
        upper = self._root(lower=False)
        if lower > upper:
            raise ArithmeticError("Catoni confidence sequence inverted to an empty interval")
        return CatoniConfidenceInterval(
            lower=lower,
            upper=upper,
            observations=self.observations,
            alpha=self.spec.alpha,
            variance_bound=self.spec.variance_bound,
        )


@dataclass(frozen=True, slots=True)
class RobustRandomizedEffectSpec:
    """Typed randomized HT effect monitored through a Catoni heavy-tail CS."""

    metric_name: str
    confidence_sequence: CatoniMixtureSpec
    superiority_margin: float = 0.0
    harm_margin: float = 0.0
    min_propensity: float = 0.05
    higher_is_better: bool = True
    estimand: str = "stationary_randomized_ht_mean_effect"

    def __post_init__(self) -> None:
        if not self.metric_name.strip():
            raise ValueError("metric_name cannot be empty")
        for name, value in (
            ("superiority_margin", self.superiority_margin),
            ("harm_margin", self.harm_margin),
            ("min_propensity", self.min_propensity),
        ):
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0 < self.min_propensity < 0.5:
            raise ValueError("min_propensity must be in (0, 0.5)")
        if self.harm_margin > self.superiority_margin:
            raise ValueError("harm_margin cannot exceed superiority_margin")
        if self.estimand != "stationary_randomized_ht_mean_effect":
            raise ValueError("unsupported robust randomized estimand")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.robust-randomized-effect.v1",
                "metric_name": self.metric_name,
                "confidence_sequence_fingerprint": self.confidence_sequence.fingerprint,
                "superiority_margin": self.superiority_margin,
                "harm_margin": self.harm_margin,
                "min_propensity": self.min_propensity,
                "higher_is_better": self.higher_is_better,
                "estimand": self.estimand,
                "effect_estimator": "horvitz_thompson_single_unit_contribution",
            }
        )


@dataclass(frozen=True, slots=True)
class RobustEffectSnapshot:
    decision: RobustEffectDecision
    observations: int
    lower: float
    upper: float
    superiority_margin: float
    harm_margin: float
    protocol_fingerprint: str


class RobustRandomizedEffectMonitor:
    """Single-metric heavy-tail randomized-effect evidence plane.

    Each unique randomized analysis unit contributes one Horvitz-Thompson scalar
    `A*Y/p - (1-A)*Y/(1-p)`, oriented so positive means challenger is better.
    The Catoni variance bound applies to this scalar contribution, not directly to
    raw outcome variance. The monitor stores only experiment-scoped unit hashes.

    The class emits evidence only. It does not mutate a champion, ramp traffic, or
    override SRM, censoring, cluster, legal, or safety authorities.
    """

    def __init__(self, *, experiment_id: str, spec: RobustRandomizedEffectSpec) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id cannot be empty")
        self.experiment_id = experiment_id
        self.spec = spec
        self.cs = CatoniMixtureConfidenceSequence(spec.confidence_sequence)
        self._unit_tokens: set[bytes] = set()

    def _unit_token(self, analysis_unit_id: str) -> bytes:
        if not analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        return blake2b(
            f"{self.experiment_id}|robust-effect|{analysis_unit_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    @property
    def observations(self) -> int:
        return self.cs.observations

    def update(
        self,
        *,
        analysis_unit_id: str,
        assigned_to_challenger: bool,
        assignment_probability: float,
        outcome: float,
    ) -> RobustEffectSnapshot:
        probability = float(assignment_probability)
        outcome = float(outcome)
        if not isfinite(probability) or not 0 < probability < 1:
            raise ValueError("assignment_probability must be finite and in (0, 1)")
        if probability < self.spec.min_propensity or probability > 1.0 - self.spec.min_propensity:
            raise ValueError("assignment_probability violates the preregistered support floor")
        if not isfinite(outcome):
            raise ValueError("outcome must be finite")

        token = self._unit_token(analysis_unit_id)
        if token in self._unit_tokens:
            raise ValueError("analysis unit already contributed to robust effect evidence")

        if assigned_to_challenger:
            contribution = outcome / probability
        else:
            contribution = -outcome / (1.0 - probability)
        if not self.spec.higher_is_better:
            contribution = -contribution
        if not isfinite(contribution):
            raise ValueError("Horvitz-Thompson contribution overflowed")

        # Atomicity: mutate dedupe/evidence only after every numeric check passes.
        self.cs.update(contribution)
        self._unit_tokens.add(token)
        return self.snapshot()

    def snapshot(self) -> RobustEffectSnapshot:
        interval = self.cs.interval()
        decision = RobustEffectDecision.HOLD
        if interval.observations:
            if interval.lower > self.spec.superiority_margin:
                decision = RobustEffectDecision.SUPPORTS_SUPERIORITY
            elif interval.upper < self.spec.harm_margin:
                decision = RobustEffectDecision.SUPPORTS_HARM
        return RobustEffectSnapshot(
            decision=decision,
            observations=interval.observations,
            lower=interval.lower,
            upper=interval.upper,
            superiority_margin=self.spec.superiority_margin,
            harm_margin=self.spec.harm_margin,
            protocol_fingerprint=self.spec.fingerprint,
        )
