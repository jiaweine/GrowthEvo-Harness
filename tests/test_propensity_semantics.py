from __future__ import annotations

import pytest

from growthevo.causal.dr_learner import CrossFittedDRLearner, LoggedTreatmentRecord
from growthevo.models import Channel


def _record(
    index: int,
    action: Channel,
    *,
    treatment_probability: float,
) -> LoggedTreatmentRecord:
    return LoggedTreatmentRecord(
        unit_id=f"row-{index}",
        features=(float(index),),
        action=action,
        outcome=float(action is Channel.PUSH),
        action_propensities={
            Channel.NO_TREATMENT: 1.0 - treatment_probability,
            Channel.PUSH: treatment_probability,
        },
    )


def _extreme_overlap_rows() -> list[LoggedTreatmentRecord]:
    return [
        _record(0, Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(1, Channel.PUSH, treatment_probability=0.99),
        _record(2, Channel.NO_TREATMENT, treatment_probability=0.01),
        _record(3, Channel.PUSH, treatment_probability=0.99),
        _record(4, Channel.NO_TREATMENT, treatment_probability=0.40),
        _record(5, Channel.PUSH, treatment_probability=0.60),
        _record(6, Channel.NO_TREATMENT, treatment_probability=0.40),
        _record(7, Channel.PUSH, treatment_probability=0.60),
    ]


def test_dr_does_not_clip_propensity_by_default() -> None:
    model = CrossFittedDRLearner(n_folds=2).fit(
        _extreme_overlap_rows(),
        treatment=Channel.PUSH,
    )

    assert model.overlap_coverage == pytest.approx(1.0)
    assert model.practical_overlap_coverage is None
    assert model.propensity_clip_fraction == pytest.approx(0.0)


def test_practical_overlap_threshold_does_not_imply_clipping() -> None:
    model = CrossFittedDRLearner(
        n_folds=2,
        practical_overlap_floor=0.05,
    ).fit(
        _extreme_overlap_rows(),
        treatment=Channel.PUSH,
    )

    assert model.practical_overlap_coverage == pytest.approx(0.5)
    assert model.propensity_clip_fraction == pytest.approx(0.0)


def test_explicit_propensity_clipping_is_reported() -> None:
    model = CrossFittedDRLearner(
        n_folds=2,
        propensity_clip_floor=0.05,
    ).fit(
        _extreme_overlap_rows(),
        treatment=Channel.PUSH,
    )

    assert model.propensity_clip_fraction == pytest.approx(0.5)


def test_exact_pairwise_positivity_violation_is_rejected() -> None:
    rows = [
        _record(0, Channel.NO_TREATMENT, treatment_probability=0.0),
        _record(1, Channel.PUSH, treatment_probability=0.5),
        _record(2, Channel.NO_TREATMENT, treatment_probability=0.5),
        _record(3, Channel.PUSH, treatment_probability=0.5),
    ]

    with pytest.raises(ValueError, match="pairwise positivity violated"):
        CrossFittedDRLearner(n_folds=2).fit(rows, treatment=Channel.PUSH)
