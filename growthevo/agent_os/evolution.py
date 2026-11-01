"""Evidence-gated recursive improvement of the *operator policy*, not self-editing code.

Candidates are descended from the active policy and archived. Evaluation is
delegated to an independent, caller-supplied held-out evaluator. An evaluator
must produce real measurements; no fixture metrics are synthesized here.
Promotion requires a separate trusted authority and real shadow/canary gates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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

    def propose(self, traces: list[dict[str, Any]]) -> EvolutionCandidate | None:
        """Mine only actual operator traces; ignore fixtures and unverifiable runs."""
        with self._lock:
            real = [t for t in traces if str(t.get("run_id", "")).startswith("op_")
                    and isinstance(t.get("steps"), list)]
            if len(real) < 8:
                return None
            recent = real[:30]
            step_limited = sum(t.get("status") == "step_limit" for t in recent)
            # A model finish is not evidence of task success; this only mines a candidate.
            completed = [t for t in recent if t.get("status") == "completed"]
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

    def evaluate(self, candidate_id: str,
                 heldout_evaluator: Callable[[OperatorPolicy, OperatorPolicy], Mapping[str, Any]]
                 ) -> EvolutionCandidate:
        """Evaluation happens outside the model and must use an independent holdout.

        The evaluator must return measured baseline/candidate task success,
        safety violation rates, normalized cost and a unique evidence identity.
        """
        with self._lock:
            candidate = next((c for c in self.archive if c.id == candidate_id), None)
            if candidate is None or candidate.parent != self.active.fingerprint:
                raise ValueError("candidate is missing or no longer descended from active policy")
            if candidate.status != "requires_independent_eval":
                raise ValueError("candidate has already been evaluated")
            measured = dict(heldout_evaluator(self.active, candidate.proposal))
            expected = {"baseline_success", "candidate_success", "baseline_violations",
                        "candidate_violations", "baseline_cost", "candidate_cost",
                        "sample_size", "evidence_id"}
            if set(measured) != expected:
                raise ValueError("heldout evidence schema is incomplete")
            for key in expected - {"sample_size", "evidence_id"}:
                value = measured[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("invalid heldout measurement")
                from math import isfinite
                if not isfinite(value) or value < 0:
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
            candidate.evaluation = measured
            eligible = (
                measured["candidate_success"] > measured["baseline_success"]
                and measured["candidate_violations"] <= measured["baseline_violations"]
                and measured["candidate_cost"] <= measured["baseline_cost"] * 1.1
            )
            candidate.status = "awaiting_shadow_canary" if eligible else "rejected_by_eval"
            return candidate

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
            return [
                {"id": c.id, "parent": c.parent, "proposal": asdict(c.proposal),
                 "reason": c.reason, "source_count": c.source_count, "status": c.status,
                 "evaluation": c.evaluation}
                for c in reversed(self.archive)
            ]
