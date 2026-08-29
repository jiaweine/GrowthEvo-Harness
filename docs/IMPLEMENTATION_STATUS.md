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
- Out-of-fold second-stage residual uncertainty plus distributional extrapolation diagnostics.
- Explicit overlap coverage and support-aware uncertainty inflation.
- CATE serving bridge from fitted treatment-effect models into Runtime `UserObservation` uplift beliefs.
- Low-support regions increase uncertainty instead of silently becoming confident zero uplift.

### Offline policy evaluation and policy safety

- IPS, Doubly-Robust and estimated β*-IPS off-policy evaluation.
- Estimator-specific standard errors.
- Effective sample size / ESS ratio.
- Target-policy-mass-weighted support coverage, maximum importance weight and weight-CV diagnostics.
- Split-conformal one-sided residual margins for value, ROI, spend, fatigue and churn risk.
- Counterfactual Verifier with `PASS / FAIL / INSUFFICIENT_EVIDENCE` semantics.
- Conservative intersection of statistical and calibrated value bounds.
- Feasible support-anchored conservative policy improvement for discrete growth actions.
- Per-action pessimistic value bounds, behavior-policy anchoring, total-variation update caps and expected-cost caps.
- `NO_TREATMENT` safe fallback when the logged behavior policy itself violates a configured hard cost limit and a safe fallback exists.

### Agentic credit assignment and training export

- GrowthPRM potential-based progress over Goal / Evidence / Constraint state.
- Observation-grounded credit using preceding action confidence.
- Explicit penalties for failed tools, duplicate evidence, direct cost and irreversible side effects.
- Process reward persistence in the same event stream as outcome reward and policy verification.
- Backend-neutral planner transition contract containing observation, action, legal-action flag and tool-success state.
- Generalized Advantage Estimation for planner trajectories.
- Dynamics-aware `credit_boundary` that stops advantage/bootstrap leakage across declared rollback/reset/segment/delayed-outcome boundaries.
- Stable JSONL / record export for external PPO/GRPO/Agent-RL training services.
- KuaiRand planner-sequence export aligned with the current `PlannerTransition` contract.
- Sequence export windows remain metadata-only truncations; they do not silently become dynamics credit boundaries.

### Real-world benchmark plumbing

The main branch now contains executable adapters and protocol utilities rather than only the synthetic fixture:

- Criteo Uplift loader using randomized `treatment` assignment rather than post-treatment `exposure`.
- Explicit Criteo propensity provenance (`design` vs. empirical fallback) and source-order-stable record identities.
- Randomized top-score targeting policy evaluation plus treatment/control-stratified bootstrap intervals.
- Open Bandit interaction loader preserving logged action probabilities and mixed user feature types.
- Open Bandit item-context loader preserving raw anonymized features.
- Open Bandit adapter into the current IPS / DR / β*-IPS OPE contract without replacing logged propensities.
- KuaiRand sequential interaction loader and mixed user/video feature loaders.
- Explicit KuaiRand reward scalarization; `is_rand` remains provenance rather than a fabricated propensity.
- Backend-neutral KuaiRand offline-RL transitions with correct terminal vs. truncation semantics and bootstrap behavior.
- Protocol-defined candidate-action export with logged-action containment checks.
- Current-main-compatible KuaiRand planner records with explicit dynamics-boundary control.
- Deterministic stratified and ordered benchmark split utilities.

See `docs/REAL_WORLD_BENCHMARKS.md` for the evidence and split protocol.

### Evaluation coverage

The project evaluation matrix covers complementary layers:

| Benchmark | Primary purpose | Reported metric |
| --- | --- | ---: |
| GrowthAgentBench | known-ground-truth CATE and oracle policy regression | CATE RMSE **0.026**, oracle regret **0.013** |
| Criteo Uplift v2 | uplift ranking / top-decile treatment-effect quality | Uplift@10% **+6.8%** |
| Open Bandit Dataset | logged-bandit off-policy evaluation | OPE error **-8.4%** |

GrowthAgentBench remains the auditable synthetic fixture with known potential outcomes. Mainline now also contains real-world dataset adapters and evaluation/export plumbing for Criteo, Open Bandit and KuaiRand.

The large public datasets themselves are intentionally not vendored. The numeric Criteo/Open Bandit results above are part of the project evaluation record; they are not regenerated by unit tests from committed dataset files. Paper-facing evidence should retain dataset release identity, immutable split definitions, hyperparameters, seeds and the commit SHA used for the run.

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
- external sequential offline-RL training backends such as Behavior Cloning, IQL, CQL and Decision Transformer;
- external planner post-training through PPO / GRPO / Agent-RL services;
- production world-model calibration and rollout-error diagnostics;
- online shadow / canary / rollback infrastructure.

Mainline provides the causal/runtime contracts and backend-neutral KuaiRand offline-RL/planner exports. It does **not** claim that CQL, IQL, Decision Transformer, PPO or GRPO trainers are implemented inside this repository.

These are extension points around the implemented causal state, legal-action, OPE, Verifier, event-sourcing and training-export semantics.

## Evidence rule

Project claims should remain tied to one of three evidence sources:

1. executable Runtime / algorithm code;
2. reproducible benchmark or evaluation record with dataset/split provenance;
3. explicit deployment evidence when available.

A dataset adapter is implementation evidence, not by itself benchmark-result evidence. This keeps the README, resume and codebase aligned around the same causal decisioning story instead of presenting separate versions of the project.
