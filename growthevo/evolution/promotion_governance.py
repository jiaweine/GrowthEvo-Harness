from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import blake2b
import json

from .online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanarySnapshot,
    CanaryStatus,
)
from .promotion_manifest import (
    ManifestReason,
    PromotionEvidenceLedger,
    PromotionEvidencePolicy,
    PromotionTransition,
)
from .sequential_causal import (
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
    HighPowerOnlineCanaryMonitor,
    HighPowerOnlinePromotionController,
)


def _fingerprint(payload: object, *, digest_size: int = 20) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return blake2b(encoded, digest_size=digest_size).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernanceAuthorizationRecord:
    transition: PromotionTransition
    authorized: bool
    reasons: tuple[str, ...]
    manifest_fingerprint: str
    policy_fingerprint: str
    subject_fingerprint: str
    ledger_head_hash: str
    ledger_event_count: int

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.governance-authorization-record.v1",
                "transition": self.transition.value,
                "authorized": self.authorized,
                "reasons": list(self.reasons),
                "manifest_fingerprint": self.manifest_fingerprint,
                "policy_fingerprint": self.policy_fingerprint,
                "subject_fingerprint": self.subject_fingerprint,
                "ledger_head_hash": self.ledger_head_hash,
                "ledger_event_count": self.ledger_event_count,
            },
            digest_size=32,
        )


class PromotionManifestGate:
    """Read-only transition gate backed by the Phase-14 evidence ledger.

    The gate never manufactures authority. It builds a manifest from the current
    append-only ledger and evaluates that exact ledger head under one frozen policy.
    """

    def __init__(
        self,
        *,
        ledger: PromotionEvidenceLedger,
        policy: PromotionEvidencePolicy,
        expected_plan_fingerprint: str,
    ) -> None:
        if not expected_plan_fingerprint.strip():
            raise ValueError("expected_plan_fingerprint cannot be empty")
        if ledger.subject.plan_fingerprint != expected_plan_fingerprint:
            raise ValueError("promotion subject is bound to a different online plan")
        self.ledger = ledger
        self.policy = policy
        self.expected_plan_fingerprint = expected_plan_fingerprint

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.promotion-manifest-gate.v1",
                "subject_fingerprint": self.ledger.subject.fingerprint,
                "policy_fingerprint": self.policy.fingerprint,
                "expected_plan_fingerprint": self.expected_plan_fingerprint,
                "default": "fail_closed",
            }
        )

    def evaluate(self, transition: PromotionTransition) -> GovernanceAuthorizationRecord:
        # Configuration errors remain errors; runtime evidence failures become a
        # blocked record rather than accidentally opening the gate.
        self.policy.transition_policy(transition)
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
        manifest = self.ledger.build_manifest(
            policy=self.policy,
            transition=transition,
        )
        evaluation = self.ledger.evaluate(manifest=manifest, policy=self.policy)
        return GovernanceAuthorizationRecord(
            transition=transition,
            authorized=evaluation.authorized,
            reasons=evaluation.reasons,
            manifest_fingerprint=evaluation.manifest_fingerprint,
            policy_fingerprint=self.policy.fingerprint,
            subject_fingerprint=evaluation.subject_fingerprint,
            ledger_head_hash=evaluation.ledger_head_hash,
            ledger_event_count=len(self.ledger.events),
        )


class GovernedHighPowerOnlineCanaryMonitor(HighPowerOnlineCanaryMonitor):
    """High-power monitor whose state transitions require fresh authority manifests.

    Rollback is intentionally never gated: a safety failure must be able to stop
    exposure immediately. ENTER_CANARY, ADVANCE_STAGE, and FINAL_PROMOTION are gated.
    """

    def __init__(self, plan: HighPowerCanaryPlan, gate: PromotionManifestGate) -> None:
        super().__init__(plan)
        self.gate = gate
        self._pending_transition: PromotionTransition | None = None
        self._authorization_records: list[GovernanceAuthorizationRecord] = []

    @property
    def pending_transition(self) -> PromotionTransition | None:
        return self._pending_transition

    @property
    def authorization_records(self) -> tuple[GovernanceAuthorizationRecord, ...]:
        return tuple(self._authorization_records)

    def _evaluate_authority(
        self,
        transition: PromotionTransition,
    ) -> GovernanceAuthorizationRecord:
        if (
            self._pending_transition is transition
            and self._authorization_records
            and self._authorization_records[-1].transition is transition
            and self._authorization_records[-1].ledger_head_hash == self.gate.ledger.head_hash
        ):
            return self._authorization_records[-1]
        record = self.gate.evaluate(transition)
        self._authorization_records.append(record)
        self._pending_transition = None if record.authorized else transition
        return record

    def _authority_hold(
        self,
        transition: PromotionTransition,
        record: GovernanceAuthorizationRecord,
    ) -> CanarySnapshot:
        return self.snapshot(
            CanaryDecision.HOLD,
            (
                f"promotion_authority_blocked:{transition.value}",
                *(f"authority:{reason}" for reason in record.reasons),
            ),
        )

    def start(self) -> CanarySnapshot:
        if self.status is not CanaryStatus.REGISTERED:
            raise RuntimeError("canary can only be started once")
        record = self._evaluate_authority(PromotionTransition.ENTER_CANARY)
        if not record.authorized:
            return self._authority_hold(PromotionTransition.ENTER_CANARY, record)
        return super().start()

    def reevaluate_authority(self) -> CanarySnapshot:
        """Re-check a pending authority transition without ingesting new outcomes."""

        transition = self._pending_transition
        if transition is None:
            return self.snapshot(CanaryDecision.HOLD, ("no_pending_promotion_transition",))

        if transition is PromotionTransition.ENTER_CANARY:
            if self.status is not CanaryStatus.REGISTERED:
                raise RuntimeError("pending enter-canary authority has invalid monitor status")
            # Force a new lookup only when the ledger changed. _evaluate_authority
            # handles same-head idempotence.
            record = self._evaluate_authority(transition)
            if not record.authorized:
                return self._authority_hold(transition, record)
            return super().start()

        if self.status is not CanaryStatus.RUNNING:
            raise RuntimeError("pending rollout authority requires RUNNING status")

        rollback_reasons = self._rollback_reasons()
        if rollback_reasons:
            self._pending_transition = None
            self.status = CanaryStatus.ROLLED_BACK
            return self.snapshot(CanaryDecision.ROLLBACK, tuple(rollback_reasons))

        if transition is PromotionTransition.ADVANCE_STAGE:
            if self.stage_index >= len(self.plan.stages) - 1:
                raise RuntimeError("pending stage advance cannot target the final stage")
            if self._stage_matured_counts[self.stage_index] < self.plan.min_observations_per_stage:
                return self.snapshot(
                    CanaryDecision.HOLD,
                    ("minimum_current_stage_matured_observations_not_reached",),
                )
            safe, reasons = self._safe_to_ramp()
            if not safe:
                self._pending_transition = None
                return self.snapshot(CanaryDecision.HOLD, reasons)
            record = self._evaluate_authority(transition)
            if not record.authorized:
                return self._authority_hold(transition, record)
            self.stage_index += 1
            return self.snapshot(
                CanaryDecision.ADVANCE,
                ("stage_safety_and_promotion_authority_established",),
            )

        if transition is PromotionTransition.FINAL_PROMOTION:
            if self.stage_index != len(self.plan.stages) - 1:
                raise RuntimeError("final-promotion authority is pending before final rollout stage")
            primary = self.primary_group_sequential.evidence()
            safe, reasons = self._safe_to_ramp()
            if not primary.success:
                self._pending_transition = None
                return self.snapshot(
                    CanaryDecision.HOLD,
                    ("planned_group_sequential_primary_gate_not_currently_passed",),
                )
            if not safe:
                self._pending_transition = None
                return self.snapshot(CanaryDecision.HOLD, reasons)
            record = self._evaluate_authority(transition)
            if not record.authorized:
                return self._authority_hold(transition, record)
            self.status = CanaryStatus.PROMOTED
            return self.snapshot(
                CanaryDecision.PROMOTE,
                ("statistical_and_promotion_authority_gates_passed",),
            )

        raise RuntimeError("unsupported pending promotion transition")

    def observe(self, observation: HighPowerCanaryObservation) -> CanarySnapshot:
        if self.status is not CanaryStatus.RUNNING:
            raise RuntimeError("canary observations require RUNNING status")
        if (
            self._pending_transition is PromotionTransition.FINAL_PROMOTION
            and self.primary_group_sequential.evidence().next_target is None
        ):
            raise RuntimeError(
                "final statistical analysis is complete; reevaluate authority instead of ingesting more outcomes"
            )
        if observation.routing_stage_index >= len(self.plan.stages):
            raise ValueError("routing_stage_index is outside pre-registered stages")
        if observation.routing_stage_index > self.stage_index:
            raise ValueError("outcome cannot arrive from a future rollout stage")
        unit_token = self._unit_token(observation.analysis_unit_id)
        if unit_token in self._seen_unit_tokens:
            raise ValueError("analysis_unit_id has already been observed")
        if abs(observation.assignment_probability - self.plan.challenger_probability) > 1e-12:
            raise ValueError("observation assignment probability differs from canary plan")
        expected_traffic = self.plan.stages[observation.routing_stage_index]
        if abs(observation.traffic_fraction - expected_traffic) > 1e-12:
            raise ValueError("observation traffic fraction differs from routing stage")
        observation = self._preflight_observation(observation)

        self._seen_unit_tokens.add(unit_token)
        self._total_observations += 1
        self._stage_matured_counts[observation.routing_stage_index] += 1
        if observation.assigned_to_challenger:
            self._challenger_observations += 1
            if self.plan.cumulative_cost_metric is not None:
                self._cumulative_challenger_cost += float(
                    observation.metrics[self.plan.cumulative_cost_metric]
                )

        base_observation = observation.as_base_observation()
        for monitor in self._monitors.values():
            monitor.update(
                base_observation,
                plan=self.plan,
                update_superiority=False,
            )

        final_stage_index = len(self.plan.stages) - 1
        previous_looks = len(self.primary_group_sequential.evidence().looks)
        if observation.routing_stage_index == final_stage_index:
            self.primary_group_sequential.observe(observation)
        primary = self.primary_group_sequential.evidence()
        new_primary_look = len(primary.looks) > previous_looks

        rollback_reasons = self._rollback_reasons()
        if rollback_reasons:
            self._pending_transition = None
            self.status = CanaryStatus.ROLLED_BACK
            return self.snapshot(CanaryDecision.ROLLBACK, tuple(rollback_reasons))

        if self._stage_matured_counts[self.stage_index] < self.plan.min_observations_per_stage:
            return self.snapshot(
                CanaryDecision.HOLD,
                ("minimum_current_stage_matured_observations_not_reached",),
            )

        if self.stage_index == final_stage_index:
            safe, reasons = self._safe_to_ramp()
            if new_primary_look and not primary.success:
                self._pending_transition = None
            if new_primary_look and primary.success and safe:
                record = self._evaluate_authority(PromotionTransition.FINAL_PROMOTION)
                if record.authorized:
                    self.status = CanaryStatus.PROMOTED
                    return self.snapshot(
                        CanaryDecision.PROMOTE,
                        ("statistical_and_promotion_authority_gates_passed",),
                    )
                return self._authority_hold(PromotionTransition.FINAL_PROMOTION, record)
            if primary.exhausted:
                self._pending_transition = None
                self.status = CanaryStatus.ROLLED_BACK
                return self.snapshot(
                    CanaryDecision.ROLLBACK,
                    ("group_sequential_primary_exhausted_without_superiority",),
                )
            if primary.next_target is None:
                self._pending_transition = None
                self.status = CanaryStatus.ROLLED_BACK
                return self.snapshot(
                    CanaryDecision.ROLLBACK,
                    ("group_sequential_final_safety_gates_not_established", *reasons),
                )
            if not safe:
                self._pending_transition = None
                return self.snapshot(CanaryDecision.HOLD, reasons)
            return self.snapshot(
                CanaryDecision.HOLD,
                ("waiting_for_planned_group_sequential_primary_look",),
            )

        safe, reasons = self._safe_to_ramp()
        if not safe:
            if self._pending_transition is PromotionTransition.ADVANCE_STAGE:
                self._pending_transition = None
            return self.snapshot(CanaryDecision.HOLD, reasons)
        record = self._evaluate_authority(PromotionTransition.ADVANCE_STAGE)
        if not record.authorized:
            return self._authority_hold(PromotionTransition.ADVANCE_STAGE, record)
        self.stage_index += 1
        return self.snapshot(
            CanaryDecision.ADVANCE,
            ("stage_safety_and_promotion_authority_established",),
        )


class GovernedHighPowerOnlinePromotionController(HighPowerOnlinePromotionController):
    """Opt-in production controller with Phase-14 authority before every ramp."""

    def __init__(
        self,
        *,
        champion_name: str,
        candidate: CanaryCandidate,
        plan: HighPowerCanaryPlan,
        gate: PromotionManifestGate,
    ) -> None:
        subject = gate.ledger.subject
        if gate.expected_plan_fingerprint != plan.fingerprint:
            raise ValueError("governance gate must bind the exact high-power canary plan")
        expected = {
            "experiment_id": plan.base_plan.experiment_id,
            "candidate_name": candidate.name,
            "candidate_contract_fingerprint": candidate.contract_fingerprint,
            "promotion_artifact_fingerprint": candidate.promotion_artifact_fingerprint,
            "plan_fingerprint": plan.fingerprint,
            "commit_sha": candidate.source_commit_sha,
        }
        actual = {
            "experiment_id": subject.experiment_id,
            "candidate_name": subject.candidate_name,
            "candidate_contract_fingerprint": subject.candidate_contract_fingerprint,
            "promotion_artifact_fingerprint": subject.promotion_artifact_fingerprint,
            "plan_fingerprint": subject.plan_fingerprint,
            "commit_sha": subject.commit_sha,
        }
        if actual != expected:
            raise ValueError("promotion governance subject does not match controller identity")

        super().__init__(
            champion_name=champion_name,
            candidate=candidate,
            plan=plan,
        )
        self.governance_gate = gate
        self.monitor = GovernedHighPowerOnlineCanaryMonitor(plan, gate)
        self._append(
            "promotion_governance_registered",
            {
                "governance_gate_fingerprint": gate.fingerprint,
                "promotion_subject_fingerprint": subject.fingerprint,
                "promotion_policy_fingerprint": gate.policy.fingerprint,
                "evidence_ledger_head": gate.ledger.head_hash,
            },
        )

    def _append_authorization_records(self, start_index: int) -> None:
        for record in self.monitor.authorization_records[start_index:]:
            self._append(
                "promotion_authority_evaluated",
                {
                    "transition": record.transition.value,
                    "authorized": record.authorized,
                    "reasons": list(record.reasons),
                    "manifest_fingerprint": record.manifest_fingerprint,
                    "policy_fingerprint": record.policy_fingerprint,
                    "subject_fingerprint": record.subject_fingerprint,
                    "ledger_head_hash": record.ledger_head_hash,
                    "ledger_event_count": record.ledger_event_count,
                    "authorization_record_fingerprint": record.fingerprint,
                },
            )

    def start(self) -> CanarySnapshot:
        before = len(self.monitor.authorization_records)
        snapshot = self.monitor.start()
        self._append_authorization_records(before)
        kind = (
            "canary_started"
            if self.monitor.status is CanaryStatus.RUNNING
            else "canary_start_blocked_by_authority"
        )
        self._append(kind, self._high_power_snapshot_payload(snapshot))
        return snapshot

    def observe(self, observation: HighPowerCanaryObservation) -> CanarySnapshot:
        before = len(self.monitor.authorization_records)
        snapshot = super().observe(observation)
        self._append_authorization_records(before)
        return snapshot

    def reevaluate_authority(self) -> CanarySnapshot:
        before = len(self.monitor.authorization_records)
        snapshot = self.monitor.reevaluate_authority()
        self._append_authorization_records(before)
        if snapshot.decision in {
            CanaryDecision.ADVANCE,
            CanaryDecision.ROLLBACK,
            CanaryDecision.PROMOTE,
        }:
            kind = {
                CanaryDecision.ADVANCE: "canary_stage_advanced",
                CanaryDecision.ROLLBACK: "challenger_rolled_back",
                CanaryDecision.PROMOTE: "challenger_promoted",
            }[snapshot.decision]
            self._append(kind, self._high_power_snapshot_payload(snapshot))
        if snapshot.decision is CanaryDecision.PROMOTE:
            self.champion_name = self.candidate.name
        return snapshot
