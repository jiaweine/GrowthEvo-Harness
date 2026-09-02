# GrowthEvo-Harness · Implementation Status

GrowthEvo-Harness provides an integrated causal decision stack for incremental user growth, combining causal effect estimation, constrained policy improvement, off-policy evaluation, evidence-governed model selection, long-horizon risk analysis, and trajectory credit assignment.

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

## Runtime and decision contracts

- Causal Belief State separates natural conversion from treatment effect.
- Hierarchical planning separates semantic intent from numeric action selection.
- `NO_TREATMENT` / holdout is a first-class action.
- Legal-action gates cover consent, budget, offer limits, fatigue, churn risk, and frequency caps.
- The event layer uses append-only hash-chained records for decision and evaluation provenance.
- Harness evolution operates through bounded, reviewable proposal coordinates.

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

GrowthEvo provides executable locked-evaluation contracts for both OPE and randomized targeting. Experiment plans freeze statistically material choices before validation, realized manifests record the actual generated configuration, and final artifacts bind the resulting evidence to source identity and code identity.

The evidence layer includes:

- stable validation/holdout identities;
- predeclared candidate sets and evidence gates;
- validation-only selection;
- a frozen final candidate;
- final-holdout evidence fingerprints;
- experiment-plan and realized-manifest fingerprints;
- code commit provenance;
- persisted compact evidence bundles.

## Real-world evidence status

| Evidence | Status | Current result |
| --- | --- | --- |
| **Criteo Uplift v2.1** | Accepted locked full-data targeting evidence | top-10% selected-group incremental visit **+9.37910 pp**; population increment **+0.93791 pp** |
| **Open Bandit Dataset** | Accepted locked full-data OPE evidence | final support coverage **1.0000**, ESS ratio **0.16123**, frozen validation winner **IPS** |
| **Small Open Bandit Dataset** | Pinned CI integration evidence | end-to-end data/Q/OPE/evidence-contract regression coverage |
| **GrowthAgentBench** | CI-reproducible synthetic evidence | CATE, policy-regret, support, safety, and trajectory regression checks |
| **KuaiRand** | Sequential integration path | offline-RL transition export and planner-sequence / credit experiments |

Full accepted evidence is stored under:

- `benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/`
- `benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/`

## CI-reproducible algorithmic gates

GrowthAgentBench provides deterministic regression coverage for the implementation stack. Current repository gates include:

| Property | Gate |
| --- | ---: |
| CATE RMSE | `< 0.03` |
| Propensity overlap | coverage `> 0.95` |
| Learned CATE policy | oracle regret `< 0.015` |
| Low-support optimistic treatment | support-aware action control |
| Unsafe expected cost | `NO_TREATMENT` fallback |
| Dynamics boundary | GAE isolation across declared discontinuities |

## Extension ecosystem

The runtime is intentionally backend-neutral at the heavy training layer. Stable contracts allow research or production integrations such as:

- causal forests, EconML, CausalML, gradient-boosted, or neural CATE backends;
- BC, IQL, CQL, Decision Transformer, and other sequential offline-RL trainers;
- PPO / GRPO / Agent-RL planner post-training systems;
- calibrated production world models and shadow/canary deployment infrastructure;
- CRM, ads, messaging, and MCP-compatible execution adapters.

This keeps the core causal, evidence, constraint, and evaluation contracts stable while allowing specialized training stacks to evolve independently.

## Evidence standard

Project-facing results are backed by one of three evidence classes:

1. executable runtime or algorithm code with deterministic regression tests;
2. reproducible pre-registered locked benchmark artifacts with source, split, model, and evidence provenance;
3. deployment evidence for production-facing claims.

This separation keeps implementation evidence, public benchmark evidence, and deployment evidence clear and independently auditable.

## Related documentation

- `docs/FRONTIER_ALGORITHM_STACK.md`
- `docs/REAL_WORLD_BENCHMARKS.md`
- `docs/OBD_ISOLATED_EXPORT.md`
- `docs/LOCKED_OPE_RUN.md`
- `docs/LOCKED_TARGETING_RUN.md`
