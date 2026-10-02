from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

JsonValue = dict[str, Any] | list[Any]
Validator = Callable[[JsonValue | str], str | None]
PayloadFactory = Callable[[int], tuple[dict[str, Any] | None, dict[str, str]]]


@dataclass(frozen=True)
class Profile:
    concurrency: int
    read_repeats: int
    decisions: int
    fallbacks: int
    agent_plans: int
    campaign_drafts: int
    approval_retries: int
    idempotency_burst: int
    max_p95_ms: float
    max_p99_ms: float
    min_rps: float


PROFILES: dict[str, Profile] = {
    "quick": Profile(16, 10, 100, 40, 25, 10, 10, 32, 1500, 2500, 10),
    "ci": Profile(48, 80, 1000, 300, 200, 100, 100, 128, 1000, 2000, 25),
    "standard": Profile(96, 300, 3000, 1000, 800, 400, 400, 256, 1500, 3000, 25),
    "soak": Profile(128, 1500, 15000, 5000, 3000, 1500, 1500, 512, 2000, 4000, 20),
}


@dataclass(frozen=True)
class RequestCase:
    name: str
    method: str
    path: str
    validator: Validator
    payload_factory: PayloadFactory
    expected_status: tuple[int, ...] = (200,)
    response_kind: str = "json"


@dataclass
class Result:
    scenario: str
    latency_ms: float
    status: int | None
    http_error: str | None = None
    semantic_error: str | None = None
    decision_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.http_error is None and self.semantic_error is None


def empty_payload(_: int) -> tuple[None, dict[str, str]]:
    return None, {}


def validate_dict_status(expected: str) -> Validator:
    def validator(value: JsonValue | str) -> str | None:
        if not isinstance(value, dict):
            return "expected JSON object"
        return None if value.get("status") == expected else f"expected status={expected!r}"
    return validator


def validate_dashboard(value: JsonValue | str) -> str | None:
    return None if isinstance(value, dict) and isinstance(value.get("kpis"), list) and len(value["kpis"]) >= 4 else "dashboard KPI contract changed"


def validate_list(value: JsonValue | str) -> str | None:
    return None if isinstance(value, list) and value else "expected non-empty JSON list"


def validate_actions(value: JsonValue | str) -> str | None:
    if not isinstance(value, list):
        return "actions is not a list"
    ids = {item.get("action_id") for item in value if isinstance(item, dict)}
    required = {"NO_TREATMENT", "free_shipping", "coupon_10", "push_reminder", "email_guide"}
    return None if required <= ids else f"stable Action Registry incomplete: {sorted(required - ids)}"


def validate_recent(value: JsonValue | str) -> str | None:
    return None if isinstance(value, list) else "recent decisions is not a list"


def validate_html(value: JsonValue | str) -> str | None:
    return None if isinstance(value, str) and "GrowthEvo" in value and 'id="app"' in value else "GrowthEvo app shell marker missing"


def validate_service_worker(value: JsonValue | str) -> str | None:
    return None if isinstance(value, str) and "CACHE" in value and "fetch" in value else "service worker markers missing"


def decision_payload(index: int) -> tuple[dict[str, Any], dict[str, str]]:
    return ({
        "entity_id": f"stress-user-{index}",
        "placement": "checkout_banner",
        "context": {"cart_value": 120 + (index % 400), "session_intent": "high" if index % 3 else "medium", "new_user": index % 2 == 0, "abandoned_cart": index % 5 == 0, "churn_risk": (index % 20) / 100},
        "candidate_action_ids": ["NO_TREATMENT", "free_shipping", "coupon_10", "push_reminder"],
        "consent_state": True,
        "frequency_remaining": 2,
        "budget_remaining": 50,
        "context_freshness_seconds": index % 60,
    }, {"Idempotency-Key": f"stress-decision-{index}"})


def fallback_payload(index: int) -> tuple[dict[str, Any], dict[str, str]]:
    payload, _ = decision_payload(index)
    payload["entity_id"] = f"stress-no-consent-{index}"
    payload["consent_state"] = False
    return payload, {"Idempotency-Key": f"stress-fallback-{index}"}


def agent_payload(index: int) -> tuple[dict[str, Any], dict[str, str]]:
    return ({"goal": f"压力测试目标 {index}: 提升新用户首购真实增量", "budget_limit": 500000, "primary_metric": "incremental_first_purchase", "guardrails": ["unsubscribe_rate", "complaint_rate"]}, {})


def campaign_payload(index: int) -> tuple[dict[str, Any], dict[str, str]]:
    return ({"name": f"Stress Campaign {index}", "goal": "验证并发 Campaign Draft 创建路径", "audience": f"synthetic-stress-audience-{index}", "budget": 1000 + index, "candidate_action_ids": ["NO_TREATMENT", "free_shipping"]}, {})


def approval_payload(index: int) -> tuple[dict[str, Any], dict[str, str]]:
    return {"decision": "approve_5", "note": f"stress retry {index}"}, {}


def validate_decision(value: JsonValue | str) -> str | None:
    if not isinstance(value, dict):
        return "decision is not an object"
    distribution = value.get("action_distribution")
    if not isinstance(distribution, dict) or "NO_TREATMENT" not in distribution:
        return "decision distribution does not contain NO_TREATMENT"
    action_id = value.get("action_id")
    if action_id not in distribution:
        return "selected action is not in decision distribution"
    propensity = value.get("propensity")
    if not isinstance(propensity, (int, float)) or isinstance(propensity, bool) or not 0 < float(propensity) <= 1:
        return "invalid behavior propensity"
    if value.get("engine_mode") != "reference-contract" or value.get("policy_id") != "policy_growth_safe":
        return "stable decision identity changed"
    return None


def validate_fallback(value: JsonValue | str) -> str | None:
    return None if isinstance(value, dict) and value.get("action_id") == "NO_TREATMENT" and value.get("propensity") == 1.0 else "guardrail fallback contract changed"


def validate_agent(value: JsonValue | str) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        return "agent plan contract changed"
    claim_types = {item.get("type") for item in value["claims"] if isinstance(item, dict)}
    if not {"FACT", "ESTIMATE", "HYPOTHESIS", "IDEA"} <= claim_types:
        return "agent claim hierarchy incomplete"
    return None if value.get("next_gate") == "Shadow preflight" else "agent control boundary changed"


def validate_campaign(value: JsonValue | str) -> str | None:
    return None if isinstance(value, dict) and value.get("status") == "Draft" and str(value.get("id", "")).startswith("cmp_") else "campaign draft contract changed"


def validate_approval(value: JsonValue | str) -> str | None:
    return None if isinstance(value, dict) and value.get("status") == "approve_5" and value.get("id") == "apr_281" else "approval retry contract changed"


READ_CASES = [
    RequestCase("health", "GET", "/api/health", validate_dict_status("ok"), empty_payload),
    RequestCase("ready", "GET", "/api/ready", validate_dict_status("ready"), empty_payload),
    RequestCase("dashboard", "GET", "/api/dashboard", validate_dashboard, empty_payload),
    RequestCase("opportunities", "GET", "/api/opportunities", validate_list, empty_payload),
    RequestCase("campaigns", "GET", "/api/campaigns", validate_list, empty_payload),
    RequestCase("experiments", "GET", "/api/experiments", validate_list, empty_payload),
    RequestCase("approvals", "GET", "/api/approvals", validate_list, empty_payload),
    RequestCase("harness", "GET", "/api/harness/runs", validate_list, empty_payload),
    RequestCase("evolution", "GET", "/api/evolution/candidates", validate_list, empty_payload),
    RequestCase("actions", "GET", "/api/actions", validate_actions, empty_payload),
    RequestCase("decision-log", "GET", "/api/decisions/recent?limit=20", validate_recent, empty_payload),
    RequestCase("web-shell", "GET", "/", validate_html, empty_payload, response_kind="text"),
    RequestCase("service-worker", "GET", "/service-worker.js", validate_service_worker, empty_payload, response_kind="text"),
]
DECISION_CASE = RequestCase("decision", "POST", "/api/decide", validate_decision, decision_payload)
FALLBACK_CASE = RequestCase("guardrail-fallback", "POST", "/api/decide", validate_fallback, fallback_payload)
AGENT_CASE = RequestCase("agent-plan", "POST", "/api/agent/plan", validate_agent, agent_payload)
CAMPAIGN_CASE = RequestCase("campaign-draft", "POST", "/api/campaigns/draft", validate_campaign, campaign_payload, (201,))
APPROVAL_CASE = RequestCase("approval-retry", "POST", "/api/approvals/apr_281/decision", validate_approval, approval_payload)


def request_once(base_url: str, case: RequestCase, index: int, timeout: float) -> Result:
    payload, extra_headers = case.payload_factory(index)
    headers = {"Accept": "application/json", **extra_headers}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base_url}{case.path}", data=data, headers=headers, method=case.method)
    started = time.perf_counter()
    status: int | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read().decode("utf-8")
        latency_ms = (time.perf_counter() - started) * 1000
        if status not in case.expected_status:
            return Result(case.name, latency_ms, status, http_error=f"unexpected HTTP {status}")
        try:
            value: JsonValue | str = json.loads(raw) if case.response_kind == "json" else raw
        except json.JSONDecodeError as exc:
            return Result(case.name, latency_ms, status, semantic_error=f"invalid JSON: {exc}")
        semantic_error = case.validator(value)
        decision_id = value.get("decision_id") if isinstance(value, dict) else None
        return Result(case.name, latency_ms, status, semantic_error=semantic_error, decision_id=decision_id)
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return Result(case.name, latency_ms, exc.code, http_error=f"HTTP {exc.code}: {body}")
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000
        return Result(case.name, latency_ms, status, http_error=f"{type(exc).__name__}: {exc}")


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil((p / 100.0) * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def summarize(results: list[Result]) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    http_errors = sum(result.http_error is not None for result in results)
    semantic_errors = sum(result.semantic_error is not None for result in results)
    return {"requests": len(results), "ok": sum(result.ok for result in results), "http_errors": http_errors, "semantic_errors": semantic_errors, "error_rate": round((http_errors + semantic_errors) / len(results), 6) if results else 0, "latency_ms": {"mean": round(statistics.fmean(latencies), 2) if latencies else 0, "p50": round(percentile(latencies, 50), 2), "p95": round(percentile(latencies, 95), 2), "p99": round(percentile(latencies, 99), 2), "max": round(max(latencies), 2) if latencies else 0}}


def run_tasks(base_url: str, tasks: list[tuple[RequestCase, int]], concurrency: int, timeout: float) -> tuple[list[Result], float]:
    results: list[Result] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(request_once, base_url, case, index, timeout) for case, index in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results, time.perf_counter() - started


def run_idempotency_burst(base_url: str, size: int, concurrency: int, timeout: float) -> dict[str, Any]:
    key = f"burst-{time.time_ns()}"
    def payload(_: int) -> tuple[dict[str, Any], dict[str, str]]:
        body, _ = decision_payload(999_999)
        body["entity_id"] = "burst-shared-entity"
        return body, {"Idempotency-Key": key}
    case = RequestCase("idempotency-burst", "POST", "/api/decide", validate_decision, payload)
    results, duration = run_tasks(base_url, [(case, index) for index in range(size)], min(concurrency, size), timeout)
    decision_ids = {result.decision_id for result in results if result.decision_id}
    summary = summarize(results)
    summary.update({"duration_seconds": round(duration, 3), "unique_decision_ids": len(decision_ids), "atomic": len(decision_ids) == 1 and summary["http_errors"] == 0 and summary["semantic_errors"] == 0})
    return summary


def build_tasks(profile: Profile) -> list[tuple[RequestCase, int]]:
    tasks: list[tuple[RequestCase, int]] = []
    for case in READ_CASES:
        tasks.extend((case, index) for index in range(profile.read_repeats))
    tasks.extend((DECISION_CASE, index) for index in range(profile.decisions))
    tasks.extend((FALLBACK_CASE, index) for index in range(profile.fallbacks))
    tasks.extend((AGENT_CASE, index) for index in range(profile.agent_plans))
    tasks.extend((CAMPAIGN_CASE, index) for index in range(profile.campaign_drafts))
    tasks.extend((APPROVAL_CASE, index) for index in range(profile.approval_retries))
    random.Random(42).shuffle(tasks)
    return tasks


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    lines = ["# GrowthEvo Product Stress Report", "", f"- Profile: `{report['profile']}`", f"- Base URL: `{report['base_url']}`", f"- Concurrency: **{report['concurrency']}**", f"- Requests: **{overall['requests']}** (+ {report['idempotency_burst']['requests']} idempotency burst)", f"- Duration: **{report['duration_seconds']} s**", f"- Throughput: **{report['throughput_rps']} req/s**", f"- HTTP errors: **{overall['http_errors']}**", f"- Semantic errors: **{overall['semantic_errors']}**", f"- Global p95 / p99: **{overall['latency_ms']['p95']} / {overall['latency_ms']['p99']} ms**", f"- Idempotency burst unique decision IDs: **{report['idempotency_burst']['unique_decision_ids']}**", f"- Result: **{'PASS' if report['passed'] else 'FAIL'}**", "", "## Scenario latency", "", "| Scenario | Requests | Errors | p50 ms | p95 ms | p99 ms | Max ms |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, summary in sorted(report["scenarios"].items()):
        latency = summary["latency_ms"]
        lines.append(f"| {name} | {summary['requests']} | {summary['http_errors'] + summary['semantic_errors']} | {latency['p50']} | {latency['p95']} | {latency['p99']} | {latency['max']} |")
    lines.extend(["", "## Thresholds", "", f"- zero HTTP errors: {'PASS' if overall['http_errors'] == 0 else 'FAIL'}", f"- zero semantic errors: {'PASS' if overall['semantic_errors'] == 0 else 'FAIL'}", f"- global p95 <= {report['thresholds']['max_p95_ms']} ms: {'PASS' if overall['latency_ms']['p95'] <= report['thresholds']['max_p95_ms'] else 'FAIL'}", f"- global p99 <= {report['thresholds']['max_p99_ms']} ms: {'PASS' if overall['latency_ms']['p99'] <= report['thresholds']['max_p99_ms'] else 'FAIL'}", f"- throughput >= {report['thresholds']['min_rps']} req/s: {'PASS' if report['throughput_rps'] >= report['thresholds']['min_rps'] else 'FAIL'}", f"- concurrent idempotency is atomic: {'PASS' if report['idempotency_burst']['atomic'] else 'FAIL'}", "", "> Results characterize the current single-container reference surface; they are not a capacity promise for future external infrastructure.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pressure-test the GrowthEvo Web/API product surface.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--no-fail", action="store_true", help="Always exit 0 after writing the report.")
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    concurrency = args.concurrency or profile.concurrency
    base_url = args.base_url.rstrip("/")
    results, duration = run_tasks(base_url, build_tasks(profile), concurrency, args.timeout)
    grouped: defaultdict[str, list[Result]] = defaultdict(list)
    for result in results:
        grouped[result.scenario].append(result)
    overall = summarize(results)
    throughput = round(len(results) / duration, 2) if duration else 0.0
    idempotency_burst = run_idempotency_burst(base_url, profile.idempotency_burst, concurrency, args.timeout)
    thresholds = {"max_p95_ms": profile.max_p95_ms, "max_p99_ms": profile.max_p99_ms, "min_rps": profile.min_rps}
    passed = overall["http_errors"] == 0 and overall["semantic_errors"] == 0 and overall["latency_ms"]["p95"] <= profile.max_p95_ms and overall["latency_ms"]["p99"] <= profile.max_p99_ms and throughput >= profile.min_rps and bool(idempotency_burst["atomic"])
    report = {"profile": args.profile, "base_url": base_url, "concurrency": concurrency, "duration_seconds": round(duration, 3), "throughput_rps": throughput, "thresholds": thresholds, "overall": overall, "idempotency_burst": idempotency_burst, "scenarios": {name: summarize(items) for name, items in grouped.items()}, "passed": passed, "sample_errors": [asdict(result) for result in results if not result.ok][:20]}
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2)
    rendered_markdown = render_markdown(report)
    print(rendered_markdown)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered_json + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered_markdown, encoding="utf-8")
    if not passed and not args.no_fail:
        print("Stress thresholds failed. See report above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
