"""Opt-in polling worker for durable journey due jobs.

The worker only materializes channel delivery intents. It never sends marketing
messages, and concurrent replicas are serialized by PostgreSQL scope locks.
"""
from __future__ import annotations

import asyncio
import logging

from .growth_ops import GrowthOperations
from .growth_store import GrowthStore

logger = logging.getLogger(__name__)


async def run_growth_worker(store: GrowthStore, *, interval_seconds: float = 5.0) -> None:
    if not 1 <= interval_seconds <= 60:
        raise ValueError("invalid worker polling interval")
    while True:
        try:
            scopes = await asyncio.to_thread(store.scopes_with_jobs)
            for scope in scopes:
                await asyncio.to_thread(
                    GrowthOperations(store, scope).process_due, limit=100,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("growth journey worker cycle failed")
        await asyncio.sleep(interval_seconds)
