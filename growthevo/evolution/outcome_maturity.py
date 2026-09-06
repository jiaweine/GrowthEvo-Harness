from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b, sha256
import json
from typing import Any, Mapping


class OutcomeFollowupState(str, Enum):
    PENDING_FOLLOWUP = "pending_followup"
    AWAITING_INGESTION = "awaiting_ingestion"
    MATURED_ON_TIME = "matured_on_time"
    OVERDUE_MISSING = "overdue_missing"


@dataclass(frozen=True, slots=True)
class OutcomeMaturitySpec:
    """Frozen endpoint follow-up contract for complete-case promotion authority."""

    endpoint_name: str
    maturity_delay_seconds: int
    ingestion_grace_seconds: int = 0
    clock_contract: str = "event_time_utc_seconds_v1"

    def __post_init__(self) -> None:
        if not self.endpoint_name.strip():
            raise ValueError("endpoint_name cannot be empty")
        if not self.clock_contract.strip():
            raise ValueError("clock_contract cannot be empty")
        if (
            isinstance(self.maturity_delay_seconds, bool)
            or not isinstance(self.maturity_delay_seconds, int)
            or self.maturity_delay_seconds <= 0
        ):
            raise ValueError("maturity_delay_seconds must be a positive integer")
        if (
            isinstance(self.ingestion_grace_seconds, bool)
            or not isinstance(self.ingestion_grace_seconds, int)
            or self.ingestion_grace_seconds < 0
        ):
            raise ValueError("ingestion_grace_seconds must be a non-negative integer")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {"schema": "growthevo.outcome-maturity-spec.v1", **asdict(self)}
        )


@dataclass(frozen=True, slots=True)
class OutcomeMaturityTicket:
    analysis_unit_id: str
    assigned_to_challenger: bool
    exposure_at: int
    maturity_at: int
    accept_until: int
    ticket_fingerprint: str


@dataclass(frozen=True, slots=True)
class OutcomeReceipt:
    ticket_fingerprint: str
    observed_at: int
    outcome_fingerprint: str
    receipt_fingerprint: str


@dataclass(frozen=True, slots=True)
class OutcomeMaturitySnapshot:
    as_of: int
    enrollment_closed: bool
    enrollment_closed_at: int | None
    total_units: int
    challenger_units: int
    control_units: int
    matured_on_time: int
    pending_followup: int
    awaiting_ingestion: int
    overdue_missing: int
    challenger_matured_on_time: int
    control_matured_on_time: int
    complete_case_ready: bool
    required_ready_at: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaturityAuditEvent:
    sequence: int
    kind: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class CompleteCaseMaturitySeal:
    """Authority that the frozen cohort has complete preregistered follow-up."""

    endpoint_name: str
    maturity_spec_fingerprint: str
    cohort_fingerprint: str
    enrollment_closed_at: int
    analysis_as_of: int
    total_units: int
    challenger_units: int
    control_units: int
    matured_on_time: int
    seal_fingerprint: str


@dataclass(frozen=True, slots=True)
class _MaturityRecord:
    unit_token_hex: str
    assigned_to_challenger: bool
    exposure_at: int
    maturity_at: int
    accept_until: int
    ticket_fingerprint: str
    receipt: OutcomeReceipt | None = None


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _timestamp(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer timestamp")
    return value


def _receipt_fingerprint(
    *,
    ticket_fingerprint: str,
    observed_at: int,
    outcome_fingerprint: str,
) -> str:
    return _fingerprint(
        {
            "schema": "growthevo.outcome-receipt.v1",
            "ticket_fingerprint": ticket_fingerprint,
            "observed_at": observed_at,
            "outcome_fingerprint": outcome_fingerprint,
        }
    )


class OutcomeMaturityLedger:
    """Privacy-preserving cohort ledger for delayed primary outcomes.

    The v1 complete-case authority is intentionally strict. After enrollment is
    frozen, every analysis unit must finish the preregistered follow-up and its
    endpoint must arrive by the preregistered ingestion cutoff. Missing or late
    endpoints require a different estimand/protocol rather than silent deletion.
    """

    def __init__(self, *, experiment_id: str, spec: OutcomeMaturitySpec) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id cannot be empty")
        self.experiment_id = experiment_id
        self.spec = spec
        self._records: dict[bytes, _MaturityRecord] = {}
        self._enrollment_closed_at: int | None = None
        self._sealed = False
        self._events: list[MaturityAuditEvent] = []
        self._append(
            "maturity_ledger_registered",
            {
                "experiment_id_hash": sha256(experiment_id.encode("utf-8")).hexdigest(),
                "maturity_spec_fingerprint": spec.fingerprint,
            },
        )

    def _unit_token(self, analysis_unit_id: str) -> bytes:
        if not analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        return blake2b(
            f"{self.experiment_id}|maturity|{analysis_unit_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    @staticmethod
    def _digest(
        sequence: int,
        kind: str,
        payload: Mapping[str, Any],
        previous_hash: str,
    ) -> str:
        return _sha256(
            {
                "sequence": sequence,
                "kind": kind,
                "payload": payload,
                "previous_hash": previous_hash,
            }
        )

    def _append(self, kind: str, payload: Mapping[str, Any]) -> MaturityAuditEvent:
        sequence = len(self._events)
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        primitive = json.loads(json.dumps(payload, sort_keys=True))
        event = MaturityAuditEvent(
            sequence=sequence,
            kind=kind,
            payload=primitive,
            previous_hash=previous_hash,
            event_hash=self._digest(sequence, kind, primitive, previous_hash),
        )
        self._events.append(event)
        return event

    def _ticket_from_record(
        self,
        analysis_unit_id: str,
        record: _MaturityRecord,
    ) -> OutcomeMaturityTicket:
        return OutcomeMaturityTicket(
            analysis_unit_id=analysis_unit_id,
            assigned_to_challenger=record.assigned_to_challenger,
            exposure_at=record.exposure_at,
            maturity_at=record.maturity_at,
            accept_until=record.accept_until,
            ticket_fingerprint=record.ticket_fingerprint,
        )

    def register_exposure(
        self,
        analysis_unit_id: str,
        *,
        assigned_to_challenger: bool,
        exposure_at: int,
    ) -> OutcomeMaturityTicket:
        if self._sealed:
            raise RuntimeError("maturity ledger is sealed")
        if self._enrollment_closed_at is not None:
            raise RuntimeError("enrollment is already closed")
        exposure_at = _timestamp(exposure_at, "exposure_at")
        token = self._unit_token(analysis_unit_id)
        existing = self._records.get(token)
        if existing is not None:
            if (
                existing.assigned_to_challenger != bool(assigned_to_challenger)
                or existing.exposure_at != exposure_at
            ):
                raise ValueError("analysis unit exposure signature changed")
            return self._ticket_from_record(analysis_unit_id, existing)

        maturity_at = exposure_at + self.spec.maturity_delay_seconds
        accept_until = maturity_at + self.spec.ingestion_grace_seconds
        ticket_fingerprint = _fingerprint(
            {
                "schema": "growthevo.outcome-maturity-ticket.v1",
                "experiment_id": self.experiment_id,
                "unit_token": token.hex(),
                "assigned_to_challenger": bool(assigned_to_challenger),
                "exposure_at": exposure_at,
                "maturity_at": maturity_at,
                "accept_until": accept_until,
                "maturity_spec_fingerprint": self.spec.fingerprint,
            }
        )
        record = _MaturityRecord(
            unit_token_hex=token.hex(),
            assigned_to_challenger=bool(assigned_to_challenger),
            exposure_at=exposure_at,
            maturity_at=maturity_at,
            accept_until=accept_until,
            ticket_fingerprint=ticket_fingerprint,
        )
        self._records[token] = record
        return self._ticket_from_record(analysis_unit_id, record)

    def close_enrollment(self, *, closed_at: int) -> None:
        if self._sealed:
            raise RuntimeError("maturity ledger is sealed")
        closed_at = _timestamp(closed_at, "closed_at")
        if self._enrollment_closed_at is not None:
            if self._enrollment_closed_at != closed_at:
                raise ValueError("enrollment close timestamp cannot change")
            return
        latest_exposure = max(
            (record.exposure_at for record in self._records.values()),
            default=0,
        )
        if closed_at < latest_exposure:
            raise ValueError("closed_at cannot precede an enrolled exposure")
        self._enrollment_closed_at = closed_at
        self._append(
            "maturity_enrollment_closed",
            {
                "closed_at": closed_at,
                "total_units": len(self._records),
                "required_ready_at": self.required_ready_at,
            },
        )

    @property
    def required_ready_at(self) -> int | None:
        if self._enrollment_closed_at is None:
            return None
        if not self._records:
            return self._enrollment_closed_at
        return max(record.accept_until for record in self._records.values())

    def record_outcome(
        self,
        analysis_unit_id: str,
        *,
        observed_at: int,
        outcome_fingerprint: str,
    ) -> OutcomeReceipt:
        if self._sealed:
            raise RuntimeError("maturity ledger is sealed")
        observed_at = _timestamp(observed_at, "observed_at")
        if not outcome_fingerprint.strip():
            raise ValueError("outcome_fingerprint cannot be empty")
        token = self._unit_token(analysis_unit_id)
        record = self._records.get(token)
        if record is None:
            raise ValueError("analysis unit was not registered for maturity tracking")
        candidate_fingerprint = _receipt_fingerprint(
            ticket_fingerprint=record.ticket_fingerprint,
            observed_at=observed_at,
            outcome_fingerprint=outcome_fingerprint,
        )
        if record.receipt is not None:
            if candidate_fingerprint != record.receipt.receipt_fingerprint:
                raise ValueError("outcome receipt changed after first acceptance")
            return record.receipt
        if observed_at < record.maturity_at:
            raise ValueError("outcome cannot be finalized before preregistered maturity")
        if observed_at > record.accept_until:
            raise ValueError("outcome arrived after preregistered ingestion cutoff")

        receipt = OutcomeReceipt(
            ticket_fingerprint=record.ticket_fingerprint,
            observed_at=observed_at,
            outcome_fingerprint=outcome_fingerprint,
            receipt_fingerprint=candidate_fingerprint,
        )
        self._records[token] = _MaturityRecord(
            unit_token_hex=record.unit_token_hex,
            assigned_to_challenger=record.assigned_to_challenger,
            exposure_at=record.exposure_at,
            maturity_at=record.maturity_at,
            accept_until=record.accept_until,
            ticket_fingerprint=record.ticket_fingerprint,
            receipt=receipt,
        )
        return receipt

    def _state(self, record: _MaturityRecord, *, as_of: int) -> OutcomeFollowupState:
        if record.receipt is not None:
            return OutcomeFollowupState.MATURED_ON_TIME
        if as_of < record.maturity_at:
            return OutcomeFollowupState.PENDING_FOLLOWUP
        if as_of <= record.accept_until:
            return OutcomeFollowupState.AWAITING_INGESTION
        return OutcomeFollowupState.OVERDUE_MISSING

    def snapshot(self, *, as_of: int) -> OutcomeMaturitySnapshot:
        as_of = _timestamp(as_of, "as_of")
        records = tuple(self._records.values())
        states = [self._state(record, as_of=as_of) for record in records]
        matured = sum(state is OutcomeFollowupState.MATURED_ON_TIME for state in states)
        pending = sum(state is OutcomeFollowupState.PENDING_FOLLOWUP for state in states)
        awaiting = sum(state is OutcomeFollowupState.AWAITING_INGESTION for state in states)
        overdue = sum(state is OutcomeFollowupState.OVERDUE_MISSING for state in states)
        challenger_units = sum(record.assigned_to_challenger for record in records)
        challenger_matured = sum(
            record.assigned_to_challenger and record.receipt is not None
            for record in records
        )
        control_matured = sum(
            (not record.assigned_to_challenger) and record.receipt is not None
            for record in records
        )

        reasons: list[str] = []
        if self._enrollment_closed_at is None:
            reasons.append("enrollment_not_closed")
        if not records:
            reasons.append("empty_analysis_cohort")
        ready_at = self.required_ready_at
        if ready_at is not None and as_of < ready_at:
            reasons.append("preregistered_followup_window_incomplete")
        if pending:
            reasons.append("pipeline_participants_pending_followup")
        if awaiting:
            reasons.append("matured_outcomes_awaiting_ingestion")
        if overdue:
            reasons.append("outcomes_missing_after_preregistered_cutoff")
        if matured != len(records):
            reasons.append("complete_case_cohort_incomplete")

        return OutcomeMaturitySnapshot(
            as_of=as_of,
            enrollment_closed=self._enrollment_closed_at is not None,
            enrollment_closed_at=self._enrollment_closed_at,
            total_units=len(records),
            challenger_units=challenger_units,
            control_units=len(records) - challenger_units,
            matured_on_time=matured,
            pending_followup=pending,
            awaiting_ingestion=awaiting,
            overdue_missing=overdue,
            challenger_matured_on_time=challenger_matured,
            control_matured_on_time=control_matured,
            complete_case_ready=not reasons,
            required_ready_at=ready_at,
            reasons=tuple(reasons),
        )

    @property
    def cohort_fingerprint(self) -> str:
        records = sorted(
            (
                {
                    "unit_token": record.unit_token_hex,
                    "assigned_to_challenger": record.assigned_to_challenger,
                    "exposure_at": record.exposure_at,
                    "maturity_at": record.maturity_at,
                    "accept_until": record.accept_until,
                    "ticket_fingerprint": record.ticket_fingerprint,
                    "receipt_fingerprint": (
                        record.receipt.receipt_fingerprint
                        if record.receipt is not None
                        else None
                    ),
                }
                for record in self._records.values()
            ),
            key=lambda item: item["unit_token"],
        )
        return _fingerprint(
            {
                "schema": "growthevo.outcome-maturity-cohort.v1",
                "maturity_spec_fingerprint": self.spec.fingerprint,
                "enrollment_closed_at": self._enrollment_closed_at,
                "records": records,
            }
        )

    def seal_complete_case_analysis(self, *, as_of: int) -> CompleteCaseMaturitySeal:
        if self._sealed:
            raise RuntimeError("maturity ledger is already sealed")
        snapshot = self.snapshot(as_of=as_of)
        if not snapshot.complete_case_ready:
            raise ValueError(
                "complete-case promotion authority unavailable: "
                + ",".join(snapshot.reasons)
            )
        assert self._enrollment_closed_at is not None
        cohort_fingerprint = self.cohort_fingerprint
        seal_payload = {
            "schema": "growthevo.complete-case-maturity-seal.v1",
            "endpoint_name": self.spec.endpoint_name,
            "maturity_spec_fingerprint": self.spec.fingerprint,
            "cohort_fingerprint": cohort_fingerprint,
            "enrollment_closed_at": self._enrollment_closed_at,
            "analysis_as_of": snapshot.as_of,
            "total_units": snapshot.total_units,
            "challenger_units": snapshot.challenger_units,
            "control_units": snapshot.control_units,
            "matured_on_time": snapshot.matured_on_time,
        }
        seal = CompleteCaseMaturitySeal(
            endpoint_name=self.spec.endpoint_name,
            maturity_spec_fingerprint=self.spec.fingerprint,
            cohort_fingerprint=cohort_fingerprint,
            enrollment_closed_at=self._enrollment_closed_at,
            analysis_as_of=snapshot.as_of,
            total_units=snapshot.total_units,
            challenger_units=snapshot.challenger_units,
            control_units=snapshot.control_units,
            matured_on_time=snapshot.matured_on_time,
            seal_fingerprint=_sha256(seal_payload),
        )
        self._sealed = True
        self._append(
            "complete_case_maturity_sealed",
            {
                "seal_fingerprint": seal.seal_fingerprint,
                "cohort_fingerprint": seal.cohort_fingerprint,
                "analysis_as_of": seal.analysis_as_of,
                "total_units": seal.total_units,
            },
        )
        return seal

    def events(self) -> tuple[MaturityAuditEvent, ...]:
        return tuple(self._events)

    def verify_audit_chain(self) -> bool:
        previous_hash = "0" * 64
        for sequence, event in enumerate(self._events):
            if event.sequence != sequence or event.previous_hash != previous_hash:
                return False
            if (
                self._digest(
                    event.sequence,
                    event.kind,
                    event.payload,
                    event.previous_hash,
                )
                != event.event_hash
            ):
                return False
            previous_hash = event.event_hash
        return True
