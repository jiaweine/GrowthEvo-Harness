# GrowthEvo-Harness project completion status

This document defines the engineering completion boundary of the guarded LLM + causal decision + production promotion architecture. It distinguishes **implemented and validated framework capabilities** from **deployment facts and repository-administration controls that must come from an external environment**.

## Completed architecture

### Original causal/RL runtime remains authoritative

The original runtime contract is preserved:

`goal -> belief -> semantic objective -> numeric hierarchical policy -> legal action gate -> world model -> causal reward -> audit integrity`

The LLM does not choose channel, offer, budget, frequency, send time or bypass legal policy.

### Guarded LLM proposal plane

Implemented:

- provider-neutral structured semantic planner;
- OpenAI / Anthropic / Gemini adapters;
- strict schema and enum validation;
- redacted context;
- local confidence gates;
- optional veto-only critic;
- deterministic fallback;
- circuit breaker;
- shadow mode;
- stable planner contract fingerprints;
- adversarial prompt/schema tests.

### Locked LLM causal benchmark

Implemented:

- provider/model candidate identities;
- hidden causal option evidence;
- validation winner selection;
- one-shot holdout hygiene;
- causal lower-confidence-bound promotion gates;
- Tier A randomized and Tier B pre-registered OPE evidence;
- diagnostic-only lower evidence tiers;
- strict separation of LLM behavioral evaluation from causal promotion evidence.

### Production operator surface

Implemented:

- `growthevo-operator` CLI over the existing typed benchmark contracts;
- strict non-secret operator manifest;
- SDK/credential-free candidate preregistration and model+harness fingerprints;
- physically separate planner-visible context files and evaluator-only evidence files;
- exact context fingerprints;
- validation/holdout split identity checks;
- deferred holdout evidence loading until after validation winner freeze;
- runtime candidate identity re-verification;
- provider SDK readiness doctor with no model request;
- deterministic offline operator smoke demo with fake transports;
- strict file-schema documentation and tests.

This layer does not duplicate promotion logic and cannot turn a diagnostic run into promotion evidence. The existing locked protocol remains authoritative.

### Real causal benchmark integration

Implemented:

- locked OPE protocol;
- Open Bandit Dataset integration;
- compact cross-fitted Q estimation;
- support / effective-sample gates;
- experiment-plan fingerprints;
- accepted evidence seal;
- regression contract;
- multi-Python CI and clean-package checks.

### Safe randomized online canary

Implemented:

- stable two-hash routing;
- fixed challenger propensity;
- staged traffic fractions;
- exact route re-verification on matured outcomes;
- one randomized analysis unit / cluster contribution;
- bounded Horvitz-Thompson treatment-control effects;
- anytime-valid safety e-processes;
- relative and absolute guardrails;
- deterministic cumulative-cost kill switch;
- immediate rollback;
- final promotion only after statistical success.

### High-power sequential inference

Implemented:

- frozen pre-experiment CUPED adjustment;
- pre-registered group-sequential primary-success looks;
- conservative alpha spending;
- delayed-outcome exposure tickets;
- original exposure-stage binding;
- no repeated-user pseudo-independence;
- no off-schedule primary peeking;
- final-stage planned success gate.

### Promotion evidence authority composition

Implemented:

- exact `PromotionSubject` identity;
- independent authority statements;
- transition scopes;
- logical evidence epochs;
- append-only hash-chain ledger;
- sticky blocks and vetoes;
- canonical latest-evidence manifests;
- stale-manifest rejection;
- policy fingerprints;
- transition-specific `ENTER_CANARY`, `ADVANCE_STAGE`, `FINAL_PROMOTION` authority.

### Signed promotion authority

Implemented:

- canonical in-toto/DSSE GrowthEvo authority statements;
- exact subject/predicate parsing;
- signer/issuer/verifier allowlists;
- trusted timestamp and transparency requirements;
- cryptographic verifier protocol boundary.

### Real Sigstore authority verifier

Implemented:

- pinned Sigstore SDK adapter;
- current bundle-v0.3 validation;
- exact DSSE envelope binding before and after verification;
- identity policy;
- transparency/trusted-time provenance;
- real SDK CI contract.

### Real PyPI PEP 740 release provenance

Implemented and validated against a real public fixture:

- exact wheel/sdist digest;
- live PyPI Integrity API provenance;
- PyPI Trusted Publisher identity;
- Fulcio source repository/workflow/commit claims;
- Sigstore/transparency cryptographic verification;
- source-commit binding before release evidence can authorize a GrowthEvo subject.

Publish provenance is deliberately not misrepresented as build provenance.

### SLSA Build Provenance

Implemented and validated against a real public Rez release fixture:

- SLSA Provenance v1 predicate;
- exact artifact subject;
- exact GitHub Actions workflow build type;
- exact external parameters;
- exact source resolved dependency / commit;
- exact builder identity;
- local signer/builder root of trust;
- local maximum trusted SLSA Build level.

A valid signature cannot self-upgrade to a higher SLSA level.

### SLSA VSA delegated verification

Implemented:

- canonical SLSA Verification Summary Attestation producer;
- `PASSED` verification summary;
- explicit Build level;
- input provenance binding;
- no transitive dependency-level overclaim;
- signer + verifier-id delegated trust pair;
- policy/resource/artifact checks;
- exact maximum delegated Build level;
- cross-commit replay protection;
- conversion to separate delegated supply-chain authority.

### Governed production promotion

Implemented:

- manifest gate before first exposure;
- manifest gate before stage ramp;
- manifest gate before final champion replacement;
- unconditional safety rollback;
- pending transition state;
- authority-only re-evaluation after evidence arrives;
- no extra outcomes after the final planned statistical analysis merely to wait for governance;
- aggregate governance audit events.

The original ungoverned controller remains available and unchanged; governance is explicit opt-in.

### Strict production authority profile

Implemented:

- exact `(evidence type, protocol fingerprint, producer)` evidence contracts;
- true OR alternatives for direct SLSA vs delegated VSA;
- no cross-product allowlist ambiguity;
- production composition for offline causal, integrity, maturity, online safety, primary success and supply chain;
- typed online-safety evidence emitter;
- typed group-sequential primary-success evidence emitter;
- first-exposure supply-chain requirement;
- complete governed lifecycle test.

## Production path

The closed in-code path is:

```text
untrusted product context
        |
        v
guarded semantic LLM proposal
        |
        v
original numeric RL / legal gate
        |
        v
locked causal validation + one-shot holdout
        |
        v
promotion-eligible immutable candidate
        |
        +---- release / build provenance verification
        |             |
        |             +-- PEP 740
        |             +-- SLSA Build Provenance
        |             +-- optional signed VSA delegation
        |
        v
strict ENTER_CANARY authority manifest
        |
        v
stable randomized canary
        |
        v
anytime-valid safety + planned primary inference
        |
        +-- typed safety authority
        +-- typed primary-success authority
        |
        v
strict ADVANCE / FINAL authority manifests
        |
        v
champion replacement
```

At every point, rollback and no-treatment remain safer fail-closed outcomes.

## What is not claimed

The repository does **not** claim that a particular GPT, Claude or Gemini snapshot is the real-world winner for a specific product.

That claim requires deployment-specific evidence that cannot be synthesized by repository code:

- real credentials and pinned model snapshots;
- real product contexts;
- semantic `GrowthOption` Tier-A randomized evidence or explicitly pre-registered Tier-B OPE mapping;
- actual consent/legal/budget configuration;
- real rollout metric distributions and maturity windows.

The repository contains the machinery to run that comparison and promotion safely once those inputs exist. It deliberately refuses to invent the result.

## External production configuration still required

Before a real deployment, operators must freeze:

- model endpoints and snapshots;
- planner contract and critic choice;
- real causal evidence producer;
- legal/consent policy;
- canary traffic fractions;
- metric bounds and non-inferiority margins;
- group-sequential expected sample / looks;
- pre-experiment CUPED reference, when used;
- integrity producer;
- maturity/censoring producer;
- trusted supply-chain builders or VSA verifiers;
- signing identities and KMS/HSM/Sigstore configuration;
- strict authority-profile contract tuples.

Those settings are deliberately deployment-owned and fingerprinted; they should not be universal defaults hidden in the framework.

## Repository-governance blocker

The codebase can be engineering-complete while the GitHub repository still has an external administrative control missing.

Issue **#63 — Protect main with the CI evidence gates** is the canonical remaining repository-governance blocker. Completion of that issue requires a real server-side GitHub branch ruleset targeting `main`, with the required GrowthEvo CI contexts and force-push/deletion protection defined in the issue.

Until GitHub itself reports an effective active rule, do **not** describe `main` as protected merely because CI runs after a push. Post-push detection is not equivalent to preventing an invalid direct push from landing.

This control cannot be implemented from code inside the repository and must be applied through an administration-capable GitHub settings/API path.

## Definition of engineering complete

For this repository, the codebase is engineering-complete when the exact candidate head passes:

1. full Python 3.11-3.14 tests;
2. runtime and training smoke tests;
3. production-operator manifest/deferred-evidence/CLI tests and offline smoke test;
4. optional model-provider SDK contract checks;
5. Sigstore SDK contract checks;
6. package build and clean-wheel install, including installed operator CLI;
7. accepted evidence-seal validation;
8. full pinned small-OBD locked-OPE integration;
9. live public PyPI PEP-740 verification;
10. live public SLSA Build Provenance verification;
11. strict production-authority lifecycle tests.

Merge is a separate human-authorized repository action. Deployment and real-model promotion remain deployment-owned evidence decisions. Server-side branch protection is tracked independently by #63 and must not be falsely conflated with in-repository engineering completion.
