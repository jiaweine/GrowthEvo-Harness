from __future__ import annotations

import pytest

from growthevo.bench import bootstrap_randomized_targeting, infer_randomized_targeting
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


def _records() -> tuple[LoggedTreatmentRecord, ...]:
    return tuple(
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


def test_stratified_bootstrap_returns_reproducible_interval() -> None:
    records = _records()
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


def test_analytic_inference_matches_ipw_policy_difference_and_selected_effect() -> None:
    result = infer_randomized_targeting(
        _records(),
        (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
        selected_fraction=0.5,
    )

    assert result.point.incremental_value_vs_none == pytest.approx(0.75)
    assert result.standard_error == pytest.approx(0.36596252735569995)
    assert result.lower_incremental_value < result.point.incremental_value_vs_none
    assert result.upper_incremental_value > result.point.incremental_value_vs_none
    assert result.selected_incremental_value == pytest.approx(1.5)
    assert result.selected_standard_error == pytest.approx(0.7319250547113999)
    assert result.lower_selected_incremental_value < result.selected_incremental_value
    assert result.upper_selected_incremental_value > result.selected_incremental_value


def test_analytic_inference_is_conditional_on_a_frozen_top_k_policy() -> None:
    records = _records()
    forward = infer_randomized_targeting(
        records,
        (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
        selected_fraction=0.5,
    )
    reverse = infer_randomized_targeting(
        records,
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
        selected_fraction=0.5,
    )

    assert forward.point.incremental_value_vs_none != reverse.point.incremental_value_vs_none
    assert forward.selected_incremental_value != reverse.selected_incremental_value


def test_analytic_inference_requires_two_rows() -> None:
    with pytest.raises(ValueError, match="at least two rows"):
        infer_randomized_targeting(
            (_record(0, True, 1.0),),
            (1.0,),
            selected_fraction=1.0,
        )
