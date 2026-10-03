from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import uuid
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import DecisionRequest

UTC = timezone.utc
REFERENCE_POLICY_ID = "policy_growth_safe"


class DecisionInputError(ValueError):
    """Raised when a syntactically valid decision request has unsafe values."""


class IdempotencyConflict(ValueError):
    """Raised when one idempotency key is reused for a materially different request."""


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
    "free_shipping": ActionDefinition("free_shipping", "首单免邮", "web", 8.0, "L2", "cr_free_ship_281", "A"),
    "coupon_10": ActionDefinition("coupon_10", "¥10 优惠券", "coupon", 10.0, "L3", "cr_coupon_104", "B"),
    "push_reminder": ActionDefinition("push_reminder", "加购提醒", "push", 0.08, "L2", "cr_push_442", "A"),
    "email_guide": ActionDefinition("email_guide", "产品指南 Email", "email", 0.03, "L1", "cr_email_090", "B"),
}


class ReferenceDecisionEngine:
    """Auditable product-level decision contract.

    This reference scorer validates API semantics and guardrails. Production deployments
    should replace ``score_actions`` with the harness' locked CATE/OPE/policy pipeline.

    Eligible actions are assigned with a stable hash draw from the logged softmax
    distribution. This keeps the reference policy reproducible while ensuring the
    recorded behavior propensity actually matches the assignment mechanism used to
    choose the action. It is still a reference contract, not a production causal policy.

    The in-process idempotency cache is deliberately bounded. Production should persist
    idempotency/decision logs in durable shared storage before using multiple replicas.
    """

    def __init__(self, max_log_size: int = 500, max_idempotency_size: int = 5_000) -> None:
        if max_log_size <= 0:
            raise ValueError("max_log_size must be > 0")
        if max_idempotency_size <= 0:
            raise ValueError("max_idempotency_size must be > 0")
        self._lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max_log_size)
        self._idempotency: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        self._max_idempotency_size = max_idempotency_size

    @staticmethod
    def _stable_jitter(entity_id: str, action_id: str) -> float:
        raw = hashlib.sha256(f"{entity_id}:{action_id}".encode()).digest()
        integer = int.from_bytes(raw[:4], "big")
        return (integer / (2**32 - 1) - 0.5) * 0.12

    @staticmethod
    def _softmax(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            raise DecisionInputError("no actions are available for scoring")
        peak = max(scores.values())
        exps = {key: math.exp(value - peak) for key, value in scores.items()}
        total = sum(exps.values())
        if not math.isfinite(total) or total <= 0:
            raise DecisionInputError("decision distribution could not be normalized")
        return {key: value / total for key, value in exps.items()}

    @staticmethod
    def _request_fingerprint(request: DecisionRequest) -> str:
        candidates = None if request.candidate_action_ids is None else sorted(set(request.candidate_action_ids))
        canonical = {
            "entity_id": request.entity_id,
            "placement": request.placement,
            "context": request.context,
            "candidate_action_ids": candidates,
            "consent_state": request.consent_state,
            "frequency_remaining": request.frequency_remaining,
            "budget_remaining": request.budget_remaining,
            "context_freshness_seconds": request.context_freshness_seconds,
        }
        try:
            encoded = json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DecisionInputError("decision request must contain finite JSON values") from exc
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _context_float(
        context: dict[str, Any],
        key: str,
        default: float = 0.0,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        raw = context.get(key, default)
        if isinstance(raw, bool):
            raise DecisionInputError(f"context.{key} must be numeric, not boolean")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise DecisionInputError(f"context.{key} must be numeric") from exc
        if not math.isfinite(value):
            raise DecisionInputError(f"context.{key} must be finite")
        if minimum is not None and value < minimum:
            raise DecisionInputError(f"context.{key} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise DecisionInputError(f"context.{key} must be <= {maximum}")
        return value

    @staticmethod
    def _context_bool(context: dict[str, Any], key: str, default: bool = False) -> bool:
        raw = context.get(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw in (0, 1):
            return bool(raw)
        raise DecisionInputError(f"context.{key} must be boolean")

    @staticmethod
    def _assignment_draw(request: DecisionRequest) -> float:
        material = f"{REFERENCE_POLICY_ID}:{request.entity_id}:{request.placement}".encode("utf-8")
        integer = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        return integer / 2**64

    @staticmethod
    def _select_action(probabilities: dict[str, float], draw: float) -> str:
        cumulative = 0.0
        last: str | None = None
        for action_id, probability in probabilities.items():
            last = action_id
            cumulative += probability
            if draw < cumulative:
                return action_id
        if last is None:  # pragma: no cover - guarded by _softmax
            raise DecisionInputError("no action could be selected")
        return last

    def _cached(
        self,
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        with self._lock:
            entry = self._idempotency.get(idempotency_key)
            if entry is None:
                return None
            stored_fingerprint, payload = entry
            if request_fingerprint != stored_fingerprint:
                raise IdempotencyConflict(
                    "Idempotency-Key was already used for a different decision request"
                )
            self._idempotency.move_to_end(idempotency_key)
            return copy.deepcopy(payload)

    def _fallback(
        self,
        request: DecisionRequest,
        reasons: list[str],
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        payload = {
            "decision_id": f"dec_{uuid.uuid4().hex[:18]}",
            "entity_id": request.entity_id,
            "placement": request.placement,
            "action_id": "NO_TREATMENT",
            "creative_id": None,
            "propensity": 1.0,
            "action_distribution": {"NO_TREATMENT": 1.0},
            "policy_id": REFERENCE_POLICY_ID,
            "policy_randomization": "guardrail-deterministic",
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
        return self._record(payload, idempotency_key, request_fingerprint)

    def score_actions(self, request: DecisionRequest, actions: list[ActionDefinition]) -> dict[str, float]:
        ctx = request.context
        cart_value = self._context_float(ctx, "cart_value", minimum=0.0)
        intent = str(ctx.get("session_intent", "medium")).lower()
        if intent not in {"low", "medium", "high"}:
            raise DecisionInputError("context.session_intent must be low, medium, or high")
        churn_risk = self._context_float(ctx, "churn_risk", minimum=0.0, maximum=1.0)
        new_user = self._context_bool(ctx, "new_user")
        abandoned_cart = self._context_bool(ctx, "abandoned_cart")
        scores: dict[str, float] = {}
        for action in actions:
            if action.action_id == "NO_TREATMENT":
                score = 0.25 + churn_risk * 0.8
            elif action.action_id == "free_shipping":
                score = 0.35 + min(cart_value / 500.0, 0.8) + (0.35 if intent == "high" else 0) + (0.2 if new_user else 0)
            elif action.action_id == "coupon_10":
                score = 0.28 + (0.25 if new_user else 0) + (0.25 if intent in {"medium", "high"} else 0)
            elif action.action_id == "push_reminder":
                score = 0.18 + (0.65 if abandoned_cart else 0) - churn_risk * 0.45
            else:
                score = 0.2 + (0.25 if intent == "medium" else 0) - churn_risk * 0.15
            score -= action.cost / 80.0
            score += self._stable_jitter(request.entity_id, action.action_id)
            scores[action.action_id] = score
        return scores

    def decide(self, request: DecisionRequest, idempotency_key: str | None = None) -> dict[str, Any]:
        if not math.isfinite(request.budget_remaining):
            raise DecisionInputError("budget_remaining must be finite")
        request_fingerprint = self._request_fingerprint(request) if idempotency_key else None
        cached = self._cached(idempotency_key, request_fingerprint)
        if cached is not None:
            return cached
        if not request.consent_state:
            return self._fallback(
                request,
                ["Consent unavailable; enforced NO_TREATMENT."],
                idempotency_key,
                request_fingerprint,
            )
        if request.frequency_remaining <= 0:
            return self._fallback(
                request,
                ["Frequency cap exhausted; enforced NO_TREATMENT."],
                idempotency_key,
                request_fingerprint,
            )
        if request.context_freshness_seconds > 300:
            return self._fallback(
                request,
                ["Context stale (>300s); conservative fallback."],
                idempotency_key,
                request_fingerprint,
            )

        if request.candidate_action_ids is None:
            candidate_ids = list(ACTION_REGISTRY)
        else:
            requested = set(request.candidate_action_ids)
            unknown = sorted(requested.difference(ACTION_REGISTRY))
            if unknown:
                raise DecisionInputError(
                    "unknown candidate_action_ids: " + ", ".join(unknown)
                )
            requested.add("NO_TREATMENT")
            # Registry order is canonical so semantically identical candidate
            # sets produce the same distribution regardless of caller list order.
            candidate_ids = [action_id for action_id in ACTION_REGISTRY if action_id in requested]

        actions = [ACTION_REGISTRY[action_id] for action_id in candidate_ids]
        actions = [a for a in actions if a.cost <= request.budget_remaining or a.action_id == "NO_TREATMENT"]
        if not actions:  # pragma: no cover - NO_TREATMENT is always eligible
            return self._fallback(
                request,
                ["No eligible action after registry and budget checks."],
                idempotency_key,
                request_fingerprint,
            )

        scores = self.score_actions(request, actions)
        probabilities = self._softmax(scores)
        draw = self._assignment_draw(request)
        chosen_id = self._select_action(probabilities, draw)
        chosen = ACTION_REGISTRY[chosen_id]
        now = datetime.now(UTC)
        payload = {
            "decision_id": f"dec_{uuid.uuid4().hex[:18]}",
            "entity_id": request.entity_id,
            "placement": request.placement,
            "action_id": chosen.action_id,
            "creative_id": chosen.creative_id,
            "propensity": probabilities[chosen.action_id],
            "action_distribution": probabilities,
            "assignment_draw": draw,
            "policy_id": REFERENCE_POLICY_ID,
            "policy_randomization": "stable-hash-softmax",
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
                "Selected action was sampled from the logged reference distribution.",
                "Behavior propensity matches the reference assignment mechanism.",
                "NO_TREATMENT remained in the candidate set.",
            ],
            "logged_at": now.isoformat(),
        }
        return self._record(payload, idempotency_key, request_fingerprint)

    def _record(
        self,
        payload: dict[str, Any],
        idempotency_key: str | None,
        request_fingerprint: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key:
                entry = self._idempotency.get(idempotency_key)
                if entry is not None:
                    stored_fingerprint, existing = entry
                    if request_fingerprint != stored_fingerprint:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different decision request"
                        )
                    self._idempotency.move_to_end(idempotency_key)
                    return copy.deepcopy(existing)

            stored = copy.deepcopy(payload)
            self._recent.appendleft(stored)
            if idempotency_key:
                if request_fingerprint is None:  # pragma: no cover - defensive invariant
                    raise RuntimeError("idempotent decisions require a request fingerprint")
                self._idempotency[idempotency_key] = (request_fingerprint, stored)
                self._idempotency.move_to_end(idempotency_key)
                while len(self._idempotency) > self._max_idempotency_size:
                    self._idempotency.popitem(last=False)
        return copy.deepcopy(stored)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(list(self._recent)[:limit])

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "recent_decisions": len(self._recent),
                "idempotency_keys": len(self._idempotency),
                "max_idempotency_keys": self._max_idempotency_size,
            }


def action_registry_payload() -> list[dict[str, Any]]:
    return [asdict(action) for action in ACTION_REGISTRY.values()]
