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

See `docs/OBD_ISOLATED_EXPORT.md` for the complete workflow.

---

## Criteo randomized targeting

`growthevo/bench/criteo.py` treats randomized `treatment` as assignment and never substitutes post-assignment `exposure`. Propensity provenance is explicit; stable content-derived row identity supports deterministic disjoint splits.

`evaluate_randomized_targeting()` measures a top-score treatment policy under randomized inverse weighting. `LockedTargetingProtocol` selects a candidate score vector on validation and accepts only the frozen winner on final holdout.

### Targeting preregistration

`TargetingExperimentPlan` adds the missing upstream layer for externally produced CATE/model scores. It freezes:

- benchmark and dataset identity;
- dataset source;
- outcome definition;
- split strategy / validation fraction;
- treatment arm;
- selected top fraction;
- score-generation protocol identifier;
- full candidate-name set.

A companion `growthevo.targeting-export.v1` manifest must match the plan before validation is opened. The actual score values are then bound by the targeting evidence fingerprint, so changing model predictions changes the evidence identity even when candidate names stay the same.

This is backend-neutral on purpose: high-performance external LightGBM, causal forest, EconML/CausalML, or neural uplift pipelines can provide scores without becoming hidden runtime dependencies. Their exact score-generation recipe belongs in the preregistered `score_protocol` and external experiment record.

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

- stable row identity;
- predeclared stratification/split logic;
- nuisance/CATE fitting only on permitted training folds;
- complete candidate score set on validation;
- frozen winner before final score vector is accepted;
- randomized final metric once on untouched holdout;
- stratified bootstrap if headline intervals are reported.

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

A backend is not called “better” because it is newer. It must win under a preregistered validation protocol and then retain acceptable untouched holdout performance/support.

---

## Reporting checklist

For any result promoted beyond integration smoke, archive:

- experiment-plan JSON and fingerprint;
- exact dataset release/source identity;
- realized export manifest and fingerprint;
- immutable split definition;
- stable row IDs with zero validation/test overlap;
- propensity provenance;
- reward/outcome definition;
- Q/model/score-generation protocol;
- complete candidate set and hyperparameter grid fixed before validation selection;
- validation selection metric;
- evidence-gate thresholds and observed diagnostics;
- final frozen candidate only on holdout;
- random seeds;
- point estimate and uncertainty;
- commit SHA;
- tuning/test/protocol fingerprints from `LockedBenchmarkArtifact`.

Do not replace missing real-world evidence with a synthetic proxy, a small-data integration result, or a legacy pre-locked headline. If the required full-data artifact does not exist yet, the correct status is **not yet promoted**.
