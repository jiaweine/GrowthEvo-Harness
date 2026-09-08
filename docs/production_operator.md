# Production operator surface

GrowthEvo's library APIs intentionally separate semantic LLM proposals, causal evaluation, and online promotion. The production operator surface adds a thin executable layer over those existing typed contracts. It does **not** add a second policy engine and it does not grant an LLM direct execution authority.

## Safety boundary

The operator path preserves the same authority split as the core runtime:

```text
non-secret candidate manifest
        |
        v
offline candidate fingerprint
        |
        v
provider shadow proposal
        |
        v
validation causal evidence
        |
        v
freeze one winner
        |
        v
open holdout causal evidence
        |
        v
one-shot locked holdout
        |
        v
promotion-eligible artifact (only when Tier A/B gates pass)
```

The manifest never contains provider credentials. Provider SDKs obtain authentication through their normal environment or workload-identity mechanism. Raw secrets are neither accepted by the manifest schema nor included in fingerprints or output artifacts.

The LLM still proposes only a semantic `GrowthOption`. Channel, offer, budget, frequency, creative, send time, legal constraints, numeric policy and eventual execution remain outside the LLM proposal plane.

## CLI

After installation:

```bash
growthevo-operator --help
```

### 1. Validate and fingerprint a manifest

```bash
growthevo-operator validate \
  --manifest examples/operator_manifest.example.json
```

This command is deliberately offline. It does not import provider SDKs, read credentials, or send network requests. It produces the exact candidate contract fingerprints plus the LLM plan, shadow plan and operator-manifest fingerprints that should be reviewed before a real benchmark is run.

A model name by itself is not candidate identity. Changing a prompt/schema threshold, critic posture, provider endpoint behavior, reasoning effort, or other behavior-defining field creates a different contract fingerprint.

### 2. Freeze context fingerprints before causal labels

Planner-visible benchmark contexts and evaluator-only causal labels are stored separately.

```bash
growthevo-operator context-fingerprints \
  --contexts validation-contexts.json \
  --output validation-context-fingerprints.json

growthevo-operator context-fingerprints \
  --contexts holdout-contexts.json \
  --output holdout-context-fingerprints.json
```

The output contains only case IDs and context fingerprints. It deliberately does not echo `user_id` or other planner context fields. Evidence bundles must bind to these exact fingerprints.

### 3. Provider readiness doctor

```bash
growthevo-operator doctor \
  --manifest operator-manifest.json
```

The default doctor checks whether the requested provider SDK modules are installed. It does not instantiate clients and does not make model requests.

To additionally test provider-client construction using the deployment environment's normal authentication mechanism:

```bash
growthevo-operator doctor \
  --manifest operator-manifest.json \
  --instantiate
```

Even with `--instantiate`, the doctor does not send a model request and does not log credential values. A client-construction failure is reported only by exception type.

### 4. Locked shadow run

Use physically separate files for validation contexts/evidence and holdout contexts/evidence:

```bash
growthevo-operator shadow-run \
  --manifest operator-manifest.json \
  --validation-contexts validation-contexts.json \
  --validation-evidence validation-evidence.json \
  --holdout-contexts holdout-contexts.json \
  --holdout-evidence holdout-evidence.json \
  --commit-sha "$DEPLOYED_CODE_SHA" \
  --output locked-llm-shadow-result.json
```

The operator uses `DeferredFileCausalEvidenceProducer`. Validation evidence is opened first and all declared candidates are evaluated there. The existing locked protocol freezes exactly one winner. Only then is the holdout evidence file opened, and only the frozen winner is invoked on holdout.

The command also verifies that the runtime candidate identity exactly matches the preregistered offline identity. A provider/harness configuration drift therefore fails before its output can become a locked artifact.

## Evidence policy

`require_promotion_evidence: true` means only Tier A randomized evidence or Tier B explicitly pre-registered OPE evidence can participate in promotion-grade scoring. Tier C model-based and Tier D proxy labels are diagnostic-only.

Do not relabel a public benchmark treatment arm as a semantic `GrowthOption` merely to make a model eligible. The semantic treatment mapping must come from the upstream experiment/OPE protocol and must be bound to its own source and protocol fingerprint.

The example manifest contains placeholder model names on purpose. Replace them with pinned deployment snapshots before preregistration. The repository does not claim that any particular GPT, Claude, or Gemini snapshot wins your product benchmark.

## Offline smoke demo

```bash
python examples/production_operator_demo.py
```

The demo uses fake provider transports and synthetic contract evidence so it is deterministic and requires no credentials or network access. It verifies that:

- the candidate with better hidden causal evidence wins validation;
- the holdout is still one-shot;
- the resulting artifact can become promotion-eligible under Tier-A-shaped test evidence;
- shadow runtime behavior remains the deterministic baseline;
- no claim is made about a real provider model.

## File schemas

See [`operator_file_schemas.md`](operator_file_schemas.md) for the exact JSON envelopes used by the operator surface.

## Repository-governance boundary

The operator surface closes an in-repository usability gap; it cannot configure GitHub repository administration.

As of the project-completion audit, repository issue **#63 — Protect main with the CI evidence gates** remains the canonical external governance blocker. `main` is not considered server-side protected until an active GitHub branch ruleset requires the normal PR path and the six GrowthEvo CI contexts, and blocks force-push/deletion as specified in that issue.

Do not replace that server-side control with a code comment, documentation promise, or client-side hook. Repository governance is a separate administrative control plane.
