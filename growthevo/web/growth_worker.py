"""Run durable, bounded simulated journey dispatches outside web request workers.

Usage:
  GROWTHEVO_MODE=api GROWTHEVO_DATABASE_URL=... python -m growthevo.web.growth_worker

A production deployment with no approved external channel transport will mark
work blocked. Simulated records are never labeled as delivered real messages.
"""
from __future__ import annotations

import os
import time

from .growth_service import GrowthService
from .growth_store import GrowthStore
from .persistence import PostgresStore
from .runtime import RuntimeSettings, postgres_pool_config_from_env


def main() -> None:
    settings = RuntimeSettings.from_env()
    if settings.synthetic_data or not settings.database_configured:
        raise RuntimeError("growth worker requires API/production mode and PostgreSQL")
    url = (os.getenv("GROWTHEVO_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    pool = postgres_pool_config_from_env()
    parent = PostgresStore(
        url, seed_reference=False,
        min_size=pool.min_size, max_size=pool.max_size,
        timeout_seconds=pool.timeout_seconds,
    )
    try:
        store = GrowthStore(parent)
        operator = GrowthService(store, "background-worker", simulation=not settings.production)
        while True:
            try:
                operator.run_due(limit=20)
            except Exception:
                # Work is durably marked failed; do not swallow a broken
                # database or another unexpected operating condition.
                raise
            time.sleep(2)
    except KeyboardInterrupt:
        return
    finally:
        parent.close()


if __name__ == "__main__":
    main()
