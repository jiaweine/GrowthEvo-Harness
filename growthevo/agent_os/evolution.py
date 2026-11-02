"""Evidence-gated recursive improvement of the *operator policy*, not self-editing code.

Candidates are descended from the active policy and archived. Evaluation is
delegated to an independent, caller-supplied held-out evaluator. An evaluator
must produce real measurements; no fixture metrics are synthesized here.
Promotion requires a separate trusted authority and real shadow/canary gates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock
from typing import Callable, Mapping, Any
from uuid import uuid4


@dataclass(frozen=True)
class OperatorPolicy:
    step_budget: int = 6
    preferred_first_read: str = "none"

    def __post_init__(self) -> None:
        if not 3 <= self.step_budget <= 8:
            raise ValueError("step budget outside approved search space")
        if self.preferred_first_read not in {"none", "opportunities", "evidence", "campaigns"}:
            raise ValueError("unapproved tool preference")

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True).encode()
        return sha256(raw).hexdigest()[:16]


@dataclass
class EvolutionCandidate:
    id: str
    parent: str
    proposal: OperatorPolicy
    reason: str
    source_count: int
    status: str = "requires_independent_eval"
    evaluation: dict[str, Any] | None = None


class EvolutionAuthority:
    """An append-only candidate archive and guarded promotion authority.

    No model can call promotion. The policy is updated only after held-out
    validation, signed-off shadow and canary evidence and an operator's approval.
    A successful promotion changes the operator instructions/limits for future
    runs; subsequent failures can propose descendants of that exact policy.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self.active = OperatorPolicy()
        self.archive: list[EvolutionCandidate] = []

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self.active) | {"fingerprint": self.active.fingerprint}

    def _eligible_traces(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        recent = []
        for trace in traces:
            run_id = trace.get("run_id", "")
            if (not isinstance(run_id, str) or not run_id.startswith("op_") or run_id in seen
                or not isinstance(trace.get("steps"), list)
                or trace.get("policy_fingerprint") != self.active.fingerprint
                or trace.get("status") in {"running", "interrupted", "awaiting_ui_confirmation"}):
                continue
            seen.add(run_id)
            recent.append(trace)
            if len(recent) == 30:
                break
        return recent

    def readiness(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        """Explain the real trace gate without manufacturing improvement metrics."""
        with self._lock:
            recent = self._eligible_traces(traces)
            step_limits = sum(t.get("status") == "step_limit" for t in recent)
            completed = sum(t.get("status") in {"completed", "ui_confirmed"} for t in recent)
            return {
                "trace_count": len(recent),
                "required_trace_count": 8,
                "step_limit_count": step_limits,
                "completed_count": completed,
                "candidate_count": len(self.archive),
                "active_policy_fingerprint": self.active.fingerprint,
                "enough_traces": len(recent) >= 8,
                "evaluation_runner": "independent_offline_only",
                "promotion": "separate_shadow_canary_and_human_approval",
                "durability": "process_local",
            }

    def propose(self, traces: list[dict[str, Any]]) -> EvolutionCandidate | None:
        """Mine only actual operator traces; ignore fixtures and unverifiable runs."""
        with self._lock:
            recent = self._eligible_traces(traces)
            if len(recent) < 8:
                return None
            step_limited = sum(t.get("status") == "step_limit" for t in recent)
            # A model finish is not evidence of task success; this only mines a candidate.
            completed = [t for t in recent if t.get("status") in {"completed", "ui_confirmed"}]
            new_policy: OperatorPolicy | None = None
            reason = ""
            if step_limited >= 3 and self.active.step_budget < 8:
                new_policy = replace(self.active, step_budget=self.active.step_budget + 1)
                reason = "Repeated real operator step-limit failures"
            elif len(completed) >= 5:
                first_reads = [
                    next((s.get("section") for s in t["steps"]
                          if s.get("tool") == "workspace.read" and s.get("outcome") == "ok"), None)
                    for t in completed
                ]
                counts = {section: first_reads.count(section)
                          for section in ("opportunities", "evidence", "campaigns")}
                preferred = max(counts, key=counts.get)
                if (counts[preferred] >= 4 and counts[preferred] / len(completed) >= 0.7
                    and preferred != self.active.preferred_first_read):
                    new_policy = replace(self.active, preferred_first_read=preferred)
                    reason = "Frequent first-read pattern among model-finished runs (task success unverified)"
            if new_policy is None:
                return None
            if any(c.parent == self.active.fingerprint
                   and c.proposal == new_policy for c in self.archive):
                return None
            candidate = EvolutionCandidate(
                id="evo_" + uuid4().hex[:12], parent=self.active.fingerprint,
                proposal=new_policy, reason=reason, source_count=len(recent)
            )
            self.archive.append(candidate)
            return candidate

    def _claim_evaluation(self, candidate_id: str) -> tuple[OperatorPolicy, OperatorPolicy, str]:
        with self._lock:
            candidate = next((c for c in self.archive if c.id == candidate_id), None)
            if candidate is None or candidate.parent != self.active.fingerprint:
                raise ValueError("candidate is missing or no longer descended from active policy")
            if candidate.status != "requires_independent_eval":
                raise ValueError("candidate has already been evaluated")
            candidate.status = "evaluating"
            return self.active, candidate.proposal, self.active.fingerprint

    @staticmethod
    def _validate_evidence(measured: Mapping[str, Any]) -> None:
        expected = {"baseline_success", "candidate_success", "baseline_violations",
                    "candidate_violations", "baseline_cost", "candidate_cost",
                    "sample_size", "evidence_id"}
        if set(measured) != expected:
            raise ValueError("heldout evidence schema is incomplete")
        from math import isfinite
        for key in expected - {"sample_size", "evidence_id"}:
            value = measured[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or value < 0):
                raise ValueError("heldout measurements must be finite and nonnegative")
        if (not isinstance(measured["sample_size"], int)
            or isinstance(measured["sample_size"], bool)
            or measured["sample_size"] < 30):
            raise ValueError("insufficient independent evaluation samples")
        if (not isinstance(measured["evidence_id"], str)
            or len(measured["evidence_id"].strip()) < 12):
            raise ValueError("missing independent evidence identity")
        if any(measured[k] > 1 for k in ("baseline_success", "candidate_success",
                                        "baseline_violations", "candidate_violations")):
            raise ValueError("invalid probability metric")

    def _release_evaluation(self, candidate_id: str, parent: str) -> None:
        with self._lock:
            candidate = next(c for c in self.archive if c.id == candidate_id)
            if candidate.status == "evaluating":
                candidate.status = ("requires_independent_eval" if self.active.fingerprint == parent
                                    else "stale_evaluation")

    def _finish_evaluation(self, candidate_id: str, parent: str, measured: dict[str, Any]) -> EvolutionCandidate:
        with self._lock:
            candidate = next(c for c in self.archive if c.id == candidate_id)
            if self.active.fingerprint != parent or candidate.parent != parent:
                candidate.status = "stale_evaluation"
                raise ValueError("active policy changed during independent evaluation")
            if candidate.status != "evaluating":
                raise ValueError("candidate evaluation claim was invalidated")
            candidate.evaluation = deepcopy(measured)
            eligible = (
                measured["candidate_success"] > measured["baseline_success"]
                and measured["candidate_violations"] <= measured["baseline_violations"]
                and measured["candidate_cost"] <= measured["baseline_cost"] * 1.1
            )
            candidate.status = "awaiting_shadow_canary" if eligible else "rejected_by_eval"
            return candidate

    def evaluate(self, candidate_id: str,
                 heldout_evaluator: Callable[[OperatorPolicy, OperatorPolicy], Mapping[str, Any]]
                 ) -> EvolutionCandidate:
        baseline, proposal, parent = self._claim_evaluation(candidate_id)
        try:
            measured = dict(heldout_evaluator(baseline, proposal))
            self._validate_evidence(measured)
        except BaseException:
            self._release_evaluation(candidate_id, parent)
            raise
        return self._finish_evaluation(candidate_id, parent, measured)

    def export_state(self) -> dict[str, Any]:
        with self._lock:
            return {"active": asdict(self.active), "archive": [asdict(c) for c in self.archive]}

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> EvolutionAuthority:
        authority = cls()
        authority.active = OperatorPolicy(**state["active"])
        authority.archive = [EvolutionCandidate(**(item | {"proposal": OperatorPolicy(**item["proposal"])}))
                             for item in state["archive"]]
        return authority

    def promote(self, candidate_id: str, *, operator_approved: bool,
                shadow_passed: bool, canary_passed: bool,
                evidence_reference: str) -> OperatorPolicy:
        """Trusted server/operator only; never expose promotion to the model."""
        with self._lock:
            candidate = next((c for c in self.archive if c.id == candidate_id), None)
            if (candidate is None or candidate.parent != self.active.fingerprint
                or candidate.status != "awaiting_shadow_canary"):
                raise ValueError("not a promotable descendant of the active policy")
            if (not operator_approved or not shadow_passed or not canary_passed
                or not isinstance(evidence_reference, str)
                or len(evidence_reference.strip()) < 12):
                raise ValueError("independent shadow/canary evidence and approval required")
            # Production callers must authenticate and independently verify their
            # evidence reference; booleans are NOT cryptographic attestations.
            candidate.status = "promoted"
            self.active = candidate.proposal
            return self.active

    def candidates(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy([
                {"id": c.id, "parent": c.parent, "proposal": asdict(c.proposal),
                 "reason": c.reason, "source_count": c.source_count, "status": c.status,
                 "evaluation": c.evaluation}
                for c in reversed(self.archive)
            ])
