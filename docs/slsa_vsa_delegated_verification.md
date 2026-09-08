# SLSA Verification Summary Attestation (VSA) delegated verification

Phase 19 adds a deliberately separate delegated-verification layer on top of the Phase-18 SLSA Build Provenance verifier.

The VSA predicate is the SLSA v1 predicate:

`https://slsa.dev/verification_summary/v1`

GrowthEvo uses VSA for one narrow purpose: a trusted verification service can summarize that an exact release artifact was already evaluated against an exact supply-chain policy and reached a specific SLSA Build level. A VSA does not replace the underlying provenance and it does not replace GrowthEvo's promotion evidence manifest.

## Why this is a separate layer

Phase 18 consumes original SLSA Build Provenance and performs the expensive policy evaluation:

1. exact artifact digest;
2. cryptographic PEP-740/Sigstore verification;
3. exact Trusted Publisher;
4. local signer/builder root of trust;
5. approved build type;
6. exact external parameters;
7. exact source dependency and commit.

Phase 19 can summarize the result so another GrowthEvo control plane does not need all original material locally. That is delegated verification, not weaker verification.

The trust equation is therefore:

`trusted VSA = valid signature + trusted (signer, verifier.id) pair + exact subject + exact resource + exact policy + PASSED + acceptable level + GrowthEvo source binding`

A cryptographically valid VSA from the wrong verifier, or a VSA signed by an otherwise trusted signer for an unapproved verifier identity, fails closed.

## Producer

`produce_slsa_vsa(...)` accepts only a `VerifiedSLSABuildProvenance` object. It cannot start from an arbitrary JSON claim.

`SLSAVSAProductionSpec` freezes:

- verifier identity;
- artifact resource URI;
- policy URI and SHA-256;
- input provenance URI;
- Build level to report;
- verifier component versions;
- optional additional input attestations;
- SLSA version;
- optional explicit verification time.

The requested Build level must be less than or equal to the local trusted Build level already established by Phase 18. A caller cannot take an L2 verification and produce an L3 VSA.

The producer always includes the SHA-256 of the exact PEP-740 provenance object used by Phase 18 in `inputAttestations`.

## Dependency claims are intentionally absent

The VSA contains:

`"dependencyLevels": null`

This is intentional. Under the SLSA VSA semantics, null or an absent `dependencyLevels` means the verifier makes no claim about transitive dependency levels. An empty object instead means there are no dependencies at all.

Phase 18 validates the expected source dependency that anchors the build to a source commit. It does not recursively verify every transitive build dependency. GrowthEvo therefore does not turn that narrower fact into a transitive dependency-level claim.

## GrowthEvo VSA context extension

The producer adds a signed URI-named extension:

`https://github.com/jiaweine/GrowthEvo-Harness/attestation/slsa-vsa-context/v1`

It contains:

- source commit SHA;
- source dependency URI;
- fingerprint of the exact `VerifiedSLSABuildProvenance` result;
- Phase-18 build expectation fingerprint;
- SHA-256 of the provenance input.

The base SLSA VSA remains standards-compatible: SLSA consumers are required to ignore unrecognized fields. GrowthEvo consumers may require this extension when they need promotion-subject binding.

## Signing boundary

`VSAEnvelopeSigner` is a protocol, not a built-in private-key implementation.

GrowthEvo does not store or invent signing keys. A production deployment can back this boundary with Sigstore keyless signing, KMS/HSM signing, or another reviewed DSSE signer. `sign_slsa_vsa(...)` verifies that the returned DSSE envelope contains the exact canonical VSA statement bytes and the correct in-toto DSSE payload type.

This avoids a common integration bug where a signing service returns an envelope for different bytes than the caller records in audit metadata.

## Consumer trust policy

`SLSAVSAConsumerPolicy` contains the delegated trust root.

Each `VSAVerifierTrust` binds one exact `verifier.id` to:

- allowed signer identities;
- allowed signer issuers;
- allowed cryptographic verifier adapters;
- maximum Build level this verifier is allowed to delegate;
- transparency-log requirement;
- trusted-timestamp requirement.

This is intentionally different from Phase-15 `SignedAttestationPolicy`. A VSA signer is asserting the result of supply-chain verification; a Phase-15 signer is asserting a GrowthEvo promotion-authority statement. A key trusted for one purpose is not automatically trusted for the other.

## Consumer verification

`verify_slsa_vsa(...)` performs the SLSA VSA consumer checks and GrowthEvo's extra bindings:

1. DSSE payload type is approved;
2. duplicate JSON keys are rejected;
3. in-toto statement type is correct;
4. predicate type is exactly the SLSA VSA v1 URI;
5. the single subject name and SHA-256 match the expected artifact;
6. `verifier.id` selects an exact local trust rule;
7. DSSE signature verification succeeds;
8. the returned signer identity and issuer match that verifier rule;
9. required transparency and trusted-time evidence are present;
10. `resourceUri` matches the intended artifact resource;
11. `verificationResult` is `PASSED`;
12. exactly one highest Build-track result is present;
13. the level meets consumer minimum and does not exceed delegated maximum;
14. policy URI and policy digest are allowlisted;
15. `slsaVersion`, when declared, is allowlisted;
16. dependency-level claims are absent when the policy requires no such claim;
17. the expected input provenance digest is present;
18. the GrowthEvo extension binds the expected source commit and the exact Phase-18 verification result.

Unknown VSA fields are otherwise ignored as required by the SLSA v1 parsing model. GrowthEvo does not make the base parser artificially strict in a way that would break compatible future minor extensions.

## Promotion evidence conversion

Only a fully verified `VerifiedSLSAVSA` can become Phase-14 authority evidence.

`to_delegated_authority_evidence(...)` additionally requires:

- the signed VSA source commit equals `PromotionSubject.commit_sha`;
- the VSA Build level meets the transition's requested minimum;
- the authorized transition scope is explicit.

The emitted evidence type is:

`slsa_vsa_delegated_verification.v1`

The evidence producer is `verifier.id`, not merely the certificate signer. This preserves the SLSA delegated-verification identity model in the Phase-14 manifest.

## Threats explicitly covered

The tests fail closed for:

- VSA level above Phase-18 local trust;
- signer returning an envelope for different statement bytes;
- signer/verifier identity mismatch;
- cryptographic verifier receipt mismatch;
- delegated L3 from an L2-trusted verifier;
- `FAILED` result;
- wrong resource URI;
- wrong policy digest;
- unauthorized dependency-level claims;
- multiple Build-track levels;
- missing expected input provenance;
- wrong source commit;
- cross-commit replay into promotion authority;
- duplicate JSON keys.

A future SLSA-compatible extension field is accepted and ignored unless GrowthEvo policy explicitly depends on it.

## What VSA does not prove

A VSA does not protect against compromise of the trusted verifier itself. That is why verifier identity and signing identity are a local root-of-trust pair and why Build-level delegation is capped per verifier.

A VSA also does not prove causal model quality, online treatment safety, legal compliance, or final promotion success. Those remain independent authorities in the Phase-14 evidence manifest.

## Recommended production deployment

A production control plane should run Phase-18 verification in an isolated verification service, sign the resulting canonical VSA with a purpose-limited identity, publish the VSA next to the immutable artifact, and configure consuming GrowthEvo deployments with a small exact `(signer, verifier.id)` root of trust.

For final promotion, require both the behavioral/causal authorities and either direct Phase-18 build evidence or an explicitly approved Phase-19 delegated VSA authority. Do not silently treat the two evidence types as interchangeable; the manifest policy must name the accepted evidence type and verifier producer explicitly.
