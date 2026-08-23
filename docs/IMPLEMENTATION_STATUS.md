# GrowthEvo-Harness · Implementation Status

This repository is presented as one coherent initial implementation. It does not use staged project labels such as v1/v2 to describe the architecture.

## Implemented

### Runtime and decision contracts

- Causal Belief State separating baseline conversion from treatment uplift.
- Hierarchical planner/policy split for semantic intent vs. numeric action selection.
- First-class `NO_TREATMENT` / holdout action.
- Hard legal-action gates for consent, budget, offer limits, fatigue, churn risk and frequency caps.
- Append-only hash-chained Event Store.
- Failure classification and bounded Harness patch proposals.

### Causal evaluation and policy safety

- IPS, Doubly-Robust and estimated β*-IPS off-policy evaluation.
- Estimator-specific standard errors.
- Effective sample size / ESS ratio.
- Logging-policy support coverage, maximum importance weight and weight-CV diagnostics.
- Split-conformal one-sided residual margins for value, ROI, spend, fatigue and churn risk.
- Counterfactual Verifier with `PASS / FAIL / INSUFFICIENT_EVIDENCE` semantics.
- Conservative intersection of statistical and calibrated value bounds.

### Agentic credit assignment

- GrowthPRM potential-based progress over Goal / Evidence / Constraint state.
- Observation-grounded credit using preceding action confidence.
- Explicit penalties for failed tools, duplicate evidence, direct cost and irreversible side effects.
- Process reward persistence in the same event stream as outcome reward and policy verification.

### Long-horizon model-based safety

- Stateful fatigue, churn, spend, touch-count and intent transitions.
- Uplift-degradation, cost-inflation and fatigue-amplification stress scenarios.
- Multi-seed stochastic rollout.
- Downside CVaR return and constraint-violation probability.
- Risk-sensitive MPC candidate ranking.

## Deliberately not claimed

The repository does not claim any of the following until reproducible code and evaluation are present:

- trained production IQL/CQL/CPO/GRPO policies;
- reproduced DARA/LBM training algorithms;
- learned neural user-world models;
- calibrated CATE on a real GrowthEvo dataset;
- real online A/B uplift;
- production ad-auction latency;
- full Agent Lightning / verl trainer integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity.

## Next engineering work

- Open Bandit Dataset / Criteo uplift adapters.
- CATE / uplift backend with calibrated uncertainty.
- Offline constrained-RL trainer adapters.
- Agent-RL planner training from real Harness trajectories and GrowthPRM rewards.
- World-model calibration and rollout-error diagnostics.
- Sequential replay → OPE → calibrated gate → shadow → canary → rollback evaluation.
- GrowthAgentBench with reproducible experiment reports.

The rule for adding project claims is simple: **code first, reproducible evidence second, README result last.**
