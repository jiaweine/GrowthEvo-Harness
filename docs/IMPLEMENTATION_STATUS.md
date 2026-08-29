# GrowthEvo-Harness · Implementation Status

GrowthEvo-Harness is one coherent causal decisioning/evolution runtime organized around auditable causal estimation, constrained policy improvement, off-policy evaluation, trajectory credit assignment, and evidence-governed benchmark promotion.

## Implemented

### Runtime and decision contracts

- Causal Belief State separating baseline conversion from treatment uplift.
- Hierarchical planner/policy split for semantic intent vs. numeric action selection.
- First-class `NO_TREATMENT` / holdout action.
- Hard legal-action gates for consent, budget, offer limits, fatigue, churn risk and frequency caps.
- Append-only hash-chained Event Store.
- Failure classification and bounded Harness patch proposals.

### Causal learning and serving

- Logged multi-action treatment records with full logging-policy propensity vectors.
- Group-aware cross-fitted one-vs-control Doubly Robust learner using out-of-fold AIPW pseudo-outcomes.
- Treatment-vs-control propensity renormalization for multi-action logs.
- Pluggable nuisance/effect learners; dependency-free ridge remains the auditable reference backend.
- Strict positivity, practical overlap and propensity clipping represented separately.
- Out-of-fold second-stage residual uncertainty plus regularized Mahalanobis distributional-support diagnostics.
- CATE serving bridge from fitted treatment-effect models into runtime uplift beliefs.

### OPE and policy safety

- Direct Method, IPS, SNIPS, Doubly Robust, SWITCH-DR and DR-OS.
- Cross-fitted β*-IPS as the default efficient policy-evidence estimator.
- Same-sample β*-IPS retained only for diagnostic/reproduction use.
- Meta-OPE/BLUE-style correlated combination available as an opt-in diagnostic/candidate.
- Estimator-specific IID or experiment-defined cluster-robust standard errors.
- ESS / ESS ratio, target-mass support coverage and importance-weight tail/normalization diagnostics.
- One-sided conformal residual margins.
- Counterfactual Verifier with `PASS / FAIL / INSUFFICIENT_EVIDENCE` semantics.
- Calibrated/inferential bound mode for safe policy improvement plus explicit Gaussian reference mode.
- Final-feasible per-action support-anchored conservative policy improvement with TV/cost caps.
- `NO_TREATMENT` fallback when a feasible safe fallback exists.

### Benchmark evidence governance

- Locked validation selection and one-shot final holdout for OPE and randomized targeting.
- Validation/test stable-identity overlap fails closed.
- OPE evidence fingerprints bind rewards, propensities, target-policy probabilities, Q predictions, record IDs and cluster IDs.
- Targeting fingerprints bind randomized rows and model score vectors.
- OPE evidence gates run before estimator ranking and can require support coverage, ESS ratio and positive supported importance mass.
- Strict `OPEExperimentPlan` preregistration freezes source, policy direction, reward, split, Q model/folds, simulation count, seed, evidence gate and estimator grid.
- Strict `TargetingExperimentPlan` preregistration freezes source, outcome, split, treatment, selected fraction, score protocol and candidate set.
- Plan/runtime/realized-manifest disagreement fails before validation evidence is opened.
- Final locked artifacts bind plan fingerprint, realized manifest fingerprint, tuning/test evidence fingerprints, bound protocol fingerprint and commit SHA.

### Real-world benchmark plumbing

- Criteo Uplift loader uses randomized `treatment`, never post-treatment `exposure`, with explicit propensity provenance and stable row IDs.
- Randomized top-score targeting evaluation plus treatment/control-stratified bootstrap utilities.
- Open Bandit loaders preserve logged propensities and raw anonymized item features.
- Open Bandit adapter supports stable record IDs and protocol-defined clusters without guessing semantics.
- Standalone OBD exporter reconstructs BernoulliTS target probabilities and produces cross-fitted logistic Q terms for DM/DR-family estimators.
- OBP regression-model slate width is passed explicitly instead of relying on the single-position default.
- Python 3.12 CI exercises a real pinned small OBD source end-to-end through preregistration, logistic Q, evidence gates, validation selection and final holdout.
- Checked-in small-integration and full-research OBD experiment plans.
- `scripts/run_obd_full_locked.py` downloads/uses the official full ZOZO release and executes the research-scale preregistered protocol.
- KuaiRand sequential loaders, feature loaders, offline-RL transition export and current planner-sequence export.
- KuaiRand `is_rand` remains intervention provenance, not a fabricated action propensity.

### Training / credit semantics

- GrowthPRM potential-based process reward over goal/evidence/constraint state.
- Explicit penalties for failed tools, duplicate evidence, direct cost and irreversible side effects.
- Backend-neutral planner transition/export contracts.
- Generalized Advantage Estimation.
- Dynamics-aware `credit_boundary` stops advantage/bootstrap leakage only at declared dynamics discontinuities.
- Artificial export windows remain truncation metadata and do not silently change GAE targets.

### Long-horizon safety

- Stateful fatigue, churn, spend, touch-count and intent transitions.
- Multi-seed stochastic rollout and stress scenarios.
- Downside CVaR and constraint-violation probability.
- Risk-sensitive MPC candidate ranking.

## Evidence status

| Evidence | Current status | Meaning |
| --- | --- | --- |
| GrowthAgentBench | CI-reproducible synthetic regression | implementation/causal-regression evidence |
| Small Open Bandit Dataset | real pinned external integration artifact in PR CI | API/data/Q/OPE/evidence-chain integration, **not** full-data performance |
| Full Open Bandit Dataset | executable preregistered research runner | promotable only after a fresh full-data locked artifact is archived |
| Criteo Uplift | adapter + locked/preregisterable targeting path | promotable only from a fresh preregistered score/model experiment |
| KuaiRand | sequential/offline-RL/planner export integration | training/export semantics, not IPS evidence |

Historical Criteo `+6.8%` and Open Bandit `-8.4%` records are pre-locked legacy provenance. They are not claimed as confirmed performance of the current frontier algorithm stack and are not used to select the canonical estimator/model version.

## Synthetic acceptance gates

GrowthAgentBench remains the auditable fixture with known potential outcomes. Current repository acceptance gates include CATE RMSE `< 0.03`, oracle policy regret `< 0.015`, overlap/support behavior and safety/trajectory invariants. These tests are intentionally separate from real-world performance claims.

## Engineering boundary

Several heavy training/research stacks remain modular extension points rather than hidden dependencies:

- nonlinear CATE backends such as causal forests, EconML/CausalML and neural uplift;
- sequential offline-RL backends such as BC, IQL, CQL and Decision Transformer;
- external planner post-training through PPO / GRPO / Agent-RL services;
- production world-model calibration, shadow/canary and rollback infrastructure.

Mainline provides causal/runtime contracts, evidence governance, backend-neutral exports and safe evaluation semantics. It does **not** claim those external trainers are implemented internally.

## Evidence rule

A project claim must be tied to one of:

1. executable algorithm/runtime code and deterministic regression tests;
2. a reproducible **preregistered locked** benchmark artifact with source/split/model/evidence provenance;
3. explicit deployment evidence when available.

A dataset adapter, small-data smoke, legacy number or synthetic proxy is not a substitute for the corresponding fresh real-world artifact.

See:

- `docs/FRONTIER_ALGORITHM_STACK.md`
- `docs/REAL_WORLD_BENCHMARKS.md`
- `docs/OBD_ISOLATED_EXPORT.md`
- `docs/LOCKED_OPE_RUN.md`
