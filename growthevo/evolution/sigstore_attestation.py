from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from typing import Any, Mapping

from .signed_attestation import (
    DSSEEnvelope,
    DSSESignature,
    SignatureVerificationResult,
)


SIGSTORE_BUNDLE_V03_MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
_SIGSTORE_ADAPTER_SCHEMA = "growthevo.sigstore-python-dsse-verifier.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(value: object, *, digest_size: int = 32) -> str:
    return blake2b(_canonical_json(value), digest_size=digest_size).hexdigest()


def _reject_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key is not allowed: {key}")
        result[key] = value
    return result


def _strict_json_document(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_object_pairs)
    except json.JSONDecodeError as exc:
        raise ValueError("Sigstore bundle must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Sigstore bundle must be a JSON object")
    return value


def _require_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class SigstoreBundleVerifierSpec:
    """Pinned trust/runtime contract for the real sigstore-python adapter.

    Version 1 intentionally accepts only the current canonical Sigstore bundle v0.3
    media type and one exact sigstore-python SDK version. Widening either contract
    changes the verifier identity and therefore requires an explicit policy update.
    """

    expected_signer_identity: str
    expected_issuer: str
    sigstore_sdk_version: str = "4.5.0"
    offline: bool = True
    allowed_bundle_media_types: tuple[str, ...] = (SIGSTORE_BUNDLE_V03_MEDIA_TYPE,)
    require_transparency_log: bool = True
    max_bundle_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        for name in (
            "expected_signer_identity",
            "expected_issuer",
            "sigstore_sdk_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if not self.allowed_bundle_media_types:
            raise ValueError("allowed_bundle_media_types cannot be empty")
        if len(set(self.allowed_bundle_media_types)) != len(self.allowed_bundle_media_types):
            raise ValueError("allowed_bundle_media_types must contain unique values")
        for value in self.allowed_bundle_media_types:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("allowed bundle media types must be non-empty strings")
        if (
            isinstance(self.max_bundle_bytes, bool)
            or not isinstance(self.max_bundle_bytes, int)
            or self.max_bundle_bytes < 1024
        ):
            raise ValueError("max_bundle_bytes must be an integer >= 1024")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": _SIGSTORE_ADAPTER_SCHEMA,
                **asdict(self),
                "bundle_parse": "strict-json-no-duplicate-keys",
                "bundle_content": "exact-single-signature-dsse",
                "identity_policy": "sigstore.verify.policy.Identity",
                "verification_api": "Verifier.verify_dsse",
            },
            digest_size=20,
        )

    @property
    def verifier_id(self) -> str:
        return f"growthevo.sigstore-python-dsse.v1:{self.fingerprint}"


@dataclass(frozen=True, slots=True)
class _SigstoreAPI:
    Bundle: Any
    Verifier: Any
    Identity: Any
    sdk_version: str


def _load_sigstore_api() -> _SigstoreAPI:
    """Load only documented sigstore-python public APIs, lazily."""

    try:
        from sigstore.models import Bundle
        from sigstore.verify import Verifier
        from sigstore.verify.policy import Identity
    except ImportError as exc:
        raise RuntimeError(
            "sigstore-python is optional; install GrowthEvo with the "
            "attestation-sigstore extra"
        ) from exc
    try:
        sdk_version = package_version("sigstore")
    except PackageNotFoundError as exc:  # pragma: no cover - import succeeded
        raise RuntimeError("sigstore-python package metadata is unavailable") from exc
    return _SigstoreAPI(
        Bundle=Bundle,
        Verifier=Verifier,
        Identity=Identity,
        sdk_version=sdk_version,
    )


@dataclass(frozen=True, slots=True)
class _ParsedSigstoreBundle:
    raw_json: str
    document: Mapping[str, object]
    dsse_envelope: DSSEEnvelope
    verification_material: Mapping[str, object]
    tlog_entries: tuple[object, ...]
    timestamp_verification_data: Mapping[str, object]
    media_type: str


class SigstoreBundleVerifier:
    """Real sigstore-python adapter implementing Phase-15 `AttestationVerifier`.

    The supplied Sigstore bundle is parsed and structurally bound to the Phase-15
    DSSE envelope before `sigstore-python` is invoked. A successful receipt is
    emitted only when the real `Verifier.verify_dsse` call succeeds under the exact
    expected Identity/OIDC issuer policy and returns the exact payload bytes/type.
    """

    def __init__(
        self,
        *,
        bundle_json: str | bytes,
        spec: SigstoreBundleVerifierSpec,
    ) -> None:
        self.spec = spec
        raw_bytes = (
            bundle_json.encode("utf-8") if isinstance(bundle_json, str) else bundle_json
        )
        if not isinstance(raw_bytes, bytes):
            raise TypeError("bundle_json must be str or bytes")
        if not raw_bytes:
            raise ValueError("Sigstore bundle cannot be empty")
        if len(raw_bytes) > spec.max_bundle_bytes:
            raise ValueError("Sigstore bundle exceeds the preregistered size limit")
        try:
            raw_json = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Sigstore bundle must be UTF-8 JSON") from exc
        self._parsed = self._parse_bundle(raw_json)

    @property
    def verifier_id(self) -> str:
        return self.spec.verifier_id

    def _parse_bundle(self, raw_json: str) -> _ParsedSigstoreBundle:
        document = _strict_json_document(raw_json)
        expected_top = {"mediaType", "verificationMaterial", "dsseEnvelope"}
        if set(document) != expected_top:
            raise ValueError(
                "Sigstore DSSE bundle must contain exactly mediaType, "
                "verificationMaterial, and dsseEnvelope"
            )

        media_type = _require_nonempty_string(document["mediaType"], "mediaType")
        if media_type not in self.spec.allowed_bundle_media_types:
            raise ValueError("Sigstore bundle media type is not approved")

        verification_material = _require_object(
            document["verificationMaterial"], "verificationMaterial"
        )
        tlog_raw = verification_material.get("tlogEntries", [])
        if not isinstance(tlog_raw, list):
            raise ValueError("verificationMaterial.tlogEntries must be an array")
        tlog_entries = tuple(tlog_raw)
        if self.spec.require_transparency_log and not tlog_entries:
            raise ValueError("Sigstore transparency-log entry is required")

        timestamp_raw = verification_material.get("timestampVerificationData", {})
        if timestamp_raw is None:
            timestamp_raw = {}
        timestamp_data = _require_object(
            timestamp_raw, "verificationMaterial.timestampVerificationData"
        )
        rfc3161 = timestamp_data.get("rfc3161Timestamps", [])
        if not isinstance(rfc3161, list):
            raise ValueError("rfc3161Timestamps must be an array")
        if not tlog_entries and not rfc3161:
            raise ValueError("Sigstore bundle has no trusted-time material")

        envelope_raw = _require_object(document["dsseEnvelope"], "dsseEnvelope")
        if set(envelope_raw) != {"payload", "payloadType", "signatures"}:
            raise ValueError("dsseEnvelope has unexpected or missing fields")
        signatures_raw = envelope_raw["signatures"]
        if not isinstance(signatures_raw, list) or len(signatures_raw) != 1:
            raise ValueError("Sigstore DSSE bundle must contain exactly one signature")
        signature_raw = _require_object(signatures_raw[0], "dsseEnvelope.signatures[0]")
        if set(signature_raw) not in ({"sig"}, {"sig", "keyid"}):
            raise ValueError("Sigstore DSSE signature has unexpected fields")
        signature = DSSESignature(
            keyid=(
                _require_nonempty_string(signature_raw["keyid"], "signature.keyid")
                if "keyid" in signature_raw and signature_raw["keyid"] != ""
                else ""
            ),
            sig=_require_nonempty_string(signature_raw.get("sig"), "signature.sig"),
        )
        dsse_envelope = DSSEEnvelope(
            payload_type=_require_nonempty_string(
                envelope_raw["payloadType"], "dsseEnvelope.payloadType"
            ),
            payload=_require_nonempty_string(envelope_raw["payload"], "dsseEnvelope.payload"),
            signatures=(signature,),
        )
        return _ParsedSigstoreBundle(
            raw_json=raw_json,
            document=document,
            dsse_envelope=dsse_envelope,
            verification_material=verification_material,
            tlog_entries=tlog_entries,
            timestamp_verification_data=timestamp_data,
            media_type=media_type,
        )

    def _bind_exact_envelope(self, envelope: DSSEEnvelope) -> None:
        if len(envelope.signatures) != 1:
            raise ValueError("Sigstore verification requires exactly one DSSE signature")
        if envelope.fingerprint != self._parsed.dsse_envelope.fingerprint:
            raise ValueError("Phase-15 DSSE envelope does not exactly match Sigstore bundle")

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        self._bind_exact_envelope(envelope)
        api = _load_sigstore_api()
        if api.sdk_version != self.spec.sigstore_sdk_version:
            raise RuntimeError(
                "installed sigstore-python version does not match the pinned verifier contract"
            )

        try:
            bundle = api.Bundle.from_json(self._parsed.raw_json)
            identity_policy = api.Identity(
                identity=self.spec.expected_signer_identity,
                issuer=self.spec.expected_issuer,
            )
            backend = api.Verifier.production(offline=self.spec.offline)
            verified_type, verified_payload = backend.verify_dsse(bundle, identity_policy)
        except Exception as exc:
            raise ValueError("Sigstore DSSE verification failed") from exc

        if verified_type != envelope.payload_type:
            raise ValueError("Sigstore verified payload type differs from Phase-15 envelope")
        if verified_payload != envelope.payload_bytes:
            raise ValueError("Sigstore verified payload bytes differ from Phase-15 envelope")

        tlog_fingerprint = (
            _fingerprint(
                {
                    "schema": "growthevo.sigstore-tlog-material.v1",
                    "tlogEntries": list(self._parsed.tlog_entries),
                }
            )
            if self._parsed.tlog_entries
            else "not_available"
        )
        rfc3161 = self._parsed.timestamp_verification_data.get(
            "rfc3161Timestamps", []
        )
        if rfc3161:
            timestamp_fingerprint = _fingerprint(
                {
                    "schema": "growthevo.sigstore-rfc3161-time.v1",
                    "rfc3161Timestamps": rfc3161,
                }
            )
        elif self._parsed.tlog_entries:
            # sigstore-python treats a verified Transparency Service timestamp as
            # a trusted time source. Bind the exact verified log material here.
            timestamp_fingerprint = tlog_fingerprint
        else:  # rejected during parsing, kept for exhaustiveness
            timestamp_fingerprint = "not_available"

        verification_material_fingerprint = _fingerprint(
            {
                "schema": "growthevo.sigstore-verification-material.v1",
                "bundle_media_type": self._parsed.media_type,
                "verificationMaterial": self._parsed.verification_material,
                "sigstore_sdk_version": api.sdk_version,
                "adapter_spec_fingerprint": self.spec.fingerprint,
            }
        )
        return SignatureVerificationResult(
            verifier_id=self.verifier_id,
            signer_identity=self.spec.expected_signer_identity,
            issuer=self.spec.expected_issuer,
            verification_material_fingerprint=verification_material_fingerprint,
            verified_signature_count=1,
            transparency_log_verified=bool(self._parsed.tlog_entries),
            # A successful sigstore-python verification requires a trusted signing
            # time. This flag means trusted signing-time verification, not
            # necessarily an RFC3161 timestamp specifically.
            timestamp_verified=True,
            transparency_log_entry_fingerprint=tlog_fingerprint,
            timestamp_fingerprint=timestamp_fingerprint,
        )
