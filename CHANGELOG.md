# Changelog

## 0.2.0

Frontier safety, uncertainty and long-horizon credit upgrade.

### Added

- estimated β*-IPS additive-control-variate off-policy evaluation
- estimator-specific standard errors for IPS / DR / β*-IPS
- ESS ratio, practical support coverage, maximum importance weight and weight-CV diagnostics
- typed bridge from OPE estimates into policy-promotion evidence
- split-conformal one-sided calibration for value, ROI, spend, fatigue and churn metrics
- overlap-aware Counterfactual Verifier with explicit insufficient-evidence abstention
- GrowthPRM process reward with potential-based progress and observation-grounded credit
- penalties for duplicate evidence, failed tools, direct cost and irreversible side effects
- long-horizon world-state transition model for fatigue, churn, spend and user intent
- stress scenarios for uplift degradation, cost inflation and fatigue amplification
- risk-sensitive model-based candidate ranking using lower-tail CVaR and constraint violation rate
- lazy RL package exports to keep heavyweight future trainers decoupled from the runtime kernel
- 2026 frontier research / open-source alignment document
- dedicated regression tests for OPE, conformal calibration, process reward and model-based safety

### Changed

- policy promotion now treats poor logging-policy overlap as insufficient evidence rather than policy failure
- calibrated promotion uses the more conservative of asymptotic and conformal lower bounds
- runtime event stream can persist planner process rewards in addition to outcome rewards
- demo now exercises GrowthPRM, β*-IPS diagnostics and conformal policy verification
- package version bumped to `0.2.0`

### Scope

v0.2 still does not claim trained IQL/CQL/CPO/GRPO policies, reproduced DARA/LBM training algorithms, learned user-world models or real online uplift. Those remain experiment/training milestones and must be supported by reproducible evidence before becoming project results.

---

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
