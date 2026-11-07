"""Growth data and operations tests: contracts, persisted facts and safe dispatch."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from pydantic import ValidationError

from growthevo.web.growth_api import Experiment, Profile
from growthevo.web.growth_service import GrowthService
from growthevo.web.growth_store import GrowthConflict, GrowthStore, seed_sample

DATABASE_URL = os.getenv("GROWTHEVO_TEST_DATABASE_URL", "").strip()


def test_experiment_weights_and_consent_are_strict() -> None:
    with pytest.raises(ValidationError):
        Experiment(
            id="exp", name="random test", status="active",
            variants=[{"id": "control", "weight": 4000}, {"id": "treatment", "weight": 5000}],
        )
    with pytest.raises(ValidationError):
        Profile(id="alice", segment="new", preferred_channel="email", consent="yes")


def test_growth_apis_do_not_fall_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    monkeypatch.delenv("GROWTHEVO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from growthevo.web.app import create_app
    with TestClient(create_app()) as client:
        response = client.get("/api/growth/profiles")
        assert response.status_code == 503
        assert "PostgreSQL" in response.json()["detail"]


@pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")
def test_sample_is_durable_and_principal_scoped() -> None:
    from growthevo.web.persistence import PostgresStore

    parent = PostgresStore(DATABASE_URL, seed_reference=False)
    try:
        store = GrowthStore(parent)
        seed_sample(store, "growth-demo-scope")
        assert store.get("growth-demo-scope", "profile", "sample-alex")["origin"] == "simulated"
        assert store.get("other-scope", "profile", "sample-alex") is None
    finally:
        parent.close()

    restarted = PostgresStore(DATABASE_URL, seed_reference=False)
    try:
        assert GrowthStore(restarted).get("growth-demo-scope", "profile", "sample-bo")
    finally:
        restarted.close()


@pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")
def test_experiment_and_online_feedback_have_distinct_evidence() -> None:
    from growthevo.web.persistence import PostgresStore

    parent = PostgresStore(DATABASE_URL, seed_reference=False)
    try:
        scope = "growth-experiment-test"
        store = GrowthStore(parent)
        seed_sample(store, scope)
        svc = GrowthService(store, scope, simulation=True)
        assignment = svc.assign("sample-onboarding", "sample-alex")
        assert assignment["variant"] in {"control", "treatment"}
        assert svc.assign("sample-onboarding", "sample-alex") == assignment
        exposure = svc.exposure("sample-onboarding", "sample-alex", "first-render")
        assert svc.exposure("sample-onboarding", "sample-alex", "first-render") == exposure
        assert svc.metric("sample-onboarding", "sample-alex", "event-purchase", 1)["value"] == 1
        report = svc.report("sample-onboarding")
        assert report["assignments"] == 1
        assert sum(v["exposed"] for v in report["variants"].values()) == 1
        assert report["causal_claim"] == "insufficient_data"
        with pytest.raises(GrowthConflict):
            svc.metric("sample-onboarding", "sample-alex", "event-purchase", 0)
        first = svc.decide({
            "subject_id": "sample-alex", "placement": "home",
            "decision_key": "once", "budget_remaining": 50,
            "frequency_remaining": 2,
        })
        assert first["policy_basis"] == "observational_feedback_not_causal_uplift"
        assert sum(first["action_distribution"].values()) == pytest.approx(1.0)
        assert first["propensity"] == first["action_distribution"][first["action_id"]]
        assert svc.decide({
            "subject_id": "sample-alex", "placement": "home",
            "decision_key": "once", "budget_remaining": 50,
            "frequency_remaining": 2,
        }) == first
        assert svc.feedback(first["id"], "outcome-once", True)["success"]
        with pytest.raises(GrowthConflict):
            svc.feedback(first["id"], "different-outcome", False)
        blocked = svc.decide({
            "subject_id": "sample-chen", "placement": "home",
            "decision_key": "no-consent", "budget_remaining": 50,
            "frequency_remaining": 2,
        })
        assert blocked["action_id"] == "NO_TREATMENT"
        assert blocked["propensity"] == 1.0
    finally:
        parent.close()


@pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")
def test_event_trigger_creates_durable_simulated_delivery() -> None:
    from growthevo.web.persistence import PostgresStore

    parent = PostgresStore(DATABASE_URL, seed_reference=False)
    try:
        scope = "growth-journey-test"
        store = GrowthStore(parent)
        seed_sample(store, scope)
        svc = GrowthService(store, scope, simulation=True)
        svc.event({"id": "event-cart-1", "subject_id": "sample-bo",
                   "name": "cart_abandoned", "origin": "simulated"})
        svc.event({"id": "event-cart-1", "subject_id": "sample-bo",
                   "name": "cart_abandoned", "origin": "simulated"})
        assert len(store.jobs(scope)) == 1
        done = svc.run_due()
        assert done[0]["status"] == "simulated"
        first_delivery = store.list(scope, "delivery")[0]
        assert first_delivery["status"] == "simulated"
        assert first_delivery["origin"] == "simulated"
        assert len(store.jobs(scope)) == 2  # next step queued with delay
        assert not any(j["status"] == "simulated" and j["step_index"] == 1
                       for j in store.jobs(scope))
    finally:
        parent.close()


@pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")
def test_api_uses_database_for_sample_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("GROWTHEVO_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("GROWTHEVO_GROWTH_SEED_SAMPLE", "1")
    from growthevo.web.app import create_app
    with TestClient(create_app()) as client:
        overview = client.get("/api/growth/overview")
        assert overview.status_code == 200
        assert overview.json()["storage"] == "postgresql"
        assert overview.json()["contains_simulated_data"] is True
        assert client.get("/api/growth/profiles").json()
        experiment = client.post(
            "/api/growth/experiments/sample-onboarding/assign",
            json={"subject_id": "sample-alex"},
        )
        assert experiment.status_code == 200
        invalid = client.put("/api/growth/experiments/bad", json={
            "id": "bad", "name": "bad allocation", "status": "active",
            "variants": [{"id": "control", "weight": 6000},
                         {"id": "treatment", "weight": 6000}],
        })
        assert invalid.status_code == 422
        event = client.post("/api/growth/events", json={
            "id": "sample-cart-event", "subject_id": "sample-bo",
            "name": "cart_abandoned", "origin": "simulated",
        })
        assert event.status_code == 201
        assert any(j["event_id"] == "sample-cart-event"
                   for j in client.get("/api/growth/journeys/jobs").json())
