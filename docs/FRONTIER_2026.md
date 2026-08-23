# GrowthEvo Frontier Map · 2026

This document records research signals that materially affect GrowthEvo's design and the exact boundary between **implemented contracts** and **external training backends**.

Research publication years are citations, not project-version labels.

---

## 1. Off-policy evaluation beyond plain IPS / SNIPS

### SIGIR 2026 · Additive Control Variates Dominate Self-Normalisation in Off-Policy Evaluation

- Olivier Jeunen, Shashank Gupta
- Microsoft Research: https://www.microsoft.com/en-us/research/publication/additive-control-variates-dominate-self-normalisation-in-off-policy-evaluation/
- arXiv: https://arxiv.org/abs/2602.14914

**Signal**

Logged contextual policies need lower-variance OPE without hiding overlap problems. Additive control variates provide a principled alternative to treating self-normalization as the default variance-reduction technique.

**GrowthEvo mapping**

`growthevo/rl/ope.py` implements IPS, Doubly Robust and estimated beta*-IPS plus estimator standard error, ESS, ESS ratio, support coverage, maximum importance weight and weight-CV diagnostics.

**Boundary**

No estimator repairs hidden confounding, incorrect propensities or missing support. Weak overlap produces abstention in the Verifier.

---

## 2. Advertising optimization is uncertainty-aware and hierarchical

### WWW 2026 · Auto-bidding under Return-on-Spend Constraints with Uncertainty Quantification

- arXiv: https://arxiv.org/abs/2509.16324

**Signal**

Industrial growth/bidding policies need uncertainty-aware value estimates and explicit business constraints.

**GrowthEvo mapping**

`growthevo/rl/conformal.py` and `growthevo/verifier/counterfactual.py` use one-sided residual calibration for value/ROI lower bounds and spend/fatigue/churn upper bounds. Margin fields are explicitly separated from the actual bounds applied to new predictions.

### WWW 2026 · DARA

- arXiv: https://arxiv.org/abs/2601.14711

### WWW 2026 · LBM: Hierarchical Large Auto-Bidding Model via Reasoning and Acting

- arXiv: https://arxiv.org/abs/2603.05134

**Signal**

High-level semantic reasoning and low-level numerical allocation are different control problems.

**GrowthEvo mapping**

`GrowthHypothesisPlanner` owns semantic intent/evidence acquisition while `HierarchicalGrowthPolicy` owns numeric channel/offer/timing/budget decisions.

**Boundary**

GrowthEvo does not claim to reproduce DARA's or LBM's exact training algorithms.

---

## 3. Causal uplift should be trained out-of-fold and served with support diagnostics

GrowthEvo's causal learner is not copied from one 2026 paper; it follows established doubly-robust / cross-fitting principles while making them explicit in the Agent Runtime.

**Implemented mapping**

`growthevo/causal/dr_learner.py` now provides:

- full multi-action logging-policy propensity vectors;
- treatment-vs-control propensity renormalization;
- stratified K-fold nuisance fitting;
- held-out AIPW/DR pseudo-outcomes;
- second-stage fitting only on out-of-fold pseudo-outcomes;
- overlap coverage and extrapolation diagnostics.

`growthevo/causal/serving.py` then maps CATE into Runtime belief while preserving raw effects, clipping probability-scale uplift only at the serving contract boundary and adding clipping/support loss into uncertainty.

**Boundary**

The built-in ridge learner is an auditable reference backend. It is not described as a state-of-the-art nonlinear CATE model, and its serving uncertainty is not presented as a formal causal confidence interval.

---

## 4. Offline policy improvement is moving toward support constraints and safe anchoring

### AAMAS 2026 · PIQL: Projective Implicit Q-Learning with Support Constraint for Offline Reinforcement Learning

- DOI: https://doi.org/10.65109/GZIN7614

**Signal**

OOD action error remains a central offline-RL failure mode; policy improvement increasingly treats data support as a first-class constraint rather than a logging detail.

### Neural Networks 2026 · Offline constrained policy optimization with safe anchoring

- DOI: https://doi.org/10.1016/j.neunet.2026.108865
- PubMed: https://pubmed.ncbi.nlm.nih.gov/41934715/

**Signal**

Safety constraints and behavior-policy anchoring can be combined to bound offline updates and avoid unsafe OOD actions.

### 2026 · Support-Constrained RL Enables Real-World Policy Improvement without Real-World Experience

- arXiv: https://arxiv.org/abs/2606.27475

**Signal**

Constraining improvement to the support of a competent base policy can preserve transferability while still allowing useful improvement.

**GrowthEvo mapping**

`growthevo/rl/safe_policy_improvement.py` implements a dependency-free contextual safe-improvement kernel:

- pessimistic action value lower bounds;
- behavior support floor;
- unsupported treatment exclusion;
- behavior-policy mixture rather than direct argmax jumps;
- total-variation update cap;
- expected-cost cap;
- `NO_TREATMENT` fallback.

**Boundary**

This module is not advertised as PIQL, CQL, IQL or the cited safe-anchoring algorithm. It implements the shared systems principle—support-aware conservative improvement—while final promotion remains an independent OPE/Verifier decision.

---

## 5. Agentic RL needs observation-grounded and dynamics-aware credit

### ACL 2026 · SOAR: Supervision from Observation for Agentic Reinforcement Learning

- ACL Anthology: https://aclanthology.org/2026.acl-long.1624/

**Signal**

Environment observations can provide learning signal for actions instead of relying only on sparse terminal outcomes.

**GrowthEvo mapping**

`growthevo/rl/process_reward.py` implements Goal/Evidence/Constraint potential change, evidence gain, action-confidence weighting, tool failure, duplicate evidence, direct cost and irreversible-side-effect penalties.

### AAAI 2026 · SHADOW: Dynamic-Aware Credit Assignment Against Long-Horizon Tasks

- DOI: https://doi.org/10.1609/aaai.v40i28.39570

**Signal**

Long-horizon credit can be biased when transitions from dynamically inconsistent states are compared or propagated as if they belonged to one regime.

**GrowthEvo mapping**

`growthevo/training/trajectory.py` computes GAE while allowing a `credit_boundary` to reset bootstrap/advantage propagation across rollback, reset, user/segment switch and delayed-outcome attribution boundaries.

This is a Runtime-level dynamics boundary contract, not a reproduction of SHADOW's full algorithm.

### Findings of ACL 2026 · ToolPRMBench

- ACL Anthology: https://aclanthology.org/2026.findings-acl.602/
- Code: https://github.com/David-Li0406/ToolPRMBench

**Signal**

Tool-using process reward models need local-step and trajectory-level evaluation.

**GrowthEvo mapping**

Process rewards and terminal business outcomes are stored separately, and planner transitions export legal-action/tool-success state for external trainers.

---

## 6. User simulation must be auditable

### SIGIR 2026 Tutorial · Verifiable User Simulation for Search and Recommendation Systems

- arXiv: https://arxiv.org/abs/2606.14474
- SIGIR listing: https://sigir2026.org/en-AU/pages/program/accepted-tutorials

**GrowthEvo mapping**

`UserWorldModel` and `RiskSensitiveMPC` are replay/stress components only. Synthetic returns are never sufficient for policy promotion.

`GrowthAgentBench` follows the same discipline: known synthetic potential outcomes are useful for regression testing because the oracle is inspectable, but they are not business evidence.

---

## 7. Long-horizon model-based safety

Repeated growth interventions change fatigue, churn risk, spend, intent and future treatment effect.

`growthevo/rl/model_based.py` models long-horizon belief transitions, fatigue accumulation/decay, churn deterioration/recovery, spend, touch constraints, stress scenarios, multi-seed rollout, downside CVaR and constraint-violation probability.

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation)
\]

This remains a candidate-ranking/stress layer, not a replacement for causal evaluation.

---

## 8. GrowthAgentBench closes the code-to-evidence loop

`growthevo/bench/` now contains an auditable synthetic contextual-bandit oracle with:

- heterogeneous treatment effects;
- context-dependent logging propensities;
- explicit `NO_TREATMENT`, push and email potential outcomes;
- configurable outcome noise;
- held-out CATE RMSE/MAE/bias;
- serving support/uncertainty metrics;
- oracle policy value/regret.

**Boundary**

Real benchmark claims still require Open Bandit Dataset / Criteo adapters and reproducible experiment configuration.

---

## 9. External systems to integrate behind stable adapters

The core package stays dependency-light. Heavy systems belong behind typed adapters.

| Project | Intended role | Link |
|---|---|---|
| verl | scalable PPO/GRPO and RL post-training | https://github.com/volcengine/verl |
| Agent Lightning | execution/training separation and agent credit | https://github.com/microsoft/agent-lightning |
| Open Bandit Pipeline | public logged-bandit data and OPE baselines | https://github.com/st-tech/zr-obp |
| CausalML | uplift / treatment-effect backends | https://github.com/uber/causalml |
| EconML | heterogeneous treatment effects / DML | https://github.com/py-why/EconML |
| RecSim NG | probabilistic user / recommender simulation | https://github.com/google-research/recsim_ng |
| Tool-Star | multi-tool Agent-RL recipes | https://github.com/RUC-NLPIR/Tool-Star |
| SmartSearch | process-reward-guided local refinement | https://github.com/RUC-NLPIR/SmartSearch |

Runtime facts, consent, budget, event history and promotion semantics remain owned by GrowthEvo.

---

## 10. Claims boundary

The following are intentionally **not** presented as completed results:

- production neural IQL/CQL/CPO/GRPO policies;
- reproduced DARA GRPO-Adaptive or LBM GQPO;
- learned neural user world model;
- calibrated CATE on real GrowthEvo data;
- Open Bandit / Criteo benchmark numbers;
- real online A/B uplift;
- production ad-auction latency;
- full Agent Lightning / verl trainer integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity.

These become project claims only after code plus reproducible evaluation exist.

---

## 11. Next research-grade work

1. Open Bandit Dataset / Criteo schema adapters and propensity validation.
2. Nonlinear CATE backends and uncertainty calibration.
3. Sequential IQL/CQL adapters with support-constrained action serving.
4. External planner PPO/GRPO training from exported Harness trajectories.
5. World-model calibration and rollout-error growth curves.
6. Anytime-valid / sequential OPE for replay → shadow → canary promotion decisions.
