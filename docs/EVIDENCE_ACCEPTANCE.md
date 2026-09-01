# Full-Data Evidence Acceptance Handoff

This document covers the boundary between a successful manual full-data workflow artifact and a new persisted accepted-evidence directory in the repository.

It does **not** decide whether a result should be promoted. Statistical eligibility still follows the preregistration, validation-only selection, frozen-winner, one-shot holdout, uncertainty/support, and research-rerun policies. This procedure starts only after a full-data run is scientifically admissible and has completed successfully.

## Why this boundary is separate

GrowthEvo has two different integrity layers:

1. A successful full-data workflow writes `evidence-integrity.json`, which SHA-256 binds the files in that workflow artifact.
2. Persisted accepted evidence is protected after commit by `benchmarks/accepted-evidence-integrity.v1.json`, which binds repository paths to exact Git blob identities.

Those layers protect different moments. The acceptance handoff must additionally prove that the files copied or compacted into a proposed accepted-evidence directory came from the verified workflow bundle rather than from another run, an edited local copy, or an incomplete subset.

## Required acceptance metadata

A proposed `evidence-metadata.json` must retain the workflow run/artifact identity and its GitHub-reported artifact digest according to the repository's evidence-record schema. Before extraction, compare that recorded `workflow_artifact_digest` with the digest reported for the downloaded GitHub Actions artifact.

For the extracted bundle, `source_artifact_file_sha256` and `persisted_copy_format` must cover **every file named by `evidence-integrity.json` exactly once**. No source file may disappear from the acceptance record merely because it is not persisted in the repository.

Each file must use one of these explicit copy contracts:

- `byte-identical ...`: the persisted file must have the exact source bytes, size, and SHA-256.
- `content-preserving compact JSON ...`: JSON whitespace/layout may change, but parsed JSON content must be exactly equal to the source artifact.
- `not persisted ...`: the source file remains workflow-artifact evidence only, and no same-named persisted file may appear in the accepted-evidence directory.

The current full-data workflow bundles use unique basenames for their integrity-manifest files. The acceptance verifier rejects duplicate basenames rather than guessing which source file a metadata entry refers to.

## Verification procedure

After downloading and extracting the successful workflow artifact, prepare the proposed persisted evidence directory and its `evidence-metadata.json`. Then run:

```bash
python scripts/verify_evidence_acceptance.py \
  --source-root /path/to/extracted-workflow-artifact \
  --integrity-manifest /path/to/extracted-workflow-artifact/evidence-integrity.json \
  --persisted-root benchmarks/.../results/.../<evidence-id> \
  --metadata benchmarks/.../results/.../<evidence-id>/evidence-metadata.json
```

The verifier fails closed if:

- the source bundle no longer matches `evidence-integrity.json`;
- acceptance metadata omits or adds a source file;
- a metadata SHA-256 disagrees with the verified source manifest;
- a byte-identical persisted copy differs in bytes or size;
- a compact JSON copy differs semantically;
- a file declared `not persisted` is nevertheless present;
- a copy mode is unknown;
- `locked-result.json` or `source-provenance.json` disagrees with the metadata evidence commit.

A successful verifier run is necessary but not sufficient for promotion. Review must also confirm that the recorded GitHub workflow run/artifact IDs and `workflow_artifact_digest` refer to the intended successful manual run, and that the experiment is scientifically admissible under `docs/RESEARCH_RERUN_POLICY.md`.

## Persisting and sealing

Only after the acceptance handoff verifies should a PR add or update a promoted accepted-evidence set and its repository seal. The PR must keep the accepted machine-readable record explicit, update `benchmarks/accepted-evidence-integrity.v1.json` for the new accepted file set, and pass:

```bash
python scripts/verify_accepted_evidence_integrity.py
```

That final verifier is intentionally different from the acceptance-handoff verifier: it proves that the accepted files in the commit/worktree exactly match the repository's Git-blob seal after persistence.

Historical accepted Criteo and OBD evidence predate the current full-data `evidence-integrity.json` workflow bundle format. They remain governed by their existing `evidence-metadata.json`, persisted-evidence tests, and the global accepted-evidence Git-blob seal; this handoff procedure is for future accepted full-data evidence rather than a retroactive rewrite of historical records.
