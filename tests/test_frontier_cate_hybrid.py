from __future__ import annotations

from typing import Iterable, Sequence

import pytest

from growthevo.causal.dr_learner import (
    CrossFittedDRLearner,
    LoggedTreatmentRecord,
)
from growthevo.models import Channel


def _record(
    index: int,
    *,
    action: Channel,
    treatment_probability: float,
    features: tuple[float, ...] | None = None,
    group_id: str | None = None,
) -> LoggedTreatmentRecord:
    x = features or (float(index), float(index) / 10.0)
    outcome = 0.2 + 0.03 * x[0] + (0.1 if action is Channel.ADS else 0.0)
    return LoggedTreatmentRecord(
        unit_id=f"unit-{index}-{action.value}",
        group_id=group_id,
        features=x,
        action=action,
        outcome=outcome,
        action_propensities={
            Channel.ADS: treatment_probability,
            Channel.NO_TREATMENT: 1.0 - treatment_probability,
        },
    )


def test_default_dr_does_not_silently_clip_propensities() -> None:
    rows = [
        _record(0, action=Channel.ADS, treatment_probability=0.01),
        _record(1, action=Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(2, action=Channel.ADS, treatment_probability=0.50),
        _record(3, action=Channel.NO_TREATMENT, treatment_probability=0.50),
        _record(4, action=Channel.ADS, treatment_probability=0.01),
        _record(5, action=Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(6, action=Channel.ADS, treatment_probability=0.50),
        _record(7, action=Channel.NO_TREATMENT, treatment_probability=0.50),
    ]

    fitted = CrossFittedDRLearner(n_folds=2).fit(rows, treatment=Channel.ADS)

    assert fitted.overlap_coverage == pytest.approx(1.0)
    assert fitted.practical_overlap_coverage == pytest.approx(0.5)
    assert fitted.propensity_clip_fraction == pytest.approx(0.0)


def test_explicit_propensity_clipping_is_reported_separately_from_support() -> None:
    rows = [
        _record(0, action=Channel.ADS, treatment_probability=0.01),
        _record(1, action=Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(2, action=Channel.ADS, treatment_probability=0.50),
        _record(3, action=Channel.NO_TREATMENT, treatment_probability=0.50),
        _record(4, action=Channel.ADS, treatment_probability=0.01),
        _record(5, action=Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(6, action=Channel.ADS, treatment_probability=0.50),
        _record(7, action=Channel.NO_TREATMENT, treatment_probability=0.50),
    ]

    fitted = CrossFittedDRLearner(
        n_folds=2,
        practical_overlap_floor=0.02,
        propensity_clip_floor=0.02,
    ).fit(rows, treatment=Channel.ADS)

    assert fitted.overlap_coverage == pytest.approx(1.0)
    assert fitted.practical_overlap_coverage == pytest.approx(0.5)
    assert fitted.propensity_clip_fraction == pytest.approx(0.5)


def test_group_aware_cross_fitting_keeps_repeated_units_in_one_fold() -> None:
    rows: list[LoggedTreatmentRecord] = []
    for group_index in range(4):
        group = f"user-{group_index}"
        rows.extend(
            [
                _record(
                    group_index * 2,
                    action=Channel.ADS,
                    treatment_probability=0.5,
                    group_id=group,
                ),
                _record(
                    group_index * 2 + 1,
                    action=Channel.NO_TREATMENT,
                    treatment_probability=0.5,
                    group_id=group,
                ),
            ]
        )

    learner = CrossFittedDRLearner(n_folds=2)
    assignments = learner._fold_assignments(rows, Channel.ADS, Channel.NO_TREATMENT)

    by_group: dict[str, set[int]] = {}
    for row, fold in zip(rows, assignments, strict=True):
        assert row.group_id is not None
        by_group.setdefault(row.group_id, set()).add(fold)
    assert all(len(folds) == 1 for folds in by_group.values())
    assert set(assignments) == {0, 1}


def test_distributional_support_rejects_off_manifold_point_inside_feature_box() -> None:
    rows: list[LoggedTreatmentRecord] = []
    index = 0
    for value in (0.0, 1.0, 2.0, 3.0):
        for action in (Channel.ADS, Channel.NO_TREATMENT):
            rows.append(
                _record(
                    index,
                    action=action,
                    treatment_probability=0.5,
                    features=(value, value),
                )
            )
            index += 1

    fitted = CrossFittedDRLearner(n_folds=2, support_quantile=0.75).fit(
        rows,
        treatment=Channel.ADS,
    )
    on_manifold = fitted.predict((1.5, 1.5))
    off_manifold = fitted.predict((0.5, 2.5))

    assert off_manifold.extrapolation_distance > on_manifold.extrapolation_distance
    assert off_manifold.support_score < on_manifold.support_score
    assert off_manifold.uncertainty > on_manifold.uncertainty


class MeanRegressor:
    def __init__(self) -> None:
        self.mean = 0.0

    def fit(
        self,
        features: Iterable[Sequence[float]],
        targets: Iterable[float],
    ) -> "MeanRegressor":
        rows = list(features)
        values = list(targets)
        if not rows or len(rows) != len(values):
            raise ValueError("aligned data required")
        self.mean = sum(values) / len(values)
        return self

    def predict_one(self, features: Sequence[float]) -> float:
        _ = tuple(features)
        return self.mean


def test_nuisance_and_effect_backends_are_pluggable() -> None:
    rows = [
        _record(index, action=action, treatment_probability=0.5)
        for index, action in enumerate(
            (
                Channel.ADS,
                Channel.NO_TREATMENT,
                Channel.ADS,
                Channel.NO_TREATMENT,
                Channel.ADS,
                Channel.NO_TREATMENT,
            )
        )
    ]
    fitted = CrossFittedDRLearner(
        n_folds=2,
        outcome_model_factory=MeanRegressor,
        effect_model_factory=MeanRegressor,
    ).fit(rows, treatment=Channel.ADS)

    assert isinstance(fitted.model, MeanRegressor)
    assert fitted.predict((1.0, 0.1)).effect == pytest.approx(fitted.model.mean)


def test_exact_pairwise_positivity_violation_fails_closed() -> None:
    rows = []
    for index in range(6):
        action = Channel.ADS if index % 2 == 0 else Channel.NO_TREATMENT
        propensities = (
            {Channel.ADS: 1.0, Channel.NO_TREATMENT: 0.0}
            if action is Channel.ADS
            else {Channel.ADS: 0.0, Channel.NO_TREATMENT: 1.0}
        )
        rows.append(
            LoggedTreatmentRecord(
                unit_id=f"u-{index}",
                features=(float(index),),
                action=action,
                outcome=float(index % 2),
                action_propensities=propensities,
            )
        )

    with pytest.raises(ValueError, match="positivity violated"):
        CrossFittedDRLearner(n_folds=2).fit(rows, treatment=Channel.ADS)