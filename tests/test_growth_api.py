"""End-to-end growth API contracts, including the real PostgreSQL path."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from growthevo.web.app import create_app


def test_growth_operations_fail_closed_without_database(monkeypatch):
    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/growth/overview")
    assert response.status_code == 503
    assert "PostgreSQL" in response.json()["detail"]


def test_growth_api_writes_real_postgres_and_separates_external_sends(monkeypatch):
    database_url = os.getenv("GROWTHEVO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires PostgreSQL service in Product Persistence CI")
    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("GROWTHEVO_DATABASE_URL", database_url)
    for key in ("GROWTHEVO_AUTH_ISSUER", "GROWTHEVO_AUTH_JWKS_URL", "GROWTHEVO_AUTH_AUDIENCE"):
        monkeypatch.delenv(key, raising=False)
    prefix = "test_" + uuid4().hex[:12]
    customer = prefix + "_user"
    segment = prefix + "_segment"
    creative = prefix + "_creative"
    journey = prefix + "_journey"
    exp = prefix + "_experiment"

    with TestClient(create_app()) as client:
        overview = client.get("/api/growth/overview")
        assert overview.status_code == 200
        assert overview.json()["backend"] == "postgresql"
        assert overview.json()["data_origin"] == "synthetic_and_observed"

        created = client.post("/api/growth/customers", json={
            "customer_id": customer,
            "attributes": {"lifecycle": "new", "region": "west"},
            "consent": True,
        })
        assert created.status_code == 201, created.text
        assert client.post("/api/growth/customers", json={
            "customer_id": customer, "attributes": {}, "consent": True,
        }).status_code == 409

        assert client.post("/api/growth/segments", json={
            "segment_id": segment, "name": "Recently joined",
            "equals": {"lifecycle": "new"},
        }).status_code == 201
        matched = client.get(f"/api/growth/segments/{segment}/preview")
        assert customer in matched.json()["customer_ids"]
        assert client.post("/api/growth/creatives", json={
            "creative_id": creative, "channel": "email",
            "title": "Welcome", "body": "Thanks for joining",
        }).status_code == 201
        assert client.post("/api/growth/journeys", json={
            "journey_id": journey, "name": "Onboarding welcome",
            "trigger_event": "signup", "segment_id": segment,
            "steps": [{"channel": "email", "creative_id": creative,
                       "offer_id": None, "delay_seconds": 0}],
        }).status_code == 201
        assert client.post(f"/api/growth/journeys/{journey}/activate").status_code == 200

        event = {"event_id": prefix + "_signup", "customer_id": customer,
                 "name": "signup"}
        ingested = client.post("/api/growth/events", json=event)
        assert ingested.status_code == 201, ingested.text
        assert ingested.json()["new_enrollments"] == 1
        assert client.post("/api/growth/events", json=event).status_code == 409  # missing original occurred_at

        processed = client.post("/api/growth/journeys/process", json={"limit": 50})
        assert processed.status_code == 200, processed.text
        queued = [d for d in client.get("/api/growth/deliveries").json()
                  if d["customer_id"] == customer]
        assert len(queued) == 1
        assert queued[0]["status"] == "queued"
        assert client.post(
            f"/api/growth/deliveries/{queued[0]['delivery_id']}/submit"
        ).status_code == 409  # No real sending from API mode.

        assert client.post("/api/growth/experiments", json={
            "experiment_id": exp, "name": "Checkout offer",
            "metric_event": "purchase", "control": "holdout",
            "variants": [{"key": "holdout", "weight": 50},
                         {"key": "offer", "weight": 50}],
            "window_days": 7,
        }).status_code == 201
        exposure = {"customer_id": customer, "request_id": prefix + "_exposure",
                    "surface": "checkout"}
        first = client.post(f"/api/growth/experiments/{exp}/exposures", json=exposure)
        assert first.status_code == 201
        again = client.post(f"/api/growth/experiments/{exp}/exposures", json=exposure)
        assert again.json() == first.json()
        assert client.post("/api/growth/events", json={
            "event_id": prefix + "_purchase", "customer_id": customer,
            "name": "purchase",
        }).status_code == 201
        report = client.get(f"/api/growth/experiments/{exp}/report")
        assert report.status_code == 200
        assert report.json()["causal_claim"] is False
        assert sum(arm["converted_customers"] for arm in report.json()["results"]) == 1
