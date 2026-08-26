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
    """One-sided non-negative error margins, not absolute metric bounds.

    ``alpha`` is the requested gate-level error budget. ``per_metric_alpha`` is
    the marginal level used when simultaneous calibration is enabled. The number
    of calibrated metrics is derived from the actual residual collection rather
    than duplicated as a separate constant.
    """

    alpha: float
    calibration_size: int
    value_lower_margin: float
    roi_lower_margin: float
    spend_upper_margin: float
    fatigue_upper_margin: float
    churn_risk_upper_margin: float
    per_metric_alpha: float | None = None

    def value_lcb(self, predicted_delta: float) -> float:
        return predicted_delta - self.value_lower_margin

    def roi_lcb(self, predicted_roi: float) -> float:
        return predicted_roi - self.roi_lower_margin

    def spend_ucb(self, predicted_spend: float) -> float:
        return predicted_spend + self.spend_upper_margin

    def fatigue_ucb(self, predicted_fatigue: float) -> float:
        return predicted_fatigue + self.fatigue_upper_margin

    def churn_risk_ucb(self, predicted_churn_risk: float) -> float:
        return predicted_churn_risk + self.churn_risk_upper_margin


def _conservative_quantile(residuals: list[float], alpha: float) -> float:
    """Finite-sample split-conformal one-sided quantile."""

    if not residuals:
        raise ValueError("at least one calibration residual is required")
    ordered = sorted(residuals)
    rank = min(len(ordered), ceil((len(ordered) + 1) * (1.0 - alpha)))
    return max(0.0, ordered[rank - 1])


class ConformalPolicyCalibrator:
    """Calibrate simultaneous promotion bounds from matured policy cohorts.

    Promotion checks several metrics at once. Reusing the full marginal error
    budget independently for every metric does not preserve a gate-level error
    budget, so simultaneous calibration is enabled by default. The Bonferroni
    allocation is computed from the actual calibrated metric set.
    """

    def __init__(
        self,
        alpha: float = 0.05,
        min_calibration_size: int = 30,
        *,
        simultaneous: bool = True,
    ) -> None:
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if min_calibration_size <= 0:
            raise ValueError("min_calibration_size must be positive")
        self.alpha = alpha
        self.min_calibration_size = min_calibration_size
        self.simultaneous = simultaneous

    def fit(self, records: Iterable[ConformalCalibrationRecord]) -> ConformalMargins:
        rows = list(records)
        if len(rows) < self.min_calibration_size:
            raise ValueError(
                f"need at least {self.min_calibration_size} calibration cohorts, got {len(rows)}"
            )

        residuals = {
            "value": [row.predicted_value_delta - row.observed_value_delta for row in rows],
            "roi": [row.predicted_roi - row.observed_roi for row in rows],
            "spend": [row.observed_spend - row.predicted_spend for row in rows],
            "fatigue": [row.observed_fatigue - row.predicted_fatigue for row in rows],
            "churn": [
                row.observed_churn_risk - row.predicted_churn_risk for row in rows
            ],
        }
        metric_count = len(residuals)
        if metric_count <= 0:  # pragma: no cover - defensive for future refactors.
            raise RuntimeError("no conformal metrics configured")
        per_metric_alpha = self.alpha / metric_count if self.simultaneous else self.alpha

        return ConformalMargins(
            alpha=self.alpha,
            calibration_size=len(rows),
            value_lower_margin=_conservative_quantile(residuals["value"], per_metric_alpha),
            roi_lower_margin=_conservative_quantile(residuals["roi"], per_metric_alpha),
            spend_upper_margin=_conservative_quantile(residuals["spend"], per_metric_alpha),
            fatigue_upper_margin=_conservative_quantile(residuals["fatigue"], per_metric_alpha),
            churn_risk_upper_margin=_conservative_quantile(residuals["churn"], per_metric_alpha),
            per_metric_alpha=per_metric_alpha,
        )
