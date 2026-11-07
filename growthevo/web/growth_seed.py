"""Deterministic, clearly labelled synthetic records stored in PostgreSQL.

Only API/reference mode may load this fixture. Production never imports it.
Seed IDs are stable, so app restarts never duplicate the example workspace.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, Any


def seed_records() -> Iterator[tuple[str, str, dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    stamp = lambda hours: (now + timedelta(hours=hours)).isoformat()
    synthetic = {"synthetic": True}

    yield "segments", "demo_new_customers", {
        "segment_id": "demo_new_customers", "name": "演示 · 新用户",
        "equals": {"lifecycle": "new"}, **synthetic,
    }
    yield "creatives", "demo_welcome_email", {
        "creative_id": "demo_welcome_email", "channel": "email",
        "title": "欢迎加入", "body": "这是演示内容，不会实际发送。", **synthetic,
    }
    yield "creatives", "demo_welcome_push", {
        "creative_id": "demo_welcome_push", "channel": "push",
        "title": "完成首购", "body": "这是一条模拟推送，不会实际发送。", **synthetic,
    }
    yield "offers", "demo_shipping", {
        "offer_id": "demo_shipping", "name": "演示 · 首单免邮",
        "amount": 8.0, "max_redemptions": 100, **synthetic,
    }
    yield "journeys", "demo_welcome_flow", {
        "journey_id": "demo_welcome_flow", "name": "演示 · 新用户欢迎旅程",
        "trigger_event": "signup", "segment_id": "demo_new_customers",
        "active": True, "created_at": stamp(-72),
        "steps": [
            {"channel": "email", "creative_id": "demo_welcome_email",
             "offer_id": "demo_shipping", "delay_seconds": 0},
            {"channel": "push", "creative_id": "demo_welcome_push",
             "offer_id": None, "delay_seconds": 3600},
        ], **synthetic,
    }
    yield "experiments", "demo_first_purchase", {
        "experiment_id": "demo_first_purchase",
        "name": "演示 · 首购激励对照",
        "metric_event": "purchase", "control": "holdout",
        "variants": [{"key": "holdout", "weight": 50},
                     {"key": "free_shipping", "weight": 50}],
        "window_days": 7, "state": "active",
        "created_at": stamp(-72), **synthetic,
    }
    for index in range(1, 13):
        customer_id = f"demo_customer_{index:02d}"
        yield "customers", customer_id, {
            "customer_id": customer_id,
            "attributes": {"lifecycle": "new" if index <= 8 else "returning",
                           "region": "north" if index % 2 else "south"},
            "consent": index != 12, "created_at": stamp(-96),
            **synthetic,
        }
        if index <= 8:
            yield "events", f"demo_signup_{index:02d}", {
                "event_id": f"demo_signup_{index:02d}",
                "customer_id": customer_id, "name": "signup",
                "occurred_at": stamp(-70), "ingested_at": stamp(-69),
                "properties": {}, **synthetic,
            }
        arm = "holdout" if index <= 6 else "free_shipping"
        yield "assignments", f"demo_first_purchase:{customer_id}", {
            "experiment_id": "demo_first_purchase", "customer_id": customer_id,
            "variant": arm, "assigned_at": stamp(-65), **synthetic,
        }
        yield "exposures", f"demo_first_purchase:demo_exposure_{index:02d}", {
            "exposure_id": f"demo_first_purchase:demo_exposure_{index:02d}",
            "experiment_id": "demo_first_purchase",
            "customer_id": customer_id, "variant": arm,
            "surface": "app_home", "occurred_at": stamp(-64), **synthetic,
        }
        if index in {1, 3, 7, 8, 9, 10}:
            yield "events", f"demo_purchase_{index:02d}", {
                "event_id": f"demo_purchase_{index:02d}",
                "customer_id": customer_id, "name": "purchase",
                "occurred_at": stamp(-24), "ingested_at": stamp(-24),
                "properties": {"amount": 99 + index}, **synthetic,
            }
    yield "jobs", "job_demo_welcome_flow_demo_signup_01_0", {
        "job_id": "job_demo_welcome_flow_demo_signup_01_0",
        "journey_id": "demo_welcome_flow", "customer_id": "demo_customer_01",
        "step_index": 0, "due_at": stamp(-1), "status": "pending", **synthetic,
    }
