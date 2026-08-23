"""Runtime package with lazy public exports to avoid import cycles."""

from __future__ import annotations

from typing import Any

__all__ = ["EventStore", "GrowthEvoRuntime", "GrowthHypothesisPlanner", "LegalActionGate"]


def __getattr__(name: str) -> Any:
    if name == "GrowthEvoRuntime":
        from .engine import GrowthEvoRuntime

        return GrowthEvoRuntime
    if name == "EventStore":
        from .event_store import EventStore

        return EventStore
    if name == "LegalActionGate":
        from .legal_action import LegalActionGate

        return LegalActionGate
    if name == "GrowthHypothesisPlanner":
        from .planner import GrowthHypothesisPlanner

        return GrowthHypothesisPlanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
