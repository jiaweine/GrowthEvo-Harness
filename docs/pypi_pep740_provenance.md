# PyPI PEP 740 release provenance

## Scope

This layer verifies a Python distribution against PyPI's PEP 740 provenance and an exact GitHub Trusted Publisher identity. It is deliberately separate from GrowthEvo's signed promotion-authority attestation layer.

The two statements answer different questions:

- Phase 15: *who signed this GrowthEvo promotion-authority claim?*
- Phase 17: *was this exact Python distribution published through the expected PyPI Trusted Publisher, and which source repository/workflow/commit did the verified publishing certificate identify?*

A cryptographically valid statement about one subject cannot be reused as evidence about the other subject.

## Standards and implementation

PyPI's Integrity API is the index implementation of PEP 740. A provenance object groups one or more attestations by Trusted Publisher identity.

GrowthEvo v1 pins the public `pypi-attestations` library at `0.0.30` and the underlying `sigstore` verifier at `4.5.0` through the optional `attestation-pypi` extra. Base GrowthEvo installation remains dependency-free.

The verifier uses public `pypi-attestations` APIs:

- `Provenance.model_validate_json(...)`;
- `Distribution(...)`;
- `GitHubPublisher`;
- `Attestation.verify(identity=publisher, dist=distribution, offline=True)`.

The upstream library converts the PEP 740 attestation into a Sigstore bundle, verifies it with the Sigstore production verifier and the Trusted Publisher policy, then verifies the in-toto subject filename/digest and predicate type against the supplied distribution contract.

## Frozen verification contract

`PyPIPublishProvenanceSpec` fingerprints:

- exact distribution filename;
- exact SHA-256 digest;
- GitHub owner/repository slug;
- workflow filename;
- optional expected source commit SHA;
- required predicate type;
- exact `pypi-attestations` version;
- offline/online trust-root mode;
- provenance size limit;
- transparency-entry cardinality policy.

Changing any of these creates a new verifier identity.

## Fail-closed parsing

Before invoking the PEP 740 library, GrowthEvo:

1. requires non-empty UTF-8 JSON;
2. rejects duplicate JSON keys;
3. enforces a preregistered provenance byte limit;
4. requires the pinned `pypi-attestations` version.

Duplicate-key rejection is intentional. A signature/provenance parser and an authorization parser must not be allowed to interpret the same JSON object differently.

## Trusted Publisher selection

Version 1 supports GitHub Trusted Publishing for release-channel evidence.

The provenance must contain exactly one publisher bundle matching:

- `repository == expected_repository`;
- `workflow == expected_workflow`.

Unrelated publisher bundles may coexist in a provenance object, but duplicate matching bundles are rejected as ambiguous.

The publisher object is then passed directly into `Attestation.verify(...)`. The pypi-attestations GitHub policy cryptographically verifies the GitHub OIDC issuer, source repository URI and workflow Build Config URI against the signing certificate.

GrowthEvo does not trust the publisher JSON by itself.

## Predicate selection

The default and reference v1 predicate is:

`https://docs.pypi.org/attestations/publish/v1`

Exactly one attestation with the required predicate must verify successfully inside the selected publisher bundle.

Other predicates, such as SLSA Provenance, are not silently interpreted as PyPI Publish evidence and vice versa.

## Distribution binding

The verifier supplies an exact distribution filename and SHA-256 digest to `Attestation.verify(...)`.

The upstream verifier requires the signed in-toto subject to match the Python distribution name and content digest. GrowthEvo therefore never treats a project/version label as sufficient identity for a wheel or sdist.

## Source commit binding

After cryptographic verification GrowthEvo reads the verified Fulcio certificate claims already exposed by `pypi-attestations`:

- Source Repository URI;
- Source Repository Digest;
- Build Config URI.

The repository URI must be exactly:

`https://github.com/<expected_repository>`

The Build Config URI must identify the exact expected workflow.

When `expected_source_commit_sha` is registered, the verified Source Repository Digest must match it exactly.

This additional check is what permits external release evidence to be composed with a GrowthEvo promotion subject later.

## Release authority conversion

`VerifiedPyPIProvenance.to_release_authority_evidence(...)` creates Phase-14 `AuthorityEvidence` only when:

`verified_source_repository_digest == PromotionSubject.commit_sha`

The resulting evidence type is fixed to:

`pypi_publish_provenance.v1`

The evidence producer is the verified Trusted Publisher identity, the artifact fingerprint is the complete verified-provenance fingerprint, and the source-chain head is the transparency-log fingerprint.

The Phase-14 policy still decides whether this authority is required for `enter_canary`, `advance_stage`, or `final_promotion`.

The verifier itself grants no production authority.

## Important semantic limit

A PyPI Publish attestation proves release-channel integrity: an exact distribution was uploaded using a particular Trusted Publisher identity.

It does **not** by itself prove that the distribution bytes were reproducibly built from the source commit named in the publishing certificate.

A stronger source-to-binary claim requires a separately verified build provenance, for example a suitable SLSA Provenance predicate and policy. GrowthEvo therefore names this evidence `pypi_publish_provenance`, not `reproducible_build_provenance`.

## Transparency evidence

The reference contract requires one transparency-log entry. `pypi-attestations`/Sigstore verifies the cryptographic bundle and inclusion material; GrowthEvo fingerprints the verified certificate plus transparency entry into the resulting evidence.

A future verifier may support multiple independently verified log entries under a newly fingerprinted protocol. V1 rejects ambiguous cardinality instead of silently ignoring extra material.

## Real public integration fixture

GrowthEvo includes a dedicated main-target workflow that performs a real public verification against:

- project: `pypi-attestations`;
- version: `0.0.30`;
- file: `pypi_attestations-0.0.30-py3-none-any.whl`;
- SHA-256: `b3a9c53f6cb89e5e7b5b70e6cfca97cfc66008c1ed54087355e06e40071cef21`;
- publisher repository: `pypi/pypi-attestations`;
- workflow: `release.yml`;
- source tag commit: `845bfac2f2912912fb2d1ab96775ac75708279c4`.

The workflow downloads the fixed wheel, checks its SHA-256, obtains live provenance from the PyPI Integrity API, and then performs offline cryptographic verification using the pinned local trust stack.

The provenance JSON itself is not pinned by SHA-256 because PEP 740 explicitly allows an index to add attestations or signing identities to provenance after upload. The security anchors are the exact distribution digest, required predicate, expected publisher, verified certificate claims and cryptographic transparency evidence.

## Network boundary

Only the dedicated integration workflow fetches the public wheel and PyPI provenance. Normal unit tests and the base runtime do not perform network requests.

Once the wheel/provenance bytes are fetched, cryptographic verification is invoked with `offline=True`; the Sigstore verifier must use its local/baked-in trust root rather than refreshing trust metadata during the verification step.

## Tests

Unit tests cover:

- verifier fingerprint sensitivity;
- invalid distribution and digest contracts;
- duplicate JSON keys;
- provenance size limits;
- wrong and ambiguous publishers;
- cryptographic verification failure;
- source repository URI mismatch;
- source commit mismatch;
- workflow claim mismatch;
- predicate ambiguity;
- transparency-log cardinality;
- dependency version drift;
- Phase-14 conversion and cross-commit replay rejection.

The dedicated real-fixture workflow then validates the current public API and cryptographic path end to end.

## Non-goals

This phase does not:

- make PyPI attestations mandatory for GrowthEvo runtime execution;
- claim a PyPI Publish predicate is a reproducible-build proof;
- use PyPI provenance as a Phase-15 promotion-authority signature;
- trust PyPI publisher metadata without cryptographic certificate verification;
- make network access part of the baseline runtime;
- automatically authorize promotion.
