from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Profile:
    requests: int
    concurrency: int


PROFILES: dict[str, Profile] = {
    "quick": Profile(64, 16),
    "ci": Profile(256, 48),
    "standard": Profile(1024, 96),
    "soak": Profile(4096, 128),
}


def payload(index: int) -> dict[str, Any]:
    return {
        "entity_id": f"propensity-stress-{index}",
        "placement": "checkout_banner",
        "context": {
            "cart_value": 120 + (index % 400),
            "session_intent": "high" if index % 3 else "medium",
            "new_user": index % 2 == 0,
            "abandoned_cart": index % 5 == 0,
            "churn_risk": (index % 20) / 100,
        },
        "candidate_action_ids": [
            "NO_TREATMENT",
            "free_shipping",
            "coupon_10",
            "push_reminder",
        ],
        "consent_state": True,
        "frequency_remaining": 2,
        "budget_remaining": 50,
        "context_freshness_seconds": index % 60,
    }


def request_decision(base_url: str, index: int, timeout: float) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload(index), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/decide",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": f"propensity-stress-{index}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def validate_response(value: dict[str, Any]) -> str | None:
    distribution = value.get("action_distribution")
    if not isinstance(distribution, dict) or not distribution:
        return "missing action_distribution"
    if "NO_TREATMENT" not in distribution:
        return "NO_TREATMENT missing from action_distribution"
    probabilities: dict[str, float] = {}
    for action_id, probability in distribution.items():
        if not isinstance(action_id, str) or not action_id:
            return "distribution contains invalid action id"
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            return f"distribution probability for {action_id!r} is not numeric"
        numeric = float(probability)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            return f"distribution probability for {action_id!r} is invalid: {probability!r}"
        probabilities[action_id] = numeric
    total = math.fsum(probabilities.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        return f"action_distribution does not sum to 1: {total:.12f}"
    action_id = value.get("action_id")
    if not isinstance(action_id, str) or action_id not in probabilities:
        return "selected action missing from action_distribution"
    propensity = value.get("propensity")
    if not isinstance(propensity, (int, float)) or isinstance(propensity, bool):
        return "propensity is not numeric"
    propensity_float = float(propensity)
    if not math.isfinite(propensity_float) or not 0.0 < propensity_float <= 1.0:
        return f"invalid propensity: {propensity!r}"
    if not math.isclose(propensity_float, probabilities[action_id], rel_tol=0.0, abs_tol=1e-12):
        return "behavior propensity does not match selected action probability"
    if value.get("engine_mode") != "reference-contract":
        return "unexpected engine_mode"
    if value.get("policy_id") != "policy_growth_safe":
        return "unexpected stable policy identity"
    return None


def validate_assignment_calibration(responses: list[dict[str, Any]]) -> list[str]:
    observed: Counter[str] = Counter()
    expected: defaultdict[str, float] = defaultdict(float)
    variance: defaultdict[str, float] = defaultdict(float)
    for value in responses:
        observed[str(value["action_id"])] += 1
        for candidate, probability_raw in value["action_distribution"].items():
            probability = float(probability_raw)
            expected[candidate] += probability
            variance[candidate] += probability * (1.0 - probability)
    failures: list[str] = []
    for action_id in sorted(expected):
        expected_count = expected[action_id]
        observed_count = observed[action_id]
        standard_deviation = math.sqrt(max(variance[action_id], 1e-12))
        z_score = abs(observed_count - expected_count) / standard_deviation
        if expected_count >= 2.0 and z_score > 7.0:
            failures.append(
                "assignment frequency is inconsistent with logged probabilities: "
                f"action={action_id!r} observed={observed_count} expected={expected_count:.2f} z={z_score:.2f}"
            )
    expected_material_actions = sum(count >= 2.0 for count in expected.values())
    if expected_material_actions >= 2 and len(observed) < 2:
        failures.append("assignment collapsed to one action despite material logged mass on multiple actions")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-check GrowthEvo behavior-propensity and assignment semantics.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    base_url = args.base_url.rstrip("/")
    responses: list[dict[str, Any]] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=profile.concurrency) as pool:
        futures = {pool.submit(request_decision, base_url, index, args.timeout): index for index in range(profile.requests)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                status, value = future.result()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:300]
                failures.append(f"request {index}: HTTP {exc.code}: {body}")
                continue
            except Exception as exc:  # noqa: BLE001
                failures.append(f"request {index}: {type(exc).__name__}: {exc}")
                continue
            if status != 200:
                failures.append(f"request {index}: unexpected HTTP {status}")
                continue
            error = validate_response(value)
            if error is not None:
                failures.append(f"request {index}: {error}")
                continue
            responses.append(value)
    if len(responses) == profile.requests:
        failures.extend(validate_assignment_calibration(responses))
    observed = Counter(str(value["action_id"]) for value in responses)
    passed = not failures and len(responses) == profile.requests
    print(json.dumps({"profile": args.profile, "requests": profile.requests, "validated": len(responses), "observed_actions": dict(sorted(observed.items())), "failures": failures[:20], "passed": passed}, ensure_ascii=False, indent=2))
    if not passed:
        print("Decision propensity semantics stress check failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
