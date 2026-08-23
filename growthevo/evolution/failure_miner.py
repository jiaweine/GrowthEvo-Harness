from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import FailureKind, VerificationResult, VerificationStatus
from growthevo.runtime.legal_action import ActionDecision


@dataclass(frozen=True, slots=True)
class FailureTrace:
    kind: FailureKind
    message: str
    evidence: tuple[str, ...]


class FailureMiner:
    """Classify failures without allowing the classifier to redefine success."""

    def from_action_decision(self, decision: ActionDecision) -> FailureTrace | None:
        if decision.allowed:
            return None
        joined = " ".join(decision.reasons)
        if "consented" in joined:
            kind = FailureKind.CONSENT
        elif "budget" in joined or "offer_cap" in joined:
            kind = FailureKind.BUDGET
        elif "fatigue" in joined or "touch_" in joined:
            kind = FailureKind.FATIGUE
        else:
            kind = FailureKind.UNKNOWN
        return FailureTrace(kind=kind, message="Growth action blocked by legal action gate.", evidence=decision.reasons)

    def from_verification(self, result: VerificationResult) -> FailureTrace | None:
        if result.status is VerificationStatus.PASS:
            return None
        joined = " ".join(result.reasons)
        if result.status is VerificationStatus.INSUFFICIENT_EVIDENCE:
            kind = FailureKind.UNCERTAINTY
        elif "roi" in joined:
            kind = FailureKind.ROI
        elif "budget" in joined:
            kind = FailureKind.BUDGET
        elif "fatigue" in joined or "churn" in joined:
            kind = FailureKind.FATIGUE
        elif "lcb" in joined:
            kind = FailureKind.ATTRIBUTION
        else:
            kind = FailureKind.UNKNOWN
        return FailureTrace(kind=kind, message="Candidate policy did not pass verification.", evidence=result.reasons)
