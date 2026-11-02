"""Atomic, principal-scoped persistence of the existing evolution authority."""
from __future__ import annotations

from copy import deepcopy
from secrets import token_urlsafe
from time import time
from typing import Any, Callable

from .evolution import EvolutionAuthority, OperatorPolicy
from .journal import ExecutionConflict


class DurableEvolutionAuthority:
    EVALUATION_LEASE_SECONDS = 600

    def __init__(self, backend: Any, scope: str):
        self.backend, self.scope = backend, scope

    @staticmethod
    def _initial() -> dict[str, Any]:
        return EvolutionAuthority().export_state() | {"claims": {}}

    def _state(self) -> dict[str, Any]:
        try:
            return self.backend.get(self.scope, "evolution", "current")
        except KeyError:
            return self._initial()

    def _change(self, transition: Callable) -> Any:
        def apply(state, now):
            authority = EvolutionAuthority.from_state(state)
            result = transition(authority, state["claims"], now)
            return authority.export_state() | {"claims": state["claims"]}, result

        return self.backend.mutate(self.scope, "evolution", "current", apply, initial=self._initial())

    def snapshot(self) -> dict[str, Any]:
        return EvolutionAuthority.from_state(self._state()).snapshot()

    @property
    def active(self) -> OperatorPolicy:
        return OperatorPolicy(**self._state()["active"])

    def readiness(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        return EvolutionAuthority.from_state(self._state()).readiness(traces) | {"durability": self.backend.durability}

    def propose(self, traces: list[dict[str, Any]]) -> Any:
        return self._change(lambda authority, claims, now: authority.propose(traces))

    def candidates(self) -> list[dict[str, Any]]:
        state = self._state()
        items = EvolutionAuthority.from_state(state).candidates()
        for item in items:
            claim = state["claims"].get(item["id"])
            item["retryable_evaluation"] = bool(claim and claim["expires_at"] <= time())
        return items

    def evaluate(self, candidate_id: str, heldout_evaluator: Callable) -> Any:
        token = token_urlsafe(32)

        def claim(authority, claims, now):
            previous = claims.get(candidate_id)
            if previous is not None and previous["expires_at"] <= now:
                authority._release_evaluation(candidate_id, previous["parent"])
                del claims[candidate_id]
            baseline, proposal, parent = authority._claim_evaluation(candidate_id)
            claims[candidate_id] = {"token": token, "parent": parent,
                                    "expires_at": now + self.EVALUATION_LEASE_SECONDS}
            return baseline, proposal, parent

        baseline, proposal, parent = self._change(claim)
        try:
            measured = dict(heldout_evaluator(baseline, proposal))
            EvolutionAuthority._validate_evidence(measured)
        except BaseException:
            def release(authority, claims, now):
                current = claims.get(candidate_id)
                if current is not None and current["token"] == token:
                    authority._release_evaluation(candidate_id, parent)
                    del claims[candidate_id]

            self._change(release)
            raise

        def commit(authority, claims, now):
            current = claims.get(candidate_id)
            if current is None or current["token"] != token or current["expires_at"] <= now:
                return False, "evaluation lease was lost or expired"
            del claims[candidate_id]
            try:
                return True, deepcopy(authority._finish_evaluation(candidate_id, parent, measured))
            except ValueError as exc:
                # Commit the stale status before reporting rejection.
                return False, str(exc)

        accepted, result = self._change(commit)
        if not accepted:
            raise ExecutionConflict(result)
        return result

    def promote(self, candidate_id: str, **evidence: Any) -> Any:
        # Trusted host API only. No model or public HTTP promotion route is added.
        return self._change(lambda authority, claims, now: authority.promote(candidate_id, **evidence))
