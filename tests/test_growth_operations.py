from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest

pytest.importorskip("pydantic")

from growthevo.web.growth_ops import GrowthOperations
from growthevo.web.growth_schemas import CustomerInput, EventInput, ExposureInput
from growthevo.web.growth_seed import seed_records
from growthevo.web.growth_store import GrowthConflict, GrowthStore


class _Tx:
    def __init__(self, records):
        self.records = records

    def get(self, kind, key):
        return deepcopy(self.records.get((kind, key)))

    def all(self, kind, *, limit=2000):
        return [deepcopy(v) for (name, _), v in sorted(self.records.items())
                if name == kind][:limit]

    def put(self, kind, key, data, *, new=False):
        if new and (kind, key) in self.records:
            raise GrowthConflict("already exists")
        self.records[(kind, key)] = deepcopy(data)


class _FakeStore:
    def __init__(self):
        self.records = {}

    def run(self, scope, operation, *, write=False):
        return operation(_Tx(self.records))

    def seed(self):
        for kind, key, item in seed_records():
            _Tx(self.records).put(kind, key, item, new=True)


def _event(event_id, customer_id, name):
    return EventInput(event_id=event_id, customer_id=customer_id,
                      name=name).model_dump(mode="json")


def test_db_demo_fixtures_are_explicit_and_coherent():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    overview = service.overview if False else None  # fake has no actual PostgreSQL
    profile = service.profile("demo_customer_01")
    assert profile["customer"]["synthetic"] is True
    assert "demo_new_customers" in profile["segments"]
    report = service.report("demo_first_purchase")
    assert report["causal_claim"] is False
    assert report["source"] == "synthetic_and_observed"
    assert [row["exposed_customers"] for row in report["results"]] == [6, 6]
    assert [row["converted_customers"] for row in report["results"]] == [2, 4]


def test_assignment_is_sticky_and_exposure_is_idempotent():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    payload = ExposureInput(
        customer_id="demo_customer_01", request_id="newrequest_01",
        surface="app_home",
    ).model_dump(mode="json")
    first = service.expose("demo_first_purchase", payload)
    assert service.expose("demo_first_purchase", payload) == first
    second = service.expose("demo_first_purchase", payload | {"request_id": "newrequest_02"})
    assert first["variant"] == second["variant"]
    with pytest.raises(GrowthConflict, match="exposure request identity"):
        service.expose("demo_first_purchase", payload | {"customer_id": "demo_customer_02"})
    with pytest.raises(GrowthConflict, match="no consent"):
        service.expose("demo_first_purchase", payload | {
            "request_id": "newrequest_03", "customer_id": "demo_customer_12",
        })


def test_event_enrolls_journey_once_and_requires_delivery_receipt():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    event = _event("signup_fresh_01", "demo_customer_01", "signup")
    result = service.ingest_event(event)
    assert result["new_enrollments"] == 1
    assert service.ingest_event(event)["deduplicated"] is True
    processed = service.process_due(limit=50)
    selected = next(x for x in processed["processed"] if "signup_fresh_01" in x["job_id"])
    assert selected["status"] == "simulated"
    delivery_id = selected["delivery_id"]
    receipt = {"provider_event_id": "receipt_test_01", "status": "delivered",
               "occurred_at": datetime.now(timezone.utc).isoformat()}
    applied = service.record_receipt(delivery_id, receipt, permit_simulation=True)
    assert applied["delivery"]["status"] == "delivered"
    assert service.record_receipt(delivery_id, receipt, permit_simulation=True)["deduplicated"]
    assert any(j["step_index"] == 1 and "signup_fresh_01" in j["job_id"]
               for j in service.list("jobs"))


def test_consent_suppresses_journey_and_duplicate_event_conflicts():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    event = _event("signup_not_allowed", "demo_customer_12", "signup")
    assert service.ingest_event(event)["new_enrollments"] == 0
    with pytest.raises(GrowthConflict, match="event identity"):
        service.ingest_event(event | {"name": "purchase"})


def test_postgres_demo_survives_store_recreation_when_configured():
    database_url = os.getenv("GROWTHEVO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("real PostgreSQL is only exercised in the persistence CI job")
    from growthevo.web.persistence import PostgresStore

    scope = "growth-test-" + uuid4().hex
    first = PostgresStore(database_url, seed_reference=False)
    second = None
    try:
        store = GrowthStore(first)
        store.ensure_demo(scope)
        service = GrowthOperations(store, scope)
        assert service.report("demo_first_purchase")["results"][0]["exposed_customers"] == 6
        event = _event("persisted_new_event", "demo_customer_01", "signup")
        assert service.ingest_event(event)["new_enrollments"] == 1
        second = PostgresStore(database_url, seed_reference=False)
        recovered = GrowthOperations(GrowthStore(second), scope)
        assert recovered.profile("demo_customer_01")["customer"]["synthetic"]
        assert recovered.ingest_event(event)["deduplicated"] is True
        assert len([j for j in recovered.list("jobs") if "persisted_new_event" in j["job_id"]]) == 1
    finally:
        if second is not None:
            second.close()
        first.close()
