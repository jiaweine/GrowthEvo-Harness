from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from growthevo.web.app import create_app


def test_idempotency_header_stays_single_string_in_openapi() -> None:
    schema = TestClient(create_app()).get("/api/openapi.json").json()
    parameters = schema["paths"]["/api/decide"]["post"]["parameters"]
    header = next(item for item in parameters if item.get("in") == "header" and item.get("name") == "Idempotency-Key")
    assert header["required"] is False
    variants = header["schema"].get("anyOf", [header["schema"]])
    string_schema = next(item for item in variants if item.get("type") == "string")
    assert all(item.get("type") in {"string", "null"} for item in variants)
    assert string_schema["minLength"] == 1
    assert string_schema["maxLength"] == 256
