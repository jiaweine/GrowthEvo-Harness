# GrowthEvo-Harness project completion status

This document defines the engineering-completion boundary of GrowthEvo-Harness. It separates three things that must not be conflated:

1. capabilities implemented and validated in repository code;
2. deployment-specific evidence and credentials that only a real environment can supply;
3. GitHub repository settings that require administrator authority outside the codebase.

GrowthEvo keeps one stable product identity. Numbered tokens that remain in locked evidence or schema identifiers are immutable protocol identities required to verify historical artifacts; they are not product generations.

## Engineering-complete architecture

### Causal decision core

Implemented and validated:

- causal belief state separating baseline conversion from incremental treatment effect;
- group-aware cross-fitted Doubly Robust CATE estimation;
- explicit behavior propensities and multi-action support diagnostics;
- practical overlap and distributional-support checks;
- calibrated pessimistic Safe Policy Improvement with cost, support and trust-region constraints;
- `NO_TREATMENT` as a first-class safe fallback;
- DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, cross-fitted β*-IPS and Meta-OPE candidates;
- deterministic stress and numerical-regression gates.

### Locked evidence and benchmark governance

Implemented and validated:

- pre-registered experiment plans and realized manifests;
- validation-only candidate selection and frozen final winners;
- independent final holdout contracts;
- accepted evidence seals and fingerprint chains;
- full Criteo Uplift targeting evidence;
- Open Bandit Dataset locked OPE evidence;
- small-OBD pinned CI integration;
- benchmark cache/raw-data exclusion from public Actions artifacts;
- exact PR-head plus landed-main CI identity gates before full-data research workflows can run.

Locked evidence schema identifiers remain versioned where byte-contract compatibility requires it. That is evidence provenance, not GrowthEvo product versioning.

### Guarded LLM proposal and production operator

Implemented and validated:

- provider-neutral structured semantic planner;
- OpenAI, Anthropic and Gemini adapters;
- strict schema/enum validation and redacted context;
- confidence gates, optional veto-only critic, deterministic fallback and circuit breaker;
- shadow mode and stable planner/model/harness fingerprints;
- non-secret candidate preregistration;
- provider readiness doctor without a model request;
- physically separated planner-visible context and evaluator-only evidence;
- deferred holdout loading until the validation winner is frozen;
- deterministic offline operator smoke path.

The LLM proposal plane cannot bypass numeric policy, legal-action gates or causal promotion evidence.

### Online safety and governed promotion

Implemented and validated:

- stable randomized canary routing;
- fixed challenger propensities and staged traffic fractions;
- exact route re-verification on matured outcomes;
- anytime-valid safety monitoring;
- frozen CUPED reference support;
- pre-registered group-sequential primary looks;
- deterministic cumulative-cost kill switch;
- immediate rollback;
- typed online-safety and primary-success evidence;
- append-only authority ledger and sticky blocks/vetoes;
- `ENTER_CANARY`, `ADVANCE_STAGE` and `FINAL_PROMOTION` authority contracts;
- Sigstore-backed authority verification;
- PyPI PEP 740 provenance verification;
- SLSA Build Provenance and delegated VSA verification.

Algorithmic promotion controllers remain reference components until a deployment supplies real traffic, real outcome collection and real promotion evidence. The repository does not fabricate those facts.

## Product runtime completion

### Web / PWA / mobile product surface

Implemented and validated:

- responsive Growth OS web workspace;
- dashboard, opportunities, campaign studio, experiments, approvals, realtime decisions, harness and evolution workbenches;
- strict API mode with no silent fallback to synthetic data;
- PWA shell whose service worker never masks API failure with cached application HTML/data;
- real-browser API-mode integration tests;
- real-browser fail-closed outage tests;
- Expo / React Native companion application;
- Expo compatibility verification in CI;
- mobile production transport that requires HTTPS for remote APIs.

Synthetic data is limited to explicit Demo Workspace behavior and is labeled as such.

### Stable API identity

Implemented and validated:

- stable `/api/*` public routes without numbered product-generation prefixes;
- bounded request bodies and validated request schemas;
- strict CORS behavior;
- duplicate/blank/oversized `Idempotency-Key` rejection;
- request fingerprints for idempotency conflicts;
- stable reference assignment where recorded propensity equals the actual sampling distribution;
- API outage behavior that fails closed instead of displaying demo data.

### Durable PostgreSQL state

Implemented and validated with real PostgreSQL in CI:

- durable decision log;
- durable idempotency state;
- durable Campaign and Approval state;
- migrations on runtime initialization;
- transactional same-key idempotency across multiple app instances;
- bounded expired-idempotency cleanup;
- restart recovery;
- multi-replica concurrency checks;
- real API verification against restored state.

### OIDC / JWKS authentication

Implemented and validated in a real production-container CI path:

- explicit issuer + JWKS URL + audience trust contract;
- signed Bearer verification with restricted algorithms;
- issuer, audience, expiry and signature checks;
- duplicate Authorization rejection;
- JWKS redirect rejection;
- bounded unknown-key refresh behavior;
- IdP/JWKS outage returns 503 fail-closed rather than silently bypassing authentication;
- CORS preflight works without requiring a Bearer token while business requests remain authenticated;
- production readiness requires both durable persistence and active authentication.

The repository deliberately does not claim generic OIDC discovery when the configured contract is explicit issuer/JWKS/audience.

### Self-hosting and disaster recovery

Implemented and validated:

- pinned PostgreSQL and GrowthEvo Docker Compose stack;
- PostgreSQL volume persistence;
- loopback-only API exposure by default;
- blank required database credentials in the environment template so a copied template fails fast until configured;
- custom-format `pg_dump` backups;
- SHA-256 integrity metadata;
- private backup file permissions;
- refusal to overwrite an existing backup destination;
- mandatory checksum validation before restore;
- archive readability preflight before the API is stopped or database objects are changed;
- fail-stopped restore behavior: a failed/invalid recovery does not automatically re-expose partial state;
- clean-database restore verification in CI;
- restored API readiness plus Campaign/Decision state verification.

See `docs/SELF_HOSTING.md` for the operator runbook.

## CI and repository evidence gates

Every pull request targeting `main` now emits stable required-check contexts for the production product and research/runtime stack. The audited merge contract includes:

- Python 3.11, 3.12, 3.13 and 3.14 tests;
- package/build verification;
- OBD integration;
- OIDC/JWKS production-container verification;
- PostgreSQL persistence/recovery verification;
- mixed product stress;
- web and mobile product surface checks;
- `codeql-required` security aggregation;
- SLSA build-provenance verification;
- PyPI PEP 740 provenance verification.

The product stress path also verifies concurrency, idempotency and propensity semantics. Core stress independently exercises CATE, OPE, Safe-PI and evidence-canonicalization workloads.

## What the repository does not claim

Engineering completion does not imply that a deployment has real customer data, credentials or causal evidence.

GrowthEvo does **not** claim that a particular GPT, Claude, Gemini, advertising platform, CRM, warehouse or messaging provider is connected or superior without real deployment evidence.

Real deployment still owns:

- provider credentials and pinned model snapshots;
- organization/workspace identity data;
- actual legal/consent/budget rules;
- real product contexts and outcome streams;
- real canary traffic and maturity windows;
- deployment-specific metric bounds and non-inferiority margins;
- real causal evidence producers;
- external storage/provider credentials;
- production signing/KMS/HSM identities where used.

Those inputs are intentionally not replaced by fake connectors or synthetic production claims.

## Remaining external administrator actions

At the repository-code level, the project is engineering-complete. Two GitHub-hosted settings remain external administrator actions and are intentionally tracked separately.

### #63 — Protect `main` with the CI evidence gates

The repository rulesets API still reports no active ruleset. The audited 14-check ruleset, strict status-check configuration, PR-only merge contract and force-push/deletion protection are documented in issue #63.

Until GitHub itself reports the active rule, do **not** describe `main` as server-side protected merely because post-push CI is green.

### #137 — Enable GitHub Pages deployment

The Pages workflow is already bootstrap-safe and validates the static Web/PWA artifact. Repository Pages publishing is not enabled with GitHub Actions as the source, so configure/upload/deploy steps remain skipped.

Enabling that setting requires repository administration/pages write authority that the connected automation does not possess. Issue #137 contains the one-time administrator action and deployment verification checklist.

These two items are external repository configuration, not missing product code.

## Definition of engineering complete

A candidate head is engineering-complete when it passes the repository's complete merge evidence, including:

1. Python 3.11-3.14 runtime/research tests;
2. package build and clean install;
3. OBD integration and accepted evidence contracts;
4. product API/browser/mobile verification;
5. OIDC/JWKS production-container authentication tests;
6. PostgreSQL persistence, concurrency, restart and recovery tests;
7. product and core stress gates;
8. CodeQL security gate;
9. SLSA Build Provenance verification;
10. PyPI PEP 740 provenance verification;
11. stable product-identity checks;
12. self-hosting/backup/restore contract checks.

Merge is a separate repository action. Real deployment and real-model/policy promotion remain deployment-evidence decisions. Server-side branch protection and Pages enablement are tracked independently by #63 and #137 and must not be falsely conflated with in-repository engineering completion.
