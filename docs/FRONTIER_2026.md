# GrowthEvo Frontier Map · 2026

This document records the research signals behind GrowthEvo and the exact boundary between **what the repository implements** and **what remains an external or future training backend**.

The goal is not citation decoration. Each reference below maps to a concrete runtime, evaluation or learning decision.

---

## 1. Off-policy evaluation beyond plain IPS / SNIPS

### SIGIR 2026 · Additive Control Variates Dominate Self-Normalisation in Off-Policy Evaluation

- Olivier Jeunen, Shashank Gupta.
- Microsoft Research: https://www.microsoft.com/en-us/research/publication/additive-control-variates-dominate-self-normalisation-in-off-policy-evaluation/
- arXiv: https://arxiv.org/abs/2602.14914

**Research signal**

Contextual recommendation and growth policies are evaluated from logged propensities. The work shows that an optimally chosen additive control variate can dominate self-normalisation in mean-squared error under its assumptions.

**GrowthEvo mapping**

`growthevo/rl/ope.py` implements:

- IPS;
- Doubly-Robust estimation;
- estimated β*-IPS with `w - 1` as the zero-mean control variate;
- estimator-specific standard errors;
- ESS and ESS ratio;
- practical support coverage;
- maximum importance weight;
- importance-weight coefficient of variation.

**Boundary**

No OPE estimator fixes hidden confounding, missing propensity logging or arbitrary support mismatch. GrowthEvo explicitly abstains when overlap evidence is weak.

---

## 2. Advertising optimization is uncertainty-aware and hierarchical

### WWW 2026 · Auto-bidding under Return-on-Spend Constraints with Uncertainty Quantification

- Jiale Han et al.
- arXiv: https://arxiv.org/abs/2509.16324

**Research signal**

Industrial bidding must reason about prediction uncertainty while satisfying business constraints such as budget and Return-on-Spend.

**GrowthEvo mapping**

`growthevo/rl/conformal.py` and `growthevo/verifier/counterfactual.py` implement:

- one-sided split-conformal residual margins from matured cohorts;
- calibrated value and ROI lower confidence bounds;
- calibrated spend, fatigue and churn upper confidence bounds;
- conservative intersection with the statistical value LCB.

The fitted conformal values are named explicitly as **margins**, not absolute bounds. A margin only becomes an LCB/UCB after it is applied to a new prediction.

**Boundary**

Split-conformal coverage relies on calibration/test exchangeability. Under distribution shift, GrowthEvo must recalibrate or abstain; it does not claim shift-proof guarantees.

### WWW 2026 · DARA

- Mingxuan Song et al.
- arXiv: https://arxiv.org/abs/2601.14711

**Research signal**

High-level semantic reasoning and fine-grained numerical allocation are different decision problems.

**GrowthEvo mapping**

`GrowthHypothesisPlanner` owns semantic intent; `HierarchicalGrowthPolicy` owns channel, offer, timing and budget decisions. The runtime boundary is explicit so either side can later be replaced by a learned backend.

### WWW 2026 · LBM: Hierarchical Large Auto-Bidding Model via Reasoning and Acting

- Yewen Li et al.
- arXiv: https://arxiv.org/abs/2603.05134

**Research signal**

Hierarchical `Think` / `Act` policies and offline reinforcement fine-tuning are increasingly used for dynamic bidding.

**GrowthEvo mapping**

CausalLift-HRL follows the same systems principle: semantic reasoning and numerically precise control are separate policy layers.

**Boundary**

GrowthEvo does not claim to reproduce DARA's or LBM's exact training algorithm.

---

## 3. Agentic RL needs trajectory-level credit

### ACL 2026 · SOAR: Supervision from Observation for Agentic Reinforcement Learning

- Meng Li et al.
- ACL Anthology: https://aclanthology.org/2026.acl-long.1624/

**Research signal**

Environment observations can provide training signal for agent actions instead of relying only on sparse terminal outcomes.

**GrowthEvo mapping**

`growthevo/rl/process_reward.py` implements a GrowthPRM contract with:

- potential-based Goal / Evidence / Constraint progress;
- normalized action entropy;
- environment-evidence gain;
- confidence-weighted observation credit;
- tool failure, duplicate evidence, direct-cost and irreversible-side-effect penalties.

This is a runtime-level credit contract, not a reproduction of token-level SOAR training.

### Findings of ACL 2026 · ToolPRMBench

- Dawei Li et al.
- ACL Anthology: https://aclanthology.org/2026.findings-acl.602/
- Code: https://github.com/David-Li0406/ToolPRMBench

**Research signal**

Tool-using process reward models require local-step and full-trajectory evaluation rather than only outcome scoring.

**GrowthEvo mapping**

`GrowthProcessRewardModel` exposes step-level and trajectory-level rewards and keeps process reward separate from terminal business outcome.

### Findings of ACL 2026 · AgentV-RL

- Jiazheng Zhang et al.
- ACL Anthology: https://aclanthology.org/2026.findings-acl.1156/

**Research signal**

Verifier behavior itself can become agentic and tool-using.

**GrowthEvo boundary**

The current `CounterfactualVerifier` remains intentionally frozen and statistical. A future evidence-gathering verifier agent may collect more evidence, but it must never rewrite constraints, consent rules or promotion semantics.

### ACL 2026 · Plan-RewardBench

- Jiaxuan Wang et al.
- ACL Anthology: https://aclanthology.org/2026.acl-long.1062/

**GrowthEvo mapping**

GrowthAgentBench should include hard negatives covering poor attribution, unnecessary tool calls, bad recovery, unsupported extrapolation and constraint regressions.

---

## 4. Search-agent RL contributes local refinement patterns

### SIGIR 2026 · SmartSearch

- arXiv: https://arxiv.org/abs/2601.04888
- Code: https://github.com/RUC-NLPIR/SmartSearch

**GrowthEvo mapping**

Failure-Driven Evolution should prefer local typed repair of audience queries, evidence retrieval, tool routing or reward proxies instead of rewriting an entire Harness after every failure.

### SIGIR 2026 · Tool-Star

- arXiv: https://arxiv.org/abs/2505.16410
- Code: https://github.com/RUC-NLPIR/Tool-Star

**GrowthEvo mapping**

Tool registration, legal-action checks and process credit are kept as separate contracts so future multi-tool RL does not train against an unconstrained flat action list.

---

## 5. User simulation must be auditable

### SIGIR 2026 Tutorial · Verifiable User Simulation for Search and Recommendation Systems

- arXiv: https://arxiv.org/abs/2606.14474
- SIGIR listing: https://sigir2026.org/en-AU/pages/program/accepted-tutorials

**GrowthEvo mapping**

`UserWorldModel` and `RiskSensitiveMPC` are replay/stress components only. Their synthetic returns are never sufficient for policy promotion. Promotion still requires logged or experimental evidence through OPE and the Counterfactual Verifier.

---

## 6. Long-horizon model-based safety

Repeated growth interventions change fatigue, churn risk, spend, intent and future treatment effect. `growthevo/rl/model_based.py` therefore models:

- long-horizon belief transitions;
- fatigue decay and accumulation;
- churn recovery / deterioration;
- budget accumulation;
- repeated-touch constraints;
- lower-uplift / higher-cost / stronger-fatigue stress scenarios;
- multi-seed stochastic rollout;
- downside CVaR return;
- constraint-violation probability;
- risk-sensitive MPC ranking.

The robust score is:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation)
\]

This is a candidate-ranking and stress-test layer, not a replacement for causal evaluation.

---

## 7. External systems to integrate behind stable adapters

The core package stays dependency-light. Heavy causal and RL systems should be integrated behind typed contracts.

| Project | Intended role | Link |
|---|---|---|
| verl | PPO/GRPO and RL post-training | https://github.com/volcengine/verl |
| Agent Lightning | agent execution / RL training separation and credit assignment | https://github.com/microsoft/agent-lightning |
| Tool-Star | multi-tool Agent-RL recipes | https://github.com/RUC-NLPIR/Tool-Star |
| SmartSearch | process-reward-guided local refinement | https://github.com/RUC-NLPIR/SmartSearch |
| Open Bandit Pipeline | logged bandit data and OPE baselines | https://github.com/st-tech/zr-obp |
| CausalML | uplift / treatment-effect modeling | https://github.com/uber/causalml |
| EconML | heterogeneous treatment effects / DML | https://github.com/py-why/EconML |
| RecSim NG | probabilistic user / recommender simulation | https://github.com/google-research/recsim_ng |

Runtime facts, consent, budget, event history and promotion semantics remain owned by GrowthEvo.

---

## 8. Claims boundary

The following are intentionally **not** presented as completed results:

- trained production IQL/CQL/CPO/GRPO policies;
- reproduced DARA GRPO-Adaptive or LBM GQPO;
- a learned neural user world model;
- calibrated CATE on real GrowthEvo datasets;
- real online A/B uplift;
- production ad-auction latency;
- full Agent Lightning / verl integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity.

These become project claims only after reproducible code and evaluation exist.

---

## 9. Research-grade milestones

1. **GrowthAgentBench**: OBD/Criteo adapters, delayed outcomes, support mismatch and fatigue scenarios.
2. **CATE backend**: DR-Learner / causal forest / neural uplift with calibrated uncertainty.
3. **Offline RL backend**: constrained IQL/CQL with behavior-support regularization.
4. **Planner Agent-RL**: real Harness trajectory collection, GrowthPRM rewards and external trainer adapters.
5. **World-model audit**: next-state calibration, rollout-error growth curves and real-vs-sim discrepancy reports.
6. **Sequential promotion**: replay → OPE → calibrated gate → shadow cohort → canary → rollback.
