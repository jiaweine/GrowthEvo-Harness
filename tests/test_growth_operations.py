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
    profile = service.profile("demo_customer_01")
    assert profile["customer"]["synthetic"] is True
    assert "demo_new_customers" in profile["segments"]
    report = service.report("demo_first_purchase")
    assert report["causal_claim"] is False
    assert report["source"] == "synthetic_and_observed"
    assert [row["exposed_customers"] for row in report["results"]] == [6, 6]
    assert [row["converted_customers"] for row in report["results"]] == [2, 4]


def test_synthetic_events_keep_customer_provenance_across_feedback():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    synthetic = service.ingest_event(_event("demo_new_purchase", "demo_customer_01", "purchase"))
    assert synthetic["event"]["synthetic"] is True
    assert service.ingest_event(_event("demo_new_purchase", "demo_customer_01", "purchase"))["deduplicated"]
    service.create("customers", "customer_real_provenance", {
        "customer_id": "customer_real_provenance", "attributes": {}, "consent": True
    })
    observed = service.ingest_event(_event("real_purchase", "customer_real_provenance", "purchase"))
    assert observed["event"]["synthetic"] is False
    assert all(x["synthetic"] for x in service.profile("demo_customer_01")["events"])
    assert all(not x["synthetic"] for x in service.profile("customer_real_provenance")["events"])


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



def test_external_dispatch_is_scoped_consent_gated_and_cannot_replay():
    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    # Synthetic delivery cannot be promoted into a real channel submission.
    delivery = service.process_due()["processed"][0]["delivery_id"]
    with pytest.raises(GrowthConflict, match="only real queued"):
        service.reserve_external_submission(delivery)


def test_channel_webhook_rejects_untrusted_or_insecure_hosts():
    from growthevo.web.growth_channels import ChannelWebhook, ChannelConfigurationError
    with pytest.raises(ChannelConfigurationError):
        ChannelWebhook("http://api.example.com/callback", "x" * 20, {"api.example.com"})
    with pytest.raises(ChannelConfigurationError):
        ChannelWebhook("https://attacker.example.com/callback", "x" * 20, {"api.example.com"})
    with pytest.raises(ChannelConfigurationError):
        ChannelWebhook("https://api.example.com/callback", "short", {"api.example.com"})
    client = ChannelWebhook("https://api.example.com/callback", "x" * 20, {"api.example.com"})
    assert client.url.startswith("https://")




def test_real_gateway_receipt_requires_prior_submission_and_profile_consent():
    fake = _FakeStore()
    service = GrowthOperations(fake, "test")
    service.create("customers", "customer_real", {
        "customer_id": "customer_real", "attributes": {"lifecycle": "new"}, "consent": True,
    })
    service.create("creatives", "creative_real", {
        "creative_id": "creative_real", "channel": "email",
        "title": "Welcome", "body": "Your welcome message",
    })
    service.create_journey({
        "journey_id": "journey_real", "name": "Real welcome",
        "trigger_event": "signup", "segment_id": None,
        "steps": [{"channel": "email", "creative_id": "creative_real",
                   "offer_id": None, "delay_seconds": 0}],
    })
    service.activate_journey("journey_real")
    service.ingest_event(_event("event_real", "customer_real", "signup"))
    delivery_id = service.process_due()["processed"][0]["delivery_id"]
    receipt = {"provider_event_id": "receipt_real", "status": "delivered",
               "occurred_at": datetime.now(timezone.utc).isoformat()}
    with pytest.raises(GrowthConflict, match="must be submitted"):
        service.record_receipt(delivery_id, receipt, permit_simulation=False)
    command = service.reserve_external_submission(delivery_id)
    assert command["idempotency_key"] == delivery_id
    with pytest.raises(GrowthConflict, match="already reserved"):
        service.reserve_external_submission(delivery_id)
    service.finish_external_submission(delivery_id, accepted=True, reason="gateway accepted")
    assert service.record_receipt(delivery_id, receipt, permit_simulation=False)["delivery"]["status"] == "delivered"
    assert service.update_customer("customer_real", {"consent": False})["consent"] is False
    assert service.ingest_event(_event("event_real_second", "customer_real", "signup"))["new_enrollments"] == 0



def test_stopped_journey_suppresses_pending_dispatch_and_stale_submit():
    fake = _FakeStore()
    service = GrowthOperations(fake, "test")
    service.create("customers", "stop_customer", {
        "customer_id": "stop_customer", "attributes": {}, "consent": True,
    })
    service.create("creatives", "stop_creative", {
        "creative_id": "stop_creative", "channel": "email",
        "title": "Example", "body": "Only an example",
    })
    service.create_journey({
        "journey_id": "stop_flow", "name": "Stopping test",
        "trigger_event": "signup", "segment_id": None,
        "steps": [{"channel": "email", "creative_id": "stop_creative",
                   "offer_id": None, "delay_seconds": 0}],
    })
    service.activate_journey("stop_flow")
    service.ingest_event(_event("stop_event", "stop_customer", "signup"))
    delivery_id = service.process_due()["processed"][0]["delivery_id"]
    assert service.list("deliveries")[0]["status"] == "queued"
    service.stop_journey("stop_flow")
    assert service.list("deliveries")[0]["status"] == "suppressed"
    with pytest.raises(GrowthConflict, match="only real queued"):
        service.reserve_external_submission(delivery_id)

    # Second gate blocks an accidentally stale queued record as well.
    fake.records[("deliveries", delivery_id)]["status"] = "queued"
    with pytest.raises(GrowthConflict, match="journey is stopped"):
        service.reserve_external_submission(delivery_id)


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


def test_contextual_personalization_uses_stable_logged_propensities():
    from growthevo.web.growth_personalization import ContextualPersonalizer, CONTROL_FLOOR

    fake = _FakeStore()
    fake.seed()
    personalizer = ContextualPersonalizer(fake, "test")
    payload = {
        "customer_id": "demo_customer_01", "request_id": "request_personalized_01",
        "placement": "checkout", "candidate_action_ids": [
            "NO_TREATMENT", "free_shipping", "coupon_10",
        ],
        "consent_state": True, "frequency_remaining": 3,
        "budget_remaining": 100.0,
    }
    decision = personalizer.decide(payload)
    assert decision["causal_claim"] is False
    assert decision["exposure_confirmed"] is False
    assert decision["action_distribution"]["NO_TREATMENT"] == CONTROL_FLOOR
    assert abs(sum(decision["action_distribution"].values()) - 1) < 1e-12
    assert decision["propensity"] == decision["action_distribution"][decision["action_id"]]
    assert personalizer.decide(payload) == decision
    with pytest.raises(GrowthConflict, match="idempotency"):
        personalizer.decide(payload | {"budget_remaining": 0})
    exposure = personalizer.confirm_exposure(payload["request_id"], "checkout")
    assert exposure["decision_id"] == decision["decision_id"]
    assert personalizer.confirm_exposure(payload["request_id"], "checkout") == exposure
    assert personalizer.metrics()["confirmed_exposures"] == 1
    with pytest.raises(GrowthConflict, match="surface"):
        personalizer.confirm_exposure(payload["request_id"], "wrong_surface")
    GrowthOperations(fake, "test").update_customer("demo_customer_01", {"consent": False})
    with pytest.raises(GrowthConflict, match="consent withdrawn"):
        personalizer.decide(payload)



def test_contextual_personalization_cold_start_holdout_and_matured_feedback():
    from datetime import timedelta
    from growthevo.web.growth_personalization import ContextualPersonalizer

    fake = _FakeStore()
    fake.seed()
    service = ContextualPersonalizer(fake, "test")
    payload = {
        "customer_id": "demo_customer_01", "request_id": "request_feedback_01",
        "placement": "checkout", "candidate_action_ids": [
            "NO_TREATMENT", "free_shipping", "coupon_10",
        ],
        "consent_state": True, "frequency_remaining": 3,
        "budget_remaining": 100.0,
    }
    started = datetime.now(timezone.utc) - timedelta(days=10)
    actions = ["NO_TREATMENT", "free_shipping", "coupon_10"]
    for action in actions:
        for index in range(20):
            customer_id = f"feedback_{action}_{index}"
            key = f"observed_{action}_{index}"
            fake.records[("personalization_exposures", key)] = {
                "request_id": key, "customer_id": customer_id, "cohort": "new",
                "action_id": action, "occurred_at": started.isoformat(), "synthetic": True,
            }
            converted = (
                (action == "NO_TREATMENT" and index < 4)
                or (action == "free_shipping" and index < 16)
                or (action == "coupon_10" and index < 2)
            )
            if converted:
                fake.records[("events", "purchase_" + key)] = {
                    "event_id": "purchase_" + key, "customer_id": customer_id,
                    "name": "purchase", "occurred_at": (
                        started + timedelta(days=1)
                    ).isoformat(), "synthetic": True,
                }
    fake.records[("personalization_exposures", "duplicate_old_exposure")] = {
        "request_id": "duplicate_old_exposure",
        "customer_id": "feedback_free_shipping_0",
        "cohort": "new", "action_id": "coupon_10",
        "occurred_at": (started + timedelta(seconds=1)).isoformat(), "synthetic": True,
    }
    decision = service.decide(payload)
    assert decision["learning_status"] == "matured"
    assert decision["matured_sample_counts"] == {action: 20 for action in actions}
    assert decision["action_distribution"]["free_shipping"] > (
        decision["action_distribution"]["coupon_10"]
    )
    assert decision["action_distribution"]["NO_TREATMENT"] >= .35
    denied = service.decide(payload | {
        "request_id": "request_feedback_denied", "frequency_remaining": 0,
    })
    assert denied["action_id"] == "NO_TREATMENT"
    assert denied["propensity"] == 1.0


def test_experiment_report_respects_followup_window_and_srm():
    from datetime import timedelta

    fake = _FakeStore()
    fake.seed()
    service = GrowthOperations(fake, "test")
    report = service.report("demo_first_purchase")
    assert report["srm"]["status"] == "insufficient_exposures"
    assert all(row["matured_customers"] == 0 for row in report["results"])
    assert all(row["matured_conversion_rate"] is None for row in report["results"])
    assert all(row["observed_difference_pp"] is None for row in report["results"])
    assert sum(row["converted_customers"] for row in report["results"]) == 6

    older = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    for (kind, key), row in fake.records.items():
        if kind == "exposures" and row["experiment_id"] == "demo_first_purchase":
            row["occurred_at"] = older
        if kind == "events" and row["name"] == "purchase":
            row["occurred_at"] = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    matured = service.report("demo_first_purchase")
    assert all(row["matured_customers"] == 6 for row in matured["results"])
    assert all(row["pending_customers"] == 0 for row in matured["results"])
    assert all(row["matured_wilson_95"] is not None for row in matured["results"])
    assert matured["results"][1]["observed_difference_pp"] == pytest.approx(33.3333, abs=0.0001)


def test_srm_monitor_and_wilson_bounds():
    from growthevo.web.growth_statistics import sample_ratio_diagnostics, wilson_95

    assert sample_ratio_diagnostics({"A": 50, "B": 50}, {"A": 50, "B": 50})["status"] == "pass"
    mismatch = sample_ratio_diagnostics({"A": 95, "B": 5}, {"A": 50, "B": 50})
    assert mismatch["status"] == "warning"
    assert mismatch["p_value"] < 0.01
    assert sample_ratio_diagnostics({"A": 20, "B": 20, "C": 20},
                                    {"A": 33, "B": 33, "C": 34})["status"] == "pass"
    assert wilson_95(0, 0) is None
    assert 0 <= wilson_95(3, 10)[0] <= .3 <= wilson_95(3, 10)[1] <= 1
