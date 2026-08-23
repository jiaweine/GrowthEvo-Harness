# Changelog

## 0.1.0

Initial GrowthEvo-Harness runtime kernel.

### Added

- causal belief contracts separating baseline outcome and treatment uplift
- hierarchical hypothesis planner and numeric growth policy
- first-class no-treatment / holdout semantics
- hard legal action gate for consent, budget, offer, fatigue, churn and frequency constraints
- tamper-evident append-only event stream
- stochastic user world model with delayed feedback
- incremental causal reward decomposition
- IPS / Doubly Robust off-policy evaluation with effective sample size
- counterfactual policy verifier with tri-state evidence result
- typed failure miner and bounded harness patch proposals
- shared event persistence for interaction execution and cohort policy verification
- invariant-focused tests, demo and pull-request CI

### Scope

This release establishes runtime and algorithm contracts. It does not claim trained IQL/CQL/CPO/GRPO production policies or benchmark improvements; those require reproducible datasets and evaluation runs.
