from __future__ import annotations

from growthevo.web.data import build_dashboard_payload


def test_dashboard_payload_exposes_product_surface() -> None:
    payload = build_dashboard_payload()

    assert payload["project"]["name"] == "GrowthEvo-Harness"
    assert payload["project"]["surface"] == "web-dashboard"
    assert payload["summary"]["api_version"] == "v1"
    assert payload["summary"]["locked_evidence_sets"] == 2


def test_dashboard_capabilities_and_evidence_are_stable() -> None:
    payload = build_dashboard_payload()

    capability_ids = [item["id"] for item in payload["capabilities"]]
    evidence_ids = [item["id"] for item in payload["evidence"]]

    assert len(capability_ids) == len(set(capability_ids))
    assert {"causal", "safe-pi", "ope", "operator"} <= set(capability_ids)
    assert evidence_ids == ["criteo", "obd"]
    assert all(item["commit"] for item in payload["evidence"])
