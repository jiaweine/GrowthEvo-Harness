from __future__ import annotations

from typing import Any

from growthevo._version import __version__

CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "id": "causal",
        "name": "Causal effect estimation",
        "detail": "Group-aware cross-fitted doubly robust CATE.",
        "module": "growthevo.causal",
    },
    {
        "id": "support",
        "name": "Support modeling",
        "detail": "Positivity, overlap, propensity handling and distributional support.",
        "module": "growthevo.causal",
    },
    {
        "id": "safe-pi",
        "name": "Safe policy improvement",
        "detail": "Pessimistic value, conservative cost and trust-region policy updates.",
        "module": "growthevo.rl.safe_policy_improvement",
    },
    {
        "id": "ope",
        "name": "Off-policy evaluation",
        "detail": "IPS, SNIPS, DR, SWITCH-DR, DR-OS, Meta-OPE and cross-fitted beta*-IPS.",
        "module": "growthevo.rl.ope",
    },
    {
        "id": "evidence",
        "name": "Locked evidence",
        "detail": "Pre-registered plans, frozen validation selection and final holdout.",
        "module": "growthevo.bench",
    },
    {
        "id": "verification",
        "name": "Verification",
        "detail": "One-sided conformal calibration with multi-constraint correction.",
        "module": "growthevo.rl.conformal",
    },
    {
        "id": "planning",
        "name": "Risk-sensitive planning",
        "detail": "Stochastic rollout, downside CVaR and constraint-aware planning.",
        "module": "growthevo.rl.model_based",
    },
    {
        "id": "operator",
        "name": "Production operator",
        "detail": "Locked shadow execution, provider preflight and promotion authority.",
        "module": "growthevo.operator_cli",
    },
)

EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "id": "criteo",
        "name": "Criteo Uplift v2.1",
        "kind": "Locked targeting",
        "winner": "S-Learner",
        "commit": "7ac26a5aebde2c70e1b43264b89f08dddcff0245",
        "metrics": (
            {"label": "Source rows", "value": "13,979,592"},
            {"label": "Population increment", "value": "+0.93791 pp"},
            {"label": "Selected top-10% increment", "value": "+9.37910 pp"},
            {"label": "95% CI", "value": "[+0.89584, +0.97998] pp"},
        ),
        "href": "https://github.com/jiaweine/GrowthEvo-Harness/tree/main/benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a",
    },
    {
        "id": "obd",
        "name": "Open Bandit Dataset",
        "kind": "Locked OPE",
        "winner": "IPS",
        "commit": "7d538cea9698b5f0a48c585eed85e3ae526e5af6",
        "metrics": (
            {"label": "Random-policy rows", "value": "1,374,327"},
            {"label": "Final estimate", "value": "0.00452954"},
            {"label": "Support coverage", "value": "1.0000"},
            {"label": "ESS ratio", "value": "0.16123"},
        ),
        "href": "https://github.com/jiaweine/GrowthEvo-Harness/tree/main/benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea",
    },
)

ARCHITECTURE: tuple[dict[str, str], ...] = (
    {"name": "Web UI", "detail": "Responsive dashboard served from the package."},
    {"name": "FastAPI", "detail": "Read-only project and evidence JSON endpoints."},
    {"name": "Operator", "detail": "Locked execution, provider checks and promotion controls."},
    {"name": "Decision stack", "detail": "Causal estimation, safe PI, OPE and planning."},
    {"name": "Evidence", "detail": "Pre-registration, validation selection and final holdout."},
)


def build_dashboard_payload() -> dict[str, Any]:
    """Return the stable, dependency-free payload consumed by the web UI."""

    return {
        "project": {
            "name": "GrowthEvo-Harness",
            "version": __version__,
            "tagline": "Causal reinforcement learning for incremental user growth",
            "status": "research-ready",
            "surface": "web-dashboard",
        },
        "summary": {
            "capability_count": len(CAPABILITIES),
            "locked_evidence_sets": len(EVIDENCE),
            "api_version": "v1",
        },
        "capabilities": [dict(item) for item in CAPABILITIES],
        "evidence": [
            {
                **{key: value for key, value in item.items() if key != "metrics"},
                "metrics": [dict(metric) for metric in item["metrics"]],
            }
            for item in EVIDENCE
        ],
        "architecture": [dict(item) for item in ARCHITECTURE],
    }
