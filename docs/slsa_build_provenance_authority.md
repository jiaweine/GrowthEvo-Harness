# SLSA Build Provenance authority

## Scope

This layer verifies SLSA Build Provenance v1 for an exact Python distribution and turns the result into a separately typed Phase-14 build-supply-chain authority statement.

It is intentionally distinct from both preceding evidence planes:

- Phase 15 answers: **who cryptographically signed a GrowthEvo promotion-authority claim?**
- Phase 17 answers: **who published this exact Python distribution through PyPI Trusted Publishing?**
- Phase 18 answers: **does cryptographically verified build provenance say that this exact artifact was produced by a locally trusted builder, from the expected source and external build inputs?**

A valid PyPI Publish attestation is not automatically valid SLSA Build Provenance. A valid SLSA predicate is not automatically trusted at Build L2/L3.

## Current specification

GrowthEvo uses the stable SLSA provenance predicate URI:

`https://slsa.dev/provenance/v1`

SLSA v1.2 is the current Approved specification. The predicate URI intentionally does not encode the minor SLSA version.

The SLSA consumer verification model requires:

1. cryptographically verify provenance and artifact subject;
2. map the authenticated signer/builder pair to a locally trusted SLSA Build level;
3. compare canonical source, `buildType`, and `externalParameters` against expectations;
4. optionally inspect `resolvedDependencies` recursively.

GrowthEvo v1 makes the source dependency check mandatory for its GitHub workflow profile.

## Build level is local policy

`SLSABuilderTrust` maps:

`(verified publisher identity, builder.id) -> max trusted Build level`

The Build level is **not** read from the provenance and is not accepted from a builder's self-description.

A builder that claims L3 but is locally assessed at L2 remains L2.

GitHub's current artifact-attestation documentation states that ordinary artifact attestations provide SLSA Build L2; reaching L3 requires an architecture such as a known, vetted reusable workflow that isolates trusted build instructions. The reference Rez fixture therefore deliberately maps its direct project workflow to L2, not L3.

## GitHub Actions build profile

The current `@actions/attest` toolkit generates SLSA v1 provenance with:

`buildType = https://actions.github.io/buildtypes/workflow/v1`

For the GitHub workflow build type, `externalParameters.workflow` contains:

- `ref`;
- canonical repository URL;
- workflow path.

The source checkout appears in `resolvedDependencies` as:

- URI `git+https://github.com/<owner>/<repo>@<ref>`;
- digest key `gitCommit`.

The builder id is derived from the OIDC `job_workflow_ref`. This is important: GrowthEvo does not substitute a generic `github-hosted` string when the signed provenance identifies a more specific workflow builder.

## Frozen expectation contract

`SLSABuildExpectationSpec` fingerprints:

- exact distribution filename;
- exact distribution SHA-256;
- exact GitHub repository;
- exact publishing/attesting workflow filename;
- exact source ref;
- exact source commit;
- canonical exact `externalParameters` JSON;
- locally trusted signer/builder roots;
- minimum required Build level;
- allowed build types;
- SLSA predicate type;
- pinned `pypi-attestations` version;
- offline verification mode;
- maximum provenance size;
- source-dependency cardinality policy;
- transparency-entry cardinality policy.

Changing any of these values creates a new protocol fingerprint.

## Cryptographic verification boundary

Phase 18 consumes SLSA attestations transported through PyPI PEP 740 provenance.

It delegates cryptographic verification and Trusted Publisher authentication to the pinned `pypi-attestations`/Sigstore stack. The verifier supplies the exact distribution filename and SHA-256 and invokes:

`Attestation.verify(identity=publisher, dist=distribution, offline=True)`

Only after that succeeds does GrowthEvo parse and authorize the SLSA predicate.

## Trusted Publisher and builder are distinct

The signer/publisher identity and `builder.id` are separate security coordinates.

This matches the SLSA model: a signing authority may sign provenance for more than one builder, and consumers must accept only approved signer-builder pairs.

GrowthEvo therefore requires both values to match one `SLSABuilderTrust` root entry.

## Exact artifact subject

The upstream verifier validates the signed in-toto subject against the expected distribution filename and digest.

GrowthEvo never grants build authority from a package name/version alone.

## buildType

`buildType` defines how `externalParameters` are interpreted.

GrowthEvo requires it to be in the frozen allowlist before interpreting the rest of the build definition.

The v1 reference profile permits the current GitHub Actions workflow build type only.

A future build platform must receive its own typed expectations and root-of-trust assessment rather than being accepted because its JSON resembles GitHub's schema.

## externalParameters

The SLSA specification treats `externalParameters` as untrusted inputs that consumers must compare against expectations.

GrowthEvo uses exact canonical JSON equality.

That means all of the following fail:

- unofficial source repository;
- wrong ref;
- wrong workflow path;
- missing expected input;
- one additional unrecognized input field.

There is no permissive `dict.get()` policy that silently ignores unknown external controls.

If a future builder has an external parameter whose arbitrary value is proven safe, that relaxation must be expressed in a separately fingerprinted verification profile.

## Source dependency

For the GitHub Actions workflow build type, GrowthEvo requires one matching source dependency:

`git+https://github.com/<repo>@<expected ref>`

with:

`digest.gitCommit == expected source commit`

By default the match must be unique.

Other resolved dependencies may exist because SLSA does not currently guarantee completeness of that array. GrowthEvo fingerprints the entire verified dependency list for audit, but v1 does not claim that all dependencies have recursively satisfied SLSA policy.

## Internal parameters

GrowthEvo does not use `internalParameters` as a promotion expectation in v1.

Under the SLSA model these are generated inside the trusted build platform and are primarily useful for debugging, incident response, and vulnerability management. The complete predicate is fingerprinted so they remain auditable.

## Authority conversion

`VerifiedSLSABuildProvenance.to_build_authority_evidence(...)` emits Phase-14 evidence type:

`slsa_build_provenance.v1`

only when:

- `PromotionSubject.commit_sha` equals the verified SLSA source commit;
- the locally trusted Build level meets the conversion requirement;
- transition scope is explicitly supplied.

The evidence producer is `builder.id`, not a package name and not the free-form provenance publisher JSON.

The Phase-14 policy still decides whether build provenance is required for canary entry, stage advance, final promotion, or none of those transitions.

## Real public fixture

The dedicated workflow verifies Rez `3.4.0`, whose project documentation explicitly states that every release artifact carries both a SLSA build-provenance attestation generated by GitHub `actions/attest` and a separate PyPI Publish attestation.

Reference artifact:

- file `rez-3.4.0-py3-none-any.whl`;
- SHA-256 `d5f45c2bc759a85f0efd91078f541c1c0455577bf4fd42ca23d645013295bf60`;
- source repository `AcademySoftwareFoundation/rez`;
- source ref `refs/tags/3.4.0`;
- source commit `f19dad25ec9cbb6b0e9f53ff2ec5c964b077912a`;
- workflow `.github/workflows/pypi.yaml`;
- expected builder `https://github.com/AcademySoftwareFoundation/rez/.github/workflows/pypi.yaml@refs/tags/3.4.0`;
- locally trusted Build level: 2.

The Rez workflow shows that artifacts are built in a separate job, downloaded into an `attest-and-publish` job, attested with `actions/attest@v4`, converted to PyPI attestations, and then published. The same SLSA Sigstore bundle is also uploaded to the GitHub release.

The integration workflow downloads the exact wheel from PyPI, verifies its SHA-256, fetches live PyPI Integrity API provenance, cryptographically verifies the SLSA attestation offline, then enforces all GrowthEvo expectations.

## Why this is not automatically L3

Cryptographic provenance authenticity and SLSA Build level are related but different.

GitHub documents ordinary artifact attestations as Build L2. A consumer that needs L3 must configure a builder identity whose architecture has actually been assessed for L3 properties, such as an appropriate trusted reusable workflow with isolation guarantees.

GrowthEvo therefore does not include code such as:

`if signer == GitHub: level = 3`

That would be a privilege escalation disguised as convenience.

## Fail-closed conditions

The verifier rejects:

- malformed or duplicate-key provenance JSON;
- oversized provenance;
- unexpected dependency version;
- missing or multiple matching publisher bundles;
- invalid cryptographic verification;
- missing or multiple SLSA predicates;
- unapproved `buildType`;
- any external-parameter mismatch;
- unknown signer/builder pair;
- insufficient local Build level;
- missing/wrong/ambiguous source dependency;
- missing or ambiguous transparency evidence;
- source commit mismatch during Phase-14 conversion.

## Non-goals

Phase 18 does not:

- infer SLSA level from the predicate itself;
- claim all `resolvedDependencies` are complete;
- recursively verify every transitive dependency;
- treat PyPI Publish provenance as SLSA Build Provenance;
- treat a valid SLSA attestation as proof that the artifact is vulnerability-free;
- automatically authorize GrowthEvo promotion;
- make network access part of the base runtime.

## Future extensions

A later phase can add:

- reusable-workflow roots explicitly assessed at Build L3;
- recursive dependency verification and Verification Summary Attestations;
- GitHub Artifact Attestations API / native Sigstore bundle transport independent of PyPI;
- SLSA Source Track evidence;
- SBOM authority composition;
- signed policy/root distribution.

Each stronger guarantee should create a new typed protocol/fingerprint instead of silently widening this verifier.
