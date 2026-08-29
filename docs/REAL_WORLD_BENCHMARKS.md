# Real-World Benchmark Protocol

GrowthEvo uses different public datasets for different causal questions. A dataset is not treated as proof of components it cannot identify, and dataset plumbing is kept separate from headline experimental evidence.

> **Promotion boundary:** a real-world number may enter the README only when a fresh evaluation produces a preregistered locked artifact tying the result to code, upstream protocol, realized data/model outputs, validation selection, evidence diagnostics, and a single final holdout reveal.

## Benchmark matrix

| Dataset | Identified signal | Mainline use | Do not infer |
| --- | --- | --- | --- |
| Criteo Uplift | randomized advertising assignment | CATE/uplift experiments and randomized targeting evaluation | sequential RL performance or exact business ROI |
| Open Bandit Dataset | logged recommendation actions with behavior propensities | contextual-bandit OPE and overlap diagnostics | long-horizon user-state control |
| KuaiRand | sequential recommendation trajectories and rich feedback | state/history construction, offline-RL export and planner credit experiments | exact action propensities from `is_rand` alone |
| GrowthAgentBench | synthetic potential outcomes with known ground truth | deterministic algorithmic regression for CATE and policy regret | production evidence |

---

## Evidence lifecycle

A promotable real-world experiment follows this order:

```text
pre-register upstream protocol
        ↓
materialize model/policy outputs
        ↓
validate realized manifest against plan
        ↓
open validation evidence
        ↓
pass evidence/support gates where applicable
        ↓
select and freeze one candidate
        ↓
open final holdout once
        ↓
emit locked artifact with all fingerprints
```

The important property is **ordering**. If plan/runtime/manifest agreement fails, validation must not be read. If validation fails an evidence gate, a new cohort cannot be substituted. After a winner is frozen, only that winner reaches final holdout.

### Durable identities

The artifact chain binds different layers separately:

- experiment-plan fingerprint: intended upstream protocol before evidence;
- candidate-config fingerprint where a benchmark pre-registers model recipes;
- export-manifest fingerprint: realized data/model-generation configuration;
- tuning fingerprint: actual validation rows and predictions;
- test fingerprint: actual holdout rows and frozen predictions;
- protocol fingerprint: candidate/evidence-gate/selection contract, bound to the experiment plan;
- commit SHA: code identity.

This is not claimed to be cryptographic enforcement against a researcher deliberately forking the repository and inventing a new experiment. It is an auditable definition of which run is admissible as the result of a named protocol.

---

## Open Bandit Dataset

### Data and adapter semantics

`growthevo/bench/real_world.py` preserves logged action probabilities from `propensity_score` (or the historical `action_prob` alias). `open_bandit_to_ope()` does not replace observed propensities and only accepts cluster/record identity semantics supplied by the experiment.

The OPE panel exposes:

- Direct Method;
- IPS;
- SNIPS;
- Doubly Robust;
- SWITCH-DR;
- DR-OS;
- cross-fitted β*-IPS as the default efficient estimator;
- same-sample β*-IPS only as a diagnostic;
- Meta-OPE/BLUE-style combination as an opt-in efficiency diagnostic/candidate;
- IID or protocol-defined cluster-robust standard errors;
- ESS / ESS ratio;
- target-policy-mass support coverage;
- maximum/mean importance weight, normalization error and weight CV.

### Evidence gate before estimator ranking

`EvidenceGatedOPEProtocol` applies predeclared support/ESS requirements **before** validation error ranking. A point estimate that accidentally matches the reference does not qualify when its logged evidence is inadequate.

The current checked-in OBD protocols require:

- support coverage `>= 0.95`;
- ESS ratio `>= 0.05`;
- positive supported importance mass.

These are benchmark-specific acceptance thresholds, not universal statistical constants.

### Pre-registered OBD plans

The repository contains two explicit plans:

- `benchmarks/ope/obd-small-all-random-to-bts.v1.json` — pinned real-data integration protocol;
- `benchmarks/ope/obd-full-all-random-to-bts.v1.json` — research-scale promotion protocol.

`OPEExperimentPlan` freezes dataset source, campaign, policy direction, reward, split, Q backend/folds, BernoulliTS simulation count, seed, support floor, evidence gates, and complete candidate grid.

The small CI source is pinned to:

```text
sb-ai-lab/sb-obp@1c6d14677ec6f06094a2f8886a1158bab99c571e
```

The full plan targets the official ZOZO Research Open Bandit Dataset release. The full dataset is not downloaded on every PR because it contains roughly 26M impressions; use `scripts/run_obd_full_locked.py` for the research run.

The current promoted OBD result is persisted under `benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/`. Nine preregistered estimators were ranked on validation; IPS won that frozen validation cohort and alone saw final holdout. The final relative OPE error is `9.20045%`, with support coverage `1.0` and ESS ratio about `0.16123`. This is a result of that protocol, not a universal claim that IPS dominates cross-fitted β*-IPS or DR.

See `docs/OBD_ISOLATED_EXPORT.md` for the complete workflow.

---

## Criteo randomized targeting

`growthevo/bench/criteo.py` treats randomized `treatment` as assignment and never substitutes post-assignment `exposure`. Propensity provenance is explicit; stable content-derived row identity supports deterministic disjoint splits.

`evaluate_randomized_targeting()` measures a top-score treatment policy under randomized inverse weighting. `LockedTargetingProtocol` selects a candidate score vector on validation and accepts only the frozen winner on final holdout.

### Targeting preregistration v2

`TargetingExperimentPlan` v2 freezes the upstream training and score-generation choices before validation is opened:

- benchmark and dataset identity;
- exact dataset source/release;
- outcome definition;
- training fraction, validation fraction and final holdout remainder;
- split strategy and split seed;
- treatment arm;
- selected top fraction;
- propensity protocol;
- score-generation protocol identifier;
- full candidate-name set;
- candidate-config fingerprint.

The companion `growthevo.targeting-export.v2` manifest must match these fields before validation is opened. Actual score values are bound by the targeting evidence fingerprint, so changing model predictions changes evidence identity even when candidate names are unchanged.

The generic locked CLI remains backend-neutral. The full Criteo evidence path deliberately uses an explicit fixed backend/config instead of hiding model training behind a label.

### Current full Criteo v2.1 locked evidence

The promoted Criteo experiment is pre-registered in `benchmarks/targeting/criteo-v2.1-visit-top10.v1.json` and executed by `scripts/run_criteo_full_locked.py`.

Data/protocol identity:

- Criteo Uplift v2.1, `13,979,592` rows;
- source commit `82811785048bb633de2d55c02bab4e57066e6423`;
- source SHA256 `2716e1bf0fd157a93b5bf86924d9088419dfbac2022c6cd90030220634f616dc`;
- outcome `visit`;
- randomized `treatment` is the assignment variable;
- `exposure` is explicitly forbidden as treatment or feature;
- SplitMix64 source-row split, seed `20260830`;
- `6,990,168` training rows, `3,494,354` validation rows, `3,495,070` holdout rows;
- top-10% treatment policy;
- propensity `0.8501983071079264` estimated from the independent training split and then frozen.

Five LightGBM 4.7.0 candidates were fixed before validation: S-, T-, X-, R- and DR-Learner. The candidate-config fingerprint is `e10eb2fc6552b28109b67cfe075b55fd1d0e8f62`. Validation ranking by randomized population incremental visit value was:

```text
S > X > DR > R > T
```

S-Learner therefore became the frozen winner. The runner then discarded the multi-candidate validation score set, re-read the source, and produced final holdout scores only for S-Learner.

Final locked holdout result:

| Metric | Value |
| --- | ---: |
| Holdout rows | 3,495,070 |
| Treat-none value | `0.0381058865` |
| Locked top-10% policy value | `0.0474849889` |
| Population incremental visit value | **`0.0093791024`** |
| Population standard error | `0.0002146266` |
| Population 95% CI | **`[0.0089584420, 0.0097997628]`** |
| Selected top-10% incremental visit value | **`0.0937910242`** |
| Selected-group standard error | `0.0021462659` |
| Selected-group 95% CI | **`[0.0895844204, 0.0979976281]`** |
| Treat-all value | `0.0483788909` |

`0.0093791024` is an **absolute population visit-probability increment**, about **+0.93791 percentage points**. `0.0937910242` is the corresponding absolute increment within the selected top 10%, about **+9.37910 percentage points**. The policy value is about `24.61%` higher relative to treat-none, but that ratio is not the historical repository metric named `Uplift@10%`.

The top-10% locked policy is a **budgeted targeting** experiment. Treat-all happens to have a slightly higher holdout value in this run; therefore this result must not be described as unconstrained global policy optimality. It answers the preregistered top-10% targeting question.

The historical Criteo `+6.8%` record predates the locked protocol and does not have a sufficiently matching metric/provenance contract. It remains legacy provenance and is **not numerically comparable** to `+0.93791 pp`, `+9.37910 pp`, or the `24.61%` relative policy-value ratio.

Audited compact evidence is persisted under:

```text
benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/
```

It records the exact evidence commit `7ac26a5aebde2c70e1b43264b89f08dddcff0245`, plan/config/manifest/protocol/tuning/test fingerprints, source SHA256, exact environment freeze, GitHub Actions run `33263792683`, artifact ID `9718130078`, and artifact digest `sha256:bbdc93a306e532ba6f880dadf409808b65c3dea872a7b41032f4b2e09819ada0`.

---

## KuaiRand

`load_kuairand()` preserves sequential interactions and records `is_rand` only as intervention provenance. `is_rand` is **not** converted into an action propensity because it does not provide the probability of the logged item or full candidate set.

Two mainline export paths remain available:

1. `kuairand_to_offline_rl()` → backend-neutral `(state, action, reward, next_state)` transitions;
2. `kuairand_to_planner_records()` / `kuairand_to_planner_transitions()` → current planner/GAE sequences.

Artificial export windows are truncations, not environment terminals, and do not automatically become planner credit boundaries. Only an explicit dynamics-boundary predicate can stop bootstrap/GAE propagation.

KuaiRand is therefore a sequential/offline-RL integration benchmark, not an excuse to fabricate IPS/OPE propensity evidence.

---

## Split rules

### Criteo

- exact source release and SHA256 fixed before validation;
- train / validation / holdout fractions and split seed preregistered;
- nuisance/CATE fitting only on the training split/folds;
- propensity learned only from the independent training split and frozen;
- complete candidate set/config fixed before validation;
- complete candidate score set on validation;
- frozen winner before final score vector is generated;
- winner-only randomized metric once on untouched holdout;
- analytic Horvitz–Thompson uncertainty for the research-scale frozen policy; inference is conditional on the frozen training-derived propensity;
- bootstrap remains available for smaller studies where its computation is practical.

### Open Bandit Dataset

- preserve policy identity and logged propensity;
- paired chronological validation/final windows as defined by the checked-in GrowthEvo plan;
- independently cross-fitted Q predictions inside validation and holdout windows;
- stable `record_id` values;
- `cluster_id` only when a defensible repeated-unit/block definition exists;
- estimator ranking only after support/ESS evidence gates;
- one frozen final-holdout estimator.

### KuaiRand

- chronological ordering for future-policy questions;
- current feedback may affect reward and next state, never current state;
- candidate-set generation fixed across compared offline-RL methods;
- random-intervention analyses kept separate from unsupported propensity claims.

---

## External algorithm backends

The repository intentionally keeps heavy research stacks optional. Paper-facing experiments may plug in:

- CQL / IQL / Behavior Cloning;
- Decision Transformer or another sequence baseline;
- causal forests;
- EconML / CausalML meta-learners;
- gradient-boosted or neural uplift models.

A backend is not called “better” because it is newer. It must win under a preregistered validation protocol and then retain acceptable untouched holdout performance/support. The current Criteo result illustrates this rule: S-Learner won the frozen validation cohort over X/DR/R/T despite the latter methods being more sophisticated causal meta-learners.

---

## Reporting checklist

For any result promoted beyond integration smoke, archive:

- experiment-plan JSON and fingerprint;
- exact dataset release/source identity and digest;
- candidate-config JSON/fingerprint when model recipes are benchmark inputs;
- realized export manifest and fingerprint;
- immutable split definition;
- stable row/source identities with zero validation/test overlap;
- propensity provenance;
- reward/outcome definition;
- Q/model/score-generation protocol;
- complete candidate set and hyperparameter grid fixed before validation selection;
- validation selection metric;
- evidence-gate thresholds and observed diagnostics where applicable;
- final frozen candidate only on holdout;
- random seeds;
- point estimate and uncertainty with metric units stated explicitly;
- commit SHA;
- tuning/test/protocol fingerprints from `LockedBenchmarkArtifact`;
- exact research environment;
- workflow artifact ID/digest for promoted full-data runs.

Do not replace missing real-world evidence with a synthetic proxy, a small-data integration result, or a legacy pre-locked headline. Do not compare percentages across different metric definitions merely because they use the word “uplift”. If a required full-data artifact does not exist yet, the correct status is **not yet promoted**.
