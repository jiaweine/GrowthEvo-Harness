"""Dependency-free campaign contracts shared by the operator and Web models.

The causal control arm is mandatory. The core execution runtime must not
import optional FastAPI/Pydantic dependencies just to create a draft.
"""
from __future__ import annotations

from math import isfinite
from typing import Any


KNOWN_ACTION_IDS = frozenset({
    "NO_TREATMENT", "free_shipping", "coupon_10", "push_reminder", "email_guide",
})


def validated_action_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError("candidate_action_ids must be a string list")
    deduped = list(dict.fromkeys(values))
    unknown = sorted(set(deduped).difference(KNOWN_ACTION_IDS))
    if unknown:
        raise ValueError(f"unknown candidate_action_ids: {unknown}")
    return deduped


def validated_campaign_draft(
    payload: dict[str, Any], *, max_budget: float | None = None,
) -> dict[str, Any]:
    """Normalize a draft write at the same authority boundary as the API.

    Models may propose strings and action IDs, but not new legal actions,
    arbitrary object properties or floating-point NaNs.
    """
    expected = {"name", "goal", "audience", "budget", "candidate_action_ids"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("campaign draft contract fields are invalid")
    result: dict[str, Any] = {}
    for key, lo, hi in (("name", 2, 200), ("goal", 3, 1000), ("audience", 2, 500)):
        value = payload[key]
        if not isinstance(value, str) or not lo <= len(value.strip()) <= hi:
            raise ValueError(f"invalid campaign draft {key}")
        result[key] = value.strip()
    budget = payload["budget"]
    if (isinstance(budget, bool) or not isinstance(budget, (int, float))
        or not isfinite(budget) or budget < 0
        or (max_budget is not None and budget > max_budget)):
        raise ValueError("campaign draft budget outside permitted bounds")
    result["budget"] = float(budget)
    action_ids = validated_action_ids(payload["candidate_action_ids"])
    if len(action_ids) > 64:
        raise ValueError("too many candidate_action_ids")
    if "NO_TREATMENT" not in action_ids:
        action_ids.insert(0, "NO_TREATMENT")
    result["candidate_action_ids"] = action_ids
    return result
