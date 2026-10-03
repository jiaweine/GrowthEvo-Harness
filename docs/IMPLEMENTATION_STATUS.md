# GrowthEvo-Harness · Implementation Status

GrowthEvo-Harness provides an integrated causal decision and product runtime for incremental user growth. The implementation combines causal effect estimation, constrained policy improvement, off-policy evaluation, locked evidence, guarded LLM proposals, durable product state, production authentication, browser/mobile product surfaces, and self-host recovery.

## Current capability snapshot

| Area | Mainline capability |
| --- | --- |
| **Causal state** | Baseline conversion and treatment uplift are represented separately in the Causal Belief State |
| **CATE estimation** | Group-aware cross-fitted Doubly Robust learning with pluggable nuisance/effect learners |
| **Support modeling** | Strict positivity, practical overlap, propensity handling, and distributional-support diagnostics |
| **Safe policy improvement** | Calibrated pessimistic value, conservative cost, TV trust region, support anchoring, and final-feasible ranking |
| **Off-policy evaluation** | Cross-fitted β*-IPS plus DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, and Meta-OPE candidates |
| **Evidence governance** | Pre-registered plans, realized manifests, validation selection, frozen winners, and final holdout artifacts |
| **Verification** | One-sided conformal margins and `PASS / FAIL / INSUFFICIENT_EVIDENCE` verifier semantics |
| **Long-horizon planning** | Stateful stochastic rollout, downside CVaR, stress scenarios, and constraint-aware MPC |
| **Trajectory credit** | Potential shaping, GAE, and dynamics-aware credit boundaries |
| **Benchmark bridges** | Criteo Uplift, Open Bandit Dataset, KuaiRand, and GrowthAgentBench |
| **Optional LLM proposals** | Provider adapters, guarded semantic proposals, shadow candidate factory, model+harness fingerprints |
| **Causal LLM evaluation** | Typed evidence tiers, validation-only candidate selection, deferred one-shot holdout |
| **Online promotion** | Reference randomized canary controllers, continuous safety, frozen CUPED, planned sequential success, rollback and authority evidence |
| **Product API** | Stable `/api/*` FastAPI contract, strict failure behavior, realtime decisions, campaigns, approvals, harness/evolution and decision logs |
| **Durable state** | PostgreSQL-backed decision/idempotency/Campaign/Approval state with migrations, restart recovery and multi-replica concurrency checks |
| **Production authentication** | Explicit OIDC/JWKS trust contract with signed bearer verification, issuer/audience/expiry validation and fail-closed IdP outage handling |
| **Web / PWA** | Responsive Growth OS UI, real-browser API integration, strict outage UI, installable PWA shell |
| **Mobile** | Expo / React Native companion app with official Expo compatibility check, TypeScript gate and production HTTPS transport |
| **Self-hosting** | Pinned Docker Compose runtime, loopback API default, guarded PostgreSQL backup/restore and clean-database recovery CI |
| **Security / supply chain** | CodeQL gate, Sigstore authority verification, SLSA build provenance, PyPI PEP 740 provenance |

## Runtime and decision contracts

- Causal Belief State separates natural conversion from treatment effect.
- Hierarchical planning separates semantic intent from numeric action selection.
- `NO_TREATMENT` / holdout is a first-class action.
- Legal-action gates cover consent, budget, offer limits, fatigue, churn risk, and frequency caps.
- Realtime assignment records the probability distribution actually used to sample the served action.
- Idempotency conflicts are request-fingerprint aware and durable across app instances when PostgreSQL is active.
- Production readiness requires durable PostgreSQL and active authentication; configuration strings alone cannot make the service ready.
- Demo data appears only in explicit Demo Workspace mode and never silently replaces a failed live API.

## Product runtime and operations

The product runtime now has a durable operational path rather than only in-memory UI fixtures:

- Campaign, Approval, Decision and idempotency state can live in PostgreSQL;
- restart and two-replica concurrency are verified in CI;
- bounded expired-idempotency cleanup prevents indefinite key accumulation;
- production requests require valid signed bearer credentials;
- JWKS redirect, malformed key material and IdP outage paths fail closed;
- browser CORS preflight remains usable while authenticated business requests stay protected;
- the self-host stack uses pinned PostgreSQL and application images;
- backup and restore helpers require integrity metadata and refuse unsafe recovery paths;
- a failed restore leaves the API stopped instead of automatically serving possible partial state.

The algorithmic online-promotion controllers remain reference control components. Their canary state and real-world outcome collection are not claimed to be a complete external campaign execution platform. Durable product API state and durable causal-promotion execution are separate concerns.

## Optional LLM and online promotion

The guarded proposal layer supports OpenAI, Anthropic, and Gemini through optional SDK adapters. It proposes semantic growth options; the numeric policy, legal gates, evidence contracts, and promotion authority remain authoritative.

The locked shadow runner binds typed causal evidence to exact model+harness identities, freezes one validation winner, and accesses final holdout evidence afterward. Diagnostic lower-tier results cannot create promotable online candidates.

The online controllers provide stable randomized routing, one outcome per analysis unit, continuous safety monitoring, and hashed aggregate audit events. Advanced inference supports registered first-exposure stages, frozen CUPED and planned primary-success looks. Promotion requires primary and safety gates at the same planned look; invalid mappings or unrepresentable statistics are rejected before state changes.

## Causal learning and serving

The causal stack supports logged multi-action treatment records with full behavior-policy propensity vectors. Pairwise treatment-vs-control propensities are normalized explicitly before out-of-fold AIPW/DR pseudo-outcomes are constructed.

Mainline includes:

- group-aware cross-fitting for repeated users or clusters;
- pluggable nuisance and second-stage effect learners;
- a dependency-light Ridge reference backend;
- separate positivity, overlap, and clipping semantics;
- OOF residual diagnostics;
- regularized Mahalanobis distributional support;
- a serving bridge that maps fitted CATE models into runtime uplift beliefs.

## Policy improvement and OPE

Safe policy improvement consumes pessimistic value and conservative cost bounds, applies support-aware feasibility, and ranks final deployable candidates under trust-region and cost constraints.

The OPE panel includes:

- Direct Method;
- IPS and SNIPS;
- Doubly Robust;
- SWITCH-DR and DR-OS;
- cross-fitted β*-IPS;
- Meta-OPE / BLUE-style combination candidates;
- estimator-specific IID or protocol-defined cluster-robust standard errors;
- ESS, ESS ratio, support coverage, and importance-weight diagnostics.

## Locked evidence governance

GrowthEvo provides executable locked-evaluation contracts for both OPE and randomized targeting. Experiment plans freeze statistically material choices before validation, realized manifests record the actual generated configuration, and final artifacts bind evidence to source and code identity.

The evidence layer includes stable validation/holdout identities, predeclared candidate sets, validation-only selection, frozen final candidates, experiment-plan and realized-manifest fingerprints, code provenance and compact accepted evidence bundles.

Schema identifiers in already accepted evidence remain immutable even when they contain numbered protocol tokens. Those tokens are evidence-contract identities, not GrowthEvo product generations.

## Real-world evidence status

| Evidence | Status | Current result |
| --- | --- | --- |
| **Criteo Uplift v2.1** | Accepted locked full-data targeting evidence | top-10% selected-group incremental visit **+9.37910 pp**; population increment **+0.93791 pp** |
| **Open Bandit Dataset** | Accepted locked full-data OPE evidence | final support coverage **1.0000**, ESS ratio **0.16123**, frozen validation winner **IPS** |
| **Small Open Bandit Dataset** | Pinned CI integration evidence | end-to-end data/Q/OPE/evidence-contract regression coverage |
| **GrowthAgentBench** | CI-reproducible synthetic evidence | CATE, policy-regret, support, safety, and trajectory regression checks |
| **KuaiRand** | Sequential integration path | offline-RL transition export and planner-sequence / credit experiments |

Accepted evidence remains under `benchmarks/` with its original source/protocol identities intact.

## CI-reproducible gates

The merge path currently verifies:

- Python 3.11-3.14;
- package build/install;
- OBD integration;
- OIDC/JWKS production container;
- PostgreSQL persistence and recovery;
- product stress and concurrency semantics;
- real-browser Web/PWA behavior;
- Expo compatibility and mobile type checking;
- CodeQL;
- SLSA Build Provenance;
- PyPI PEP 740 provenance;
- stable GrowthEvo product/implementation identity.

Core stress additionally checks large-batch CATE/OPE/Safe-PI workloads and numerical invariants.

## Deployment boundary

Two repository-hosted administrator actions are still external to code:

- issue #63: activate the audited `main` ruleset with the required CI evidence gates;
- issue #137: enable GitHub Pages with GitHub Actions as the publishing source and verify a real deployment.

External product providers, real customer data, real model credentials and real promotion evidence remain deployment-owned. The repository does not fabricate those states.

## Related documentation

- `docs/PROJECT_COMPLETION.md`
- `docs/SELF_HOSTING.md`
- `docs/repository_governance_audit.md`
- `docs/FRONTIER_ALGORITHM_STACK.md`
- `docs/REAL_WORLD_BENCHMARKS.md`
- `docs/OBD_ISOLATED_EXPORT.md`
- `docs/LOCKED_OPE_RUN.md`
- `docs/LOCKED_TARGETING_RUN.md`
- `docs/deployment_architecture.md`
- `docs/performance_testing.md`
