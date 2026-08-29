from __future__ import annotations

import pytest

from growthevo.bench import bootstrap_randomized_targeting
from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel


def _record(index: int, treated: bool, outcome: float) -> LoggedTreatmentRecord:
    return LoggedTreatmentRecord(
        unit_id=f"unit-{index}",
        features=(float(index),),
        action=Channel.ADS if treated else Channel.NO_TREATMENT,
        outcome=outcome,
        action_propensities={Channel.ADS: 0.5, Channel.NO_TREATMENT: 0.5},
    )


def test_stratified_bootstrap_returns_reproducible_interval() -> None:
    records = tuple(
        [
            _record(0, True, 1.0),
            _record(1, True, 1.0),
            _record(2, True, 0.0),
            _record(3, True, 1.0),
        ]
        + [
            _record(4, False, 0.0),
            _record(5, False, 0.0),
            _record(6, False, 1.0),
            _record(7, False, 0.0),
        ]
    )
    scores = (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0)

    left = bootstrap_randomized_targeting(
        records,
        scores,
        selected_fraction=0.5,
        replicates=200,
        seed=29,
    )
    right = bootstrap_randomized_targeting(
        records,
        scores,
        selected_fraction=0.5,
        replicates=200,
        seed=29,
    )

    assert left == right
    assert left.lower_incremental_value <= left.point.incremental_value_vs_none <= left.upper_incremental_value
    assert left.bootstrap_standard_error > 0
    assert left.confidence_level == pytest.approx(0.95)
    assert left.replicates == 200
