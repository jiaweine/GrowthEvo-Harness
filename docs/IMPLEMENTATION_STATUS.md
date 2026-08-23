# GrowthEvo-Harness · Implementation Status

This repository is presented as one coherent initial implementation. Project architecture is not described through staged v1/v2 labels.

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

### GrowthAgentBench research fixtures

- Reproducible contextual logged-bandit generator with known heterogeneous treatment effects.
- Context-dependent behavior propensities and explicit oracle potential outcomes.
- Held-out CATE RMSE / MAE / bias / support / uncertainty metrics.
- Oracle policy-value and regret evaluation.
- Synthetic benchmark is explicitly separated from deployment evidence.

### Long-horizon model-based safety

- Stateful fatigue, churn, spend, touch-count and intent transitions.
- Uplift-degradation, cost-inflation and fatigue-amplification stress scenarios.
- Multi-seed stochastic rollout.
- Downside CVaR return and constraint-violation probability.
- Risk-sensitive MPC candidate ranking.

## Deliberately not claimed

The repository does not claim any of the following until reproducible code and evaluation are present:

- production neural IQL/CQL/CPO/GRPO policies;
- reproduced DARA/LBM training algorithms;
- learned neural user-world models;
- calibrated CATE on a real GrowthEvo dataset;
- Open Bandit Dataset / Criteo benchmark numbers;
- real online A/B uplift;
- production ad-auction latency;
- full Agent Lightning / verl trainer integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity.

## Next engineering work

- Open Bandit Dataset / Criteo uplift adapters with schema and propensity validation.
- Pluggable nonlinear CATE backends through CausalML / EconML / neural uplift models.
- Sequential offline-RL adapters for IQL/CQL with support-constrained action serving.
- External planner post-training through verl / Agent-Lightning-style execution-training separation.
- World-model calibration and rollout-error diagnostics.
- Anytime-valid / sequential replay → OPE → calibrated gate → shadow → canary → rollback evaluation.
- Reproducible experiment reports generated from GrowthAgentBench and public datasets.

The rule for adding project claims is simple: **code first, reproducible evidence second, README result last.**
