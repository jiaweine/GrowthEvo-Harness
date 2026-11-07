"""Bounded online personalization driven by real, matured outcome events.

This is an observable contextual policy service, not an unvalidated CATE model
promotion. Cold-start decisions randomize safely; matured outcome data can
shift subsequent treatment allocation while keeping a control arm. Decisions
and actual exposures are separate durable records.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any

from .decisioning import ACTION_REGISTRY
from .growth_store import GrowthConflict, GrowthMissing, GrowthStore

UTC = timezone.utc
OBSERVATION_WINDOW = timedelta(days=7)
MIN_MATURED_PER_ARM = 20
CONTROL_FLOOR = 0.35


def _hash_fraction(value: str) -> float:
    return int.from_bytes(sha256(value.encode()).digest()[:8], "big") / 2**64


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


class ContextualPersonalizer:
    def __init__(self, store: GrowthStore, scope: str):
        self.store = store
        self.scope = scope

    def _empirical_rates(self, tx: Any, cohort: str, actions: list[str],
                         synthetic: bool, at: datetime) -> dict[str, dict[str, Any]]:
        records = [row for row in tx.all("personalization_exposures")
                   if row.get("cohort") == cohort
                   and row.get("synthetic", False) == synthetic
                   and datetime.fromisoformat(row["occurred_at"]) + OBSERVATION_WINDOW <= at
                   and row.get("action_id") in actions]
        events: dict[str, list[datetime]] = {}
        for event in tx.all("events"):
            if event.get("name") == "purchase" and event.get("synthetic", False) == synthetic:
                events.setdefault(event["customer_id"], []).append(
                    datetime.fromisoformat(event["occurred_at"])
                )
        stats: dict[str, dict[str, Any]] = {
            action: {"matured": 0, "converted": 0, "posterior_mean": None}
            for action in actions
        }
        # A customer may see multiple messages. Do not count one eventual
        # purchase repeatedly as independent evidence across several arms.
        seen_customers: set[str] = set()
        for row in sorted(records, key=lambda item: item["occurred_at"]):
            if row["customer_id"] in seen_customers:
                continue
            seen_customers.add(row["customer_id"])
            record = stats[row["action_id"]]
            record["matured"] += 1
            started = datetime.fromisoformat(row["occurred_at"])
            end = started + OBSERVATION_WINDOW
            if any(started <= timestamp <= end for timestamp in
                   events.get(row["customer_id"], [])):
                record["converted"] += 1
        for record in stats.values():
            n = record["matured"]
            # Explicitly a descriptive smoothed rate, not an uplift estimate.
            record["posterior_mean"] = (record["converted"] + 1) / (n + 2) if n else None
        return stats

    def decide(self, data: dict[str, Any]) -> dict[str, Any]:
        def decide(tx: Any) -> dict[str, Any]:
            customer = tx.get("customers", data["customer_id"])
            if customer is None:
                raise GrowthMissing("customer not found")
            key = data["request_id"]
            fingerprint = sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            previous = tx.get("personalizations", key)
            if previous is not None:
                if not customer["consent"]:
                    raise GrowthConflict("customer consent withdrawn since decision")
                if previous["request_fingerprint"] != fingerprint:
                    raise GrowthConflict("personalization idempotency key reused")
                return previous

            candidates = sorted(set(data["candidate_action_ids"]) | {"NO_TREATMENT"})
            eligible = [
                action for action in candidates
                if action in ACTION_REGISTRY
                and ACTION_REGISTRY[action].cost <= data["budget_remaining"]
            ]
            if not data["consent_state"] or not customer["consent"] or data["frequency_remaining"] <= 0:
                eligible = ["NO_TREATMENT"]
            if "NO_TREATMENT" not in eligible:
                eligible.insert(0, "NO_TREATMENT")
            cohort = str(customer.get("attributes", {}).get("lifecycle", "unknown"))[:60]
            synthetic = bool(customer.get("synthetic", False))
            now = datetime.now(UTC)
            observed = self._empirical_rates(tx, cohort, eligible, synthetic, now)
            treatment = [action for action in eligible if action != "NO_TREATMENT"]
            ready = bool(treatment) and all(
                observed[action]["matured"] >= MIN_MATURED_PER_ARM for action in eligible
            )
            if not treatment:
                distribution = {"NO_TREATMENT": 1.0}
            elif ready:
                scores = {
                    action: max(0.01, observed[action]["posterior_mean"])
                    for action in treatment
                }
                treatment_weights = _normalize(scores)
                distribution = {"NO_TREATMENT": CONTROL_FLOOR}
                distribution.update({
                    action: (1 - CONTROL_FLOOR) * treatment_weights[action]
                    for action in treatment
                })
            else:
                distribution = {"NO_TREATMENT": CONTROL_FLOOR}
                distribution.update({
                    action: (1 - CONTROL_FLOOR) / len(treatment)
                    for action in treatment
                })

            draw = _hash_fraction(
                json.dumps([self.scope, data["request_id"]], separators=(",", ":"))
            )
            running = 0.0
            chosen = next(reversed(distribution))
            for action, probability in distribution.items():
                running += probability
                if draw < running:
                    chosen = action
                    break
            decision = {
                "decision_id": "pd_" + sha256((self.scope + ":" + key).encode()).hexdigest()[:22],
                "customer_id": data["customer_id"],
                "request_id": key, "request_fingerprint": fingerprint,
                "placement": data["placement"], "cohort": cohort,
                "action_id": chosen, "action_distribution": distribution,
                "propensity": distribution[chosen],
                "policy_id": "contextual_observational_policy",
                "learning_status": "matured" if ready else "collecting_evidence",
                "matured_sample_counts": {key: v["matured"] for key, v in observed.items()},
                "evidence_tier": "D", "causal_claim": False,
                "exposure_confirmed": False, "synthetic": synthetic,
                "created_at": now.isoformat(),
                "note": "Decision is not exposure. Confirm actual display separately.",
            }
            tx.put("personalizations", key, decision, new=True)
            return decision
        return self.store.run(self.scope, decide, write=True)

    def confirm_exposure(self, request_id: str, surface: str) -> dict[str, Any]:
        def confirm(tx: Any) -> dict[str, Any]:
            decision = tx.get("personalizations", request_id)
            if decision is None:
                raise GrowthMissing("personalization not found")
            if surface != decision["placement"]:
                raise GrowthConflict("exposure surface must match the decision")
            if datetime.now(UTC) - datetime.fromisoformat(decision["created_at"]) > timedelta(minutes=15):
                raise GrowthConflict("personalization decision expired; request a fresh decision")
            key = request_id
            existing = tx.get("personalization_exposures", key)
            if existing is not None:
                return existing
            customer = tx.get("customers", decision["customer_id"])
            if customer is None or not customer["consent"]:
                raise GrowthConflict("customer no longer consents")
            exposure = {
                "decision_id": decision["decision_id"], "request_id": request_id,
                "customer_id": decision["customer_id"], "cohort": decision["cohort"],
                "action_id": decision["action_id"], "surface": surface,
                "occurred_at": datetime.now(UTC).isoformat(),
                "synthetic": decision["synthetic"],
            }
            tx.put("personalization_exposures", key, exposure, new=True)
            decision["exposure_confirmed"] = True
            tx.put("personalizations", request_id, decision)
            return exposure
        return self.store.run(self.scope, confirm, write=True)

    def metrics(self) -> dict[str, Any]:
        def collect(tx: Any) -> dict[str, Any]:
            decisions = tx.all("personalizations")
            exposures = tx.all("personalization_exposures")
            return {
                "decisions": len(decisions), "confirmed_exposures": len(exposures),
                "recent_decisions": decisions[-20:],
                "evidence_tier": "D", "causal_claim": False,
                "metric_definition": "Matured observed purchase rate by customer cohort and action.",
                "policy": "Bounded treatment allocation with a control floor.",
            }
        return self.store.run(self.scope, collect)
