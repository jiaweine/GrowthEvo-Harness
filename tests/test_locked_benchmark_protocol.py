from __future__ import annotations

from dataclasses import replace
from json import loads

import pytest

from growthevo.bench.locked_evaluation import (
    LockedOPEProtocol,
    LockedTargetingProtocol,
    OPECandidate,
    ope_records_fingerprint,
    treatment_records_fingerprint,
)
from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel
from growthevo.rl.ope import LoggedBanditRecord


def _ope_rows(prefix: str, *, target_q: float) -> tuple[LoggedBanditRecord, ...]:
    rewards = (1.0, 0.0, 1.0, 0.0)
    return tuple(
        LoggedBanditRecord(
            reward=reward,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=target_q,
            target_q=target_q,
            record_id=f"{prefix}-{index}",
        )
        for index, reward in enumerate(rewards)
    )


def _targeting_rows(prefix: str) -> tuple[LoggedTreatmentRecord, ...]:
    actions = (
        Channel.ADS,
        Channel.NO_TREATMENT,
        Channel.ADS,
        Channel.NO_TREATMENT,
        Channel.ADS,
        Channel.NO_TREATMENT,
        Channel.ADS,
        Channel.NO_TREATMENT,
    )
    outcomes = (1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)
    return tuple(
        LoggedTreatmentRecord(
            unit_id=f"{prefix}-{index}",
            features=(float(index),),
            action=action,
            outcome=outcome,
            action_propensities={
                Channel.ADS: 0.5,
                Channel.NO_TREATMENT: 0.5,
            },
        )
        for index, (action, outcome) in enumerate(zip(actions, outcomes, strict=True))
    )


def test_locked_ope_selects_on_validation_then_reveals_only_winner_once() -> None:
    protocol = LockedOPEProtocol(
        [
            OPECandidate("dm", "direct_method"),
            OPECandidate("ips", "ips"),
            OPECandidate("beta", "beta_ips", beta_folds=2),
        ]
    )
    tuning = _ope_rows("tune", target_q=0.6)

    selected = protocol.tune(tuning, reference_value=0.6)

    assert selected.name == "dm"
    assert len(protocol.validation_scores) == 3
    holdout = protocol.evaluate_once(_ope_rows("test", target_q=0.7), reference_value=0.65)
    assert holdout.candidate.name == "dm"
    assert holdout.estimate == pytest.approx(0.7)
    assert holdout.absolute_error == pytest.approx(0.05)

    artifact = protocol.artifact(
        holdout,
        benchmark="open-bandit-ope",
        dataset="obd-test-fixture",
        commit_sha="deadbeef",
    )
    payload = loads(artifact.to_json())
    assert payload["selected_candidate"] == "dm"
    assert payload["metrics"]["estimator"] == "direct_method"
    assert payload["tuning_fingerprint"] != payload["test_fingerprint"]

    with pytest.raises(RuntimeError, match="already been revealed"):
        protocol.evaluate_once(_ope_rows("test-2", target_q=0.7), reference_value=0.65)


def test_locked_ope_fingerprint_is_order_invariant_but_evidence_sensitive() -> None:
    rows = _ope_rows("stable", target_q=0.6)
    assert ope_records_fingerprint(rows) == ope_records_fingerprint(reversed(rows))

    changed = list(rows)
    changed[0] = replace(changed[0], target_q=0.61)
    assert ope_records_fingerprint(rows) != ope_records_fingerprint(changed)

    missing_identity = replace(rows[0], record_id=None)
    with pytest.raises(ValueError, match="record_id"):
        ope_records_fingerprint((missing_identity, *rows[1:]))


def test_locked_ope_rejects_test_equal_to_tuning_evidence() -> None:
    rows = _ope_rows("same", target_q=0.6)
    protocol = LockedOPEProtocol([OPECandidate("dm", "direct_method")])
    protocol.tune(rows, reference_value=0.6)

    with pytest.raises(ValueError, match="must differ"):
        protocol.evaluate_once(reversed(rows), reference_value=0.6)


def test_ope_candidate_hyperparameters_are_predeclared_and_typed() -> None:
    with pytest.raises(ValueError, match="switch_threshold"):
        OPECandidate("switch", "switch_dr")
    with pytest.raises(ValueError, match="only valid"):
        OPECandidate("ips", "ips", switch_threshold=5.0)
    with pytest.raises(ValueError, match="dr_os_lambda"):
        OPECandidate("shrink", "dr_os")

    assert OPECandidate("switch", "switch_dr", switch_threshold=10.0).switch_threshold == 10.0
    assert OPECandidate("shrink", "dr_os", dr_os_lambda=2.0).dr_os_lambda == 2.0


def test_locked_targeting_selects_candidate_on_validation_and_test_is_single_winner() -> None:
    tuning = _targeting_rows("tune")
    protocol = LockedTargetingProtocol(selected_fraction=0.5)
    selected = protocol.tune(
        tuning,
        {
            "good": (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
            "bad": (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
        },
    )

    assert selected == "good"
    by_name = {score.candidate_name: score.result for score in protocol.validation_scores}
    assert by_name["good"].incremental_value_vs_none == pytest.approx(0.5)
    assert by_name["bad"].incremental_value_vs_none == pytest.approx(-0.5)

    holdout = protocol.evaluate_once(
        _targeting_rows("test"),
        (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
    )
    assert holdout.candidate_name == "good"
    assert holdout.result.incremental_value_vs_none == pytest.approx(0.5)

    artifact = protocol.artifact(
        holdout,
        benchmark="criteo-targeting",
        dataset="criteo-test-fixture",
        commit_sha="cafebabe",
    )
    assert loads(artifact.to_json())["metrics"]["incremental_value_vs_none"] == pytest.approx(0.5)

    with pytest.raises(RuntimeError, match="already been revealed"):
        protocol.evaluate_once(
            _targeting_rows("test-2"),
            (8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
        )


def test_targeting_fingerprint_is_order_invariant_and_score_free() -> None:
    rows = _targeting_rows("stable")
    assert treatment_records_fingerprint(rows) == treatment_records_fingerprint(reversed(rows))

    changed = list(rows)
    changed[0] = replace(changed[0], outcome=0.0)
    assert treatment_records_fingerprint(rows) != treatment_records_fingerprint(changed)
