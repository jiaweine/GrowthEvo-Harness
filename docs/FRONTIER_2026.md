# GrowthEvo Frontier Map · 2026

This document connects current research directions to concrete GrowthEvo-Harness components. It is a research map for architecture and algorithm selection rather than a project-version history.

## Frontier map

| Research direction | GrowthEvo component | Repository role |
| --- | --- | --- |
| Efficient off-policy evaluation | `growthevo/rl/ope.py` | cross-fitted β*-IPS, DR-family estimators, evidence diagnostics |
| Uncertainty-aware constrained optimization | `growthevo/rl/conformal.py`, verifier, Safe PI | calibrated lower/upper bounds and final-feasible policy selection |
| Hierarchical decision systems | planner + numeric policy | semantic growth intent separated from channel/offer/timing/budget control |
| Orthogonal CATE learning | `growthevo/causal/dr_learner.py` | group-aware cross-fitting and pluggable effect estimation |
| Support-constrained policy improvement | `growthevo/rl/safe_policy_improvement.py` | behavior anchoring, trust regions, cost constraints, support-aware action search |
| Agentic process credit | GrowthPRM + trajectory adapter | observation-grounded process reward and dynamics-aware GAE |
| Verifiable simulation | `UserWorldModel`, GrowthAgentBench | inspectable stress testing and synthetic ground-truth regression |
| Risk-sensitive long horizon | `growthevo/rl/model_based.py` | stochastic rollout, downside CVaR, constraint-risk ranking |

---

## 1. Efficient OPE with additive control variates

### SIGIR 2026 · Additive Control Variates Dominate Self-Normalisation in Off-Policy Evaluation

- Olivier Jeunen, Shashank Gupta
- Microsoft Research: https://www.microsoft.com/en-us/research/publication/additive-control-variates-dominate-self-normalisation-in-off-policy-evaluation/
- arXiv: https://arxiv.org/abs/2602.14914

**Research signal**

Additive control variates provide a principled variance-reduction direction for off-policy evaluation and motivate treating β*-IPS as a first-class estimator rather than relying solely on self-normalization.

**GrowthEvo mapping**

`growthevo/rl/ope.py` provides cross-fitted β*-IPS together with IPS, SNIPS, Doubly Robust, SWITCH-DR, DR-OS, Meta-OPE candidates, estimator uncertainty, ESS, support coverage, and importance-weight diagnostics.

The repository adds an explicit evidence layer around estimator choice: a real-data benchmark predeclares the candidate panel, applies support gates, selects on validation, and evaluates only the frozen winner on final holdout.

---

## 2. Uncertainty-aware and hierarchical growth optimization

### WWW 2026 · Auto-bidding under Return-on-Spend Constraints with Uncertainty Quantification

- arXiv: https://arxiv.org/abs/2509.16324

### WWW 2026 · DARA

- arXiv: https://arxiv.org/abs/2601.14711

### WWW 2026 · LBM: Hierarchical Large Auto-Bidding Model via Reasoning and Acting

- arXiv: https://arxiv.org/abs/2603.05134

**Research signal**

Modern growth and bidding systems increasingly combine uncertainty-aware value estimation, business constraints, high-level reasoning, and low-level allocation.

**GrowthEvo mapping**

`GrowthHypothesisPlanner` owns semantic intent and evidence acquisition. `HierarchicalGrowthPolicy` owns numeric channel, offer, timing, and budget decisions. `growthevo/rl/conformal.py` and the counterfactual verifier provide one-sided lower/upper margins for value, ROI, spend, fatigue, and churn quantities.

The common architectural theme is a clean separation between semantic planning, numerical optimization, and independently evaluated evidence.

---

## 3. Orthogonal CATE learning with serving-time support

GrowthEvo's causal learner follows doubly-robust and cross-fitting principles while making the serving contract explicit for an agent runtime.

`growthevo/causal/dr_learner.py` provides:

- full multi-action behavior-policy propensity vectors;
- treatment-vs-control propensity normalization;
- group-aware stratified cross-fitting;
- held-out AIPW/DR pseudo-outcomes;
- second-stage fitting on out-of-fold targets;
- pluggable nuisance and effect learners;
- practical-overlap diagnostics;
- OOF residual diagnostics;
- regularized Mahalanobis distributional support.

`growthevo/causal/serving.py` maps fitted treatment effects into runtime beliefs while preserving channel-level effect, uncertainty, and support information.

This allows sophisticated nonlinear or neural CATE backends to participate behind the same orthogonal estimation and serving interfaces.

---

## 4. Support-constrained and safe offline improvement

### AAMAS 2026 · PIQL: Projective Implicit Q-Learning with Support Constraint for Offline Reinforcement Learning

- DOI: https://doi.org/10.65109/GZIN7614

### Neural Networks 2026 · Offline constrained policy optimization with safe anchoring

- DOI: https://doi.org/10.1016/j.neunet.2026.108865
- PubMed: https://pubmed.ncbi.nlm.nih.gov/41934715/

### 2026 · Support-Constrained RL Enables Real-World Policy Improvement without Real-World Experience

- arXiv: https://arxiv.org/abs/2606.27475

**Research signal**

Support constraints, behavior anchoring, and explicit cost limits are central tools for controlling offline policy updates under distribution shift.

**GrowthEvo mapping**

`growthevo/rl/safe_policy_improvement.py` implements a contextual safe-improvement kernel with:

- pessimistic action-value bounds;
- explicit behavior support;
- support-aware candidate eligibility;
- behavior-policy mixtures;
- total-variation update caps;
- expected-cost constraints;
- final-feasible candidate ranking;
- first-class `NO_TREATMENT` fallback.

GrowthEvo uses these ideas as a deployment-facing policy-improvement contract while keeping the underlying sequential trainer backend modular.

---

## 5. Observation-grounded and dynamics-aware agent credit

### ACL 2026 · SOAR: Supervision from Observation for Agentic Reinforcement Learning

- ACL Anthology: https://aclanthology.org/2026.acl-long.1624/

### AAAI 2026 · SHADOW: Dynamic-Aware Credit Assignment Against Long-Horizon Tasks

- DOI: https://doi.org/10.1609/aaai.v40i28.39570

### Findings of ACL 2026 · ToolPRMBench

- ACL Anthology: https://aclanthology.org/2026.findings-acl.602/
- Code: https://github.com/David-Li0406/ToolPRMBench

**Research signal**

Long-horizon agent training benefits from process signals grounded in observations and from credit rules that respect transition dynamics.

**GrowthEvo mapping**

`growthevo/rl/process_reward.py` scores Goal/Evidence/Constraint progress, evidence gain, action confidence, tool outcomes, direct cost, duplicate evidence, and irreversible-side-effect signals.

`growthevo/training/trajectory.py` computes GAE with an explicit `credit_boundary` that can reset propagation across rollback, environment reset, user/segment switch, and delayed-outcome attribution boundaries.

Process rewards and terminal business outcomes remain separate fields in the trajectory contract, which makes the export usable by external Agent-RL trainers without changing runtime evidence semantics.

---

## 6. Verifiable simulation and long-horizon risk

### SIGIR 2026 Tutorial · Verifiable User Simulation for Search and Recommendation Systems

- arXiv: https://arxiv.org/abs/2606.14474
- SIGIR listing: https://sigir2026.org/en-AU/pages/program/accepted-tutorials

**Research signal**

Simulation is most useful when its role, assumptions, and failure modes are inspectable and separated from empirical policy evidence.

**GrowthEvo mapping**

`UserWorldModel` and `RiskSensitiveMPC` provide replay and stress-testing surfaces. GrowthAgentBench supplies known synthetic potential outcomes for deterministic regression testing.

The long-horizon planner models fatigue, churn risk, spend, touch counts, intent, and effective treatment response across multi-seed stochastic rollouts.

```math
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
```

This gives the runtime an explicit downside-risk objective while locked real-world evaluation remains the benchmark evidence layer.

---

## 7. Public evidence closes the research loop

GrowthEvo now carries accepted locked full-data evidence for both major contextual causal benchmarks used by the repository.

### Criteo Uplift v2.1

The pre-registered top-10% targeting experiment selected S-Learner on randomized validation and reported on final holdout:

- population incremental visit: **+0.93791 pp**;
- selected top-10% incremental visit: **+9.37910 pp**;
- evidence commit: `7ac26a5aebde2c70e1b43264b89f08dddcff0245`.

### Open Bandit Dataset

The pre-registered OPE experiment selected IPS on validation and reported on final holdout:

- support coverage: **1.0000**;
- ESS ratio: **0.16123**;
- final estimate: **0.0045295435**;
- evidence commit: `7d538cea9698b5f0a48c585eed85e3ae526e5af6`.

These results connect the algorithm stack to frozen public-data evidence rather than leaving the frontier map at the implementation-only level.

Full protocol and provenance details are in `docs/REAL_WORLD_BENCHMARKS.md` and the corresponding evidence directories.

---

## 8. External ecosystem behind stable adapters

The dependency-light core is designed to interoperate with specialized research systems through typed contracts.

| Project | Intended role | Link |
| --- | --- | --- |
| verl | scalable PPO/GRPO and RL post-training | https://github.com/volcengine/verl |
| Agent Lightning | execution/training separation and agent credit | https://github.com/microsoft/agent-lightning |
| Open Bandit Pipeline | public logged-bandit data and OPE baselines | https://github.com/st-tech/zr-obp |
| CausalML | uplift / treatment-effect backends | https://github.com/uber/causalml |
| EconML | heterogeneous treatment effects / DML | https://github.com/py-why/EconML |
| RecSim NG | probabilistic user / recommender simulation | https://github.com/google-research/recsim_ng |
| Tool-Star | multi-tool Agent-RL recipes | https://github.com/RUC-NLPIR/Tool-Star |
| SmartSearch | process-reward-guided local refinement | https://github.com/RUC-NLPIR/SmartSearch |

GrowthEvo keeps runtime facts, consent, budget, event history, causal estimates, and benchmark-promotion semantics stable while allowing specialized trainers and modeling libraries to evolve independently.

## Active research extensions

Current extension directions include:

1. richer nonlinear CATE backends and calibrated uncertainty;
2. sequential IQL/CQL-style trainer integrations using the existing KuaiRand contract;
3. planner PPO/GRPO post-training from exported Harness trajectories;
4. learned world-model calibration and rollout-error diagnostics;
5. sequential / anytime-valid OPE for staged deployment evaluation;
6. broader real-world benchmark coverage under the same locked-evidence protocol.
