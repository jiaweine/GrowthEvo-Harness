from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ConformalCalibrationRecord:
    """Paired predicted/observed cohort metrics for split-conformal calibration.

    The record is intentionally policy-level rather than user-level. A caller
    should construct it from historical shadow/canary cohorts whose metrics have
    matured. Under exchangeability between calibration and future cohorts, the
    one-sided margins provide finite-sample coverage in the usual split-
    conformal sense. Distribution shift must still be handled explicitly.
    """

    predicted_value_delta: float
    observed_value_delta: float
    predicted_roi: float
    observed_roi: float
    predicted_spend: float
    observed_spend: float
    predicted_fatigue: float
    observed_fatigue: float
    predicted_churn_risk: float
    observed_churn_risk: float


@dataclass(frozen=True, slots=True)
class ConformalMargins:
    alpha: float
    calibration_size: int
    value_lower: float
    roi_lower: float
    spend_upper: float
    fatigue_upper: float
    churn_risk_upper: float

    def value_lcb(self, predicted_delta: float) -> float:
        return predicted_delta - self.value_lower

    def roi_lcb(self, predicted_roi: float) -> float:
        return predicted_roi - self.roi_lower

    def spend_ucb(self, predicted_spend: float) -> float:
        return predicted_spend + self.spend_upper

    def fatigue_ucb(self, predicted_fatigue: float) -> float:
        return predicted_fatigue + self.fatigue_upper

    def churn_risk_ucb(self, predicted_churn_risk: float) -> float:
        return predicted_churn_risk + self.churn_risk_upper


def _conservative_quantile(residuals: list[float], alpha: float) -> float:
    """Finite-sample split-conformal one-sided quantile.

    The rank is ceil((n + 1) * (1 - alpha)), capped at n. We clip the margin at
    zero so calibration can never make the promotion gate less conservative than
    the raw prediction.
    """

    if not residuals:
        raise ValueError("at least one calibration residual is required")
    ordered = sorted(residuals)
    rank = min(len(ordered), ceil((len(ordered) + 1) * (1.0 - alpha)))
    return max(0.0, ordered[rank - 1])


class ConformalPolicyCalibrator:
    """Calibrate value and constraint predictions from matured shadow cohorts."""

    def __init__(self, alpha: float = 0.05, min_calibration_size: int = 30) -> None:
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if min_calibration_size <= 0:
            raise ValueError("min_calibration_size must be positive")
        self.alpha = alpha
        self.min_calibration_size = min_calibration_size

    def fit(self, records: Iterable[ConformalCalibrationRecord]) -> ConformalMargins:
        rows = list(records)
        if len(rows) < self.min_calibration_size:
            raise ValueError(
                f"need at least {self.min_calibration_size} calibration cohorts, got {len(rows)}"
            )

        # Lower-bound quantities use predicted - observed residuals. Upper-bound
        # risk/cost quantities use observed - predicted residuals.
        value_residuals = [
            row.predicted_value_delta - row.observed_value_delta for row in rows
        ]
        roi_residuals = [row.predicted_roi - row.observed_roi for row in rows]
        spend_residuals = [row.observed_spend - row.predicted_spend for row in rows]
        fatigue_residuals = [
            row.observed_fatigue - row.predicted_fatigue for row in rows
        ]
        churn_residuals = [
            row.observed_churn_risk - row.predicted_churn_risk for row in rows
        ]

        return ConformalMargins(
            alpha=self.alpha,
            calibration_size=len(rows),
            value_lower=_conservative_quantile(value_residuals, self.alpha),
            roi_lower=_conservative_quantile(roi_residuals, self.alpha),
            spend_upper=_conservative_quantile(spend_residuals, self.alpha),
            fatigue_upper=_conservative_quantile(fatigue_residuals, self.alpha),
            churn_risk_upper=_conservative_quantile(churn_residuals, self.alpha),
        )
