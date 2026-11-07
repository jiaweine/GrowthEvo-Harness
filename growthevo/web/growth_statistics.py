"""Conservative experiment diagnostics using the Python standard library.

These are descriptive monitoring checks; statistical significance must not be
confused with an audited causal estimate or a shipping authorization.
"""
from __future__ import annotations

from math import exp, isfinite, lgamma, log, sqrt
from typing import Any


def wilson_95(successes: int, trials: int) -> list[float] | None:
    """Wilson score interval for a binomial proportion (95% coverage target)."""
    if trials == 0:
        return None
    if not (0 <= successes <= trials):
        raise ValueError("invalid binomial observations")
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    halfwidth = z / denominator * sqrt(
        p * (1 - p) / trials + z * z / (4 * trials * trials)
    )
    return [max(0.0, center - halfwidth), min(1.0, center + halfwidth)]


def _regularized_gamma_upper(a: float, x: float) -> float:
    """Gamma Q(a,x) for chi-square survival probabilities.

    Standard series and continued-fraction evaluation; bounded iteration and
    convergence threshold prevent an unbounded computation in an API request.
    """
    if not (a > 0 and x >= 0 and isfinite(a) and isfinite(x)):
        raise ValueError("invalid gamma arguments")
    if x == 0:
        return 1.0
    threshold, minimum = 1e-13, 1e-300
    factor = exp(a * log(x) - x - lgamma(a))
    if x < a + 1:
        term = 1.0 / a
        total = term
        for i in range(1, 1001):
            term *= x / (a + i)
            total += term
            if abs(term) <= abs(total) * threshold:
                return max(0.0, min(1.0, 1 - total * factor))
        raise ArithmeticError("gamma series failed to converge")
    b = x + 1 - a
    c = 1.0 / minimum
    d = 1.0 / (b if abs(b) >= minimum else minimum)
    total = d
    for i in range(1, 1001):
        coefficient = -i * (i - a)
        b += 2
        d = coefficient * d + b
        if abs(d) < minimum:
            d = minimum
        c = b + coefficient / c
        if abs(c) < minimum:
            c = minimum
        d = 1.0 / d
        delta = d * c
        total *= delta
        if abs(delta - 1) <= threshold:
            return max(0.0, min(1.0, total * factor))
    raise ArithmeticError("gamma fraction failed to converge")


def sample_ratio_diagnostics(
    observed: dict[str, int], weights: dict[str, int],
) -> dict[str, Any]:
    """Chi-square SRM monitor; require >=20 total distinct exposed customers."""
    if set(observed) != set(weights) or sum(weights.values()) != 100:
        raise ValueError("SRM arms or weights do not match the experiment")
    total = sum(observed.values())
    expected = {arm: total * weight / 100 for arm, weight in weights.items()}
    if total < 20:
        return {
            "status": "insufficient_exposures", "p_value": None,
            "chi_square": None, "exposed_total": total,
            "expected_exposures": expected,
        }
    chi_square = sum(
        (observed[arm] - count) ** 2 / count
        for arm, count in expected.items()
    )
    p_value = _regularized_gamma_upper((len(weights) - 1) / 2, chi_square / 2)
    return {
        "status": "warning" if p_value < 0.01 else "pass",
        "p_value": p_value, "chi_square": chi_square,
        "exposed_total": total, "expected_exposures": expected,
    }
