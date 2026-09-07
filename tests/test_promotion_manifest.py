from __future__ import annotations

from dataclasses import replace

import pytest

from growthevo.evolution.promotion_manifest import (
    AuthorityEvidence,
    AuthorityRequirement,
    AuthorityVerdict,
    ManifestReason,
    PromotionEvidenceLedger,
    PromotionEvidenceManifest,
    PromotionEvidencePolicy,
    PromotionSubject,
    PromotionTransition,
    TransitionPolicy,
)


AUTHORITIES = (
    "offline_causal",
    "integrity",
    "maturity",
    "online_safety",
    "primary_success",
)


def _subject(**overrides: str) -> PromotionSubject:
    values = {
        "experiment_id": "exp-42",
        "candidate_name": "challenger-v2",
        "candidate_contract_fingerprint": "candidate-contract-fp",
        "promotion_artifact_fingerprint": "promotion-artifact-fp",
        "plan_fingerprint": "canary-plan-fp",
        "commit_sha": "0123456789abcdef",
    }
    values.update(overrides)
    return PromotionSubject(**values)


def _requirement(authority_id: str, *, minimum_epoch: int = 0) -> AuthorityRequirement:
    return AuthorityRequirement(
        authority_id=authority_id,
        allowed_evidence_types=(f"{authority_id}.v1",),
        allowed_protocol_fingerprints=(f"{authority_id}-protocol-v1",),
        allowed_producers=(f"{authority_id}-producer",),
        minimum_evidence_epoch=minimum_epoch,
    )


def _policy(*, sticky: tuple[str, ...] = ("integrity",)) -> PromotionEvidencePolicy:
    return PromotionEvidencePolicy(
        policy_id="strict-promotion-authority-v1",
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
                requirements=tuple(_requirement(item) for item in AUTHORITIES),
            ),
        ),
        veto_authorities=("integrity", "online_safety"),
        sticky_block_authorities=sticky,
    )


def _evidence(
    subject: PromotionSubject,
    authority_id: str,
    *,
    verdict: AuthorityVerdict = AuthorityVerdict.SATISFIED,
    transitions: tuple[PromotionTransition, ...] = (PromotionTransition.FINAL_PROMOTION,),
    epoch: int = 1,
    evidence_type: str | None = None,
    protocol: str | None = None,
    producer: str | None = None,
    artifact: str | None = None,
) -> AuthorityEvidence:
    return AuthorityEvidence(
        authority_id=authority_id,
        evidence_type=evidence_type or f"{authority_id}.v1",
        producer=producer or f"{authority_id}-producer",
        subject_fingerprint=subject.fingerprint,
        protocol_fingerprint=protocol or f"{authority_id}-protocol-v1",
        artifact_fingerprint=artifact or f"{authority_id}-artifact-{epoch}",
        verdict=verdict,
        authorized_transitions=transitions,
        evidence_epoch=epoch,
        source_chain_head=f"{authority_id}-chain-{epoch}",
        details_fingerprint=f"{authority_id}-details-{epoch}",
    )


def _fully_green_ledger(subject: PromotionSubject) -> PromotionEvidenceLedger:
    ledger = PromotionEvidenceLedger(subject)
    for authority_id in AUTHORITIES:
        ledger.append(_evidence(subject, authority_id))
    return ledger


def test_subject_fingerprint_binds_candidate_plan_artifact_and_commit() -> None:
    baseline = _subject()
    assert baseline.fingerprint != _subject(candidate_name="other").fingerprint
    assert baseline.fingerprint != _subject(plan_fingerprint="other-plan").fingerprint
    assert baseline.fingerprint != _subject(promotion_artifact_fingerprint="other-artifact").fingerprint
    assert baseline.fingerprint != _subject(commit_sha="fedcba9876543210").fingerprint


def test_cross_subject_evidence_is_rejected() -> None:
    subject = _subject()
    other = _subject(candidate_name="other")
    ledger = PromotionEvidenceLedger(subject)
    with pytest.raises(ValueError, match="different promotion subject"):
        ledger.append(_evidence(other, "integrity"))
    assert ledger.events == ()


def test_exact_evidence_replay_is_idempotent() -> None:
    subject = _subject()
    ledger = PromotionEvidenceLedger(subject)
    evidence = _evidence(subject, "integrity")
    first = ledger.append(evidence)
    second = ledger.append(evidence)
    assert first == second
    assert len(ledger.events) == 1
    assert ledger.verify_chain()


def test_stale_and_conflicting_same_epoch_evidence_are_rejected() -> None:
    subject = _subject()
    ledger = PromotionEvidenceLedger(subject)
    ledger.append(_evidence(subject, "integrity", epoch=2))
    with pytest.raises(ValueError, match="stale"):
        ledger.append(_evidence(subject, "integrity", epoch=1))
    with pytest.raises(ValueError, match="conflicting"):
        ledger.append(
            _evidence(
                subject,
                "integrity",
                epoch=2,
                artifact="different-artifact-same-epoch",
            )
        )
    assert len(ledger.events) == 1


def test_fully_green_final_manifest_authorizes() -> None:
    subject = _subject()
    policy = _policy()
    ledger = _fully_green_ledger(subject)
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert result.authorized
    assert result.reasons == (ManifestReason.AUTHORIZED.value,)
    assert result.manifest_fingerprint == manifest.fingerprint
    assert ledger.verify_chain()


def test_missing_required_authority_fails_closed() -> None:
    subject = _subject()
    policy = _policy()
    ledger = PromotionEvidenceLedger(subject)
    for authority_id in AUTHORITIES[:-1]:
        ledger.append(_evidence(subject, authority_id))
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert "missing_authority:primary_success" in result.reasons


def test_required_blocked_authority_vetoes_transition() -> None:
    subject = _subject()
    policy = _policy(sticky=())
    ledger = _fully_green_ledger(subject)
    ledger.append(
        _evidence(
            subject,
            "online_safety",
            verdict=AuthorityVerdict.BLOCKED,
            epoch=2,
        )
    )
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert "blocked_authority:online_safety" in result.reasons


def test_nonsticky_block_can_be_cleared_by_newer_evidence() -> None:
    subject = _subject()
    policy = _policy(sticky=())
    ledger = PromotionEvidenceLedger(subject)
    for authority_id in AUTHORITIES:
        if authority_id == "online_safety":
            ledger.append(
                _evidence(
                    subject,
                    authority_id,
                    verdict=AuthorityVerdict.BLOCKED,
                    epoch=1,
                )
            )
            ledger.append(_evidence(subject, authority_id, epoch=2))
        else:
            ledger.append(_evidence(subject, authority_id))
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    assert ledger.evaluate(manifest=manifest, policy=policy).authorized


def test_sticky_block_survives_newer_satisfied_evidence() -> None:
    subject = _subject()
    policy = _policy(sticky=("integrity",))
    ledger = PromotionEvidenceLedger(subject)
    for authority_id in AUTHORITIES:
        if authority_id == "integrity":
            ledger.append(
                _evidence(
                    subject,
                    authority_id,
                    verdict=AuthorityVerdict.BLOCKED,
                    epoch=1,
                )
            )
            ledger.append(_evidence(subject, authority_id, epoch=2))
        else:
            ledger.append(_evidence(subject, authority_id))
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert "sticky_block:integrity" in result.reasons


def test_earlier_transition_scope_cannot_authorize_final_promotion() -> None:
    subject = _subject()
    policy = _policy()
    ledger = _fully_green_ledger(subject)
    ledger.append(
        _evidence(
            subject,
            "offline_causal",
            transitions=(PromotionTransition.ENTER_CANARY,),
            epoch=2,
        )
    )
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert "insufficient_scope:offline_causal" in result.reasons


def test_minimum_epoch_prevents_stale_proof_replay() -> None:
    subject = _subject()
    base = _policy()
    final_requirements = tuple(
        _requirement(item, minimum_epoch=2 if item == "online_safety" else 0)
        for item in AUTHORITIES
    )
    policy = replace(
        base,
        transitions=tuple(
            TransitionPolicy(PromotionTransition.FINAL_PROMOTION, final_requirements)
            if item.transition is PromotionTransition.FINAL_PROMOTION
            else item
            for item in base.transitions
        ),
    )
    ledger = _fully_green_ledger(subject)
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert "stale_evidence:online_safety" in result.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("evidence_type", "unapproved-type", "unapproved_evidence_type:primary_success"),
        ("protocol", "unapproved-protocol", "unapproved_protocol:primary_success"),
        ("producer", "unapproved-producer", "unapproved_producer:primary_success"),
    ),
)
def test_policy_allowlists_type_protocol_and_producer(
    field: str,
    value: str,
    reason: str,
) -> None:
    subject = _subject()
    policy = _policy()
    ledger = PromotionEvidenceLedger(subject)
    for authority_id in AUTHORITIES:
        kwargs = {field: value} if authority_id == "primary_success" else {}
        ledger.append(_evidence(subject, authority_id, **kwargs))
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert reason in result.reasons


def test_manifest_becomes_stale_when_ledger_head_advances() -> None:
    subject = _subject()
    policy = _policy(sticky=())
    ledger = _fully_green_ledger(subject)
    old_manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    ledger.append(_evidence(subject, "online_safety", epoch=2))
    result = ledger.evaluate(manifest=old_manifest, policy=policy)
    assert not result.authorized
    assert ManifestReason.LEDGER_HEAD_MISMATCH.value in result.reasons
    assert ManifestReason.MANIFEST_EVIDENCE_MISMATCH.value in result.reasons


def test_caller_cannot_forge_manifest_evidence_subset() -> None:
    subject = _subject()
    policy = _policy()
    ledger = _fully_green_ledger(subject)
    canonical = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    forged = PromotionEvidenceManifest(
        subject=canonical.subject,
        transition=canonical.transition,
        policy_fingerprint=canonical.policy_fingerprint,
        ledger_head_hash=canonical.ledger_head_hash,
        ledger_event_count=canonical.ledger_event_count,
        latest_evidence=canonical.latest_evidence[:1],
    )
    result = ledger.evaluate(manifest=forged, policy=policy)
    assert not result.authorized
    assert ManifestReason.MANIFEST_EVIDENCE_MISMATCH.value in result.reasons


def test_policy_or_subject_mismatch_blocks_manifest() -> None:
    subject = _subject()
    policy = _policy()
    ledger = _fully_green_ledger(subject)
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    changed_policy = replace(policy, policy_id="different-policy")
    result = ledger.evaluate(manifest=manifest, policy=changed_policy)
    assert not result.authorized
    assert ManifestReason.MANIFEST_POLICY_MISMATCH.value in result.reasons

    forged_subject_manifest = replace(manifest, subject=_subject(candidate_name="other"))
    result = ledger.evaluate(manifest=forged_subject_manifest, policy=policy)
    assert not result.authorized
    assert ManifestReason.MANIFEST_SUBJECT_MISMATCH.value in result.reasons


def test_ledger_hash_chain_tamper_is_detected() -> None:
    subject = _subject()
    policy = _policy()
    ledger = _fully_green_ledger(subject)
    manifest = ledger.build_manifest(
        policy=policy,
        transition=PromotionTransition.FINAL_PROMOTION,
    )
    first = ledger._events[0]  # explicit adversarial test of internal tampering
    ledger._events[0] = replace(first, event_hash="f" * 64)
    assert not ledger.verify_chain()
    result = ledger.evaluate(manifest=manifest, policy=policy)
    assert not result.authorized
    assert ManifestReason.LEDGER_CHAIN_INVALID.value in result.reasons


def test_policy_fingerprint_binds_transition_requirements_and_sticky_veto() -> None:
    baseline = _policy()
    assert baseline.fingerprint != _policy(sticky=()).fingerprint
    changed_requirement = _requirement("offline_causal", minimum_epoch=5)
    changed = replace(
        baseline,
        transitions=(
            TransitionPolicy(
                PromotionTransition.ENTER_CANARY,
                (changed_requirement, _requirement("integrity")),
            ),
            *baseline.transitions[1:],
        ),
    )
    assert baseline.fingerprint != changed.fingerprint
