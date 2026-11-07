"""Pressure and integrity check for the PostgreSQL-backed growth workbench.

Unlike the general product stress runner, this suite exercises growth writes,
their browser-facing reads and concurrent journey processing across replicas.
It does not submit anything to real marketing providers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import statistics
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

LATENCIES: list[tuple[str, float]] = []
LOCK = threading.Lock()


def call(base: str, method: str, path: str, payload: dict[str, Any] | None = None,
         expected: tuple[int, ...] = (200,)) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(base.rstrip("/") + path, data=data, method=method,
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    start = time.perf_counter()
    try:
        with urlopen(request, timeout=25) as response:
            status = response.status
            value = json.load(response)
    except HTTPError as exc:
        raise AssertionError(
            f"{method} {path}: HTTP {exc.code}: {exc.read()[:300]!r}"
        ) from exc
    except URLError as exc:
        raise AssertionError(f"{method} {path}: {exc}") from exc
    finally:
        latency = 1000 * (time.perf_counter() - start)
        with LOCK:
            LATENCIES.append((path.split("?")[0], latency))
    if status not in expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status}")
    return value


def percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered)*percent/100)-1))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--peer-url")
    parser.add_argument("--customers", type=int, default=32)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    if args.customers < 10 or not 1 <= args.concurrency <= 64:
        parser.error("customers must be >=10 and concurrency within 1..64")
    bases = [args.base_url.rstrip("/")]
    if args.peer_url:
        bases.append(args.peer_url.rstrip("/"))
    prefix = "stress_g_" + uuid4().hex[:12]
    experiment = prefix + "_exp"
    journey = prefix + "_journey"
    creative = prefix + "_creative"
    segment = prefix + "_segment"
    user_ids = [f"{prefix}_customer_{index:03d}" for index in range(args.customers)]
    started = time.perf_counter()

    call(bases[0], "POST", "/api/growth/segments", {
        "segment_id": segment, "name": "Growth stress cohort",
        "equals": {"lifecycle": "stress"}
    }, (201,))
    call(bases[0], "POST", "/api/growth/creatives", {
        "creative_id": creative, "channel": "email",
        "title": "Growth stress content", "body": "No external sends."
    }, (201,))
    call(bases[0], "POST", "/api/growth/journeys", {
        "journey_id": journey, "name": "Growth stress journey",
        "trigger_event": "signup", "segment_id": segment,
        "steps": [{"channel": "email", "creative_id": creative,
                   "offer_id": None, "delay_seconds": 0}]
    }, (201,))
    call(bases[0], "POST", f"/api/growth/journeys/{journey}/activate", {})
    call(bases[0], "POST", "/api/growth/experiments", {
        "experiment_id": experiment, "name": "Growth stress randomization",
        "metric_event": "purchase", "control": "holdout",
        "variants": [{"key": "holdout", "weight": 50}, {"key": "offer", "weight": 50}],
        "window_days": 7
    }, (201,))

    def create_customer(index: int) -> None:
        call(bases[index % len(bases)], "POST", "/api/growth/customers", {
            "customer_id": user_ids[index], "attributes": {"lifecycle": "stress"},
            "consent": True
        }, (201,))

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(create_customer, range(args.customers)))

    decision_actions: list[str] = []
    def exercise_customer(index: int) -> None:
        base = bases[index % len(bases)]
        customer = user_ids[index]
        event = {"event_id": f"{prefix}_signup_{index:03d}",
                 "customer_id": customer, "name": "signup"}
        ingestion = call(base, "POST", "/api/growth/events", event, (201,))
        if ingestion["new_enrollments"] != 1:
            raise AssertionError("event did not create one journey job")
        same = call(base, "POST", "/api/growth/events", event, (201,))
        if not same["deduplicated"] or same["new_enrollments"] != 0:
            raise AssertionError("event replay generated another job")
        impression = {
            "customer_id": customer,
            "request_id": f"{prefix}_exposure_{index:03d}",
            "surface": "growth_workspace"
        }
        exposed = call(base, "POST",
                       f"/api/growth/experiments/{experiment}/exposures", impression, (201,))
        replay = call(bases[(index+1) % len(bases)], "POST",
                      f"/api/growth/experiments/{experiment}/exposures", impression, (201,))
        if replay != exposed:
            raise AssertionError("experiment exposure is not replica-idempotent")
        decision = call(base, "POST", "/api/growth/personalization/decide", {
            "customer_id": customer,
            "request_id": f"{prefix}_policy_{index:03d}",
            "placement": "growth_workspace",
            "candidate_action_ids": ["NO_TREATMENT", "free_shipping"],
            "consent_state": True, "frequency_remaining": 1, "budget_remaining": 100
        }, (201,))
        distribution = decision["action_distribution"]
        if not 0.35 <= distribution["NO_TREATMENT"] <= 1:
            raise AssertionError("decision lost no-treatment floor")
        if decision["propensity"] != distribution[decision["action_id"]]:
            raise AssertionError("decision propensity mismatch")
        confirmation = call(bases[(index+1) % len(bases)], "POST",
            f"/api/growth/personalization/{decision['request_id']}/exposure",
            {"surface": "growth_workspace"}, (201,))
        replay_confirmation = call(base, "POST",
            f"/api/growth/personalization/{decision['request_id']}/exposure",
            {"surface": "growth_workspace"}, (201,))
        if replay_confirmation != confirmation:
            raise AssertionError("exposure confirmation is not replica-idempotent")
        with LOCK:
            decision_actions.append(decision["action_id"])

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(exercise_customer, range(args.customers)))

    def process(index: int) -> dict[str, Any]:
        return call(bases[index % len(bases)], "POST",
                    "/api/growth/journeys/process", {"limit": 200})
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        processing=list(pool.map(process, range(args.concurrency)))

    def read(index: int) -> None:
        paths=[
            "/api/growth/overview", "/api/growth/customers",
            "/api/growth/segments", "/api/growth/events",
            "/api/growth/experiments", f"/api/growth/experiments/{experiment}/report",
            "/api/growth/journeys", "/api/growth/journeys/jobs",
            "/api/growth/deliveries", "/api/growth/creatives",
            "/api/growth/personalization/metrics",
            "/api/growth/personalization/offline-evidence?target_action_id=NO_TREATMENT",
        ]
        result=call(bases[index % len(bases)], "GET", paths[index % len(paths)])
        if not isinstance(result, (dict, list)):
            raise AssertionError("invalid growth API payload")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(read, range(args.customers * 4)))

    deliveries=call(bases[-1], "GET", "/api/growth/deliveries")
    selected=[row for row in deliveries if row["journey_id"]==journey]
    if len(selected)!=args.customers or len({r["delivery_id"] for r in selected})!=args.customers:
        raise AssertionError(f"journey delivery integrity lost: {len(selected)}")
    if any(row["status"]!="queued" for row in selected):
        raise AssertionError("queued growth delivery was submitted externally")
    report=call(bases[0], "GET", f"/api/growth/experiments/{experiment}/report")
    if sum(row["exposed_customers"] for row in report["results"])!=args.customers:
        raise AssertionError("experiment exposure uniqueness lost")
    if report["causal_claim"] or any(row["matured_customers"] for row in report["results"]):
        raise AssertionError("immature experiment result claimed causality")
    metrics=call(bases[0], "GET", "/api/growth/personalization/metrics")
    if metrics["confirmed_exposures"]<args.customers:
        raise AssertionError("confirmed personalization exposures missing")
    offline=call(bases[-1], "GET",
        "/api/growth/personalization/offline-evidence?target_action_id=NO_TREATMENT")
    if offline["promotion_allowed"] or offline["causal_claim"]:
        raise AssertionError("unsafe policy promotion evidence")
    if sum(value["count"] for value in processing)!=args.customers:
        # The fresh run may coexist with unrelated pending demo tasks. Verify
        # the actual delivery set above rather than treating those as ours.
        if sum(value["count"] for value in processing)<args.customers:
            raise AssertionError("concurrent worker did not process all new jobs")
    duration=time.perf_counter()-started
    latency=[ms for _,ms in LATENCIES]
    report_data={
        "scenario":"postgresql-growth-workbench",
        "replicas":len(bases),
        "customers":args.customers,
        "concurrency":args.concurrency,
        "requests":len(LATENCIES),
        "duration_seconds":round(duration,2),
        "throughput_rps":round(len(latency)/duration,2),
        "latency_ms":{
            "p50":round(percentile(latency,50),2),
            "p95":round(percentile(latency,95),2),
            "p99":round(percentile(latency,99),2)
        },
        "unique_deliveries":len(selected),
        "unique_exposures":args.customers,
        "confirmed_decisions":len(decision_actions),
        "external_sends":0,
        "offline_status":offline["status"],
    }
    passed=(report_data["latency_ms"]["p95"]<=12000
            and report_data["latency_ms"]["p99"]<=25000
            and report_data["throughput_rps"]>=3)
    report_data["passed"]=passed
    args.json_out.parent.mkdir(parents=True,exist_ok=True)
    args.json_out.write_text(json.dumps(report_data,ensure_ascii=False,indent=2))
    print(json.dumps(report_data,ensure_ascii=False,indent=2))
    return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(main())
