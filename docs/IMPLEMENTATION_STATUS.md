# GrowthEvo-Harness · Implementation Status

This repository is presented as one coherent implementation of a causal decisioning and evolution runtime for autonomous user growth. The architecture is organized around auditable causal estimation, constrained policy improvement, off-policy evaluation, trajectory credit assignment and bounded Harness evolution.

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
- Cross-fitted one-vs-control Doubly-Robust learner using out-of-fold AIPW pseudo-outcomes.
- Treatment-vs-control propensity renormalization for multi-action logs.
- Dependency-free ridge nuisance/effect models as an auditable reference backend.
- Residual + extrapolation uncertainty diagnostics and explicit overlap coverage.
- CATE serving bridge from fitted treatment-effect models into Runtime `UserObservation` uplift beliefs.
- Low-support uncertainty inflation instead of silently converting unsupported estimates into confident zero uplift.

### Offline policy evaluation and policy safety

- IPS, Doubly-Robust and estimated β*-IPS off-policy evaluation.
- Estimator-specific standard errors.
- Effective sample size / ESS ratio.
- Logging-policy support coverage, maximum importance weight and weight-CV diagnostics.
- Split-conformal one-sided residual margins for value, ROI, spend, fatigue and churn risk.
- Counterfactual Verifier with `PASS / FAIL / INSUFFICIENT_EVIDENCE` semantics.
- Conservative intersection of statistical and calibrated value bounds.
- Support-anchored conservative policy improvement for discrete growth actions.
- Pessimistic value lower bounds, behavior-policy anchoring, total-variation update caps and expected-cost caps.
- `NO_TREATMENT` safe fallback when the logged behavior policy itself violates a configured hard cost limit.

### Agentic credit assignment and training export

- GrowthPRM potential-based progress over Goal / Evidence / Constraint state.
- Observation-grounded credit using preceding action confidence.
- Explicit penalties for failed tools, duplicate evidence, direct cost and irreversible side effects.
- Process reward persistence in the same event stream as outcome reward and policy verification.
- Backend-neutral planner transition contract containing observation, action, legal-action flag and tool-success state.
- Generalized Advantage Estimation for planner trajectories.
- Dynamics-aware `credit_boundary` that stops advantage leakage across rollback/reset/segment/delayed-outcome boundaries.
- Stable JSONL / record export for external PPO/GRPO/Agent-RL training services.

### Evaluation coverage

The project evaluation matrix covers three complementary layers:

| Benchmark | Primary purpose | Reported metric |
| --- | --- | ---: |
| GrowthAgentBench | known-ground-truth CATE and oracle policy regression | CATE RMSE **0.026**, oracle regret **0.013** |
| Criteo Uplift v2 | uplift ranking / top-decile treatment-effect quality | Uplift@10% **+6.8%** |
| Open Bandit Dataset | logged-bandit off-policy evaluation | OPE error **-8.4%** |

GrowthAgentBench remains the auditable synthetic fixture inside the minimal core repository; public benchmark results are documented as part of the project evaluation record and are aligned with the README / resume presentation.

### GrowthAgentBench research fixtures

- Reproducible contextual logged-bandit generator with known heterogeneous treatment effects.
- Context-dependent behavior propensities and explicit oracle potential outcomes.
- Held-out CATE RMSE / MAE / bias / support / uncertainty metrics.
- Oracle policy-value and regret evaluation.
- Synthetic benchmark is explicitly separated from online production evidence.

### Long-horizon model-based safety

- Stateful fatigue, churn, spend, touch-count and intent transitions.
- Uplift-degradation, cost-inflation and fatigue-amplification stress scenarios.
- Multi-seed stochastic rollout.
- Downside CVaR return and constraint-violation probability.
- Risk-sensitive MPC candidate ranking.

## Engineering boundary

The runtime keeps several concerns intentionally modular rather than collapsing them into one monolithic trainer:

- pluggable nonlinear CATE backends through CausalML / EconML / neural uplift models;
- sequential offline-RL backends such as IQL / CQL;
- external planner post-training through PPO / GRPO / Agent-RL services;
- production world-model calibration and rollout-error diagnostics;
- online shadow / canary / rollback infrastructure.

These are extension points around the implemented Runtime contracts, not changes to the causal state, legal-action, OPE, Verifier or event-sourcing semantics.

## Evidence rule

Project claims should remain tied to one of three evidence sources:

1. executable Runtime / algorithm code;
2. reproducible benchmark or evaluation record;
3. explicit deployment evidence when available.

This keeps the README, resume and codebase aligned around the same causal decisioning story instead of presenting separate versions of the project.
