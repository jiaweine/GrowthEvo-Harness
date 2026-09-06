from __future__ import annotations

import pytest

from growthevo.evolution.outcome_maturity import (
    OutcomeFollowupState,
    OutcomeMaturityLedger,
    OutcomeMaturitySpec,
)


def _spec() -> OutcomeMaturitySpec:
    return OutcomeMaturitySpec(
        endpoint_name="day7_incremental_value",
        maturity_delay_seconds=7 * 24 * 3600,
        ingestion_grace_seconds=6 * 3600,
    )


def test_maturity_spec_fingerprint_changes_with_followup_contract() -> None:
    base = _spec()
    changed = OutcomeMaturitySpec(
        endpoint_name=base.endpoint_name,
        maturity_delay_seconds=base.maturity_delay_seconds + 1,
        ingestion_grace_seconds=base.ingestion_grace_seconds,
    )
    assert base.fingerprint != changed.fingerprint


def test_exposure_registration_is_idempotent_but_signature_is_frozen() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    first = ledger.register_exposure(
        "user-1",
        assigned_to_challenger=True,
        exposure_at=100,
    )
    second = ledger.register_exposure(
        "user-1",
        assigned_to_challenger=True,
        exposure_at=100,
    )
    assert first == second
    with pytest.raises(ValueError, match="signature changed"):
        ledger.register_exposure(
            "user-1",
            assigned_to_challenger=False,
            exposure_at=100,
        )


def test_outcome_cannot_finalize_before_preregistered_maturity() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    ticket = ledger.register_exposure(
        "user-1",
        assigned_to_challenger=True,
        exposure_at=100,
    )
    with pytest.raises(ValueError, match="before preregistered maturity"):
        ledger.record_outcome(
            "user-1",
            observed_at=ticket.maturity_at - 1,
            outcome_fingerprint="outcome-v1",
        )
    snapshot = ledger.snapshot(as_of=ticket.maturity_at - 1)
    assert snapshot.matured_on_time == 0
    assert snapshot.pending_followup == 1


def test_pipeline_participant_forces_wait_after_enrollment_closes() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    early = ledger.register_exposure(
        "early",
        assigned_to_challenger=False,
        exposure_at=100,
    )
    late = ledger.register_exposure(
        "late",
        assigned_to_challenger=True,
        exposure_at=1000,
    )
    ledger.close_enrollment(closed_at=1000)

    ledger.record_outcome(
        "early",
        observed_at=early.maturity_at,
        outcome_fingerprint="early-outcome",
    )
    snapshot = ledger.snapshot(as_of=late.maturity_at - 1)
    assert snapshot.pending_followup == 1
    assert not snapshot.complete_case_ready
    assert "pipeline_participants_pending_followup" in snapshot.reasons
    with pytest.raises(ValueError, match="promotion authority unavailable"):
        ledger.seal_complete_case_analysis(as_of=late.maturity_at - 1)


def test_all_frozen_units_must_arrive_by_preregistered_cutoff() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    control = ledger.register_exposure(
        "control",
        assigned_to_challenger=False,
        exposure_at=10,
    )
    challenger = ledger.register_exposure(
        "challenger",
        assigned_to_challenger=True,
        exposure_at=10,
    )
    ledger.close_enrollment(closed_at=10)
    ledger.record_outcome(
        "control",
        observed_at=control.maturity_at,
        outcome_fingerprint="control-outcome",
    )

    snapshot = ledger.snapshot(as_of=challenger.accept_until + 1)
    assert snapshot.overdue_missing == 1
    assert not snapshot.complete_case_ready
    assert "outcomes_missing_after_preregistered_cutoff" in snapshot.reasons
    with pytest.raises(ValueError, match="promotion authority unavailable"):
        ledger.seal_complete_case_analysis(as_of=challenger.accept_until + 1)


def test_late_outcome_is_rejected_instead_of_adaptively_extending_cutoff() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    ticket = ledger.register_exposure(
        "user-1",
        assigned_to_challenger=True,
        exposure_at=10,
    )
    ledger.close_enrollment(closed_at=10)
    with pytest.raises(ValueError, match="after preregistered ingestion cutoff"):
        ledger.record_outcome(
            "user-1",
            observed_at=ticket.accept_until + 1,
            outcome_fingerprint="late",
        )
    snapshot = ledger.snapshot(as_of=ticket.accept_until + 1)
    assert snapshot.overdue_missing == 1


def test_complete_cohort_earns_seal_only_after_followup_and_grace() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    tickets = [
        ledger.register_exposure(
            f"unit-{index}",
            assigned_to_challenger=bool(index % 2),
            exposure_at=100 + index,
        )
        for index in range(4)
    ]
    ledger.close_enrollment(closed_at=103)
    for index, ticket in enumerate(tickets):
        ledger.record_outcome(
            ticket.analysis_unit_id,
            observed_at=ticket.maturity_at,
            outcome_fingerprint=f"outcome-{index}",
        )

    assert ledger.required_ready_at == tickets[-1].accept_until
    before = ledger.snapshot(as_of=ledger.required_ready_at - 1)
    assert not before.complete_case_ready
    assert "preregistered_followup_window_incomplete" in before.reasons

    seal = ledger.seal_complete_case_analysis(as_of=ledger.required_ready_at)
    assert seal.total_units == 4
    assert seal.matured_on_time == 4
    assert seal.challenger_units == 2
    assert seal.control_units == 2
    assert ledger.verify_audit_chain()
    with pytest.raises(RuntimeError, match="sealed"):
        ledger.register_exposure(
            "after-seal",
            assigned_to_challenger=True,
            exposure_at=200,
        )


def test_outcome_receipt_is_idempotent_and_tamper_evident() -> None:
    ledger = OutcomeMaturityLedger(experiment_id="exp", spec=_spec())
    ticket = ledger.register_exposure(
        "user-1",
        assigned_to_challenger=True,
        exposure_at=10,
    )
    first = ledger.record_outcome(
        "user-1",
        observed_at=ticket.maturity_at,
        outcome_fingerprint="same",
    )
    second = ledger.record_outcome(
        "user-1",
        observed_at=ticket.maturity_at,
        outcome_fingerprint="same",
    )
    assert first == second
    with pytest.raises(ValueError, match="changed after first acceptance"):
        ledger.record_outcome(
            "user-1",
            observed_at=ticket.maturity_at,
            outcome_fingerprint="different",
        )


def test_followup_state_enum_is_explicit_for_downstream_policy() -> None:
    assert OutcomeFollowupState.PENDING_FOLLOWUP.value == "pending_followup"
    assert OutcomeFollowupState.OVERDUE_MISSING.value == "overdue_missing"
