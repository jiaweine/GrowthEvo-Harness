from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b, sha256
import json
from typing import Iterable, Mapping, Sequence


class PromotionTransition(str, Enum):
    ENTER_CANARY = "enter_canary"
    ADVANCE_STAGE = "advance_stage"
    FINAL_PROMOTION = "final_promotion"


class AuthorityVerdict(str, Enum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"


class ManifestReason(str, Enum):
    AUTHORIZED = "authorized"
    MISSING_AUTHORITY = "missing_authority"
    BLOCKED_AUTHORITY = "blocked_authority"
    STICKY_BLOCK = "sticky_block"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    STALE_EVIDENCE = "stale_evidence"
    UNAPPROVED_EVIDENCE_TYPE = "unapproved_evidence_type"
    UNAPPROVED_PROTOCOL = "unapproved_protocol"
    UNAPPROVED_PRODUCER = "unapproved_producer"
    MANIFEST_POLICY_MISMATCH = "manifest_policy_mismatch"
    MANIFEST_SUBJECT_MISMATCH = "manifest_subject_mismatch"
    LEDGER_HEAD_MISMATCH = "ledger_head_mismatch"


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(payload: Mapping[str, object], *, digest_size: int = 20) -> str:
    return blake2b(_canonical_json(payload), digest_size=digest_size).hexdigest()


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


@dataclass(frozen=True, slots=True)
class PromotionSubject:
    """Frozen subject to which every promotion authority attestation must bind."""

    experiment_id: str
    candidate_name: str
    candidate_contract_fingerprint: str
    promotion_artifact_fingerprint: str
    plan_fingerprint: str
    commit_sha: str

    def __post_init__(self) -> None:
        for name in (
            "experiment_id",
            "candidate_name",
            "candidate_contract_fingerprint",
            "promotion_artifact_fingerprint",
            "plan_fingerprint",
            "commit_sha",
        ):
            _nonempty(getattr(self, name), name)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.promotion-subject.v1",
                **asdict(self),
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorityEvidence:
    """One authority's provenance-bound, transition-scoped evidence statement.

    `evidence_epoch` is monotone within one authority for one subject. It is a
    logical freshness coordinate, not wall-clock time. `authorized_transitions`
    describes the strongest transition(s) this exact artifact was designed to
    authorize; an earlier-stage proof cannot be replayed for final promotion.
    """

    authority_id: str
    evidence_type: str
    producer: str
    subject_fingerprint: str
    protocol_fingerprint: str
    artifact_fingerprint: str
    verdict: AuthorityVerdict
    authorized_transitions: tuple[PromotionTransition, ...]
    evidence_epoch: int
    source_chain_head: str = "not_applicable"
    details_fingerprint: str = "not_applicable"

    def __post_init__(self) -> None:
        for name in (
            "authority_id",
            "evidence_type",
            "producer",
            "subject_fingerprint",
            "protocol_fingerprint",
            "artifact_fingerprint",
            "source_chain_head",
            "details_fingerprint",
        ):
            _nonempty(getattr(self, name), name)
        if not self.authorized_transitions:
            raise ValueError("authorized_transitions cannot be empty")
        normalized = tuple(dict.fromkeys(self.authorized_transitions))
        if normalized != self.authorized_transitions:
            raise ValueError("authorized_transitions must be unique and ordered")
        if (
            isinstance(self.evidence_epoch, bool)
            or not isinstance(self.evidence_epoch, int)
            or self.evidence_epoch < 0
        ):
            raise ValueError("evidence_epoch must be a non-negative integer")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.authority-evidence.v1",
                "authority_id": self.authority_id,
                "evidence_type": self.evidence_type,
                "producer": self.producer,
                "subject_fingerprint": self.subject_fingerprint,
                "protocol_fingerprint": self.protocol_fingerprint,
                "artifact_fingerprint": self.artifact_fingerprint,
                "verdict": self.verdict.value,
                "authorized_transitions": [item.value for item in self.authorized_transitions],
                "evidence_epoch": self.evidence_epoch,
                "source_chain_head": self.source_chain_head,
                "details_fingerprint": self.details_fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorityRequirement:
    """Exact allowlist for one authority at one promotion transition."""

    authority_id: str
    allowed_evidence_types: tuple[str, ...]
    allowed_protocol_fingerprints: tuple[str, ...]
    allowed_producers: tuple[str, ...]
    minimum_evidence_epoch: int = 0

    def __post_init__(self) -> None:
        _nonempty(self.authority_id, "authority_id")
        for name, values in (
            ("allowed_evidence_types", self.allowed_evidence_types),
            ("allowed_protocol_fingerprints", self.allowed_protocol_fingerprints),
            ("allowed_producers", self.allowed_producers),
        ):
            if not values:
                raise ValueError(f"{name} cannot be empty")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique values")
            for value in values:
                _nonempty(value, name)
        if (
            isinstance(self.minimum_evidence_epoch, bool)
            or not isinstance(self.minimum_evidence_epoch, int)
            or self.minimum_evidence_epoch < 0
        ):
            raise ValueError("minimum_evidence_epoch must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TransitionPolicy:
    transition: PromotionTransition
    requirements: tuple[AuthorityRequirement, ...]

    def __post_init__(self) -> None:
        if not self.requirements:
            raise ValueError("transition requirements cannot be empty")
        ids = [item.authority_id for item in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("each authority can appear only once per transition")


@dataclass(frozen=True, slots=True)
class PromotionEvidencePolicy:
    """Policy-as-code for promotion authority composition.

    `veto_authorities` are checked even when they are not listed as positive
    requirements for a transition. `sticky_block_authorities` are stronger: once a
    BLOCKED statement has ever appeared for the current subject, a later SATISFIED
    statement cannot clear it under this policy. Recovery requires a new subject
    identity (for example a new experiment/plan/artifact) or a different policy.
    """

    policy_id: str
    transitions: tuple[TransitionPolicy, ...]
    veto_authorities: tuple[str, ...] = ()
    sticky_block_authorities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.policy_id, "policy_id")
        if not self.transitions:
            raise ValueError("at least one transition policy is required")
        transitions = [item.transition for item in self.transitions]
        if len(set(transitions)) != len(transitions):
            raise ValueError("each promotion transition can appear only once")
        for name, values in (
            ("veto_authorities", self.veto_authorities),
            ("sticky_block_authorities", self.sticky_block_authorities),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique values")
            for value in values:
                _nonempty(value, name)
        if not set(self.sticky_block_authorities).issubset(set(self.veto_authorities)):
            raise ValueError("sticky_block_authorities must be a subset of veto_authorities")

    def transition_policy(self, transition: PromotionTransition) -> TransitionPolicy:
        for policy in self.transitions:
            if policy.transition is transition:
                return policy
        raise ValueError("promotion transition is not configured by this policy")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.promotion-evidence-policy.v1",
                "policy_id": self.policy_id,
                "transitions": [
                    {
                        "transition": item.transition.value,
                        "requirements": [asdict(requirement) for requirement in item.requirements],
                    }
                    for item in self.transitions
                ],
                "veto_authorities": list(self.veto_authorities),
                "sticky_block_authorities": list(self.sticky_block_authorities),
                "selection": "latest_epoch_per_authority",
                "default": "fail_closed",
            }
        )


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEvent:
    sequence: int
    evidence: AuthorityEvidence
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class PromotionEvidenceManifest:
    subject: PromotionSubject
    transition: PromotionTransition
    policy_fingerprint: str
    ledger_head_hash: str
    ledger_event_count: int
    latest_evidence: tuple[AuthorityEvidence, ...]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.promotion-evidence-manifest.v1",
                "subject_fingerprint": self.subject.fingerprint,
                "transition": self.transition.value,
                "policy_fingerprint": self.policy_fingerprint,
                "ledger_head_hash": self.ledger_head_hash,
                "ledger_event_count": self.ledger_event_count,
                "latest_evidence": [item.fingerprint for item in self.latest_evidence],
            },
            digest_size=32,
        )


@dataclass(frozen=True, slots=True)
class ManifestEvaluation:
    authorized: bool
    transition: PromotionTransition
    reasons: tuple[str, ...]
    manifest_fingerprint: str
    subject_fingerprint: str
    ledger_head_hash: str
    selected_evidence_fingerprints: tuple[str, ...]


class PromotionEvidenceLedger:
    """Append-only evidence ledger with monotone per-authority freshness.

    The ledger stores only fingerprints/aggregate authority statements. It is not a
    cryptographic signer. Authenticity of an upstream artifact remains the
    responsibility of the producer/verification boundary named by the policy.
    """

    _GENESIS = "0" * 64

    def __init__(self, subject: PromotionSubject) -> None:
        self.subject = subject
        self._events: list[EvidenceLedgerEvent] = []
        self._latest: dict[str, AuthorityEvidence] = {}

    @property
    def events(self) -> tuple[EvidenceLedgerEvent, ...]:
        return tuple(self._events)

    @property
    def head_hash(self) -> str:
        return self._events[-1].event_hash if self._events else self._GENESIS

    def append(self, evidence: AuthorityEvidence) -> EvidenceLedgerEvent:
        if evidence.subject_fingerprint != self.subject.fingerprint:
            raise ValueError("authority evidence is bound to a different promotion subject")
        latest = self._latest.get(evidence.authority_id)
        if latest is not None:
            if evidence.evidence_epoch < latest.evidence_epoch:
                raise ValueError("stale authority evidence cannot be appended")
            if evidence.evidence_epoch == latest.evidence_epoch:
                if evidence.fingerprint == latest.fingerprint:
                    # Exact replay is idempotent and does not extend the audit chain.
                    for event in reversed(self._events):
                        if event.evidence.fingerprint == evidence.fingerprint:
                            return event
                    raise RuntimeError("latest evidence is missing from the audit ledger")
                raise ValueError("conflicting authority evidence at the same epoch")

        sequence = len(self._events)
        previous_hash = self.head_hash
        event_hash = sha256(
            _canonical_json(
                {
                    "schema": "growthevo.promotion-evidence-ledger-event.v1",
                    "sequence": sequence,
                    "subject_fingerprint": self.subject.fingerprint,
                    "evidence_fingerprint": evidence.fingerprint,
                    "previous_hash": previous_hash,
                }
            )
        ).hexdigest()
        event = EvidenceLedgerEvent(
            sequence=sequence,
            evidence=evidence,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        self._latest[evidence.authority_id] = evidence
        return event

    def verify_chain(self) -> bool:
        previous = self._GENESIS
        for sequence, event in enumerate(self._events):
            if event.sequence != sequence or event.previous_hash != previous:
                return False
            expected = sha256(
                _canonical_json(
                    {
                        "schema": "growthevo.promotion-evidence-ledger-event.v1",
                        "sequence": sequence,
                        "subject_fingerprint": self.subject.fingerprint,
                        "evidence_fingerprint": event.evidence.fingerprint,
                        "previous_hash": previous,
                    }
                )
            ).hexdigest()
            if event.event_hash != expected:
                return False
            previous = event.event_hash
        return True

    def latest_evidence(self) -> tuple[AuthorityEvidence, ...]:
        return tuple(
            self._latest[key]
            for key in sorted(self._latest)
        )

    def build_manifest(
        self,
        *,
        policy: PromotionEvidencePolicy,
        transition: PromotionTransition,
    ) -> PromotionEvidenceManifest:
        policy.transition_policy(transition)
        if not self.verify_chain():
            raise RuntimeError("promotion evidence ledger hash chain is invalid")
        return PromotionEvidenceManifest(
            subject=self.subject,
            transition=transition,
            policy_fingerprint=policy.fingerprint,
            ledger_head_hash=self.head_hash,
            ledger_event_count=len(self._events),
            latest_evidence=self.latest_evidence(),
        )

    def _sticky_blocked(self, authority_id: str) -> AuthorityEvidence | None:
        for event in self._events:
            if (
                event.evidence.authority_id == authority_id
                and event.evidence.verdict is AuthorityVerdict.BLOCKED
            ):
                return event.evidence
        return None

    def evaluate(
        self,
        *,
        manifest: PromotionEvidenceManifest,
        policy: PromotionEvidencePolicy,
    ) -> ManifestEvaluation:
        reasons: list[str] = []
        if manifest.policy_fingerprint != policy.fingerprint:
            reasons.append(ManifestReason.MANIFEST_POLICY_MISMATCH.value)
        if manifest.subject.fingerprint != self.subject.fingerprint:
            reasons.append(ManifestReason.MANIFEST_SUBJECT_MISMATCH.value)
        if (
            manifest.ledger_head_hash != self.head_hash
            or manifest.ledger_event_count != len(self._events)
        ):
            reasons.append(ManifestReason.LEDGER_HEAD_MISMATCH.value)
        if manifest.transition not in [item.transition for item in policy.transitions]:
            raise ValueError("manifest transition is not configured by the policy")

        # The evaluator never trusts a caller-provided evidence subset. It rebuilds
        # the latest view from the verified ledger and only uses the manifest as a
        # provenance snapshot whose head/policy/subject must match.
        latest = dict(self._latest)
        transition_policy = policy.transition_policy(manifest.transition)

        for authority_id in policy.sticky_block_authorities:
            blocked = self._sticky_blocked(authority_id)
            if blocked is not None:
                reasons.append(f"{ManifestReason.STICKY_BLOCK.value}:{authority_id}")

        for authority_id in policy.veto_authorities:
            evidence = latest.get(authority_id)
            if evidence is not None and evidence.verdict is AuthorityVerdict.BLOCKED:
                reasons.append(f"{ManifestReason.BLOCKED_AUTHORITY.value}:{authority_id}")

        for requirement in transition_policy.requirements:
            evidence = latest.get(requirement.authority_id)
            if evidence is None:
                reasons.append(
                    f"{ManifestReason.MISSING_AUTHORITY.value}:{requirement.authority_id}"
                )
                continue
            if evidence.verdict is AuthorityVerdict.BLOCKED:
                reasons.append(
                    f"{ManifestReason.BLOCKED_AUTHORITY.value}:{requirement.authority_id}"
                )
                continue
            if manifest.transition not in evidence.authorized_transitions:
                reasons.append(
                    f"{ManifestReason.INSUFFICIENT_SCOPE.value}:{requirement.authority_id}"
                )
            if evidence.evidence_epoch < requirement.minimum_evidence_epoch:
                reasons.append(
                    f"{ManifestReason.STALE_EVIDENCE.value}:{requirement.authority_id}"
                )
            if evidence.evidence_type not in requirement.allowed_evidence_types:
                reasons.append(
                    f"{ManifestReason.UNAPPROVED_EVIDENCE_TYPE.value}:{requirement.authority_id}"
                )
            if evidence.protocol_fingerprint not in requirement.allowed_protocol_fingerprints:
                reasons.append(
                    f"{ManifestReason.UNAPPROVED_PROTOCOL.value}:{requirement.authority_id}"
                )
            if evidence.producer not in requirement.allowed_producers:
                reasons.append(
                    f"{ManifestReason.UNAPPROVED_PRODUCER.value}:{requirement.authority_id}"
                )

        authorized = not reasons
        if authorized:
            reasons.append(ManifestReason.AUTHORIZED.value)
        selected = tuple(
            evidence.fingerprint
            for _, evidence in sorted(latest.items())
        )
        return ManifestEvaluation(
            authorized=authorized,
            transition=manifest.transition,
            reasons=tuple(reasons),
            manifest_fingerprint=manifest.fingerprint,
            subject_fingerprint=self.subject.fingerprint,
            ledger_head_hash=self.head_hash,
            selected_evidence_fingerprints=selected,
        )
