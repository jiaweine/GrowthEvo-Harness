from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b, sha256
import json
from math import isfinite
from typing import Mapping

from .online_promotion import CanaryObservation, CanaryRoute
from .sequential_causal import HighPowerCanaryObservation, HighPowerExposureTicket


class ClusterAggregationMode(str, Enum):
    SUM = "sum"
    MEAN = "mean"
    BINARY_ANY = "binary_any"


class ClusterEstimand(str, Enum):
    TYPICAL_CLUSTER = "typical_cluster"


@dataclass(frozen=True, slots=True)
class ClusterOutcomeSpec:
    """Frozen mapping from repeated events to one randomized-cluster outcome."""

    metric_name: str
    aggregation: ClusterAggregationMode
    window_seconds: int
    event_min: float
    event_max: float
    outcome_min: float
    outcome_max: float
    max_events: int
    empty_value: float
    estimand: ClusterEstimand = ClusterEstimand.TYPICAL_CLUSTER

    def __post_init__(self) -> None:
        if not self.metric_name.strip():
            raise ValueError("metric_name cannot be empty")
        if isinstance(self.window_seconds, bool) or not isinstance(self.window_seconds, int) or self.window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")
        if isinstance(self.max_events, bool) or not isinstance(self.max_events, int) or self.max_events <= 0:
            raise ValueError("max_events must be a positive integer")
        for name, value in (
            ("event_min", self.event_min),
            ("event_max", self.event_max),
            ("outcome_min", self.outcome_min),
            ("outcome_max", self.outcome_max),
            ("empty_value", self.empty_value),
        ):
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.event_max < self.event_min:
            raise ValueError("event_max cannot be below event_min")
        if self.outcome_max < self.outcome_min:
            raise ValueError("outcome_max cannot be below outcome_min")
        if not self.outcome_min <= self.empty_value <= self.outcome_max:
            raise ValueError("empty_value must lie inside outcome bounds")
        if self.aggregation is ClusterAggregationMode.MEAN:
            if self.outcome_min > self.event_min or self.outcome_max < self.event_max:
                raise ValueError("mean outcome bounds must contain event bounds")
        elif self.aggregation is ClusterAggregationMode.SUM:
            possible = (
                0.0,
                self.event_min,
                self.event_max,
                self.max_events * self.event_min,
                self.max_events * self.event_max,
            )
            required_min = min(possible)
            required_max = max(possible)
            if self.outcome_min > required_min or self.outcome_max < required_max:
                raise ValueError("sum outcome bounds must contain all preregistered event-count sums")
        elif self.aggregation is ClusterAggregationMode.BINARY_ANY:
            if self.event_min < 0.0 or self.event_max > 1.0:
                raise ValueError("binary_any event bounds must lie in [0, 1]")
            if self.outcome_min > 0.0 or self.outcome_max < 1.0:
                raise ValueError("binary_any outcome bounds must contain [0, 1]")
            if self.empty_value != 0.0:
                raise ValueError("binary_any empty_value must be 0")
        else:
            raise ValueError("unsupported cluster aggregation mode")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.cluster-outcome-spec.v1",
                **asdict(self),
                "aggregation": self.aggregation.value,
                "estimand": self.estimand.value,
            }
        )


@dataclass(frozen=True, slots=True)
class ClusterAssignmentTicket:
    cluster_id: str
    assigned_to_challenger: bool
    exposure_at: int
    window_end: int
    spec_fingerprint: str
    ticket_fingerprint: str


@dataclass(frozen=True, slots=True)
class ClusterOutcomeResult:
    cluster_id: str
    assigned_to_challenger: bool
    metric_name: str
    value: float
    event_count: int
    finalized_at: int
    ticket_fingerprint: str
    result_fingerprint: str

    def as_canary_observation(self, route: CanaryRoute) -> CanaryObservation:
        if not route.in_canary:
            raise ValueError("cluster route was not admitted to the canary")
        if route.analysis_unit_id != self.cluster_id:
            raise ValueError("route cluster differs from finalized cluster")
        if route.assigned_to_challenger != self.assigned_to_challenger:
            raise ValueError("route arm differs from finalized cluster assignment")
        return CanaryObservation(
            analysis_unit_id=self.cluster_id,
            assigned_to_challenger=self.assigned_to_challenger,
            assignment_probability=route.challenger_probability,
            traffic_fraction=route.traffic_fraction,
            metrics={self.metric_name: self.value},
        )

    def as_high_power_observation(
        self,
        ticket: HighPowerExposureTicket,
        *,
        covariates: Mapping[str, float] | None = None,
    ) -> HighPowerCanaryObservation:
        if not ticket.in_canary:
            raise ValueError("cluster exposure ticket was not admitted to the canary")
        if ticket.analysis_unit_id != self.cluster_id:
            raise ValueError("exposure ticket cluster differs from finalized cluster")
        if ticket.assigned_to_challenger != self.assigned_to_challenger:
            raise ValueError("exposure ticket arm differs from finalized cluster assignment")
        return HighPowerCanaryObservation(
            analysis_unit_id=self.cluster_id,
            routing_stage_index=ticket.routing_stage_index,
            assigned_to_challenger=self.assigned_to_challenger,
            assignment_probability=ticket.challenger_probability,
            traffic_fraction=ticket.traffic_fraction,
            metrics={self.metric_name: self.value},
            covariates=dict(covariates or {}),
        )


@dataclass(frozen=True, slots=True)
class _ClusterRecord:
    token_hex: str
    assigned_to_challenger: bool
    exposure_at: int
    window_end: int
    ticket_fingerprint: str
    events: tuple[tuple[str, int, float], ...] = ()
    event_tokens: frozenset[bytes] = frozenset()
    finalized: ClusterOutcomeResult | None = None


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer timestamp")
    return value


class ClusterOutcomeAccumulator:
    """Aggregates repeated events into exactly one randomized-cluster outcome.

    Internal state stores only experiment-scoped cluster/event hashes. Raw IDs are
    returned to the caller in tickets/results for routing integration but are not
    retained in the internal records.
    """

    def __init__(self, *, experiment_id: str, spec: ClusterOutcomeSpec) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id cannot be empty")
        self.experiment_id = experiment_id
        self.spec = spec
        self._records: dict[bytes, _ClusterRecord] = {}

    def _cluster_token(self, cluster_id: str) -> bytes:
        if not cluster_id:
            raise ValueError("cluster_id cannot be empty")
        return blake2b(
            f"{self.experiment_id}|cluster|{cluster_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    def _event_token(self, cluster_token: bytes, event_id: str) -> bytes:
        if not event_id:
            raise ValueError("event_id cannot be empty")
        return blake2b(
            cluster_token + b"|event|" + event_id.encode("utf-8"),
            digest_size=16,
        ).digest()

    def _ticket(self, cluster_id: str, record: _ClusterRecord) -> ClusterAssignmentTicket:
        return ClusterAssignmentTicket(
            cluster_id=cluster_id,
            assigned_to_challenger=record.assigned_to_challenger,
            exposure_at=record.exposure_at,
            window_end=record.window_end,
            spec_fingerprint=self.spec.fingerprint,
            ticket_fingerprint=record.ticket_fingerprint,
        )

    def register_cluster(
        self,
        cluster_id: str,
        *,
        assigned_to_challenger: bool,
        exposure_at: int,
    ) -> ClusterAssignmentTicket:
        exposure_at = _timestamp(exposure_at, "exposure_at")
        token = self._cluster_token(cluster_id)
        existing = self._records.get(token)
        if existing is not None:
            if (
                existing.assigned_to_challenger != bool(assigned_to_challenger)
                or existing.exposure_at != exposure_at
            ):
                raise ValueError("cluster assignment signature changed after registration")
            return self._ticket(cluster_id, existing)
        window_end = exposure_at + self.spec.window_seconds
        ticket_fingerprint = _fingerprint(
            {
                "schema": "growthevo.cluster-assignment-ticket.v1",
                "experiment_id": self.experiment_id,
                "cluster_token": token.hex(),
                "assigned_to_challenger": bool(assigned_to_challenger),
                "exposure_at": exposure_at,
                "window_end": window_end,
                "spec_fingerprint": self.spec.fingerprint,
            }
        )
        record = _ClusterRecord(
            token_hex=token.hex(),
            assigned_to_challenger=bool(assigned_to_challenger),
            exposure_at=exposure_at,
            window_end=window_end,
            ticket_fingerprint=ticket_fingerprint,
        )
        self._records[token] = record
        return self._ticket(cluster_id, record)

    def ingest_event(
        self,
        cluster_id: str,
        *,
        event_id: str,
        event_at: int,
        value: float,
    ) -> None:
        event_at = _timestamp(event_at, "event_at")
        value = float(value)
        if not isfinite(value):
            raise ValueError("event value must be finite")
        if value < self.spec.event_min - 1e-12 or value > self.spec.event_max + 1e-12:
            raise ValueError("event value lies outside preregistered event bounds")
        token = self._cluster_token(cluster_id)
        record = self._records.get(token)
        if record is None:
            raise ValueError("cluster was not registered")
        if record.finalized is not None:
            raise RuntimeError("cluster outcome is already finalized")
        if event_at < record.exposure_at or event_at > record.window_end:
            raise ValueError("event lies outside preregistered cluster outcome window")
        event_token = self._event_token(token, event_id)
        if event_token in record.event_tokens:
            raise ValueError("event_id has already been ingested for this cluster")
        if len(record.events) >= self.spec.max_events:
            raise ValueError("cluster exceeded preregistered max_events")
        encoded_event = (event_token.hex(), event_at, value)
        self._records[token] = _ClusterRecord(
            token_hex=record.token_hex,
            assigned_to_challenger=record.assigned_to_challenger,
            exposure_at=record.exposure_at,
            window_end=record.window_end,
            ticket_fingerprint=record.ticket_fingerprint,
            events=record.events + (encoded_event,),
            event_tokens=record.event_tokens | frozenset((event_token,)),
        )

    def _aggregate(self, record: _ClusterRecord) -> float:
        values = [item[2] for item in record.events]
        if not values:
            return float(self.spec.empty_value)
        if self.spec.aggregation is ClusterAggregationMode.SUM:
            value = sum(values)
        elif self.spec.aggregation is ClusterAggregationMode.MEAN:
            value = sum(values) / len(values)
        elif self.spec.aggregation is ClusterAggregationMode.BINARY_ANY:
            value = 1.0 if any(item > 0.0 for item in values) else 0.0
        else:
            raise ValueError("unsupported cluster aggregation mode")
        if not isfinite(value):
            raise ValueError("aggregated cluster outcome is non-finite")
        if value < self.spec.outcome_min - 1e-12 or value > self.spec.outcome_max + 1e-12:
            raise ValueError("aggregated outcome lies outside preregistered bounds")
        return float(value)

    def finalize(self, cluster_id: str, *, as_of: int) -> ClusterOutcomeResult:
        as_of = _timestamp(as_of, "as_of")
        token = self._cluster_token(cluster_id)
        record = self._records.get(token)
        if record is None:
            raise ValueError("cluster was not registered")
        if record.finalized is not None:
            if record.finalized.finalized_at != as_of:
                raise ValueError("cluster finalization timestamp cannot change")
            return record.finalized
        if as_of < record.window_end:
            raise ValueError("cluster outcome window is not mature")
        value = self._aggregate(record)
        event_manifest = sorted(record.events, key=lambda item: (item[1], item[0]))
        result_fingerprint = _fingerprint(
            {
                "schema": "growthevo.cluster-outcome-result.v1",
                "spec_fingerprint": self.spec.fingerprint,
                "ticket_fingerprint": record.ticket_fingerprint,
                "event_manifest": event_manifest,
                "event_count": len(event_manifest),
                "value": value,
                "finalized_at": as_of,
            }
        )
        result = ClusterOutcomeResult(
            cluster_id=cluster_id,
            assigned_to_challenger=record.assigned_to_challenger,
            metric_name=self.spec.metric_name,
            value=value,
            event_count=len(event_manifest),
            finalized_at=as_of,
            ticket_fingerprint=record.ticket_fingerprint,
            result_fingerprint=result_fingerprint,
        )
        self._records[token] = _ClusterRecord(
            token_hex=record.token_hex,
            assigned_to_challenger=record.assigned_to_challenger,
            exposure_at=record.exposure_at,
            window_end=record.window_end,
            ticket_fingerprint=record.ticket_fingerprint,
            events=record.events,
            event_tokens=record.event_tokens,
            finalized=result,
        )
        return result

    def event_count(self, cluster_id: str) -> int:
        token = self._cluster_token(cluster_id)
        record = self._records.get(token)
        if record is None:
            raise ValueError("cluster was not registered")
        return len(record.events)

    def cohort_fingerprint(self) -> str:
        records = sorted(
            (
                {
                    "cluster_token": record.token_hex,
                    "assigned_to_challenger": record.assigned_to_challenger,
                    "exposure_at": record.exposure_at,
                    "window_end": record.window_end,
                    "ticket_fingerprint": record.ticket_fingerprint,
                    "event_manifest": sorted(record.events, key=lambda item: (item[1], item[0])),
                    "result_fingerprint": (
                        record.finalized.result_fingerprint if record.finalized else None
                    ),
                }
                for record in self._records.values()
            ),
            key=lambda item: item["cluster_token"],
        )
        return sha256(
            json.dumps(
                {
                    "schema": "growthevo.cluster-outcome-cohort.v1",
                    "spec_fingerprint": self.spec.fingerprint,
                    "records": records,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
