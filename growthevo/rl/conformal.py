from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
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

    def __post_init__(self) -> None:
        for name, value in (
            ("predicted_value_delta", self.predicted_value_delta),
            ("observed_value_delta", self.observed_value_delta),
            ("predicted_roi", self.predicted_roi),
            ("observed_roi", self.observed_roi),
            ("predicted_spend", self.predicted_spend),
            ("observed_spend", self.observed_spend),
            ("predicted_fatigue", self.predicted_fatigue),
            ("observed_fatigue", self.observed_fatigue),
            ("predicted_churn_risk", self.predicted_churn_risk),
            ("observed_churn_risk", self.observed_churn_risk),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class ConformalMargins:
    """One-sided non-negative error margins, not absolute metric bounds.

    ``alpha`` is the requested gate-level error budget. ``per_metric_alpha`` is
    the marginal level actually used by the calibration rule. ``quantile_rank``
    records the finite-sample order statistic used for every metric so a
    verifier/audit artifact can reconstruct the calibration decision.
    """

    alpha: float
    calibration_size: int
    simultaneous: bool
    metric_count: int
    per_metric_alpha: float
    quantile_rank: int
    value_lower_margin: float
    roi_lower_margin: float
    spend_upper_margin: float
    fatigue_upper_margin: float
    churn_risk_upper_margin: float

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


def _conformal_rank(calibration_size: int, alpha: float) -> int:
    if calibration_size <= 0:
        raise ValueError("calibration_size must be positive")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    return ceil((calibration_size + 1) * (1.0 - alpha))


def _conservative_quantile(
    residuals: list[float],
    *,
    alpha: float,
    rank: int,
) -> float:
    """Finite-sample split-conformal one-sided quantile without rank clipping."""

    if not residuals:
        raise ValueError("at least one calibration residual is required")
    if rank > len(residuals):
        raise ValueError(
            "calibration cohort is too small for the requested conformal "
            f"miscoverage: rank={rank}, calibration_size={len(residuals)}, alpha={alpha}"
        )
    ordered = sorted(residuals)
    return max(0.0, ordered[rank - 1])


class ConformalPolicyCalibrator:
    """Calibrate promotion margins from matured policy cohorts.

    Both the gate-level error budget and whether it should be allocated jointly
    across metrics are experiment/deployment protocol choices and therefore have
    no package defaults. ``min_calibration_size`` is an optional additional
    operational evidence gate supplied by the caller; finite-sample conformal
    feasibility is checked independently from the exact order-statistic rank.

    With ``simultaneous=True`` this reference implementation uses Bonferroni
    allocation over the actual calibrated metric set. This controls the family
    error budget conservatively under the usual split-conformal exchangeability
    assumptions without assuming independence between metrics.
    """

    def __init__(
        self,
        *,
        alpha: float,
        simultaneous: bool,
        min_calibration_size: int | None = None,
    ) -> None:
        if not isfinite(alpha) or not 0 < alpha < 1:
            raise ValueError("alpha must be a finite value in (0, 1)")
        if min_calibration_size is not None and min_calibration_size <= 0:
            raise ValueError("min_calibration_size must be positive when provided")
        self.alpha = alpha
        self.min_calibration_size = min_calibration_size
        self.simultaneous = bool(simultaneous)

    def fit(self, records: Iterable[ConformalCalibrationRecord]) -> ConformalMargins:
        rows = list(records)
        if not rows:
            raise ValueError("at least one calibration cohort is required")
        if self.min_calibration_size is not None and len(rows) < self.min_calibration_size:
            raise ValueError(
                f"need at least {self.min_calibration_size} calibration cohorts by protocol, "
                f"got {len(rows)}"
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
        rank = _conformal_rank(len(rows), per_metric_alpha)
        if rank > len(rows):
            raise ValueError(
                "calibration cohort cannot support the requested finite-sample "
                f"conformal error budget: gate_alpha={self.alpha}, "
                f"per_metric_alpha={per_metric_alpha}, calibration_size={len(rows)}, "
                f"required_rank={rank}. Increase calibration data or choose a different "
                "pre-declared error allocation."
            )

        def margin(name: str) -> float:
            return _conservative_quantile(
                residuals[name],
                alpha=per_metric_alpha,
                rank=rank,
            )

        return ConformalMargins(
            alpha=self.alpha,
            calibration_size=len(rows),
            simultaneous=self.simultaneous,
            metric_count=metric_count,
            per_metric_alpha=per_metric_alpha,
            quantile_rank=rank,
            value_lower_margin=margin("value"),
            roi_lower_margin=margin("roi"),
            spend_upper_margin=margin("spend"),
            fatigue_upper_margin=margin("fatigue"),
            churn_risk_upper_margin=margin("churn"),
        )
