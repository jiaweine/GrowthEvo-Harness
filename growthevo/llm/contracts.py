from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import blake2b
import json
from typing import Any, Mapping


_SCHEMA_VERSION = "growthevo.llm-planner-contract.v1"


def _qualified_type(value: Any) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def planner_contract_payload(planner: Any) -> dict[str, Any]:
    """Return the behavior-defining harness contract for a guarded LLM planner.

    Provider/model identity is deliberately not folded into this payload because
    it is a first-class field on ``LLMPolicyCandidate``. The contract instead
    fingerprints the parts teams often mutate accidentally under a stable model
    name: prompts, schemas, thresholds, critic posture and fallback planner type.
    """

    proposal_schema = getattr(planner, "proposal_schema", None)
    critic_schema = getattr(planner, "critic_schema", None)
    config = getattr(planner, "config", None)
    fallback = getattr(planner, "fallback", None)
    critic = getattr(planner, "critic", None)
    planner_type = type(planner)

    if not callable(proposal_schema) or not callable(critic_schema):
        raise TypeError("planner does not expose the guarded structured-output contract")
    if config is None or not is_dataclass(config):
        raise TypeError("planner config must be a dataclass instance")
    if fallback is None:
        raise TypeError("planner must expose a deterministic fallback planner")

    system_prompt = getattr(planner_type, "_SYSTEM_PROMPT", None)
    critic_prompt = getattr(planner_type, "_CRITIC_PROMPT", None)
    if not isinstance(system_prompt, str) or not system_prompt:
        raise TypeError("planner system prompt is unavailable")
    if not isinstance(critic_prompt, str) or not critic_prompt:
        raise TypeError("planner critic prompt is unavailable")

    return {
        "schema_version": _SCHEMA_VERSION,
        "planner_type": _qualified_type(planner),
        "fallback_type": _qualified_type(fallback),
        "system_prompt": system_prompt,
        "proposal_schema": proposal_schema(),
        "config": asdict(config),
        "critic": {
            "enabled": critic is not None,
            "prompt": critic_prompt if critic is not None else None,
            "schema": critic_schema() if critic is not None else None,
        },
    }


def planner_contract_fingerprint(planner: Any) -> str:
    """Return a stable 160-bit BLAKE2b identity for the planner harness contract."""

    return blake2b(_canonical_bytes(planner_contract_payload(planner)), digest_size=20).hexdigest()
