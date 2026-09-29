from __future__ import annotations

from typing import Any

from .product_data import CAPABILITIES, EVIDENCE, ReferenceProductState, dashboard_payload

_COMPAT_CAPABILITIES = (
    {
        "id": "safe-pi",
        "name": "Safe policy improvement",
        "detail": "Pessimistic value, conservative cost and trust-region policy updates.",
        "module": "growthevo.rl.safe_policy_improvement",
    },
    {
        "id": "operator",
        "name": "Production operator",
        "detail": "Locked shadow execution, provider preflight and promotion controls.",
        "module": "growthevo.operator_cli",
    },
)

_ARCHITECTURE = (
    {"name": "Growth OS", "detail": "Responsive web/PWA and mobile companion surfaces."},
    {"name": "FastAPI", "detail": "Versioned product and decision contracts."},
    {"name": "Agent Harness", "detail": "Context, tools, claims, traces, evals and approval boundaries."},
    {"name": "Decision stack", "detail": "Causal estimation, safe PI, OPE and risk-aware planning."},
    {"name": "Evidence", "detail": "Pre-registration, validation selection and final holdout."},
)


def build_dashboard_payload(state: ReferenceProductState | None = None) -> dict[str, Any]:
    """Return the product dashboard while preserving the v0.1 compatibility contract."""
    payload = dashboard_payload(state)
    ids = {item["id"] for item in payload["capabilities"]}
    payload["capabilities"].extend(
        dict(item) for item in _COMPAT_CAPABILITIES if item["id"] not in ids
    )
    payload["project"].update(
        {
            "name": "GrowthEvo-Harness",
            "surface": "web-dashboard",
            "product_surface": "growth-os",
        }
    )
    payload["summary"].update(
        {
            "capability_count": len(payload["capabilities"]),
            "locked_evidence_sets": len(EVIDENCE),
            "api_version": "v1",
        }
    )
    payload["architecture"] = [dict(item) for item in _ARCHITECTURE]
    return payload
