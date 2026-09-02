# Real-World Benchmark Protocol

GrowthEvo uses public datasets as complementary evidence environments for causal estimation, contextual-bandit evaluation, and sequential decision learning. Each benchmark is paired with the question its data design can answer most directly.

## Benchmark portfolio

| Dataset | Evidence signal | Primary GrowthEvo use |
| --- | --- | --- |
| **Criteo Uplift v2.1** | randomized advertising assignment | CATE model selection and randomized top-k targeting evaluation |
| **Open Bandit Dataset** | logged recommendation actions with behavior propensities | contextual-bandit OPE, overlap analysis, and estimator selection |
| **KuaiRand** | sequential recommendation trajectories and rich feedback | state/history construction, offline-RL export, and planner-credit experiments |
| **GrowthAgentBench** | synthetic potential outcomes with known ground truth | deterministic CATE, policy-regret, safety, and trajectory regression testing |

## Locked evidence lifecycle

Promoted real-world results use a fixed evidence lifecycle:

| Stage | Contract |
| ---: | --- |
| **1** | Pre-register dataset source, split, policy/model protocol, candidate set, and evidence gates |
| **2** | Materialize model or policy outputs and record the realized manifest |
| **3** | Validate plan/runtime/manifest agreement before opening validation evidence |
| **4** | Evaluate the complete predeclared candidate set on validation |
| **5** | Apply support/evidence gates where the protocol requires them |
| **6** | Select and freeze one validation winner |
| **7** | Evaluate the frozen winner on the independent final holdout |
| **8** | Persist the result with plan, manifest, evidence, environment, and code fingerprints |

The artifact chain records intended protocol and realized execution separately. Core identities include the experiment-plan fingerprint, candidate-config fingerprint where applicable, export-manifest fingerprint, validation evidence fingerprint, holdout evidence fingerprint, locked protocol fingerprint, and code commit SHA.

---

## Open Bandit Dataset

### Evaluation contract

`growthevo/bench/real_world.py` preserves the logged action probability from `propensity_score` and carries stable record identity into the OPE layer.

The estimator panel includes:

- Direct Method;
- IPS;
- SNIPS;
- Doubly Robust;
- SWITCH-DR;
- DR-OS;
- cross-fitted β*-IPS;
- Meta-OPE / BLUE-style candidates.

Evaluation diagnostics include estimator-specific uncertainty, ESS / ESS ratio, target-policy support coverage, maximum importance weight, normalization diagnostics, and weight coefficient of variation.

### Evidence gates

The checked-in OBD protocols predeclare evidence eligibility before estimator ranking. Current gates are:

- support coverage `>= 0.95`;
- ESS ratio `>= 0.05`;
- positive supported importance mass.

These thresholds are part of the named experiment plan and therefore remain auditable together with the estimator grid.

### Pre-registered plans

The repository contains dedicated plans for both integration and research-scale execution:

- `benchmarks/ope/obd-small-all-random-to-bts.v1.json`
- `benchmarks/ope/obd-full-all-random-to-bts.v1.json`

The plan freezes dataset source, campaign, behavior/evaluation policies, reward, split, Q backend/folds, BernoulliTS simulation count, seed, support floor, evidence gates, and the complete candidate grid.

### Current full-data locked evidence

The accepted research-scale artifact is stored at:

`benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/`

Nine predeclared estimator configurations were compared on validation. IPS was the frozen validation winner and was subsequently evaluated on the independent final holdout.

| Metric | Locked result |
| --- | ---: |
| Random-policy evidence rows | **1,374,327** |
| BernoulliTS on-policy reference rows | **12,357,200** |
| Predeclared estimator configurations | **9** |
| Validation winner | **IPS** |
| Final estimate | **0.0045295435** |
| Final on-policy reference | `0.0049885087` |
| Final relative estimation error | `9.20045%` |
| Final standard error | `0.0002042614` |
| Final support coverage | **1.0000** |
| Final ESS ratio | **0.16123** |

**Evidence commit:** `7d538cea9698b5f0a48c585eed85e3ae526e5af6`

The result demonstrates the repository's validation-governed selection rule: the estimator allowed onto final holdout is determined by the predeclared validation objective rather than by estimator age or branding.

See `docs/OBD_ISOLATED_EXPORT.md` and `docs/LOCKED_OPE_RUN.md` for the execution contract.

---

## Criteo Uplift v2.1

### Randomized targeting contract

`growthevo/bench/criteo.py` uses randomized `treatment` as the assignment variable and maintains stable content-derived row identities for deterministic disjoint splits. `evaluate_randomized_targeting()` evaluates a top-score treatment policy from randomized evidence, while `LockedTargetingProtocol` selects the score model on validation and evaluates the frozen winner on final holdout.

### Targeting preregistration v2

`TargetingExperimentPlan` v2 freezes the statistically material training and evaluation choices:

- benchmark and dataset identity;
- exact source release;
- outcome definition;
- training / validation / holdout split and seed;
- treatment arm;
- selected top fraction;
- propensity protocol;
- score-generation protocol;
- complete candidate-name set;
- candidate-configuration fingerprint.

The companion `growthevo.targeting-export.v2` manifest records the realized values of these fields. Candidate scores are additionally bound into the evidence fingerprint.

### Current full-data locked evidence

The accepted experiment is declared in `benchmarks/targeting/criteo-v2.1-visit-top10.v1.json` and executed by `scripts/run_criteo_full_locked.py`.

| Protocol field | Value |
| --- | --- |
| Dataset | Criteo Uplift v2.1 |
| Source rows | **13,979,592** |
| Outcome | `visit` |
| Split | 50% train / 25% validation / 25% holdout |
| Training rows | `6,990,168` |
| Validation rows | `3,494,354` |
| Holdout rows | `3,495,070` |
| Targeting policy | top 10% by CATE score |
| Candidate family | S / T / X / R / DR LightGBM 4.7.0 |
| Validation winner | **S-Learner** |

Final holdout evidence:

| Metric | Locked result |
| --- | ---: |
| Treat-none value | `0.0381058865` |
| Locked top-10% policy value | **0.0474849889** |
| Population incremental visit value | **0.0093791024** |
| Population increment | **+0.93791 pp** |
| Population 95% CI | **[+0.89584 pp, +0.97998 pp]** |
| Selected top-10% incremental visit value | **0.0937910242** |
| Selected-group increment | **+9.37910 pp** |
| Selected-group 95% CI | **[+8.95844 pp, +9.79976 pp]** |

**Evidence commit:** `7ac26a5aebde2c70e1b43264b89f08dddcff0245`

The target is explicitly a **budgeted top-10% targeting policy**. Results are therefore reported in the units of that preregistered targeting objective: absolute population incremental visit probability and selected-group incremental visit probability.

The audited compact artifact is stored at:

`benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/`

It contains plan/config/manifest/protocol/tuning/test fingerprints, source identity, environment information, and workflow artifact provenance.

See `docs/LOCKED_TARGETING_RUN.md` for the generic evaluation contract.

---

## KuaiRand

KuaiRand supplies sequential recommendation trajectories for history/state construction and offline-RL research integration.

Mainline supports two principal export surfaces:

1. `kuairand_to_offline_rl()` for backend-neutral `(state, action, reward, next_state)` transitions;
2. `kuairand_to_planner_records()` / `kuairand_to_planner_transitions()` for planner and GAE sequences.

`is_rand` is retained as intervention provenance. Chronological ordering, current-feedback timing, truncation metadata, and declared dynamics boundaries are preserved so downstream sequential learners can share one stable trajectory contract.

---

## GrowthAgentBench

GrowthAgentBench provides a deterministic contextual-bandit oracle with known potential outcomes. It is designed for CI-level algorithmic verification where causal ground truth can be inspected directly.

Current regression coverage includes:

- heterogeneous treatment effects;
- context-dependent behavior propensities;
- CATE RMSE / MAE / bias;
- support and uncertainty diagnostics;
- oracle policy value and regret;
- legal-action and safe-policy invariants;
- dynamics-aware trajectory-credit behavior.

This benchmark complements the real-world evidence paths by making mathematical regressions easy to reproduce in ordinary CI.

---

## Split and selection rules

### Criteo

- pin the source release and digest;
- predeclare train / validation / holdout fractions and split seed;
- fit nuisance/CATE models on training data;
- freeze the propensity protocol before validation;
- freeze the complete candidate configuration before validation;
- evaluate every candidate on the validation split;
- freeze one winner before producing final-holdout scores;
- evaluate the winner once on final holdout;
- report point estimates with uncertainty and explicit metric units.

### Open Bandit Dataset

- preserve behavior-policy identity and logged propensity;
- use the plan-defined validation/final windows;
- generate cross-fitted Q predictions within each evaluation cohort;
- preserve stable `record_id` values;
- use `cluster_id` when the experiment defines a defensible repeated-unit/block identity;
- apply evidence gates before validation ranking;
- freeze one estimator for final holdout.

### KuaiRand

- preserve chronological ordering for future-policy questions;
- keep current feedback out of current state construction;
- freeze candidate-set generation across compared offline-RL methods;
- preserve intervention provenance separately from action-probability semantics.

---

## Backend ecosystem

The benchmark contracts are model-backend neutral. Research experiments can plug in specialized implementations such as:

- CQL / IQL / Behavior Cloning;
- Decision Transformer or other sequence baselines;
- causal forests;
- EconML / CausalML meta-learners;
- gradient-boosted or neural uplift models.

Model sophistication is treated as a candidate property; benchmark promotion is governed by the predeclared validation objective and frozen final holdout.

## Reporting standard

A promoted real-world result should archive:

- experiment-plan JSON and fingerprint;
- exact dataset release/source identity and digest;
- candidate configuration and fingerprint where applicable;
- realized export manifest and fingerprint;
- immutable split definition;
- stable row/source identities;
- propensity provenance;
- reward/outcome definition;
- Q/model/score-generation protocol;
- complete candidate set and hyperparameter grid;
- validation selection metric;
- evidence-gate thresholds and observed diagnostics;
- frozen final candidate;
- random seeds;
- point estimate, uncertainty, and metric units;
- commit SHA;
- tuning/test/protocol fingerprints;
- exact research environment;
- workflow artifact identity for promoted full-data runs.

This standard keeps benchmark results compact enough to inspect while preserving the provenance needed for independent reproduction and audit.
