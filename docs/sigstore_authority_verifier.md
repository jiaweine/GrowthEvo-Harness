# Real Sigstore Authority Verifier Adapter

Phase 15 defined a generic cryptographic `AttestationVerifier` boundary. Phase 16 supplies a concrete adapter backed by the real public `sigstore-python` verification API.

This is a stacked change on Phase 15. It does not add Sigstore to the base runtime dependency set and does not change the causal/RL runtime, canary controller, or promotion authority policy.

## Current pinned SDK

The v1 adapter pins:

```text
sigstore-python == 4.5.0
```

through the optional extra:

```text
attestation-sigstore
```

The exact SDK version is also part of `SigstoreBundleVerifierSpec` and therefore the verifier id. A different SDK version cannot silently inherit the same Phase-15 verifier authority.

The pin is deliberate. Signature-verification libraries are security-sensitive dependencies, so a dependency update should create an explicit review point and a changed verifier identity.

## Public API only

The adapter lazily imports only documented public APIs:

```python
from sigstore.models import Bundle
from sigstore.verify import Verifier
from sigstore.verify.policy import Identity
```

The verification path is:

```python
bundle = Bundle.from_json(bundle_json)
policy = Identity(identity=expected_identity, issuer=expected_issuer)
verifier = Verifier.production(offline=True)
payload_type, payload = verifier.verify_dsse(bundle, policy)
```

`verify_dsse` performs Sigstore certificate/time/transparency/signature verification and returns the DSSE payload type and bytes. Sigstore explicitly documents that applications must validate the returned payload type/content themselves; GrowthEvo therefore rebinds both to the Phase-15 envelope before emitting a receipt.

## Why offline by default

`offline=True` disables routine TUF trust-root refreshes during the verification call. Sigstore then uses the cached trust root or its packaged trust root.

This makes a frozen GrowthEvo verification run less dependent on ambient network state. It also means operators are responsible for updating/reviewing trust-root material deliberately. A future deployment that wants online refresh can set `offline=False`; doing so changes the verifier spec fingerprint/id.

## Strict bundle v0.3 contract

Version 1 accepts only the canonical current media type:

```text
application/vnd.dev.sigstore.bundle.v0.3+json
```

The GrowthEvo pre-parser requires the DSSE bundle to contain exactly:

```text
mediaType
verificationMaterial
dsseEnvelope
```

and requires exactly one DSSE signature.

This mirrors the Sigstore bundle specification, which requires v0.3 for the current JSON encoding and requires exactly one signature for DSSE bundle content.

Widening the accepted bundle formats is a protocol change, not a compatibility fallback.

## Duplicate-key defense

The raw bundle JSON is parsed once before the SDK with duplicate-key rejection enabled.

Standard `json.loads()` normally accepts duplicate object keys and keeps the last value. That behavior is undesirable at a signature/security boundary because different parsers may disagree about the semantic document.

Phase 16 rejects duplicate keys before passing the bundle to Sigstore.

## Bundle size bound

`max_bundle_bytes` is frozen in the verifier spec. The default is 2 MB.

The limit is not a statistical assumption; it is a resource-safety boundary for untrusted verification input. Changing it changes the verifier identity.

## Exact envelope binding

A subtle provenance bug would be possible if GrowthEvo accepted this sequence:

```text
Sigstore verifies bundle envelope A
GrowthEvo records Phase-15 envelope B
A and B contain the same payload but different signatures
```

The v1 adapter explicitly prevents this.

Before calling the SDK, it reconstructs a Phase-15 `DSSEEnvelope` from the raw Sigstore bundle and requires its full envelope fingerprint to match the envelope supplied by Phase 15.

The fingerprint binds:

- payload type;
- base64 payload bytes;
- exact single signature;
- key id when present.

After `Verifier.verify_dsse` returns, GrowthEvo again checks the verified payload type and raw payload bytes against the same Phase-15 envelope.

Therefore the recorded signed-envelope provenance and the cryptographically verified envelope cannot diverge.

## Identity verification

`SigstoreBundleVerifierSpec` freezes the expected signer identity and OIDC issuer.

They are passed directly to Sigstore's public `Identity` policy. A successful `verify_dsse` call means the signing certificate passed that identity policy in addition to Sigstore's common verification checks.

The resulting Phase-15 verification receipt reports exactly those verified values. Phase 15 independently allowlists them again under the authority's signer policy.

The duplication is intentional:

```text
Sigstore cryptographically verifies identity
        +
GrowthEvo authority policy decides whether that identity is trusted for this authority
```

## Trusted time and transparency

Sigstore verification establishes a trusted signing time from supported time sources and validates certificate validity at that time. Public Sigstore verification also validates transparency-log material when present, including inclusion proof/checkpoint semantics and DSSE/log-entry consistency.

The adapter records:

- a fingerprint of the complete verification material;
- a fingerprint of transparency-log entries;
- a trusted-time fingerprint.

If RFC3161 timestamp material is present, it receives its own canonical fingerprint. Otherwise, when transparency-log time is the trusted time source, the verified tlog material fingerprint is used as the trusted-time provenance fingerprint.

`timestamp_verified=True` in the adapter receipt therefore means **Sigstore verified a trusted signing time**. It does not mean an RFC3161 timestamp necessarily existed.

## Transparency-log policy

The adapter defaults to:

```text
require_transparency_log = true
```

because the Phase-15 public Sigstore trust profile normally requires transparency evidence.

A TSA-only bundle can be admitted only by an explicitly different verifier spec with `require_transparency_log=false`, and Phase 15 must also use a signer rule compatible with that trust model.

There is no silent fallback.

## Verification-material fingerprint

The receipt's verification-material fingerprint binds:

- canonical Sigstore `verificationMaterial` JSON;
- bundle media type;
- exact `sigstore-python` SDK version;
- complete `SigstoreBundleVerifierSpec` fingerprint.

This prevents the same bundle from appearing to have been verified under a different SDK/trust contract without changing provenance.

## Failure behavior

The adapter fails closed on:

- malformed/non-UTF-8 JSON;
- duplicate JSON keys;
- oversized bundle;
- unapproved media type;
- non-object verification material;
- malformed timestamp/tlog fields;
- missing required transparency material;
- no trusted-time material;
- non-DSSE content;
- more or fewer than one signature;
- unexpected DSSE fields;
- Phase-15/bundle envelope mismatch;
- installed SDK version mismatch;
- Sigstore parser failure;
- certificate/identity/transparency/signature verification failure;
- returned payload-type mismatch;
- returned payload-byte mismatch.

No Phase-15 verification receipt is emitted on failure.

## Real SDK contract CI

Ordinary GrowthEvo tests do not install Sigstore. Adapter behavior is unit-tested using a fake API boundary so the base installation stays dependency-free.

On Python 3.12, CI additionally installs:

```text
sigstore==4.5.0
```

and runs `tests/test_sigstore_sdk_contracts.py`.

That test checks the real installed package version and documented public API shape for:

- `Bundle.from_json`;
- `Verifier.production(offline=...)`;
- `Verifier.verify_dsse`;
- `Identity(identity=..., issuer=...)`.

It also constructs a real offline production verifier/trust-root instance and exercises the real bundle parser's rejection path.

## What this CI does not yet prove

The SDK contract test is **not** a full cryptographic verification of a pinned production DSSE fixture.

A full fixture test requires a stable bundle whose signer identity, certificate, transparency entry, trusted time and trust root remain reproducible under the pinned Sigstore version. GrowthEvo will not synthesize a fake Fulcio/Rekor bundle and call that equivalent.

The next integration gate should use a pinned real DSSE bundle with a pinned SHA-256 and known identity/issuer, preferably from a stable Sigstore conformance or release fixture. Until that exists, the documentation must distinguish:

```text
real SDK integration path: yes
real production cryptographic fixture in GrowthEvo CI: not yet
```

## Relationship to Sigstore 4.5

`sigstore-python` 4.5 exposes `Verifier.verify_dsse` as a public API. It verifies the common signing certificate policy, the DSSE signature itself, and consistency between the DSSE envelope and the transparency-log entry before returning `(payload_type, payload)`.

Sigstore also documents that verification requires a trusted signing time and that transparency-log inclusion/checkpoint data is verified as part of the verification policy.

GrowthEvo relies on those documented guarantees instead of reaching into private Sigstore fields.

## Deployment path

The intended authority path is now:

```text
Sigstore bundle
    |
SigstoreBundleVerifier
    |
real sigstore-python signature + identity verification
    |
SignatureVerificationResult
    |
Phase-15 strict in-toto authority claim verification
    |
VerifiedAuthorityAttestation
    |
Phase-14 PromotionEvidenceLedger
    |
transition-specific authority policy
```

The runtime execution plane remains unchanged.
