from __future__ import annotations

import pytest

from growthevo.evolution.online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryMetricSpec,
    CanaryPlan,
    CanaryStatus,
)
from growthevo.evolution.promotion_governance import (
    GovernedHighPowerOnlinePromotionController,
    PromotionManifestGate,
)
from growthevo.evolution.promotion_manifest import (
    AuthorityEvidence,
    AuthorityRequirement,
    AuthorityVerdict,
    PromotionEvidenceLedger,
    PromotionEvidencePolicy,
    PromotionSubject,
    PromotionTransition,
    TransitionPolicy,
)
from growthevo.evolution.sequential_causal import (
    GroupSequentialSpec,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
)


def _candidate() -> CanaryCandidate:
    return CanaryCandidate(
        name="governed-candidate",
        provider="openai",
        model="pinned-model-snapshot",
        contract_fingerprint="contract-fp",
        source_commit_sha="deadbeef",
        source_test_fingerprint="holdout-fp",
        source_evidence_manifest_fingerprint="offline-evidence-fp",
        promotion_artifact_fingerprint="promotion-artifact-fp",
    )


def _plan() -> HighPowerCanaryPlan:
    candidate = _candidate()
    base = CanaryPlan(
        experiment_id="governed-exp",
        candidate_name=candidate.name,
        candidate_contract_fingerprint=candidate.contract_fingerprint,
        source_artifact_fingerprint=candidate.promotion_artifact_fingerprint,
        metrics=(
            CanaryMetricSpec(
                name="incremental_value",
                outcome_min=0.0,
                outcome_max=1.0,
                higher_is_better=True,
                noninferiority_margin=0.10,
            ),
        ),
        primary_metric="incremental_value",
        stages=(0.5, 1.0),
        challenger_probability=0.5,
        min_observations_per_stage=4,
        primary_min_improvement=0.05,
        ramp_alpha=0.50,
        promotion_alpha=0.20,
        rollback_family_alpha=0.05,
    )
    return HighPowerCanaryPlan(
        base_plan=base,
        group_sequential=GroupSequentialSpec(
            expected_final_stage_observations=20,
            look_fractions=(1.0,),
            alpha=0.20,
            spending="equal",
            min_arm_observations=2,
        ),
        analysis_unit_name="user",
    )


def _subject(plan: HighPowerCanaryPlan | None = None, **overrides: str) -> PromotionSubject:
    value = plan or _plan()
    candidate = _candidate()
    values = {
        "experiment_id": value.base_plan.experiment_id,
        "candidate_name": candidate.name,
        "candidate_contract_fingerprint": candidate.contract_fingerprint,
        "promotion_artifact_fingerprint": candidate.promotion_artifact_fingerprint,
        "plan_fingerprint": value.fingerprint,
        "commit_sha": candidate.source_commit_sha,
    }
    values.update(overrides)
    return PromotionSubject(**values)


def _requirement(authority_id: str) -> AuthorityRequirement:
    return AuthorityRequirement(
        authority_id=authority_id,
        allowed_evidence_types=(f"{authority_id}.v1",),
        allowed_protocol_fingerprints=(f"{authority_id}-protocol-v1",),
        allowed_producers=(f"{authority_id}-producer",),
    )


def _policy() -> PromotionEvidencePolicy:
    return PromotionEvidencePolicy(
        policy_id="governed-production-v1",
        transitions=(
            TransitionPolicy(
                transition=PromotionTransition.ENTER_CANARY,
                requirements=(
                    _requirement("offline_causal"),
                    _requirement("integrity"),
                ),
            ),
            TransitionPolicy(
                transition=PromotionTransition.ADVANCE_STAGE,
                requirements=(
                    _requirement("integrity"),
                    _requirement("online_safety"),
                ),
            ),
            TransitionPolicy(
                transition=PromotionTransition.FINAL_PROMOTION,
                requirements=(
                    _requirement("offline_causal"),
                    _requirement("integrity"),
                    _requirement("online_safety"),
                    _requirement("primary_success"),
                    _requirement("supply_chain"),
                ),
            ),
        ),
        veto_authorities=("integrity", "online_safety"),
        sticky_block_authorities=("integrity",),
    )


def _evidence(
    subject: PromotionSubject,
    authority_id: str,
    transitions: tuple[PromotionTransition, ...],
    *,
    epoch: int = 1,
    verdict: AuthorityVerdict = AuthorityVerdict.SATISFIED,
) -> AuthorityEvidence:
    return AuthorityEvidence(
        authority_id=authority_id,
        evidence_type=f"{authority_id}.v1",
        producer=f"{authority_id}-producer",
        subject_fingerprint=subject.fingerprint,
        protocol_fingerprint=f"{authority_id}-protocol-v1",
        artifact_fingerprint=f"{authority_id}-artifact-{epoch}",
        verdict=verdict,
        authorized_transitions=transitions,
        evidence_epoch=epoch,
        source_chain_head=f"{authority_id}-chain-{epoch}",
        details_fingerprint=f"{authority_id}-details-{epoch}",
    )


def _ledger(plan: HighPowerCanaryPlan | None = None) -> PromotionEvidenceLedger:
    return PromotionEvidenceLedger(_subject(plan))


def _gate(plan: HighPowerCanaryPlan, ledger: PromotionEvidenceLedger) -> PromotionManifestGate:
    return PromotionManifestGate(
        ledger=ledger,
        policy=_policy(),
        expected_plan_fingerprint=plan.fingerprint,
    )


def _controller(
    plan: HighPowerCanaryPlan,
    ledger: PromotionEvidenceLedger,
) -> GovernedHighPowerOnlinePromotionController:
    return GovernedHighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
        gate=_gate(plan, ledger),
    )


def _append_start_authorities(ledger: PromotionEvidenceLedger) -> None:
    subject = ledger.subject
    ledger.append(
        _evidence(
            subject,
            "offline_causal",
            (PromotionTransition.ENTER_CANARY, PromotionTransition.FINAL_PROMOTION),
        )
    )
    ledger.append(
        _evidence(
            subject,
            "integrity",
            (
                PromotionTransition.ENTER_CANARY,
                PromotionTransition.ADVANCE_STAGE,
                PromotionTransition.FINAL_PROMOTION,
            ),
        )
    )


def _append_online_safety(ledger: PromotionEvidenceLedger, *, epoch: int = 1) -> None:
    ledger.append(
        _evidence(
            ledger.subject,
            "online_safety",
            (PromotionTransition.ADVANCE_STAGE, PromotionTransition.FINAL_PROMOTION),
            epoch=epoch,
        )
    )


def _observation(ticket, *, challenger_value: float = 1.0, control_value: float = 0.0):
    value = challenger_value if ticket.assigned_to_challenger else control_value
    return HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"incremental_value": value},
    )


def _drive_until(controller, predicate, *, prefix: str, limit: int = 5000):
    last = None
    for index in range(limit):
        ticket = controller.enroll(f"{prefix}-{index}")
        if not ticket.in_canary:
            continue
        last = controller.observe(_observation(ticket))
        if predicate(last):
            return last
    raise AssertionError(f"condition not reached; last={last}")


def test_enter_canary_is_blocked_until_manifest_authorizes() -> None:
    plan = _plan()
    ledger = _ledger(plan)
    controller = _controller(plan, ledger)

    blocked = controller.start()
    assert blocked.decision is CanaryDecision.HOLD
    assert blocked.status is CanaryStatus.REGISTERED
    assert "promotion_authority_blocked:enter_canary" in blocked.reasons
    with pytest.raises(RuntimeError, match="running canary"):
        controller.enroll("must-not-expose")

    _append_start_authorities(ledger)
    started = controller.start()
    assert started.status is CanaryStatus.RUNNING
    assert controller.monitor.pending_transition is None
    assert controller.verify_audit_chain() is True


def test_stage_advance_waits_for_authority_and_needs_no_new_outcome_after_evidence_arrives() -> None:
    plan = _plan()
    ledger = _ledger(plan)
    _append_start_authorities(ledger)
    controller = _controller(plan, ledger)
    controller.start()

    blocked = _drive_until(
        controller,
        lambda snapshot: "promotion_authority_blocked:advance_stage" in snapshot.reasons,
        prefix="stage0",
    )
    assert blocked.decision is CanaryDecision.HOLD
    assert controller.monitor.stage_index == 0
    observations_before = blocked.total_observations

    _append_online_safety(ledger)
    advanced = controller.reevaluate_authority()
    assert advanced.decision is CanaryDecision.ADVANCE
    assert advanced.stage_index == 1
    assert advanced.total_observations == observations_before
    assert controller.monitor.stage_index == 1


def test_final_promotion_waits_for_manifest_then_promotes_without_more_peeking() -> None:
    plan = _plan()
    ledger = _ledger(plan)
    _append_start_authorities(ledger)
    _append_online_safety(ledger)
    controller = _controller(plan, ledger)
    controller.start()

    _drive_until(
        controller,
        lambda snapshot: snapshot.decision is CanaryDecision.ADVANCE,
        prefix="advance",
    )
    assert controller.monitor.stage_index == 1

    blocked = _drive_until(
        controller,
        lambda snapshot: "promotion_authority_blocked:final_promotion" in snapshot.reasons,
        prefix="final",
    )
    assert blocked.decision is CanaryDecision.HOLD
    assert controller.monitor.pending_transition is PromotionTransition.FINAL_PROMOTION
    assert controller.champion_name == "deterministic-baseline"
    observations_before = blocked.total_observations

    ticket = controller.enroll("extra-after-final-look")
    if ticket.in_canary:
        with pytest.raises(RuntimeError, match="reevaluate authority"):
            controller.observe(_observation(ticket))

    ledger.append(
        _evidence(
            ledger.subject,
            "primary_success",
            (PromotionTransition.FINAL_PROMOTION,),
        )
    )
    ledger.append(
        _evidence(
            ledger.subject,
            "supply_chain",
            (PromotionTransition.FINAL_PROMOTION,),
        )
    )
    promoted = controller.reevaluate_authority()
    assert promoted.decision is CanaryDecision.PROMOTE
    assert promoted.total_observations == observations_before
    assert controller.champion_name == "governed-candidate"
    assert controller.monitor.status is CanaryStatus.PROMOTED
    assert controller.verify_audit_chain() is True


def test_safety_rollback_is_never_blocked_by_governance() -> None:
    plan = _plan()
    ledger = _ledger(plan)
    _append_start_authorities(ledger)
    _append_online_safety(ledger)
    controller = _controller(plan, ledger)
    controller.start()

    last = None
    for index in range(10000):
        ticket = controller.enroll(f"harm-{index}")
        if not ticket.in_canary:
            continue
        last = controller.observe(
            _observation(ticket, challenger_value=0.0, control_value=1.0)
        )
        if last.decision is CanaryDecision.ROLLBACK:
            break
    assert last is not None
    assert last.decision is CanaryDecision.ROLLBACK
    assert controller.monitor.status is CanaryStatus.ROLLED_BACK
    assert controller.champion_name == "deterministic-baseline"


def test_governance_controller_rejects_cross_subject_or_wrong_plan_binding() -> None:
    plan = _plan()
    wrong_subject = _subject(plan, candidate_name="different-candidate")
    wrong_ledger = PromotionEvidenceLedger(wrong_subject)
    gate = PromotionManifestGate(
        ledger=wrong_ledger,
        policy=_policy(),
        expected_plan_fingerprint=plan.fingerprint,
    )
    with pytest.raises(ValueError, match="subject does not match controller identity"):
        GovernedHighPowerOnlinePromotionController(
            champion_name="baseline",
            candidate=_candidate(),
            plan=plan,
            gate=gate,
        )

    ledger = _ledger(plan)
    with pytest.raises(ValueError, match="different online plan"):
        PromotionManifestGate(
            ledger=ledger,
            policy=_policy(),
            expected_plan_fingerprint="wrong-plan",
        )


def test_authority_audit_contains_only_aggregate_fingerprints_and_reasons() -> None:
    plan = _plan()
    ledger = _ledger(plan)
    controller = _controller(plan, ledger)
    controller.start()

    authority_events = [
        event for event in controller.events() if event.kind == "promotion_authority_evaluated"
    ]
    assert authority_events
    payload = authority_events[-1].payload
    assert payload["transition"] == PromotionTransition.ENTER_CANARY.value
    assert payload["authorized"] is False
    assert "manifest_fingerprint" in payload
    assert "analysis_unit_id" not in str(payload)
    assert "metrics" not in str(payload)
    assert controller.verify_audit_chain() is True
