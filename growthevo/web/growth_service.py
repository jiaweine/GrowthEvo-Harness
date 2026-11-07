"""Growth decisions and journeys, grounded in durable customer events.

Online feedback optimizes a bounded *predictive* bandit, not a claim of causal
uplift. Real incrementality requires randomized exposures and experiment metrics.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import math
from typing import Any
from uuid import uuid4

from .growth_store import GrowthConflict, GrowthStore, fingerprint

UTC = timezone.utc


def bucket(*values: str) -> float:
    key = "\x1f".join(values).encode()
    return int.from_bytes(sha256(key).digest()[:8], "big") / 2**64


def _as_utc() -> datetime:
    return datetime.now(UTC)


class GrowthService:
    def __init__(self, store: GrowthStore, scope: str, *, simulation: bool) -> None:
        self.store = store
        self.scope = scope
        self.simulation = simulation

    def profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self.store.put(self.scope, "profile", profile)

    def event(self, event: dict[str, Any]) -> dict[str, Any]:
        subject = event["subject_id"]
        self.store.append_fact(self.scope, "event", event["id"], subject, event["name"], event)
        journeys = self.store.list(self.scope, "journey", limit=500)
        for journey in journeys:
            if journey["status"] != "active" or journey["trigger"] != event["name"]:
                continue
            profile = self.store.get(self.scope, "profile", subject)
            if profile is None or not profile["consent"]:
                continue
            steps = journey["steps"]
            due_at = _as_utc() + timedelta(seconds=steps[0]["delay_seconds"])
            self.store.enqueue(self.scope, {
                "id": "job_" + sha256(f'{journey["id"]}:{event["id"]}:0'.encode()).hexdigest()[:24],
                "journey_id": journey["id"], "event_id": event["id"],
                "subject_id": subject, "step_index": 0, "due_at": due_at,
            })
        return {"id": event["id"], "accepted": True, "origin": event.get("origin", "observed")}

    def experiment(self, data: dict[str, Any]) -> dict[str, Any]:
        current = self.store.get(self.scope, "experiment", data["id"])
        if current is not None and self.store.has_assignments(self.scope, data["id"]):
            if current != data:
                raise GrowthConflict("experiment has assignments and cannot be changed")
            return current
        return self.store.put(self.scope, "experiment", data)

    def assign(self, experiment_id: str, subject_id: str) -> dict[str, str]:
        experiment = self.store.get(self.scope, "experiment", experiment_id)
        if experiment is None or experiment["status"] != "active":
            raise ValueError("experiment not active")
        draw = bucket(self.scope, experiment_id, subject_id)
        running = 0.0
        proposed = experiment["variants"][-1]["id"]
        for variant in experiment["variants"]:
            running += variant["weight"] / 10000.0
            if draw < running:
                proposed = variant["id"]
                break
        chosen = self.store.assignment(self.scope, experiment_id, subject_id, proposed)
        return {"experiment_id": experiment_id, "subject_id": subject_id, "variant": chosen}

    def exposure(self, experiment_id: str, subject_id: str, event_id: str) -> dict[str, Any]:
        experiment = self.store.get(self.scope, "experiment", experiment_id)
        if experiment is None:
            raise ValueError("experiment not found")
        assignments = self.store.assignments(self.scope, experiment_id)
        match = next((a for a in assignments if a["subject_id"] == subject_id), None)
        if match is None:
            raise ValueError("must assign before exposure")
        payload = {"id": event_id, "experiment_id": experiment_id,
                   "subject_id": subject_id, "variant": match["variant"]}
        return self.store.append_fact(self.scope, "exposure", event_id, subject_id, experiment_id, payload)

    def metric(self, experiment_id: str, subject_id: str,
               metric_id: str, value: float) -> dict[str, Any]:
        experiment = self.store.get(self.scope, "experiment", experiment_id)
        if experiment is None:
            raise ValueError("experiment not found")
        if not any(e["subject_id"] == subject_id for e in
                   self.store.facts(self.scope, "exposure", related_id=experiment_id, limit=1000)):
            raise ValueError("metric requires a recorded exposure")
        if value not in (0.0, 1.0):
            raise ValueError("experiment conversion metric must be binary")
        payload = {"id": metric_id, "experiment_id": experiment_id,
                   "subject_id": subject_id, "value": int(value),
                   "metric": experiment["metric"]}
        return self.store.append_fact(self.scope, "metric", metric_id, subject_id, experiment_id, payload)

    def report(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.store.get(self.scope, "experiment", experiment_id)
        if experiment is None:
            raise ValueError("experiment not found")
        assignments = self.store.assignments(self.scope, experiment_id)
        exposures = self.store.facts(self.scope, "exposure", related_id=experiment_id, limit=1000)
        metrics = self.store.facts(self.scope, "metric", related_id=experiment_id, limit=1000)
        # Count unique exposed units, not render events. A metric is a binary
        # observation, and multiple observation IDs must not double-count a unit.
        exposed = {e["subject_id"] for e in exposures}
        converted = {m["subject_id"] for m in metrics if m["value"] == 1}
        by_variant: dict[str, dict[str, Any]] = {}
        for variant in experiment["variants"]:
            units = {a["subject_id"] for a in assignments if a["variant"] == variant["id"]}
            eligible = units & exposed
            wins = len(eligible & converted)
            n = len(eligible)
            rate = wins / n if n else None
            by_variant[variant["id"]] = {
                "assigned": len(units), "exposed": n, "converted": wins,
                "conversion_rate": rate, "sufficient_data": n >= 30,
            }
        total_assigned = len(assignments)
        srm = 0.0
        for variant in experiment["variants"]:
            expected = total_assigned * variant["weight"] / 10000
            observed = by_variant[variant["id"]]["assigned"]
            if expected:
                srm += (observed - expected) ** 2 / expected
        return {
            "experiment_id": experiment_id, "metric": experiment["metric"],
            "variants": by_variant, "assignments": total_assigned,
            "sample_ratio_chi_square": round(srm, 4),
            "sample_ratio_warning": (
                len(experiment["variants"]) == 2
                and total_assigned >= 100 and srm > 10.83
            ),
            "evidence": "observed_exposures_and_binary_metrics",
            "causal_claim": "insufficient_data" if any(
                not v["sufficient_data"] for v in by_variant.values()
            ) else "requires_randomization_and_statistical_review",
            "truncated": len(exposures) >= 1000 or len(metrics) >= 1000,
        }

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        """Predictive online policy with explicit holdout and logged propensities.

        The decision key makes writes repeat-safe. A prior feedback record can
        update action preferences; it does not prove incremental treatment lift.
        """
        key = request["decision_key"]
        ident = "dec_" + sha256((self.scope + ":" + key).encode()).hexdigest()[:24]
        prior = self.store.get(self.scope, "decision", ident)
        request_fingerprint = fingerprint(request)
        if prior is not None:
            if prior["request_fingerprint"] != request_fingerprint:
                raise GrowthConflict("decision key reused with different request")
            return prior
        subject = request["subject_id"]
        profile = self.store.get(self.scope, "profile", subject)
        eligible = (
            profile is not None and profile["consent"]
            and request["frequency_remaining"] > 0
        )
        offers = [o for o in self.store.list(self.scope, "offer", limit=500)
                  if o["active"] and o["id"] != "NO_TREATMENT"
                  and o["cost"] <= request["budget_remaining"]]
        cohort = profile["segment"] if profile else "unknown"
        probabilities: dict[str, float] = {"NO_TREATMENT": 1.0}
        if eligible and offers:
            counts = self.store.feedback_counts(
                self.scope, cohort,
                "simulated" if profile.get("origin") == "simulated" else "observed",
            )
            scores: dict[str, float] = {}
            for offer in offers:
                successes, total = counts.get(offer["id"], (0, 0))
                posterior = (successes + 1) / (total + 2)
                preferred = float(offer["channel"] == profile["preferred_channel"])
                scores[offer["id"]] = 3.0 * posterior + 0.3 * preferred - 0.02 * offer["cost"]
            maximum = max(scores.values())
            weights = {name: math.exp(score - maximum) for name, score in scores.items()}
            mass = sum(weights.values())
            # A permanent randomized 10% untreated slice supports later
            # comparisons; positive probability for all eligible arms.
            probabilities = {"NO_TREATMENT": 0.1}
            probabilities.update({name: 0.9 * weight / mass for name, weight in weights.items()})
        draw = bucket(self.scope, subject, request["placement"], key)
        running = 0.0
        selected = list(probabilities)[-1]
        for action_id, probability in probabilities.items():
            running += probability
            if draw < running:
                selected = action_id
                break
        result = {
            "id": ident, "decision_key": key, "request_fingerprint": request_fingerprint,
            "subject_id": subject, "cohort": cohort, "placement": request["placement"],
            "action_id": selected, "propensity": probabilities[selected],
            "action_distribution": probabilities,
            "policy_id": "adaptive-feedback-policy",
            "policy_basis": "observational_feedback_not_causal_uplift",
            "estimated_incremental_value": None,
            "origin": "simulated" if profile and profile.get("origin") == "simulated" else "observed",
        }
        return self.store.put(self.scope, "decision", result, immutable=True)

    def feedback(self, decision_id: str, event_id: str, success: bool) -> dict[str, Any]:
        decision = self.store.get(self.scope, "decision", decision_id)
        if decision is None:
            raise ValueError("decision not found")
        result = {
            "id": event_id, "decision_id": decision_id,
            "subject_id": decision["subject_id"], "cohort": decision["cohort"],
            "action_id": decision["action_id"], "success": success,
            "origin": decision["origin"],
        }
        # One outcome per decision, even if clients retry with another event ID.
        return self.store.append_feedback_once(self.scope, decision_id, result)

    def run_due(self, limit: int = 20) -> list[dict[str, Any]]:
        """Execute queued *simulated* work. Production without a real channel blocks."""
        finished = []
        for job in self.store.claim_due(limit):
            scope = job["owner_scope"]
            try:
                journey = self.store.get(scope, "journey", job["journey_id"])
                profile = self.store.get(scope, "profile", job["subject_id"])
                allowed = bool(
                    journey and journey["status"] == "active" and
                    profile and profile["consent"] and self.simulation
                )
                if not allowed:
                    self.store.finish_job(scope, job["id"], "blocked")
                    finished.append({"id": job["id"], "status": "blocked"})
                    continue
                step = journey["steps"][job["step_index"]]
                delivery = {
                    "id": job["id"].replace("job_", "delivery_", 1),
                    "journey_id": job["journey_id"], "subject_id": job["subject_id"],
                    "event_id": job["event_id"], "step_index": job["step_index"],
                    "offer_id": step["offer_id"], "channel": step["channel"],
                    "status": "simulated", "origin": "simulated",
                }
                self.store.put(scope, "delivery", delivery, immutable=True)
                if job["step_index"] + 1 < len(journey["steps"]):
                    nxt = job["step_index"] + 1
                    wait = journey["steps"][nxt]["delay_seconds"]
                    self.store.enqueue(scope, {
                        "id": "job_" + sha256(
                            f'{journey["id"]}:{job["event_id"]}:{nxt}'.encode()
                        ).hexdigest()[:24],
                        "journey_id": journey["id"], "subject_id": job["subject_id"],
                        "event_id": job["event_id"], "step_index": nxt,
                        "due_at": _as_utc() + timedelta(seconds=wait),
                    })
                self.store.finish_job(scope, job["id"], "simulated")
                finished.append({"id": job["id"], "status": "simulated"})
            except Exception:
                self.store.finish_job(scope, job["id"], "failed")
                raise
        return finished
