from __future__ import annotations

import hashlib
import math
import threading
import uuid
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import DecisionRequest

UTC = timezone.utc


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    label: str
    channel: str
    cost: float
    risk_level: str
    creative_id: str | None = None
    evidence_tier: str = "B"


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "NO_TREATMENT": ActionDefinition("NO_TREATMENT", "No treatment", "none", 0.0, "L0", evidence_tier="A"),
    "free_shipping_v3": ActionDefinition("free_shipping_v3", "首单免邮", "web", 8.0, "L2", "cr_free_ship_281", "A"),
    "coupon_10_v2": ActionDefinition("coupon_10_v2", "¥10 优惠券", "coupon", 10.0, "L3", "cr_coupon_104", "B"),
    "push_reminder_v4": ActionDefinition("push_reminder_v4", "加购提醒", "push", 0.08, "L2", "cr_push_442", "A"),
    "email_guide_v2": ActionDefinition("email_guide_v2", "产品指南 Email", "email", 0.03, "L1", "cr_email_090", "B"),
}


class ReferenceDecisionEngine:
    """Auditable product-level decision contract.

    This reference scorer validates API semantics and guardrails. Production deployments
    should replace ``score_actions`` with the harness' locked CATE/OPE/policy pipeline.

    The in-process idempotency cache is deliberately bounded. It is only a reference
    contract for a single process; production should persist idempotency/decision logs
    in durable storage so multiple replicas share the same contract.
    """

    def __init__(self, max_log_size: int = 500, max_idempotency_size: int = 5_000) -> None:
        if max_log_size <= 0:
            raise ValueError("max_log_size must be > 0")
        if max_idempotency_size <= 0:
            raise ValueError("max_idempotency_size must be > 0")
        self._lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max_log_size)
        self._idempotency: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_idempotency_size = max_idempotency_size

    @staticmethod
    def _stable_jitter(entity_id: str, action_id: str) -> float:
        raw = hashlib.sha256(f"{entity_id}:{action_id}".encode()).digest()
        integer = int.from_bytes(raw[:4], "big")
        return (integer / (2**32 - 1) - 0.5) * 0.12

    @staticmethod
    def _softmax(scores: dict[str, float]) -> dict[str, float]:
        peak = max(scores.values())
        exps = {key: math.exp(value - peak) for key, value in scores.items()}
        total = sum(exps.values())
        return {key: value / total for key, value in exps.items()}

    def _cached(self, idempotency_key: str | None) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        with self._lock:
            payload = self._idempotency.get(idempotency_key)
            if payload is not None:
                self._idempotency.move_to_end(idempotency_key)
            return payload

    def _fallback(self, request: DecisionRequest, reasons: list[str], idempotency_key: str | None) -> dict[str, Any]:
        now = datetime.now(UTC)
        payload = {
            "decision_id": f"dec_{uuid.uuid4().hex[:18]}",
            "entity_id": request.entity_id,
            "placement": request.placement,
            "action_id": "NO_TREATMENT",
            "creative_id": None,
            "propensity": 1.0,
            "policy_id": "policy_growth_safe",
            "policy_version": "pv_reference_1",
            "engine_mode": "reference-contract",
            "evidence_tier": "A",
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "guardrails": {
                "consent": request.consent_state,
                "frequency_remaining": request.frequency_remaining,
                "budget_remaining": request.budget_remaining,
                "context_freshness_seconds": request.context_freshness_seconds,
            },
            "reasons": reasons,
            "logged_at": now.isoformat(),
        }
        return self._record(payload, idempotency_key)

    def score_actions(self, request: DecisionRequest, actions: list[ActionDefinition]) -> dict[str, float]:
        ctx = request.context
        cart_value = float(ctx.get("cart_value", 0) or 0)
        intent = str(ctx.get("session_intent", "medium")).lower()
        churn_risk = float(ctx.get("churn_risk", 0) or 0)
        new_user = bool(ctx.get("new_user", False))
        abandoned_cart = bool(ctx.get("abandoned_cart", False))
        scores: dict[str, float] = {}
        for action in actions:
            if action.action_id == "NO_TREATMENT":
                score = 0.25 + churn_risk * 0.8
            elif action.action_id == "free_shipping_v3":
                score = 0.35 + min(cart_value / 500.0, 0.8) + (0.35 if intent == "high" else 0) + (0.2 if new_user else 0)
            elif action.action_id == "coupon_10_v2":
                score = 0.28 + (0.25 if new_user else 0) + (0.25 if intent in {"medium", "high"} else 0)
            elif action.action_id == "push_reminder_v4":
                score = 0.18 + (0.65 if abandoned_cart else 0) - churn_risk * 0.45
            else:
                score = 0.2 + (0.25 if intent == "medium" else 0) - churn_risk * 0.15
            score -= action.cost / 80.0
            score += self._stable_jitter(request.entity_id, action.action_id)
            scores[action.action_id] = score
        return scores

    def decide(self, request: DecisionRequest, idempotency_key: str | None = None) -> dict[str, Any]:
        cached = self._cached(idempotency_key)
        if cached is not None:
            return cached
        if not request.consent_state:
            return self._fallback(request, ["Consent unavailable; enforced NO_TREATMENT."], idempotency_key)
        if request.frequency_remaining <= 0:
            return self._fallback(request, ["Frequency cap exhausted; enforced NO_TREATMENT."], idempotency_key)
        if request.context_freshness_seconds > 300:
            return self._fallback(request, ["Context stale (>300s); conservative fallback."], idempotency_key)

        candidate_ids = request.candidate_action_ids or list(ACTION_REGISTRY)
        if "NO_TREATMENT" not in candidate_ids:
            candidate_ids = ["NO_TREATMENT", *candidate_ids]
        actions = [ACTION_REGISTRY[action_id] for action_id in candidate_ids if action_id in ACTION_REGISTRY]
        actions = [a for a in actions if a.cost <= request.budget_remaining or a.action_id == "NO_TREATMENT"]
        if not actions:
            return self._fallback(request, ["No eligible action after registry and budget checks."], idempotency_key)

        scores = self.score_actions(request, actions)
        probabilities = self._softmax(scores)
        chosen_id = max(scores, key=scores.get)
        chosen = ACTION_REGISTRY[chosen_id]
        now = datetime.now(UTC)
        payload = {
            "decision_id": f"dec_{uuid.uuid4().hex[:18]}",
            "entity_id": request.entity_id,
            "placement": request.placement,
            "action_id": chosen.action_id,
            "creative_id": chosen.creative_id,
            "propensity": round(probabilities[chosen.action_id], 6),
            "action_distribution": {key: round(value, 6) for key, value in probabilities.items()},
            "policy_id": "policy_growth_safe",
            "policy_version": "pv_reference_1",
            "engine_mode": "reference-contract",
            "evidence_tier": chosen.evidence_tier,
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "guardrails": {
                "consent": True,
                "frequency_remaining": request.frequency_remaining,
                "budget_remaining": request.budget_remaining,
                "context_freshness_seconds": request.context_freshness_seconds,
            },
            "reasons": [
                "Action is registry-valid and guardrail-feasible.",
                "Decision distribution is logged for OPE compatibility.",
                "NO_TREATMENT remained in the candidate set.",
            ],
            "logged_at": now.isoformat(),
        }
        return self._record(payload, idempotency_key)

    def _record(self, payload: dict[str, Any], idempotency_key: str | None) -> dict[str, Any]:
        with self._lock:
            # Double-check inside the write lock. Multiple concurrent first-seen
            # requests with the same idempotency key must all observe one result.
            if idempotency_key:
                existing = self._idempotency.get(idempotency_key)
                if existing is not None:
                    self._idempotency.move_to_end(idempotency_key)
                    return existing

            self._recent.appendleft(payload)
            if idempotency_key:
                self._idempotency[idempotency_key] = payload
                self._idempotency.move_to_end(idempotency_key)
                while len(self._idempotency) > self._max_idempotency_size:
                    self._idempotency.popitem(last=False)
        return payload

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent)[:limit]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "recent_decisions": len(self._recent),
                "idempotency_keys": len(self._idempotency),
                "max_idempotency_keys": self._max_idempotency_size,
            }


def action_registry_payload() -> list[dict[str, Any]]:
    return [asdict(action) for action in ACTION_REGISTRY.values()]
