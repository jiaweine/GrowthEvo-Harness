# Full-Data Evidence Acceptance Handoff

This document covers the boundary between a successful manual full-data workflow artifact and a new persisted accepted-evidence directory in the repository.

It does **not** decide whether a result should be promoted. Statistical eligibility still follows the preregistration, validation-only selection, frozen-winner, one-shot holdout, uncertainty/support, and research-rerun policies. This procedure starts only after a full-data run is scientifically admissible and has completed successfully.

## Why this boundary is separate

GrowthEvo has two different integrity layers:

1. A successful full-data workflow writes `evidence-integrity.json`, which SHA-256 binds the files in that workflow artifact.
2. Persisted accepted evidence is protected after commit by `benchmarks/accepted-evidence-integrity.v1.json`, which binds repository paths to exact Git blob identities.

Those layers protect different moments. The acceptance handoff must additionally prove that the files copied or compacted into a proposed accepted-evidence directory came from the verified workflow bundle rather than from another run, an edited local copy, or an incomplete subset. It must also bind the proposed acceptance record to the manual dispatch identity already captured inside that hashed workflow bundle and to the run/artifact identity reported by GitHub Actions itself.

## Required acceptance metadata

A proposed `evidence-metadata.json` must retain positive-integer `workflow_run_id` and `workflow_artifact_id` values plus the GitHub-reported `workflow_artifact_digest` according to the repository's evidence-record schema.

The extracted bundle must contain `dispatch-provenance.json`, and that file must be covered by `evidence-integrity.json`. The acceptance verifier requires the dispatch provenance to record:

- schema `growthevo.research-dispatch.v1` and `event_name=workflow_dispatch`;
- an evidence commit equal to both the workflow SHA and the reviewed PR merge SHA;
- successful trusted-main ancestry and workflow-SHA checks;
- `reviewed_ci_verified=true` and a reviewed PR base equal to the trusted branch;
- a dispatch `run_id` equal to metadata `workflow_run_id`.

The source-bundle verifier can therefore prove that the proposed metadata refers to the same run/commit identity recorded inside the already-hashed bundle. Platform-assigned artifact identity is verified separately against GitHub Actions rather than trusted from hand-entered metadata.

For the extracted bundle, `source_artifact_file_sha256` and `persisted_copy_format` must cover **every file named by `evidence-integrity.json` exactly once**. No source file may disappear from the acceptance record merely because it is not persisted in the repository.

Each file must use one of these explicit copy contracts:

- `byte-identical ...`: the persisted file must have the exact source bytes, size, and SHA-256.
- `content-preserving compact JSON ...`: JSON whitespace/layout may change, but parsed JSON content must be exactly equal to the source artifact.
- `not persisted ...`: the source file remains workflow-artifact evidence only, and no same-named persisted file may appear in the accepted-evidence directory.

The current full-data workflow bundles use unique basenames for their integrity-manifest files. The acceptance verifier rejects duplicate basenames rather than guessing which source file a metadata entry refers to.

## Verify GitHub run and artifact identity

Before accepting the extracted bundle, query GitHub Actions using the exact workflow path and artifact name for the benchmark. The verifier is read-only: it does not download the artifact, trigger a workflow, modify metadata, or promote evidence.

For Criteo:

```bash
python scripts/verify_evidence_artifact_identity.py \
  --metadata benchmarks/.../results/.../<evidence-id>/evidence-metadata.json \
  --repository jiaweine/GrowthEvo-Harness \
  --workflow-path .github/workflows/full-criteo-pr-validation.yml \
  --artifact-name criteo-full-preregistered-evidence
```

For Open Bandit:

```bash
python scripts/verify_evidence_artifact_identity.py \
  --metadata benchmarks/.../results/.../<evidence-id>/evidence-metadata.json \
  --repository jiaweine/GrowthEvo-Harness \
  --workflow-path .github/workflows/full-obd-pr-validation.yml \
  --artifact-name obd-full-preregistered-evidence
```

Set `GITHUB_TOKEN` when available for authenticated API access. The verifier fails closed unless GitHub reports that:

- metadata `workflow_run_id` is a completed successful `workflow_dispatch` run in the requested repository;
- the run `head_sha` equals metadata `evidence_commit_sha`;
- the run used the exact expected full-data workflow path;
- metadata `workflow_artifact_id` names the exact expected artifact from that run;
- the artifact is not expired;
- the platform-reported artifact digest exactly equals metadata `workflow_artifact_digest`;
- the artifact's embedded run/repository/commit provenance agrees with the workflow run.

This check is intentionally for **future** accepted evidence produced by the current manual-dispatch workflows. Historical accepted Criteo and OBD evidence were produced under earlier workflow policies and are not retroactively required to satisfy `event_name=workflow_dispatch`.

## Verify the extracted bundle and persisted copies

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
- `dispatch-provenance.json` is missing from the hashed source bundle or does not describe an approved manual dispatch;
- metadata `workflow_run_id` differs from the hashed dispatch run ID;
- the dispatch commit/workflow/reviewed-merge identity differs from metadata `evidence_commit_sha`;
- metadata omits or adds a source file;
- a metadata SHA-256 disagrees with the verified source manifest;
- a byte-identical persisted copy differs in bytes or size;
- a compact JSON copy differs semantically;
- a file declared `not persisted` is nevertheless present;
- a copy mode is unknown;
- `locked-result.json` or `source-provenance.json` disagrees with the metadata evidence commit.

Both the GitHub platform identity check and the extracted-bundle acceptance check are necessary but not sufficient for promotion. The experiment must still be scientifically admissible under `docs/RESEARCH_RERUN_POLICY.md`.

## Persisting and sealing

Only after the acceptance handoff verifies should a PR add a promoted accepted-evidence set and extend the repository seal. The seal update is append-only: historical sealed evidence must remain byte-for-byte and blob-for-blob valid rather than being refreshed to whatever happens to be in the worktree.

Stage every file that belongs to the new accepted evidence set, including any already tracked preregistration/config file that should become part of that set. Then append the new set explicitly:

```bash
git add benchmarks/.../results/.../<evidence-id>/... benchmarks/.../plan-or-config.json
python scripts/append_accepted_evidence_seal.py \
  --name '<benchmark>/<evidence-id>' \
  benchmarks/.../plan-or-config.json \
  benchmarks/.../results/.../<evidence-id>/environment.txt \
  benchmarks/.../results/.../<evidence-id>/evidence-metadata.json \
  benchmarks/.../results/.../<evidence-id>/export-manifest.json \
  benchmarks/.../results/.../<evidence-id>/locked-result.json \
  benchmarks/.../results/.../<evidence-id>/source-provenance.json
git add benchmarks/accepted-evidence-integrity.v1.json
```

The append-only writer first requires the starting seal manifest itself to match `HEAD` exactly and runs the existing accepted-evidence verifier over every historical sealed file. It then rejects duplicate set names, already sealed paths, missing/non-regular index entries, and any candidate whose Git index blob differs from its worktree blob. It has no mode for resealing or refreshing an existing set. The explicit file list remains a reviewable inventory rather than being inferred from a directory glob.

The writer does **not** accept or promote evidence. It only records the exact Git blob identities of an already reviewed, already staged proposed evidence set. Review the resulting seal diff, then commit the evidence files and seal together. The PR must pass:

```bash
python scripts/verify_accepted_evidence_integrity.py
```

That final verifier is intentionally different from the acceptance-handoff verifier: it proves that the accepted files in the commit/worktree exactly match the repository's Git-blob seal after persistence.

Historical accepted Criteo and OBD evidence predate the current full-data `evidence-integrity.json` workflow bundle format. They remain governed by their existing `evidence-metadata.json`, persisted-evidence tests, and the global accepted-evidence Git-blob seal; this handoff procedure is for future accepted full-data evidence rather than a retroactive rewrite of historical records.
