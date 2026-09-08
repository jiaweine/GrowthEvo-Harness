from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b
import json
from math import isfinite
from typing import Sequence

from .online_promotion import CanaryStatus
from .promotion_governance import GovernanceAuthorizationRecord
from .promotion_manifest import (
    AuthorityEvidence,
    AuthorityVerdict,
    ManifestReason,
    PromotionEvidenceLedger,
    PromotionEvidenceManifest,
    PromotionSubject,
    PromotionTransition,
)
from .sequential_causal import HighPowerCanaryPlan, HighPowerOnlineCanaryMonitor


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(payload: object, *, digest_size: int = 20) -> str:
    return blake2b(_canonical_json(payload), digest_size=digest_size).hexdigest()


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceContract:
    """Exact producer contract for one authority evidence implementation.

    Unlike three independent allowlists, this tuple cannot be recombined with
    fields from another accepted implementation.
    """

    evidence_type: str
    protocol_fingerprint: str
    producer: str

    def __post_init__(self) -> None:
        _nonempty(self.evidence_type, "evidence_type")
        _nonempty(self.protocol_fingerprint, "protocol_fingerprint")
        _nonempty(self.producer, "producer")

    @classmethod
    def from_evidence(cls, evidence: AuthorityEvidence) -> "EvidenceContract":
        return cls(
            evidence_type=evidence.evidence_type,
            protocol_fingerprint=evidence.protocol_fingerprint,
            producer=evidence.producer,
        )

    def matches(self, evidence: AuthorityEvidence) -> bool:
        return (
            evidence.evidence_type == self.evidence_type
            and evidence.protocol_fingerprint == self.protocol_fingerprint
            and evidence.producer == self.producer
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.evidence-contract.v2",
                **asdict(self),
            }
        )


@dataclass(frozen=True, slots=True)
class StrictAuthorityRequirement:
    authority_id: str
    accepted_contracts: tuple[EvidenceContract, ...]
    minimum_evidence_epoch: int = 0

    def __post_init__(self) -> None:
        _nonempty(self.authority_id, "authority_id")
        if not self.accepted_contracts:
            raise ValueError("accepted_contracts cannot be empty")
        fingerprints = tuple(item.fingerprint for item in self.accepted_contracts)
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("accepted_contracts must be unique")
        if (
            isinstance(self.minimum_evidence_epoch, bool)
            or not isinstance(self.minimum_evidence_epoch, int)
            or self.minimum_evidence_epoch < 0
        ):
            raise ValueError("minimum_evidence_epoch must be a non-negative integer")

    def matches(self, evidence: AuthorityEvidence) -> bool:
        return any(contract.matches(evidence) for contract in self.accepted_contracts)


@dataclass(frozen=True, slots=True)
class StrictTransitionPolicy:
    transition: PromotionTransition
    requirements: tuple[StrictAuthorityRequirement, ...]

    def __post_init__(self) -> None:
        if not self.requirements:
            raise ValueError("requirements cannot be empty")
        ids = [item.authority_id for item in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("each authority can appear only once per transition")


@dataclass(frozen=True, slots=True)
class StrictPromotionEvidencePolicy:
    """Phase-21 policy with exact evidence-contract alternatives.

    This is schema-v2 on purpose. It does not silently reinterpret the Phase-14
    v1 allowlist semantics.
    """

    policy_id: str
    transitions: tuple[StrictTransitionPolicy, ...]
    veto_authorities: tuple[str, ...] = ()
    sticky_block_authorities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.policy_id, "policy_id")
        if not self.transitions:
            raise ValueError("transitions cannot be empty")
        transitions = [item.transition for item in self.transitions]
        if len(set(transitions)) != len(transitions):
            raise ValueError("each transition may appear only once")
        for name, values in (
            ("veto_authorities", self.veto_authorities),
            ("sticky_block_authorities", self.sticky_block_authorities),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
            for value in values:
                _nonempty(value, name)
        if not set(self.sticky_block_authorities).issubset(self.veto_authorities):
            raise ValueError("sticky block authorities must also be veto authorities")

    def transition_policy(self, transition: PromotionTransition) -> StrictTransitionPolicy:
        for item in self.transitions:
            if item.transition is transition:
                return item
        raise ValueError("transition is not configured by strict promotion policy")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.strict-promotion-evidence-policy.v2",
                "policy_id": self.policy_id,
                "transitions": [
                    {
                        "transition": item.transition.value,
                        "requirements": [
                            {
                                "authority_id": requirement.authority_id,
                                "accepted_contracts": [
                                    asdict(contract)
                                    for contract in requirement.accepted_contracts
                                ],
                                "minimum_evidence_epoch": requirement.minimum_evidence_epoch,
                            }
                            for requirement in item.requirements
                        ],
                    }
                    for item in self.transitions
                ],
                "veto_authorities": list(self.veto_authorities),
                "sticky_block_authorities": list(self.sticky_block_authorities),
                "contract_match": "exact_type_protocol_producer_tuple",
            }
        )


class StrictPromotionManifestGate:
    """Phase-20 compatible gate using the strict Phase-21 policy evaluator."""

    def __init__(
        self,
        *,
        ledger: PromotionEvidenceLedger,
        policy: StrictPromotionEvidencePolicy,
        expected_plan_fingerprint: str,
    ) -> None:
        _nonempty(expected_plan_fingerprint, "expected_plan_fingerprint")
        if ledger.subject.plan_fingerprint != expected_plan_fingerprint:
            raise ValueError("promotion subject is bound to a different online plan")
        self.ledger = ledger
        self.policy = policy
        self.expected_plan_fingerprint = expected_plan_fingerprint

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.strict-promotion-manifest-gate.v2",
                "subject_fingerprint": self.ledger.subject.fingerprint,
                "policy_fingerprint": self.policy.fingerprint,
                "expected_plan_fingerprint": self.expected_plan_fingerprint,
                "default": "fail_closed",
            }
        )

    def _sticky_blocked(self, authority_id: str) -> bool:
        return any(
            event.evidence.authority_id == authority_id
            and event.evidence.verdict is AuthorityVerdict.BLOCKED
            for event in self.ledger.events
        )

    def evaluate(self, transition: PromotionTransition) -> GovernanceAuthorizationRecord:
        transition_policy = self.policy.transition_policy(transition)
        if not self.ledger.verify_chain():
            return GovernanceAuthorizationRecord(
                transition=transition,
                authorized=False,
                reasons=(ManifestReason.LEDGER_CHAIN_INVALID.value,),
                manifest_fingerprint="not_available",
                policy_fingerprint=self.policy.fingerprint,
                subject_fingerprint=self.ledger.subject.fingerprint,
                ledger_head_hash=self.ledger.head_hash,
                ledger_event_count=len(self.ledger.events),
            )

        manifest = PromotionEvidenceManifest(
            subject=self.ledger.subject,
            transition=transition,
            policy_fingerprint=self.policy.fingerprint,
            ledger_head_hash=self.ledger.head_hash,
            ledger_event_count=len(self.ledger.events),
            latest_evidence=self.ledger.latest_evidence(),
        )
        latest = {item.authority_id: item for item in self.ledger.latest_evidence()}
        reasons: list[str] = []

        for authority_id in self.policy.sticky_block_authorities:
            if self._sticky_blocked(authority_id):
                reasons.append(f"{ManifestReason.STICKY_BLOCK.value}:{authority_id}")

        for authority_id in self.policy.veto_authorities:
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
            if transition not in evidence.authorized_transitions:
                reasons.append(
                    f"{ManifestReason.INSUFFICIENT_SCOPE.value}:{requirement.authority_id}"
                )
            if evidence.evidence_epoch < requirement.minimum_evidence_epoch:
                reasons.append(
                    f"{ManifestReason.STALE_EVIDENCE.value}:{requirement.authority_id}"
                )
            if not requirement.matches(evidence):
                reasons.append(f"unapproved_evidence_contract:{requirement.authority_id}")

        unique_reasons = tuple(dict.fromkeys(reasons))
        authorized = not unique_reasons
        if authorized:
            unique_reasons = (ManifestReason.AUTHORIZED.value,)
        return GovernanceAuthorizationRecord(
            transition=transition,
            authorized=authorized,
            reasons=unique_reasons,
            manifest_fingerprint=manifest.fingerprint,
            policy_fingerprint=self.policy.fingerprint,
            subject_fingerprint=self.ledger.subject.fingerprint,
            ledger_head_hash=self.ledger.head_hash,
            ledger_event_count=len(self.ledger.events),
        )


@dataclass(frozen=True, slots=True)
class OnlineAuthorityEvidenceSpec:
    plan_fingerprint: str
    safety_producer: str = "growthevo.online-safety-monitor.v1"
    success_producer: str = "growthevo.group-sequential-primary.v1"

    def __post_init__(self) -> None:
        _nonempty(self.plan_fingerprint, "plan_fingerprint")
        _nonempty(self.safety_producer, "safety_producer")
        _nonempty(self.success_producer, "success_producer")

    @classmethod
    def from_plan(
        cls,
        plan: HighPowerCanaryPlan,
        *,
        safety_producer: str = "growthevo.online-safety-monitor.v1",
        success_producer: str = "growthevo.group-sequential-primary.v1",
    ) -> "OnlineAuthorityEvidenceSpec":
        return cls(
            plan_fingerprint=plan.fingerprint,
            safety_producer=safety_producer,
            success_producer=success_producer,
        )

    @property
    def safety_protocol_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.online-safety-authority-protocol.v1",
                "plan_fingerprint": self.plan_fingerprint,
                "safety_monitor": "anytime-valid-relative-and-absolute-guardrails",
                "decision": "safe_to_ramp",
            }
        )

    @property
    def success_protocol_fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.primary-success-authority-protocol.v1",
                "plan_fingerprint": self.plan_fingerprint,
                "success_monitor": "pre-registered-group-sequential-primary",
                "decision": "latest_planned_look_success",
            }
        )

    @property
    def safety_contract(self) -> EvidenceContract:
        return EvidenceContract(
            evidence_type="online_safety.v1",
            protocol_fingerprint=self.safety_protocol_fingerprint,
            producer=self.safety_producer,
        )

    @property
    def success_contract(self) -> EvidenceContract:
        return EvidenceContract(
            evidence_type="primary_success.v1",
            protocol_fingerprint=self.success_protocol_fingerprint,
            producer=self.success_producer,
        )


def _assert_subject_plan(subject: PromotionSubject, plan: HighPowerCanaryPlan) -> None:
    if subject.plan_fingerprint != plan.fingerprint:
        raise ValueError("promotion subject is not bound to this high-power canary plan")
    if subject.experiment_id != plan.base_plan.experiment_id:
        raise ValueError("promotion subject experiment does not match canary plan")


def _assert_spec_plan(spec: OnlineAuthorityEvidenceSpec, plan: HighPowerCanaryPlan) -> None:
    if spec.plan_fingerprint != plan.fingerprint:
        raise ValueError("online authority spec is bound to another canary plan")


def _safety_is_established(monitor: HighPowerOnlineCanaryMonitor) -> tuple[bool, tuple[str, ...]]:
    snapshot = monitor.snapshot()
    plan = monitor.plan
    gaps: list[str] = []
    if snapshot.status not in {CanaryStatus.RUNNING, CanaryStatus.PROMOTED}:
        gaps.append("canary_not_running_or_promoted")
    if snapshot.stage_observations < plan.min_observations_per_stage:
        gaps.append("minimum_current_stage_matured_observations_not_reached")

    threshold = 1.0 / plan.ramp_alpha
    harm_count = len(plan.metrics) + sum(
        int(metric.absolute_min is not None) + int(metric.absolute_max is not None)
        for metric in plan.metrics
    )
    harm_threshold = harm_count / plan.rollback_family_alpha
    evidence_by_name = {item.name: item for item in snapshot.metric_evidence}
    for metric in plan.metrics:
        evidence = evidence_by_name.get(metric.name)
        if evidence is None:
            gaps.append(f"{metric.name}:missing_metric_evidence")
            continue
        if evidence.relative_noninferiority_e < threshold:
            gaps.append(f"{metric.name}:relative_noninferiority_not_established")
        if evidence.relative_harm_max_e >= harm_threshold:
            gaps.append(f"{metric.name}:relative_harm_detected")
        if (
            evidence.absolute_min_safe_e is not None
            and evidence.absolute_min_safe_e < threshold
        ):
            gaps.append(f"{metric.name}:absolute_min_safety_not_established")
        if (
            evidence.absolute_min_violation_e is not None
            and evidence.absolute_min_violation_e >= harm_threshold
        ):
            gaps.append(f"{metric.name}:absolute_min_violation_detected")
        if (
            evidence.absolute_max_safe_e is not None
            and evidence.absolute_max_safe_e < threshold
        ):
            gaps.append(f"{metric.name}:absolute_max_safety_not_established")
        if (
            evidence.absolute_max_violation_e is not None
            and evidence.absolute_max_violation_e >= harm_threshold
        ):
            gaps.append(f"{metric.name}:absolute_max_violation_detected")

    if (
        plan.max_challenger_cumulative_cost is not None
        and snapshot.cumulative_challenger_cost
        > plan.max_challenger_cumulative_cost + 1e-12
    ):
        gaps.append("challenger_cumulative_cost_cap_exceeded")
    return not gaps, tuple(gaps)


def emit_online_safety_evidence(
    *,
    monitor: HighPowerOnlineCanaryMonitor,
    subject: PromotionSubject,
    spec: OnlineAuthorityEvidenceSpec,
    transition: PromotionTransition,
) -> AuthorityEvidence:
    plan = monitor.high_power_plan
    _assert_subject_plan(subject, plan)
    _assert_spec_plan(spec, plan)
    if transition not in {
        PromotionTransition.ADVANCE_STAGE,
        PromotionTransition.FINAL_PROMOTION,
    }:
        raise ValueError("online safety authority may only scope stage advance or final promotion")

    final_stage = monitor.stage_index == len(plan.base_plan.stages) - 1
    if transition is PromotionTransition.ADVANCE_STAGE and final_stage:
        raise ValueError("cannot emit stage-advance safety authority from final stage")
    if transition is PromotionTransition.FINAL_PROMOTION and not final_stage:
        raise ValueError("final-promotion safety authority requires final rollout stage")

    safe, reasons = _safety_is_established(monitor)
    if not safe:
        raise ValueError("online safety is not established: " + ",".join(reasons))
    snapshot = monitor.snapshot()
    artifact_fingerprint = _fingerprint(
        {
            "schema": "growthevo.online-safety-authority-artifact.v1",
            "plan_fingerprint": plan.fingerprint,
            "transition": transition.value,
            "stage_index": snapshot.stage_index,
            "traffic_fraction": snapshot.traffic_fraction,
            "total_observations": snapshot.total_observations,
            "stage_observations": snapshot.stage_observations,
            "challenger_observations": snapshot.challenger_observations,
            "cumulative_challenger_cost": snapshot.cumulative_challenger_cost,
            "metric_evidence": [asdict(item) for item in snapshot.metric_evidence],
        },
        digest_size=32,
    )
    return AuthorityEvidence(
        authority_id="online_safety",
        evidence_type=spec.safety_contract.evidence_type,
        producer=spec.safety_producer,
        subject_fingerprint=subject.fingerprint,
        protocol_fingerprint=spec.safety_protocol_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        verdict=AuthorityVerdict.SATISFIED,
        authorized_transitions=(transition,),
        evidence_epoch=snapshot.total_observations,
        source_chain_head=artifact_fingerprint,
        details_fingerprint=artifact_fingerprint,
    )


def emit_primary_success_evidence(
    *,
    monitor: HighPowerOnlineCanaryMonitor,
    subject: PromotionSubject,
    spec: OnlineAuthorityEvidenceSpec,
) -> AuthorityEvidence:
    plan = monitor.high_power_plan
    _assert_subject_plan(subject, plan)
    _assert_spec_plan(spec, plan)
    if monitor.stage_index != len(plan.base_plan.stages) - 1:
        raise ValueError("primary-success authority requires final rollout stage")
    evidence = monitor.primary_group_sequential.evidence()
    if not evidence.looks or not evidence.success or not evidence.looks[-1].success:
        raise ValueError("latest planned group-sequential primary look did not establish success")
    snapshot = monitor.snapshot()
    if snapshot.status not in {CanaryStatus.RUNNING, CanaryStatus.PROMOTED}:
        raise ValueError("primary-success authority requires a live or promoted canary state")
    artifact_fingerprint = _fingerprint(
        {
            "schema": "growthevo.primary-success-authority-artifact.v1",
            "plan_fingerprint": plan.fingerprint,
            "stage_index": snapshot.stage_index,
            "total_observations": snapshot.total_observations,
            "group_sequential_evidence": asdict(evidence),
        },
        digest_size=32,
    )
    return AuthorityEvidence(
        authority_id="primary_success",
        evidence_type=spec.success_contract.evidence_type,
        producer=spec.success_producer,
        subject_fingerprint=subject.fingerprint,
        protocol_fingerprint=spec.success_protocol_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        verdict=AuthorityVerdict.SATISFIED,
        authorized_transitions=(PromotionTransition.FINAL_PROMOTION,),
        evidence_epoch=snapshot.total_observations,
        source_chain_head=artifact_fingerprint,
        details_fingerprint=artifact_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class ProductionAuthorityProfile:
    """Deployable strict authority composition for the governed canary."""

    profile_id: str
    offline_causal_contracts: tuple[EvidenceContract, ...]
    integrity_contracts: tuple[EvidenceContract, ...]
    maturity_contracts: tuple[EvidenceContract, ...]
    supply_chain_contracts: tuple[EvidenceContract, ...]
    online_spec: OnlineAuthorityEvidenceSpec
    minimum_offline_epoch: int = 0
    minimum_integrity_epoch: int = 0
    minimum_maturity_epoch: int = 0
    minimum_supply_chain_epoch: int = 0

    def __post_init__(self) -> None:
        _nonempty(self.profile_id, "profile_id")
        for name, values in (
            ("offline_causal_contracts", self.offline_causal_contracts),
            ("integrity_contracts", self.integrity_contracts),
            ("maturity_contracts", self.maturity_contracts),
            ("supply_chain_contracts", self.supply_chain_contracts),
        ):
            if not values:
                raise ValueError(f"{name} cannot be empty")
            fps = [item.fingerprint for item in values]
            if len(set(fps)) != len(fps):
                raise ValueError(f"{name} must contain unique exact contracts")
        for name, value in (
            ("minimum_offline_epoch", self.minimum_offline_epoch),
            ("minimum_integrity_epoch", self.minimum_integrity_epoch),
            ("minimum_maturity_epoch", self.minimum_maturity_epoch),
            ("minimum_supply_chain_epoch", self.minimum_supply_chain_epoch),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def from_reference_evidence(
        cls,
        *,
        profile_id: str,
        plan: HighPowerCanaryPlan,
        offline_causal: Sequence[AuthorityEvidence],
        integrity: Sequence[AuthorityEvidence],
        maturity: Sequence[AuthorityEvidence],
        supply_chain: Sequence[AuthorityEvidence],
        safety_producer: str = "growthevo.online-safety-monitor.v1",
        success_producer: str = "growthevo.group-sequential-primary.v1",
    ) -> "ProductionAuthorityProfile":
        def contracts(values: Sequence[AuthorityEvidence], authority_id: str) -> tuple[EvidenceContract, ...]:
            if not values:
                raise ValueError(f"reference evidence for {authority_id} cannot be empty")
            result: list[EvidenceContract] = []
            for evidence in values:
                if evidence.authority_id != authority_id:
                    raise ValueError(f"reference evidence must use authority_id={authority_id}")
                result.append(EvidenceContract.from_evidence(evidence))
            return tuple(result)

        return cls(
            profile_id=profile_id,
            offline_causal_contracts=contracts(offline_causal, "offline_causal"),
            integrity_contracts=contracts(integrity, "integrity"),
            maturity_contracts=contracts(maturity, "maturity"),
            supply_chain_contracts=contracts(supply_chain, "supply_chain"),
            online_spec=OnlineAuthorityEvidenceSpec.from_plan(
                plan,
                safety_producer=safety_producer,
                success_producer=success_producer,
            ),
        )

    def compile_policy(self, plan: HighPowerCanaryPlan) -> StrictPromotionEvidencePolicy:
        if self.online_spec.plan_fingerprint != plan.fingerprint:
            raise ValueError("production authority profile is bound to another canary plan")

        offline = StrictAuthorityRequirement(
            "offline_causal",
            self.offline_causal_contracts,
            self.minimum_offline_epoch,
        )
        integrity = StrictAuthorityRequirement(
            "integrity",
            self.integrity_contracts,
            self.minimum_integrity_epoch,
        )
        maturity = StrictAuthorityRequirement(
            "maturity",
            self.maturity_contracts,
            self.minimum_maturity_epoch,
        )
        supply_chain = StrictAuthorityRequirement(
            "supply_chain",
            self.supply_chain_contracts,
            self.minimum_supply_chain_epoch,
        )
        online_safety = StrictAuthorityRequirement(
            "online_safety",
            (self.online_spec.safety_contract,),
        )
        primary_success = StrictAuthorityRequirement(
            "primary_success",
            (self.online_spec.success_contract,),
        )

        return StrictPromotionEvidencePolicy(
            policy_id=self.profile_id,
            transitions=(
                StrictTransitionPolicy(
                    PromotionTransition.ENTER_CANARY,
                    (offline, integrity, supply_chain),
                ),
                StrictTransitionPolicy(
                    PromotionTransition.ADVANCE_STAGE,
                    (integrity, maturity, online_safety, supply_chain),
                ),
                StrictTransitionPolicy(
                    PromotionTransition.FINAL_PROMOTION,
                    (
                        offline,
                        integrity,
                        maturity,
                        online_safety,
                        primary_success,
                        supply_chain,
                    ),
                ),
            ),
            veto_authorities=("integrity", "online_safety"),
            sticky_block_authorities=("integrity",),
        )

    def gate(
        self,
        *,
        plan: HighPowerCanaryPlan,
        ledger: PromotionEvidenceLedger,
    ) -> StrictPromotionManifestGate:
        return StrictPromotionManifestGate(
            ledger=ledger,
            policy=self.compile_policy(plan),
            expected_plan_fingerprint=plan.fingerprint,
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.production-authority-profile.v1",
                "profile_id": self.profile_id,
                "offline_causal_contracts": [asdict(item) for item in self.offline_causal_contracts],
                "integrity_contracts": [asdict(item) for item in self.integrity_contracts],
                "maturity_contracts": [asdict(item) for item in self.maturity_contracts],
                "supply_chain_contracts": [asdict(item) for item in self.supply_chain_contracts],
                "online_spec": asdict(self.online_spec),
                "online_safety_protocol_fingerprint": self.online_spec.safety_protocol_fingerprint,
                "primary_success_protocol_fingerprint": self.online_spec.success_protocol_fingerprint,
                "minimum_offline_epoch": self.minimum_offline_epoch,
                "minimum_integrity_epoch": self.minimum_integrity_epoch,
                "minimum_maturity_epoch": self.minimum_maturity_epoch,
                "minimum_supply_chain_epoch": self.minimum_supply_chain_epoch,
                "supply_chain_semantics": "exact_contract_or",
                "transition_semantics": "all_authorities_required",
            }
        )
