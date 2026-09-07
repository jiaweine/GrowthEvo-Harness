# Signed Authority Attestation / Verification Boundary

Phase 14 introduced a promotion-evidence ledger and policy-as-code authority composition. Phase 15 adds the missing authenticity boundary: an authority statement must be cryptographically verified by a trusted verifier before it can be translated into `AuthorityEvidence`.

This is a **stacked** change on top of Phase 14 because signed attestations intentionally reuse the exact `PromotionSubject`, `AuthorityEvidence`, `AuthorityVerdict`, and `PromotionTransition` types rather than inventing a second governance schema.

## Standards alignment

GrowthEvo uses an in-toto/DSSE-compatible statement shape:

- statement type: `https://in-toto.io/Statement/v1`;
- DSSE payload type: `application/vnd.in-toto+json`;
- a GrowthEvo-specific promotion-authority predicate type;
- DSSE Pre-Authentication Encoding (PAE) for verifier implementations.

The reference module does not implement a private signature algorithm.

That is deliberate. Sigstore, enterprise PKI/KMS systems, or another reviewed cryptographic implementation can implement the `AttestationVerifier` protocol. GrowthEvo then independently verifies the signed claims, signer identity, issuer, verifier identity, subject binding, and trust policy before accepting the result.

This follows the same high-level separation used by modern supply-chain systems: claims are expressed as attestations, while verification material, signer identity, timestamps, and transparency-log evidence are validated by a dedicated verification boundary.

## Why Phase 14 alone is insufficient

Phase 14 can enforce:

- exact producer strings;
- protocol fingerprints;
- evidence freshness;
- transition scope;
- append-only ledger provenance.

But a plain `producer="safety-ci"` field does not prove that the statement actually came from that producer.

Phase 15 changes the path to:

```text
untrusted signed envelope
        |
        v
cryptographic AttestationVerifier
        |
        +-- signature valid
        +-- signer identity verified
        +-- issuer verified
        +-- transparency/timestamp verified when required
        |
        v
GrowthEvo strict claim verification
        |
        +-- exact in-toto statement type
        +-- exact predicate type
        +-- exact promotion-subject digest
        +-- exact predicate subject fingerprint
        +-- exact JSON field set/types
        +-- exact authority trust rule
        |
        v
VerifiedAuthorityAttestation
        |
        v
Phase-14 AuthorityEvidence
        |
        v
PromotionEvidenceLedger / policy evaluation
```

## DSSE envelope

`DSSEEnvelope` stores:

- `payload_type`;
- base64 payload;
- one or more base64 signatures.

`dsse_pae()` implements DSSE Pre-Authentication Encoding:

```text
DSSEv1 SP len(type) SP type SP len(payload) SP payload
```

The envelope fingerprint includes the raw payload bytes and signatures. Two semantically identical JSON statements serialized differently therefore have different envelope identities, as they should, because the signature covers bytes.

## Semantic statement identity

After successful verification, GrowthEvo parses the JSON statement and computes a canonical semantic statement fingerprint.

This means:

- compact JSON and pretty JSON can have the same statement identity;
- their DSSE envelope identities remain different;
- both identities are retained in the final verified-attestation fingerprint.

No signature bytes are discarded from provenance.

## Promotion subject binding

The in-toto subject contains exactly one GrowthEvo promotion subject with digest:

```text
blake2b-160 = PromotionSubject.fingerprint
```

The predicate independently repeats the same `subject_fingerprint`.

Both must match the caller's expected `PromotionSubject`.

The duplicate binding is intentional defense in depth. A correctly signed claim for another candidate, plan, experiment, promotion artifact, or source commit cannot be replayed into the current ledger.

## Authority predicate

`AuthorityAttestationClaims` contains only the authority claim:

- authority id;
- evidence type;
- protocol fingerprint;
- artifact fingerprint;
- verdict;
- authorized promotion transitions;
- logical evidence epoch;
- upstream source-chain head;
- upstream details fingerprint.

The signer identity is **not trusted from the predicate**. It comes from the cryptographic verifier receipt.

When the signed statement is translated to `AuthorityEvidence`, the Phase-14 `producer` field is set to the verified signer identity.

## Strict schema

The parser rejects unknown or missing fields in the statement, subject, digest, and predicate objects.

String claims must be native non-empty JSON strings. Numeric, boolean, or object values are not silently coerced with `str(...)`.

This avoids ambiguous schema behavior such as an integer authority id being converted into a string and accidentally matching a policy.

## Cryptographic verifier boundary

`AttestationVerifier` is a protocol:

```python
class AttestationVerifier(Protocol):
    verifier_id: str

    def verify(self, envelope: DSSEEnvelope) -> SignatureVerificationResult:
        ...
```

A conforming implementation must perform the actual cryptographic work before returning `SignatureVerificationResult`.

Possible implementations include:

- Sigstore bundle verification;
- enterprise X.509 PKI;
- KMS-backed signatures;
- an offline verification service;
- another reviewed signature/transparency implementation.

The GrowthEvo reference module intentionally does not implement Ed25519/RSA/ECDSA primitives itself and does not silently fall back to a non-cryptographic hash comparison.

## Verification receipt

`SignatureVerificationResult` binds:

- verifier id;
- verified signer identity;
- verified issuer;
- verification-material fingerprint;
- number of verified signatures;
- transparency-log verification result;
- trusted timestamp verification result;
- transparency-log entry fingerprint;
- timestamp fingerprint.

The receipt gets its own 256-bit fingerprint.

The verifier object's declared id and the returned receipt verifier id must match exactly.

## Signer trust policy

`AuthoritySignerRule` is defined per authority and freezes exact allowlists for:

- signer identities;
- issuers;
- verifier implementations.

It also specifies whether a transparency-log proof and trusted timestamp are mandatory.

Matching is exact in v1. Regex or prefix matching is deliberately not supported because broad identity patterns are easy to misconfigure.

`SignedAttestationPolicy` fingerprints the complete signer/issuer/verifier/transparency policy.

## Sigstore-compatible posture

A Sigstore-backed verifier can use a Sigstore bundle as its verification material.

Modern Sigstore bundles can include the signature plus certificate/public-key material, transparency-log entries, and trusted timestamp material needed for offline verification. Keyless verification also binds an OIDC signer identity and issuer.

GrowthEvo's trust rule is designed to consume exactly those verified outputs:

```text
signer identity
OIDC issuer
signature verification
transparency-log proof
trusted timestamp
verification material fingerprint
```

The Sigstore library/CLI remains responsible for Sigstore-specific certificate-chain, Rekor, timestamp, and signature semantics. GrowthEvo should not reimplement them.

## Private PKI / KMS

Transparency logs and public OIDC are not mandatory for every deployment.

A policy can explicitly set:

```text
require_transparency_log = false
require_timestamp = false
```

for an approved private verifier/issuer/signer tuple.

This is not an automatic fallback. It is a different, fingerprinted trust policy.

## Translation into Phase 14

After every verification step succeeds, GrowthEvo emits an `AuthorityEvidence` with:

- exact Phase-14 subject fingerprint;
- signed authority claim;
- `producer = verified signer identity`;
- signed protocol/artifact/scope/epoch;
- upstream source-chain head;
- a new `details_fingerprint` binding:
  - the original claimed details fingerprint;
  - semantic statement fingerprint;
  - raw DSSE envelope fingerprint;
  - verification receipt fingerprint;
  - signed-attestation policy fingerprint.

The evidence can then enter `PromotionEvidenceLedger` normally.

This means Phase 14 can allowlist an actual CI workflow identity, KMS identity, or other verified signer rather than trusting a free-form producer label.

## Tampering behavior

The reference tests separate two classes of tampering:

### Cryptographic tampering

Changing the signed payload changes the envelope fingerprint and must make a real cryptographic verifier reject the signature.

### Semantically valid but unauthorized claims

A claim can be genuinely signed yet still be rejected by GrowthEvo because of:

- wrong promotion subject;
- wrong predicate type;
- wrong authority id;
- unapproved signer;
- unapproved issuer;
- unapproved verifier;
- missing transparency proof;
- missing timestamp;
- malformed schema;
- extra executable/ambiguous fields.

A valid signature is therefore necessary but not sufficient for authority.

## Security boundary

Phase 15 does **not** claim that any arbitrary Python object implementing `AttestationVerifier` is trustworthy.

The verifier implementation itself is part of the trusted computing base and must be selected by deployment policy. Its `verifier_id` is explicitly allowlisted and bound into the verification receipt and attestation fingerprint.

The reference tests use a fake verifier only to exercise GrowthEvo's integration contract. They do not constitute a real Sigstore/PKI signature test.

A production Sigstore adapter should be tested against the real Sigstore verifier API or CLI and its actual bundle schema before being allowlisted.

## Relationship to SLSA and in-toto

SLSA v1.2 uses provenance and verification-summary attestations to communicate verified supply-chain properties. GrowthEvo's authority predicate is not a claim of SLSA conformance; it borrows the same architectural principle that a verifier should consume authenticated attestations and explicit policy rather than trusting unsigned metadata.

Likewise, using an in-toto Statement/DSSE shape provides interoperability structure but does not make a GrowthEvo authority claim an in-toto software-supply-chain guarantee by itself.

Those distinctions are intentional.

## Tests

`tests/test_signed_attestation.py` covers:

- DSSE PAE shape;
- base64 envelope validation;
- signer identity mapping into Phase-14 evidence;
- direct integration with the Phase-14 ledger;
- signer/issuer/verifier allowlists;
- verifier/receipt identity mismatch;
- transparency-log requirement;
- trusted timestamp requirement;
- explicit private-PKI policy;
- cross-subject signed replay;
- duplicate subject binding;
- wrong statement/predicate/payload types;
- unexpected statement/predicate fields;
- cryptographic-verifier rejection of tampered payload;
- semantic statement fingerprint vs raw envelope fingerprint;
- security-policy fingerprint sensitivity;
- unknown authority fail-closed behavior.

## Deployment posture

Phase 15 remains an evidence-ingestion boundary. It does not sign evidence, choose a signer, mutate a ledger automatically, ramp traffic, promote a candidate, or deploy anything.

A future production adapter can bind Sigstore/SLSA-style verified identities into this boundary without changing the causal/RL runtime or weakening Phase-14 authority composition.
