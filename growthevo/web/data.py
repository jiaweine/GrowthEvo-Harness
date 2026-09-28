from __future__ import annotations

from typing import Any

from .product_data import CAPABILITIES, EVIDENCE, dashboard_payload


def build_dashboard_payload() -> dict[str, Any]:
    """Compatibility wrapper for the original web dashboard endpoint."""
    return dashboard_payload()
