from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable

from growthevo.models import EventType, to_primitive


GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class GrowthEvent:
    sequence: int
    event_type: EventType
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class EventCheckpoint:
    sequence: int
    event_hash: str


class EventStore:
    """Append-only in-memory event store with a tamper-evident hash chain.

    The storage backend is intentionally minimal. Production deployments can
    replace this class while preserving append()/events()/verify() semantics.
    """

    def __init__(self) -> None:
        self._events: list[GrowthEvent] = []

    @staticmethod
    def _digest(
        sequence: int,
        event_type: EventType,
        timestamp: str,
        payload: dict[str, Any],
        previous_hash: str,
    ) -> str:
        body = {
            "sequence": sequence,
            "event_type": event_type.value,
            "timestamp": timestamp,
            "payload": to_primitive(payload),
            "previous_hash": previous_hash,
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(encoded).hexdigest()

    def append(self, event_type: EventType, payload: dict[str, Any]) -> GrowthEvent:
        sequence = len(self._events)
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        timestamp = datetime.now(timezone.utc).isoformat()
        primitive_payload = to_primitive(payload)
        event_hash = self._digest(sequence, event_type, timestamp, primitive_payload, previous_hash)
        event = GrowthEvent(
            sequence=sequence,
            event_type=event_type,
            timestamp=timestamp,
            payload=primitive_payload,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        return event

    def events(self) -> tuple[GrowthEvent, ...]:
        return tuple(self._events)

    def checkpoint(self) -> EventCheckpoint:
        if not self._events:
            return EventCheckpoint(sequence=-1, event_hash=GENESIS_HASH)
        last = self._events[-1]
        return EventCheckpoint(sequence=last.sequence, event_hash=last.event_hash)

    def verify(self, events: Iterable[GrowthEvent] | None = None) -> bool:
        chain = list(self._events if events is None else events)
        previous_hash = GENESIS_HASH
        for expected_sequence, event in enumerate(chain):
            if event.sequence != expected_sequence:
                return False
            if event.previous_hash != previous_hash:
                return False
            expected_hash = self._digest(
                event.sequence,
                event.event_type,
                event.timestamp,
                event.payload,
                event.previous_hash,
            )
            if event.event_hash != expected_hash:
                return False
            previous_hash = event.event_hash
        return True

    def __len__(self) -> int:
        return len(self._events)
