# GrowthEvo-Harness · Implementation Status

This document separates implemented contracts, research adapters, and evidence that has actually been reproduced. Public-dataset plumbing is not reported as a benchmark result until an experiment artifact can be traced to code, data protocol, seed, and metric definition.

## Implemented

### Runtime and decision contracts

- Causal Belief State separating baseline outcome from treatment uplift.
- Hierarchical planner/policy split for semantic intent vs. numeric channel selection.
- First-class `NO_TREATMENT` / holdout action.
- Hard legal-action gates for consent, budget, offer limits, fatigue, churn risk and frequency caps.
- Append-only hash-chained Event Store.
- Failure classification and bounded Harness patch proposals.
- Business action parameterization is injectable; channel scoring does not hard-code offer formulas, send hours, or creative IDs.

### Causal learning and serving

- Logged multi-action treatment records with full logging-policy propensity vectors.
- Cross-fitted one-vs-control Doubly-Robust learner using out-of-fold AIPW pseudo-outcomes.
- Group-aware cross-fitting that keeps repeated-user clusters intact and balances treatment/control mass across folds.
- Pluggable outcome and effect regressors; dependency-free ridge remains only a reference backend.
- No implicit propensity clipping. Strict positivity, practical overlap diagnostics, and optional clipping are separate explicit choices.
- Second-stage out-of-fold residual / extrapolation diagnostics.
- CATE serving preserves channel-specific effect, uncertainty, and support.
- Model uncertainty is not labelled as a causal confidence interval.
- Externally calibrated or inferential treatment-effect lower bounds can be injected explicitly and propagated into policy selection.

### Offline policy evaluation and promotion safety

- Direct Method, IPS, self-normalized IPS, Doubly Robust, SWITCH-DR, optimistic DR shrinkage, and additive-control-variate IPS.
- SWITCH/shrinkage parameters are external validation choices rather than hidden evaluation constants.
- Additive control-variate coefficients can be estimated on tuning data and passed to final evaluation; final-test data does not silently choose its own coefficient.
- IID standard errors plus protocol-defined cluster-robust standard errors.
- Effective sample size / ESS ratio.
- Importance-mass-weighted support coverage plus descriptive row support coverage.
- Maximum importance weight, mean-weight normalization error, and weight-CV diagnostics.
- Split-conformal one-sided residual margins with simultaneous promotion-gate calibration.
- Counterfactual Verifier with `PASS / FAIL / INSUFFICIENT_EVIDENCE` semantics.
- Promotion statistical rules and evidence-quality thresholds are injected by the experiment/deployment protocol. If they are not configured, verification fails closed with `INSUFFICIENT_EVIDENCE`.
- Support-anchored conservative policy improvement accepts an external learned policy distribution and contracts it toward logged behavior under support, total-variation, pessimistic-value, and expected-cost constraints.

### Agentic credit assignment and training export

- GrowthPRM potential-based progress over Goal / Evidence / Constraint state.
- Evidence-gain credit is separated from model confidence; raw tool success does not receive a positive bonus by default.
- Explicit penalties for failed tools, duplicate evidence, direct cost, and irreversible side effects.
- Generalized Advantage Estimation with distinct semantics for true termination, export truncation, and credit boundaries.
- True terminals stop value bootstrap. Truncations and credit boundaries stop trace propagation without pretending the environment terminated.
- Stable JSONL / record export preserves `done`, `truncated`, legal-action state, tool-success state, and provenance metadata.

### Long-horizon model-based safety

- Stateful fatigue, churn, spend, touch-count and intent transitions.
- Channel delays and churn-response thresholds are environment configuration, not planner constants.
- Injectable world-model factory and touch-state updater.
- Common random numbers across candidate plans to reduce pairwise Monte Carlo noise.
- Downside CVaR diagnostics.
- Hard rollout feasibility is separated from reward scale: a constraint-violating plan cannot become preferable merely because reward units are rescaled.

## Real-data benchmark adapters

### Criteo Uplift

Implemented:

- randomized `treatment` mapped to treatment/control semantics;
- post-assignment `exposure` is not used as the treatment variable;
- configurable known assignment probability with empirical randomized-arm share available as a fallback diagnostic;
- top-budget randomized targeting evaluation;
- treatment/control-stratified bootstrap utilities.

Not claimed yet:

- a final paper-facing Criteo result table produced by this branch.

### Open Bandit Dataset

Implemented:

- real logged propensities preserved from the impression log;
- categorical user context and numeric affinity fields kept distinct;
- item/action context loader that preserves raw anonymized item features without silently imposing ordinal encoding;
- protocol-defined clustering for OPE uncertainty;
- robust OPE estimator suite and overlap diagnostics.

Not claimed yet:

- a final cross-policy relative-error table reproduced from a pinned experiment artifact.

### KuaiRand

Implemented:

- sequential interaction loader with rich feedback and randomized-intervention provenance;
- `is_rand` is metadata and is never fabricated into an action propensity;
- history-only states exclude current feedback and logging provenance;
- true episode termination separated from artificial export truncation;
- raw user identifiers excluded from the default policy state;
- optional user/video feature lookup and action representations;
- backend-neutral transitions suitable for Behavior Cloning, CQL, IQL, and sequence-modeling experiments.

Not claimed yet:

- trained neural offline-RL benchmark scores for CQL, IQL, Decision Transformer, or other external trainers.

## Synthetic regression fixture

GrowthAgentBench remains useful because its potential outcomes are known. It is used for algorithmic regression tests such as CATE error and oracle-policy regret. Synthetic metrics are explicitly not presented as real-world growth lift.

## Deliberately not claimed

The repository does not claim any of the following until reproducible code and evaluation evidence are attached:

- production neural offline-RL policies;
- real online A/B uplift;
- learned production-faithful user world models;
- production ad-auction latency;
- full external trainer integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity;
- public-dataset headline numbers without a reproducible experiment artifact.

## Next research work

- Add a reproducible experiment runner that writes configuration, data fingerprint, split definition, seed, estimator hyperparameters, and result tables together.
- Reproduce Criteo uplift baselines with S-Learner, T-Learner, X-Learner, R-Learner, DR-Learner, and forest-based treatment-effect models.
- Reproduce Open Bandit cross-policy OPE with validation-selected estimator hyperparameters and protocol-defined clustered uncertainty.
- Train Behavior Cloning before CQL/IQL/sequence baselines on KuaiRand and report support-aware diagnostics alongside reward metrics.
- Add calibrated treatment-effect uncertainty from an external causal inference backend rather than upgrading residual diagnostics by name.
- Fit and validate a learned dynamics ensemble before using world-model rollouts as anything stronger than stress/ranking evidence.

The rule for adding project claims is: **code first → reproducible evidence second → README result last.**
