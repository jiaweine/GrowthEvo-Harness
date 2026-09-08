from __future__ import annotations

from base64 import b64encode
import json

import pytest

from growthevo.evolution.promotion_manifest import (
    AuthorityVerdict,
    PromotionSubject,
    PromotionTransition,
)
from growthevo.evolution.signed_attestation import (
    AuthorityAttestationClaims,
    AuthoritySignerRule,
    DSSEEnvelope,
    DSSESignature,
    SignedAttestationPolicy,
    verify_authority_attestation,
)
from growthevo.evolution import sigstore_attestation as sigstore_module
from growthevo.evolution.sigstore_attestation import (
    SIGSTORE_BUNDLE_V03_MEDIA_TYPE,
    SigstoreBundleVerifier,
    SigstoreBundleVerifierSpec,
)


IDENTITY = "https://github.com/jiaweine/GrowthEvo-Harness/.github/workflows/evidence.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"


def _subject() -> PromotionSubject:
    return PromotionSubject(
        experiment_id="exp-sigstore",
        candidate_name="challenger",
        candidate_contract_fingerprint="candidate-fp",
        promotion_artifact_fingerprint="artifact-fp",
        plan_fingerprint="plan-fp",
        commit_sha="commit-sha",
    )


def _claims() -> AuthorityAttestationClaims:
    return AuthorityAttestationClaims(
        authority_id="online_safety",
        evidence_type="online_safety.v1",
        protocol_fingerprint="online-safety-protocol-v1",
        artifact_fingerprint="online-safety-artifact-v1",
        verdict=AuthorityVerdict.SATISFIED,
        authorized_transitions=(PromotionTransition.FINAL_PROMOTION,),
        evidence_epoch=3,
    )


def _envelope(subject: PromotionSubject | None = None) -> DSSEEnvelope:
    subject = subject or _subject()
    payload = _claims().canonical_statement_bytes(subject)
    return DSSEEnvelope.from_payload(
        payload_type="application/vnd.in-toto+json",
        payload=payload,
        signatures=(
            DSSESignature(
                keyid="",
                sig=b64encode(b"real-signature-placeholder").decode("ascii"),
            ),
        ),
    )


def _bundle_document(
    envelope: DSSEEnvelope | None = None,
    *,
    media_type: str = SIGSTORE_BUNDLE_V03_MEDIA_TYPE,
    tlog_entries: list[object] | None = None,
    timestamp_data: dict[str, object] | None = None,
) -> dict[str, object]:
    envelope = envelope or _envelope()
    return {
        "mediaType": media_type,
        "verificationMaterial": {
            "certificate": {"rawBytes": "ZmFrZS1jZXJ0"},
            "tlogEntries": (
                [{"logIndex": "7", "canonicalizedBody": "e30="}]
                if tlog_entries is None
                else tlog_entries
            ),
            "timestampVerificationData": (
                {} if timestamp_data is None else timestamp_data
            ),
        },
        "dsseEnvelope": {
            "payload": envelope.payload,
            "payloadType": envelope.payload_type,
            "signatures": [
                {
                    "sig": envelope.signatures[0].sig,
                    **(
                        {"keyid": envelope.signatures[0].keyid}
                        if envelope.signatures[0].keyid
                        else {}
                    ),
                }
            ],
        },
    }


def _bundle_json(envelope: DSSEEnvelope | None = None, **kwargs: object) -> str:
    return json.dumps(
        _bundle_document(envelope, **kwargs),
        sort_keys=True,
        separators=(",", ":"),
    )


def _spec(**overrides: object) -> SigstoreBundleVerifierSpec:
    values: dict[str, object] = {
        "expected_signer_identity": IDENTITY,
        "expected_issuer": ISSUER,
        "sigstore_sdk_version": "4.5.0",
        "offline": True,
    }
    values.update(overrides)
    return SigstoreBundleVerifierSpec(**values)  # type: ignore[arg-type]


class _FakeBundle:
    seen_raw: str | None = None

    @classmethod
    def from_json(cls, raw: str) -> object:
        cls.seen_raw = raw
        return {"bundle": "parsed"}


class _FakeIdentity:
    def __init__(self, *, identity: str, issuer: str | None = None) -> None:
        self.identity = identity
        self.issuer = issuer


class _FakeVerifierBackend:
    offline: bool | None = None
    verified_type = "application/vnd.in-toto+json"
    verified_payload: bytes | None = None
    fail = False
    seen_policy: _FakeIdentity | None = None

    @classmethod
    def production(cls, *, offline: bool = False) -> "_FakeVerifierBackend":
        cls.offline = offline
        return cls()

    def verify_dsse(self, bundle: object, policy: _FakeIdentity) -> tuple[str, bytes]:
        type(self).seen_policy = policy
        if type(self).fail:
            raise RuntimeError("signature invalid")
        assert bundle == {"bundle": "parsed"}
        assert type(self).verified_payload is not None
        return type(self).verified_type, type(self).verified_payload


def _install_fake_api(monkeypatch: pytest.MonkeyPatch, envelope: DSSEEnvelope, *, version: str = "4.5.0") -> None:
    _FakeVerifierBackend.offline = None
    _FakeVerifierBackend.verified_type = envelope.payload_type
    _FakeVerifierBackend.verified_payload = envelope.payload_bytes
    _FakeVerifierBackend.fail = False
    _FakeVerifierBackend.seen_policy = None
    _FakeBundle.seen_raw = None
    monkeypatch.setattr(
        sigstore_module,
        "_load_sigstore_api",
        lambda: sigstore_module._SigstoreAPI(
            Bundle=_FakeBundle,
            Verifier=_FakeVerifierBackend,
            Identity=_FakeIdentity,
            sdk_version=version,
        ),
    )


def test_adapter_uses_real_public_api_contract_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    _install_fake_api(monkeypatch, envelope)
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())
    receipt = verifier.verify(envelope)
    assert receipt.verifier_id == verifier.verifier_id
    assert receipt.signer_identity == IDENTITY
    assert receipt.issuer == ISSUER
    assert receipt.verified_signature_count == 1
    assert receipt.transparency_log_verified
    assert receipt.timestamp_verified
    assert receipt.transparency_log_entry_fingerprint != "not_available"
    assert receipt.timestamp_fingerprint == receipt.transparency_log_entry_fingerprint
    assert _FakeVerifierBackend.offline is True
    assert _FakeVerifierBackend.seen_policy is not None
    assert _FakeVerifierBackend.seen_policy.identity == IDENTITY
    assert _FakeVerifierBackend.seen_policy.issuer == ISSUER


def test_adapter_composes_with_phase15_signed_authority_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    envelope = _envelope(subject)
    _install_fake_api(monkeypatch, envelope)
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())
    policy = SignedAttestationPolicy(
        policy_id="sigstore-authority-policy",
        signer_rules=(
            AuthoritySignerRule(
                authority_id="online_safety",
                allowed_signer_identities=(IDENTITY,),
                allowed_issuers=(ISSUER,),
                allowed_verifier_ids=(verifier.verifier_id,),
                require_transparency_log=True,
                require_timestamp=True,
            ),
        ),
    )
    verified = verify_authority_attestation(
        envelope=envelope,
        expected_subject=subject,
        policy=policy,
        verifier=verifier,
    )
    assert verified.evidence.producer == IDENTITY
    assert verified.evidence.protocol_fingerprint == "online-safety-protocol-v1"
    assert verified.evidence.subject_fingerprint == subject.fingerprint


def test_bundle_must_match_phase15_envelope_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    other = DSSEEnvelope.from_payload(
        payload_type=envelope.payload_type,
        payload=envelope.payload_bytes,
        signatures=(
            DSSESignature(
                keyid="",
                sig=b64encode(b"different-signature").decode("ascii"),
            ),
        ),
    )
    _install_fake_api(monkeypatch, envelope)
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())
    with pytest.raises(ValueError, match="does not exactly match"):
        verifier.verify(other)
    assert _FakeBundle.seen_raw is None


def test_real_sdk_returned_payload_and_type_are_rebound(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    _install_fake_api(monkeypatch, envelope)
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())

    _FakeVerifierBackend.verified_type = "application/evil"
    with pytest.raises(ValueError, match="payload type"):
        verifier.verify(envelope)

    _FakeVerifierBackend.verified_type = envelope.payload_type
    _FakeVerifierBackend.verified_payload = b"different"
    with pytest.raises(ValueError, match="payload bytes"):
        verifier.verify(envelope)


def test_sigstore_sdk_version_is_pinned_by_verifier_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    _install_fake_api(monkeypatch, envelope, version="4.6.0")
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())
    with pytest.raises(RuntimeError, match="version does not match"):
        verifier.verify(envelope)
    assert _FakeBundle.seen_raw is None


def test_sigstore_crypto_failure_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    _install_fake_api(monkeypatch, envelope)
    _FakeVerifierBackend.fail = True
    verifier = SigstoreBundleVerifier(bundle_json=_bundle_json(envelope), spec=_spec())
    with pytest.raises(ValueError, match="Sigstore DSSE verification failed"):
        verifier.verify(envelope)


def test_only_current_canonical_bundle_v03_media_type_is_allowed() -> None:
    envelope = _envelope()
    with pytest.raises(ValueError, match="media type"):
        SigstoreBundleVerifier(
            bundle_json=_bundle_json(
                envelope,
                media_type="application/vnd.dev.sigstore.bundle+json;version=0.2",
            ),
            spec=_spec(),
        )


def test_sigstore_bundle_requires_exactly_one_signature() -> None:
    document = _bundle_document()
    dsse = dict(document["dsseEnvelope"])  # type: ignore[arg-type]
    signatures = list(dsse["signatures"])  # type: ignore[arg-type]
    dsse["signatures"] = signatures + signatures
    document["dsseEnvelope"] = dsse
    with pytest.raises(ValueError, match="exactly one signature"):
        SigstoreBundleVerifier(
            bundle_json=json.dumps(document),
            spec=_spec(),
        )


def test_duplicate_json_keys_are_rejected_before_sigstore_sdk() -> None:
    valid = _bundle_json()
    # Inject a duplicate top-level mediaType without relying on dict serialization.
    duplicate = valid[:-1] + ',"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SigstoreBundleVerifier(bundle_json=duplicate, spec=_spec())


def test_bundle_size_limit_fails_closed() -> None:
    with pytest.raises(ValueError, match="size limit"):
        SigstoreBundleVerifier(
            bundle_json=" " * 2048,
            spec=_spec(max_bundle_bytes=1024),
        )


def test_transparency_log_is_required_by_default() -> None:
    with pytest.raises(ValueError, match="transparency-log entry"):
        SigstoreBundleVerifier(
            bundle_json=_bundle_json(tlog_entries=[]),
            spec=_spec(),
        )


def test_tsa_only_bundle_can_be_explicitly_allowed() -> None:
    envelope = _envelope()
    verifier = SigstoreBundleVerifier(
        bundle_json=_bundle_json(
            envelope,
            tlog_entries=[],
            timestamp_data={
                "rfc3161Timestamps": [{"signedTimestamp": "dGltZXN0YW1w"}]
            },
        ),
        spec=_spec(require_transparency_log=False),
    )
    assert verifier.verifier_id.startswith("growthevo.sigstore-python-dsse.v1:")


def test_bundle_without_any_trusted_time_material_is_rejected() -> None:
    with pytest.raises(ValueError, match="trusted-time material"):
        SigstoreBundleVerifier(
            bundle_json=_bundle_json(tlog_entries=[], timestamp_data={}),
            spec=_spec(require_transparency_log=False),
        )


def test_verifier_identity_changes_with_sdk_offline_or_trust_contract() -> None:
    baseline = _spec()
    assert baseline.verifier_id != _spec(sigstore_sdk_version="4.5.1").verifier_id
    assert baseline.verifier_id != _spec(offline=False).verifier_id
    assert baseline.verifier_id != _spec(require_transparency_log=False).verifier_id
    assert baseline.verifier_id != _spec(expected_signer_identity="other").verifier_id
