from __future__ import annotations

import pytest

from growthevo.causal import (
    PropensitySupportProtocol,
    calibrate_pairwise_propensity_model,
    fit_pairwise_propensity_model,
    make_support_score_provider,
)
from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel


def _record(
    unit_id: str,
    x: float,
    *,
    action: Channel,
    push: float,
    control: float,
) -> LoggedTreatmentRecord:
    email = 1.0 - push - control
    return LoggedTreatmentRecord(
        unit_id=unit_id,
        features=(x,),
        action=action,
        outcome=0.0,
        action_propensities={
            Channel.PUSH: push,
            Channel.NO_TREATMENT: control,
            Channel.EMAIL: email,
        },
    )


def test_propensity_model_uses_declared_probabilities_not_realized_action() -> None:
    rows = [
        _record("a", 0.0, action=Channel.EMAIL, push=0.40, control=0.40),
        _record("b", 1.0, action=Channel.NO_TREATMENT, push=0.30, control=0.50),
        _record("c", 2.0, action=Channel.PUSH, push=0.20, control=0.60),
    ]

    fitted = fit_pairwise_propensity_model(
        rows,
        treatment=Channel.PUSH,
        ridge=1e-9,
    )

    # The EMAIL-realized row is still valid supervision because the full logging
    # distribution contains PUSH and NO_TREATMENT probabilities at that context.
    assert fitted.sample_size == 3
    assert fitted.predict((0.0,)).propensity == pytest.approx(0.50, abs=1e-5)
    assert fitted.predict((2.0,)).propensity == pytest.approx(0.25, abs=1e-5)


def test_uncalibrated_point_propensity_cannot_be_promoted_to_support() -> None:
    fitted = fit_pairwise_propensity_model(
        [
            _record("a", 0.0, action=Channel.PUSH, push=0.40, control=0.40),
            _record("b", 1.0, action=Channel.NO_TREATMENT, push=0.30, control=0.50),
        ],
        treatment=Channel.PUSH,
        ridge=1e-9,
    )
    protocol = PropensitySupportProtocol(min_pairwise_probability=0.20)

    with pytest.raises(ValueError, match="calibrated propensity interval"):
        protocol.score(fitted.predict((0.5,)))


def test_split_conformal_interval_makes_overlap_decision_conservative() -> None:
    fitted = fit_pairwise_propensity_model(
        [
            _record("train-a", 0.0, action=Channel.PUSH, push=0.40, control=0.40),
            _record("train-b", 1.0, action=Channel.NO_TREATMENT, push=0.30, control=0.50),
            _record("train-c", 2.0, action=Channel.EMAIL, push=0.20, control=0.60),
        ],
        treatment=Channel.PUSH,
        ridge=1e-9,
    )
    calibration = [
        _record("cal-a", 0.0, action=Channel.EMAIL, push=0.44, control=0.36),
        _record("cal-b", 0.5, action=Channel.PUSH, push=0.37, control=0.43),
        _record("cal-c", 1.0, action=Channel.NO_TREATMENT, push=0.34, control=0.46),
        _record("cal-d", 1.5, action=Channel.EMAIL, push=0.27, control=0.53),
    ]
    calibrated = calibrate_pairwise_propensity_model(
        fitted,
        calibration,
        miscoverage=0.20,
    )
    protocol = PropensitySupportProtocol(min_pairwise_probability=0.21)

    central = calibrated.predict((0.0,))
    edge = calibrated.predict((2.0,))

    assert central.calibrated
    assert central.calibration_size == 4
    assert central.lower_bound is not None
    assert central.upper_bound is not None
    assert central.lower_bound < central.propensity < central.upper_bound
    assert protocol.score(central) == pytest.approx(1.0)
    # The edge point estimate is itself inside the practical-overlap region, but
    # its calibrated interval extends below the declared floor and fails closed.
    assert edge.propensity > 0.21
    assert protocol.score(edge) == pytest.approx(0.0)


def test_feature_local_support_provider_changes_with_serving_context() -> None:
    fitted = fit_pairwise_propensity_model(
        [
            _record("train-a", 0.0, action=Channel.PUSH, push=0.40, control=0.40),
            _record("train-b", 1.0, action=Channel.NO_TREATMENT, push=0.30, control=0.50),
            _record("train-c", 2.0, action=Channel.EMAIL, push=0.20, control=0.60),
        ],
        treatment=Channel.PUSH,
        ridge=1e-9,
    )
    calibrated = calibrate_pairwise_propensity_model(
        fitted,
        [
            _record("cal-a", 0.0, action=Channel.EMAIL, push=0.44, control=0.36),
            _record("cal-b", 0.5, action=Channel.PUSH, push=0.37, control=0.43),
            _record("cal-c", 1.0, action=Channel.NO_TREATMENT, push=0.34, control=0.46),
            _record("cal-d", 1.5, action=Channel.EMAIL, push=0.27, control=0.53),
        ],
        miscoverage=0.20,
    )
    provider = make_support_score_provider(
        {Channel.PUSH: calibrated},
        {Channel.PUSH: PropensitySupportProtocol(min_pairwise_probability=0.21)},
    )

    assert provider(Channel.PUSH, None, (0.0,)) == pytest.approx(1.0)
    assert provider(Channel.PUSH, None, (2.0,)) == pytest.approx(0.0)
