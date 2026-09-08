from __future__ import annotations

import pytest

from growthevo.evolution.online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryMetricSpec,
    CanaryPlan,
    CanaryStatus,
)
from growthevo.evolution.production_authority import (
    EvidenceContract,
    OnlineAuthorityEvidenceSpec,
    ProductionAuthorityProfile,
    StrictAuthorityRequirement,
    StrictPromotionEvidencePolicy,
    StrictPromotionManifestGate,
    StrictTransitionPolicy,
    emit_online_safety_evidence,
    emit_primary_success_evidence,
)
from growthevo.evolution.promotion_governance import (
    GovernedHighPowerOnlinePromotionController,
)
from growthevo.evolution.promotion_manifest import (
    AuthorityEvidence,
    AuthorityVerdict,
    PromotionEvidenceLedger,
    PromotionSubject,
    PromotionTransition,
)
from growthevo.evolution.sequential_causal import (
    GroupSequentialSpec,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
)


def _candidate() -> CanaryCandidate:
    return CanaryCandidate(
        name="production-candidate",
        provider="openai",
        model="pinned-frontier-model",
        contract_fingerprint="candidate-contract",
        source_commit_sha="deadbeef",
        source_test_fingerprint="locked-holdout",
        source_evidence_manifest_fingerprint="offline-manifest",
        promotion_artifact_fingerprint="promotion-artifact",
    )


def _plan() -> HighPowerCanaryPlan:
    candidate = _candidate()
    base = CanaryPlan(
        experiment_id="production-exp",
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


def _subject(plan: HighPowerCanaryPlan | None = None) -> PromotionSubject:
    value = plan or _plan()
    candidate = _candidate()
    return PromotionSubject(
        experiment_id=value.base_plan.experiment_id,
        candidate_name=candidate.name,
        candidate_contract_fingerprint=candidate.contract_fingerprint,
        promotion_artifact_fingerprint=candidate.promotion_artifact_fingerprint,
        plan_fingerprint=value.fingerprint,
        commit_sha=candidate.source_commit_sha,
    )


def _external(
    subject: PromotionSubject,
    authority_id: str,
    *,
    evidence_type: str,
    protocol: str,
    producer: str,
    transitions: tuple[PromotionTransition, ...],
    epoch: int = 1,
    verdict: AuthorityVerdict = AuthorityVerdict.SATISFIED,
) -> AuthorityEvidence:
    return AuthorityEvidence(
        authority_id=authority_id,
        evidence_type=evidence_type,
        producer=producer,
        subject_fingerprint=subject.fingerprint,
        protocol_fingerprint=protocol,
        artifact_fingerprint=f"{authority_id}-{evidence_type}-{epoch}",
        verdict=verdict,
        authorized_transitions=transitions,
        evidence_epoch=epoch,
        source_chain_head=f"{authority_id}-chain-{epoch}",
        details_fingerprint=f"{authority_id}-details-{epoch}",
    )


def _reference_evidence(subject: PromotionSubject):
    all_transitions = (
        PromotionTransition.ENTER_CANARY,
        PromotionTransition.ADVANCE_STAGE,
        PromotionTransition.FINAL_PROMOTION,
    )
    offline = _external(
        subject,
        "offline_causal",
        evidence_type="locked_causal_holdout.v1",
        protocol="locked-causal-protocol-v1",
        producer="growthevo.locked-causal-evaluator",
        transitions=(PromotionTransition.ENTER_CANARY, PromotionTransition.FINAL_PROMOTION),
    )
    integrity = _external(
        subject,
        "integrity",
        evidence_type="randomization_integrity.v1",
        protocol="integrity-protocol-v1",
        producer="growthevo.integrity-verifier",
        transitions=all_transitions,
    )
    maturity = _external(
        subject,
        "maturity",
        evidence_type="outcome_maturity.v1",
        protocol="maturity-protocol-v1",
        producer="growthevo.maturity-verifier",
        transitions=(PromotionTransition.ADVANCE_STAGE, PromotionTransition.FINAL_PROMOTION),
    )
    direct_supply = _external(
        subject,
        "supply_chain",
        evidence_type="slsa_build_provenance.v1",
        protocol="direct-slsa-policy-fingerprint",
        producer="https://github.com/example/repo/.github/workflows/release.yml@refs/tags/v1",
        transitions=all_transitions,
    )
    delegated_supply = _external(
        subject,
        "supply_chain",
        evidence_type="slsa_vsa_delegated_verification.v1",
        protocol="delegated-vsa-consumer-policy",
        producer="https://verifier.example/growthevo",
        transitions=all_transitions,
        epoch=2,
    )
    return offline, integrity, maturity, direct_supply, delegated_supply


def _profile(plan: HighPowerCanaryPlan, subject: PromotionSubject) -> ProductionAuthorityProfile:
    offline, integrity, maturity, direct, delegated = _reference_evidence(subject)
    return ProductionAuthorityProfile.from_reference_evidence(
        profile_id="strict-production-authority-v1",
        plan=plan,
        offline_causal=(offline,),
        integrity=(integrity,),
        maturity=(maturity,),
        supply_chain=(direct, delegated),
    )


def _observation(ticket):
    return HighPowerCanaryObservation(
        analysis_unit_id=ticket.analysis_unit_id,
        routing_stage_index=ticket.routing_stage_index,
        assigned_to_challenger=ticket.assigned_to_challenger,
        assignment_probability=ticket.challenger_probability,
        traffic_fraction=ticket.traffic_fraction,
        metrics={"incremental_value": 1.0 if ticket.assigned_to_challenger else 0.0},
    )


def _drive_until(controller, predicate, prefix: str, limit: int = 10000):
    last = None
    for index in range(limit):
        ticket = controller.enroll(f"{prefix}-{index}")
        if not ticket.in_canary:
            continue
        last = controller.observe(_observation(ticket))
        if predicate(last):
            return last
    raise AssertionError(f"condition not reached; last={last}")


def test_exact_contract_alternatives_reject_cross_product_forgery() -> None:
    subject = _subject()
    contract_a = EvidenceContract("direct.v1", "direct-protocol", "direct-producer")
    contract_b = EvidenceContract("delegated.v1", "vsa-protocol", "vsa-producer")
    policy = StrictPromotionEvidencePolicy(
        policy_id="tuple-test",
        transitions=(
            StrictTransitionPolicy(
                PromotionTransition.ENTER_CANARY,
                (
                    StrictAuthorityRequirement(
                        "supply_chain",
                        (contract_a, contract_b),
                    ),
                ),
            ),
        ),
    )
    ledger = PromotionEvidenceLedger(subject)
    forged = _external(
        subject,
        "supply_chain",
        evidence_type="direct.v1",
        protocol="vsa-protocol",
        producer="direct-producer",
        transitions=(PromotionTransition.ENTER_CANARY,),
    )
    ledger.append(forged)
    gate = StrictPromotionManifestGate(
        ledger=ledger,
        policy=policy,
        expected_plan_fingerprint=subject.plan_fingerprint,
    )
    result = gate.evaluate(PromotionTransition.ENTER_CANARY)
    assert result.authorized is False
    assert "unapproved_evidence_contract:supply_chain" in result.reasons


def test_supply_chain_direct_or_delegated_are_real_or_alternatives() -> None:
    plan = _plan()
    subject = _subject(plan)
    profile = _profile(plan, subject)
    policy = profile.compile_policy(plan)
    supply_requirement = next(
        item
        for item in policy.transition_policy(PromotionTransition.ENTER_CANARY).requirements
        if item.authority_id == "supply_chain"
    )
    _, _, _, direct, delegated = _reference_evidence(subject)
    assert supply_requirement.matches(direct)
    assert supply_requirement.matches(delegated)
    assert direct.evidence_type != delegated.evidence_type
    assert len(supply_requirement.accepted_contracts) == 2


def test_online_safety_emitter_refuses_unestablished_safety() -> None:
    plan = _plan()
    subject = _subject(plan)
    spec = OnlineAuthorityEvidenceSpec.from_plan(plan)
    ledger = PromotionEvidenceLedger(subject)
    profile = _profile(plan, subject)
    offline, integrity, maturity, direct, _ = _reference_evidence(subject)
    for evidence in (offline, integrity, maturity, direct):
        ledger.append(evidence)
    controller = GovernedHighPowerOnlinePromotionController(
        champion_name="baseline",
        candidate=_candidate(),
        plan=plan,
        gate=profile.gate(plan=plan, ledger=ledger),
    )
    controller.start()

    with pytest.raises(ValueError, match="online safety is not established"):
        emit_online_safety_evidence(
            monitor=controller.monitor,
            subject=subject,
            spec=spec,
            transition=PromotionTransition.ADVANCE_STAGE,
        )


def test_primary_success_emitter_refuses_before_final_planned_success() -> None:
    plan = _plan()
    subject = _subject(plan)
    spec = OnlineAuthorityEvidenceSpec.from_plan(plan)
    ledger = PromotionEvidenceLedger(subject)
    profile = _profile(plan, subject)
    offline, integrity, maturity, direct, _ = _reference_evidence(subject)
    for evidence in (offline, integrity, maturity, direct):
        ledger.append(evidence)
    controller = GovernedHighPowerOnlinePromotionController(
        champion_name="baseline",
        candidate=_candidate(),
        plan=plan,
        gate=profile.gate(plan=plan, ledger=ledger),
    )
    controller.start()

    with pytest.raises(ValueError, match="final rollout stage"):
        emit_primary_success_evidence(
            monitor=controller.monitor,
            subject=subject,
            spec=spec,
        )


def test_full_strict_production_authority_lifecycle_closes_the_loop() -> None:
    plan = _plan()
    subject = _subject(plan)
    profile = _profile(plan, subject)
    ledger = PromotionEvidenceLedger(subject)
    offline, integrity, maturity, direct, _ = _reference_evidence(subject)

    # Supply-chain verification is required before the first exposure, not only
    # before final promotion. Maturity can arrive early but is not used for ENTER.
    for evidence in (offline, integrity, maturity, direct):
        ledger.append(evidence)

    controller = GovernedHighPowerOnlinePromotionController(
        champion_name="deterministic-baseline",
        candidate=_candidate(),
        plan=plan,
        gate=profile.gate(plan=plan, ledger=ledger),
    )
    started = controller.start()
    assert started.status is CanaryStatus.RUNNING

    # Statistics become stage-safe first. The strict policy still blocks the ramp
    # until the typed online-safety evidence is emitted into the independent ledger.
    blocked_advance = _drive_until(
        controller,
        lambda snapshot: "promotion_authority_blocked:advance_stage" in snapshot.reasons,
        "stage0",
    )
    assert blocked_advance.decision is CanaryDecision.HOLD
    safety_stage = emit_online_safety_evidence(
        monitor=controller.monitor,
        subject=subject,
        spec=profile.online_spec,
        transition=PromotionTransition.ADVANCE_STAGE,
    )
    ledger.append(safety_stage)
    advanced = controller.reevaluate_authority()
    assert advanced.decision is CanaryDecision.ADVANCE
    assert advanced.stage_index == 1

    # Final planned primary success is established, but the latest safety statement
    # is only scoped to ADVANCE_STAGE and primary success has not yet been emitted.
    blocked_final = _drive_until(
        controller,
        lambda snapshot: "promotion_authority_blocked:final_promotion" in snapshot.reasons,
        "final",
    )
    assert blocked_final.decision is CanaryDecision.HOLD
    final_observations = blocked_final.total_observations

    safety_final = emit_online_safety_evidence(
        monitor=controller.monitor,
        subject=subject,
        spec=profile.online_spec,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    primary = emit_primary_success_evidence(
        monitor=controller.monitor,
        subject=subject,
        spec=profile.online_spec,
    )
    ledger.append(safety_final)
    ledger.append(primary)

    promoted = controller.reevaluate_authority()
    assert promoted.decision is CanaryDecision.PROMOTE
    assert promoted.total_observations == final_observations
    assert controller.champion_name == _candidate().name
    assert controller.monitor.status is CanaryStatus.PROMOTED
    assert controller.verify_audit_chain() is True
    assert ledger.verify_chain() is True

    latest = {item.authority_id: item for item in ledger.latest_evidence()}
    assert latest["online_safety"].authorized_transitions == (
        PromotionTransition.FINAL_PROMOTION,
    )
    assert latest["primary_success"].evidence_type == "primary_success.v1"


def test_profile_fingerprint_binds_supply_chain_alternatives_and_online_plan() -> None:
    plan = _plan()
    subject = _subject(plan)
    profile = _profile(plan, subject)
    offline, integrity, maturity, direct, delegated = _reference_evidence(subject)
    direct_only = ProductionAuthorityProfile.from_reference_evidence(
        profile_id=profile.profile_id,
        plan=plan,
        offline_causal=(offline,),
        integrity=(integrity,),
        maturity=(maturity,),
        supply_chain=(direct,),
    )
    assert profile.fingerprint != direct_only.fingerprint
    assert profile.compile_policy(plan).fingerprint != direct_only.compile_policy(plan).fingerprint
    assert EvidenceContract.from_evidence(delegated) in profile.supply_chain_contracts
