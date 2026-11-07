"""Growth domain operations: CDP, events, journeys, experimental exposure and feedback.

The unit of authority is the authenticated principal scope. All multi-record
mutations use the existing PostgreSQL transaction, never process-local caches.
Channel actions create *intent* records; they do not claim external delivery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any

from .growth_store import GrowthConflict, GrowthMissing, GrowthStore

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _require(tx: Any, kind: str, key: str) -> dict[str, Any]:
    value = tx.get(kind, key)
    if value is None:
        raise GrowthMissing(f"{kind} not found")
    return value


def _matches(customer: dict[str, Any], segment: dict[str, Any]) -> bool:
    return all(customer["attributes"].get(k) == v for k, v in segment["equals"].items())


class GrowthOperations:
    def __init__(self, store: GrowthStore, scope: str):
        self.store = store
        self.scope = scope

    def _read(self, fn: Any) -> Any:
        return self.store.run(self.scope, fn)

    def _write(self, fn: Any) -> Any:
        return self.store.run(self.scope, fn, write=True)

    def list(self, kind: str) -> list[dict[str, Any]]:
        if kind not in {"customers", "events", "segments", "offers", "creatives",
                        "journeys", "jobs", "deliveries", "experiments", "exposures"}:
            raise ValueError("unsupported collection")
        return self._read(lambda tx: tx.all(kind))

    def create(self, kind: str, key: str, data: dict[str, Any]) -> dict[str, Any]:
        if kind not in {"customers", "segments", "offers", "creatives"}:
            raise ValueError("unsupported resource")
        document = dict(data, created_at=_iso(_now()), synthetic=False)

        def insert(tx: Any) -> dict[str, Any]:
            tx.put(kind, key, document, new=True)
            return document
        return self._write(insert)

    def profile(self, customer_id: str) -> dict[str, Any]:
        def inspect(tx: Any) -> dict[str, Any]:
            customer = _require(tx, "customers", customer_id)
            return {
                "customer": customer,
                "events": [e for e in tx.all("events") if e["customer_id"] == customer_id],
                "segments": [s["segment_id"] for s in tx.all("segments") if _matches(customer, s)],
                "experiments": [e for e in tx.all("assignments") if e["customer_id"] == customer_id],
                "deliveries": [d for d in tx.all("deliveries") if d["customer_id"] == customer_id],
            }
        return self._read(inspect)

    def segment_preview(self, segment_id: str) -> dict[str, Any]:
        def preview(tx: Any) -> dict[str, Any]:
            segment = _require(tx, "segments", segment_id)
            matched = [c["customer_id"] for c in tx.all("customers") if _matches(c, segment)]
            return {"segment_id": segment_id, "size": len(matched), "customer_ids": matched}
        return self._read(preview)

    def create_experiment(self, data: dict[str, Any]) -> dict[str, Any]:
        document = dict(data, created_at=_iso(_now()), synthetic=False, state="active")
        return self._write(lambda tx: (tx.put("experiments", data["experiment_id"], document, new=True), document)[1])

    def expose(self, experiment_id: str, data: dict[str, Any]) -> dict[str, Any]:
        def assign(tx: Any) -> dict[str, Any]:
            exp = _require(tx, "experiments", experiment_id)
            if exp["state"] != "active":
                raise GrowthConflict("experiment is not active")
            customer = _require(tx, "customers", data["customer_id"])
            if not customer["consent"]:
                raise GrowthConflict("customer has no consent for experimental exposure")
            key = experiment_id + ":" + data["request_id"]
            prior = tx.get("exposures", key)
            if prior is not None:
                if prior["customer_id"] != data["customer_id"] or prior["surface"] != data["surface"]:
                    raise GrowthConflict("exposure request identity reused for different payload")
                return prior

            assignment_key = experiment_id + ":" + data["customer_id"]
            assignment = tx.get("assignments", assignment_key)
            if assignment is None:
                identity = json.dumps([self.scope, experiment_id, data["customer_id"]], separators=(",", ":"))
                draw = int.from_bytes(sha256(identity.encode()).digest()[:8], "big") / 2**64
                running = 0.0
                variant = exp["variants"][-1]["key"]
                for candidate in exp["variants"]:
                    running += candidate["weight"] / 100
                    if draw < running:
                        variant = candidate["key"]
                        break
                assignment = {"experiment_id": experiment_id, "customer_id": data["customer_id"],
                              "variant": variant, "assigned_at": _iso(_now())}
                tx.put("assignments", assignment_key, assignment, new=True)
            exposure = {
                "exposure_id": key, "experiment_id": experiment_id,
                "customer_id": data["customer_id"], "surface": data["surface"],
                "variant": assignment["variant"], "occurred_at": _iso(_now()),
                "synthetic": customer.get("synthetic", False),
            }
            tx.put("exposures", key, exposure, new=True)
            return exposure
        return self._write(assign)

    def report(self, experiment_id: str) -> dict[str, Any]:
        def analyze(tx: Any) -> dict[str, Any]:
            exp = _require(tx, "experiments", experiment_id)
            unique: dict[str, dict[str, Any]] = {}
            for e in sorted(tx.all("exposures"), key=lambda e: e["occurred_at"]):
                if e["experiment_id"] == experiment_id:
                    unique.setdefault(e["customer_id"], e)
            events: dict[str, list[dict[str, Any]]] = {}
            for event in tx.all("events"):
                if event["name"] == exp["metric_event"]:
                    events.setdefault(event["customer_id"], []).append(event)
            result = []
            counts = {}
            for arm in exp["variants"]:
                exposed = [e for e in unique.values() if e["variant"] == arm["key"]]
                converted = 0
                for e in exposed:
                    start = datetime.fromisoformat(e["occurred_at"])
                    end = start + timedelta(days=exp["window_days"])
                    if any(start <= datetime.fromisoformat(event["occurred_at"]) <= end
                           for event in events.get(e["customer_id"], [])):
                        converted += 1
                count = len(exposed)
                rate = converted / count if count else None
                counts[arm["key"]] = rate
                result.append({"variant": arm["key"], "exposed_customers": count,
                               "converted_customers": converted, "conversion_rate": rate})
            control_rate = counts[exp["control"]]
            for row in result:
                row["observed_difference_pp"] = (
                    round(100 * (row["conversion_rate"] - control_rate), 4)
                    if row["conversion_rate"] is not None and control_rate is not None else None
                )
            return {
                "experiment_id": experiment_id, "control": exp["control"],
                "metric_event": exp["metric_event"], "window_days": exp["window_days"],
                "results": result, "causal_claim": False,
                "note": "Observed differences only; not a significance or causal-lift claim.",
                "source": "synthetic_and_observed" if any(e["synthetic"] for e in unique.values()) else "observed",
            }
        return self._read(analyze)

    def create_journey(self, data: dict[str, Any]) -> dict[str, Any]:
        document = dict(data, active=False, created_at=_iso(_now()), synthetic=False)

        def create(tx: Any) -> dict[str, Any]:
            if document["segment_id"]:
                _require(tx, "segments", document["segment_id"])
            for step in document["steps"]:
                creative = _require(tx, "creatives", step["creative_id"])
                if creative["channel"] != step["channel"]:
                    raise GrowthConflict("creative channel does not match journey step")
                if step["offer_id"] is not None:
                    _require(tx, "offers", step["offer_id"])
            tx.put("journeys", data["journey_id"], document, new=True)
            return document
        return self._write(create)

    def activate_journey(self, journey_id: str) -> dict[str, Any]:
        def activate(tx: Any) -> dict[str, Any]:
            row = _require(tx, "journeys", journey_id)
            row["active"] = True
            tx.put("journeys", journey_id, row)
            return row
        return self._write(activate)

    def ingest_event(self, data: dict[str, Any]) -> dict[str, Any]:
        event = dict(data, ingested_at=_iso(_now()), synthetic=False)

        def ingest(tx: Any) -> dict[str, Any]:
            customer = _require(tx, "customers", data["customer_id"])
            prior = tx.get("events", event["event_id"])
            if prior is not None:
                comparable = {k: prior[k] for k in data}
                if comparable != data:
                    raise GrowthConflict("event identity reused with different content")
                return {"event": prior, "new_enrollments": 0, "deduplicated": True}
            tx.put("events", event["event_id"], event, new=True)
            started = 0
            # Historical backfills must not schedule unrequested customer contact.
            occurred = datetime.fromisoformat(event["occurred_at"])
            fresh = _now() - timedelta(hours=24) <= occurred <= _now() + timedelta(minutes=5)
            if not fresh or not customer["consent"]:
                return {"event": event, "new_enrollments": 0, "deduplicated": False}
            for journey in tx.all("journeys"):
                if not journey["active"] or journey["trigger_event"] != event["name"]:
                    continue
                if journey["segment_id"]:
                    segment = _require(tx, "segments", journey["segment_id"])
                    if not _matches(customer, segment):
                        continue
                job_id = "job_" + journey["journey_id"] + "_" + event["event_id"] + "_0"
                job = {"job_id": job_id, "journey_id": journey["journey_id"],
                       "customer_id": customer["customer_id"], "step_index": 0,
                       "status": "pending", "due_at": _iso(_now() + timedelta(
                           seconds=journey["steps"][0]["delay_seconds"])),
                       "synthetic": customer.get("synthetic", False)}
                tx.put("jobs", job_id, job, new=True)
                started += 1
            return {"event": event, "new_enrollments": started, "deduplicated": False}
        return self._write(ingest)

    def process_due(self, *, limit: int = 50) -> dict[str, Any]:
        def process(tx: Any) -> dict[str, Any]:
            processed = []
            now = _now()
            due = sorted((j for j in tx.all("jobs") if j["status"] == "pending"
                          and datetime.fromisoformat(j["due_at"]) <= now),
                         key=lambda j: (j["due_at"], j["job_id"]))
            for job in due[:limit]:
                customer = _require(tx, "customers", job["customer_id"])
                journey = _require(tx, "journeys", job["journey_id"])
                if not customer["consent"] or not journey["active"]:
                    job["status"] = "suppressed"
                    tx.put("jobs", job["job_id"], job)
                    processed.append({"job_id": job["job_id"], "status": "suppressed"})
                    continue
                step = journey["steps"][job["step_index"]]
                delivery = {
                    "delivery_id": "del_" + job["job_id"], "job_id": job["job_id"],
                    "journey_id": job["journey_id"], "customer_id": job["customer_id"],
                    "step_index": job["step_index"], "channel": step["channel"],
                    "creative_id": step["creative_id"], "offer_id": step["offer_id"],
                    "status": "simulated" if customer.get("synthetic") else "queued",
                    "created_at": _iso(now), "synthetic": bool(customer.get("synthetic")),
                }
                tx.put("deliveries", delivery["delivery_id"], delivery, new=True)
                job["status"] = "dispatched"
                tx.put("jobs", job["job_id"], job)
                processed.append({"job_id": job["job_id"], "status": delivery["status"],
                                  "delivery_id": delivery["delivery_id"]})
            return {"processed": processed, "count": len(processed)}
        return self._write(process)

    def record_receipt(self, delivery_id: str, data: dict[str, Any], *,
                       permit_simulation: bool) -> dict[str, Any]:
        def apply(tx: Any) -> dict[str, Any]:
            delivery = _require(tx, "deliveries", delivery_id)
            receipt_id = data["provider_event_id"]
            prior = tx.get("receipts", receipt_id)
            if prior is not None:
                if prior["delivery_id"] != delivery_id or prior["status"] != data["status"]:
                    raise GrowthConflict("provider receipt identity conflict")
                return {"delivery": delivery, "deduplicated": True}
            if delivery["synthetic"] and not permit_simulation:
                raise GrowthConflict("synthetic delivery receipts are disabled in production")
            if delivery["status"] not in {"queued", "simulated"}:
                raise GrowthConflict("delivery already has a final receipt")
            receipt = dict(data, delivery_id=delivery_id,
                           synthetic=bool(delivery["synthetic"]))
            tx.put("receipts", receipt_id, receipt, new=True)
            delivery["status"] = data["status"]
            delivery["provider_event_id"] = receipt_id
            tx.put("deliveries", delivery_id, delivery)
            if data["status"] == "delivered":
                journey = _require(tx, "journeys", delivery["journey_id"])
                next_step = delivery["step_index"] + 1
                if journey["active"] and next_step < len(journey["steps"]):
                    job_id = delivery["job_id"].rsplit("_", 1)[0] + "_" + str(next_step)
                    next_job = {
                        "job_id": job_id, "journey_id": delivery["journey_id"],
                        "customer_id": delivery["customer_id"], "step_index": next_step,
                        "status": "pending",
                        "due_at": _iso(_now() + timedelta(
                            seconds=journey["steps"][next_step]["delay_seconds"])),
                        "synthetic": delivery["synthetic"],
                    }
                    tx.put("jobs", job_id, next_job, new=True)
            return {"delivery": delivery, "deduplicated": False}
        return self._write(apply)

    def overview(self) -> dict[str, Any]:
        def overview(tx: Any) -> dict[str, Any]:
            names = ("customers", "events", "segments", "journeys", "experiments",
                     "exposures", "deliveries", "offers", "creatives")
            counts = {name: len(tx.all(name)) for name in names}
            return {
                "counts": counts, "backend": "postgresql",
                "data_origin": "synthetic_and_observed" if tx.get("meta", "demo-seeded") else "observed",
                "external_delivery": "not_configured",
                "note": "Dispatch records are not proof of messages delivered by external providers.",
            }
        return self._read(overview)
