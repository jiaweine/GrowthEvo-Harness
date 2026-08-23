# GrowthEvo Frontier Map · 2026

This document records the research signals behind GrowthEvo v0.2 and, more importantly, the exact boundary between **what the repository implements** and **what remains a future backend**.

The goal is not citation decoration. Every paper below is included because it changes a concrete runtime or learning decision.

---

## 1. Off-policy evaluation is moving beyond SNIPS

### SIGIR 2026 · Additive Control Variates Dominate Self-Normalisation in Off-Policy Evaluation

- Olivier Jeunen, Shashank Gupta.
- Microsoft Research publication: https://www.microsoft.com/en-us/research/publication/additive-control-variates-dominate-self-normalisation-in-off-policy-evaluation/
- arXiv: https://arxiv.org/abs/2602.14914

**Research signal**

For ranking/recommendation OPE, the work proves that an optimally chosen additive baseline correction, β\*-IPS, asymptotically dominates SNIPS in mean-squared error. This is directly relevant to user-growth policy evaluation because marketing policies are contextual decision policies evaluated from logged propensities.

**GrowthEvo mapping**

Implemented in `growthevo/rl/ope.py`:

- plain IPS;
- Doubly-Robust estimator;
- estimated β\*-IPS using `w - 1` as the zero-mean control variate;
- estimator standard errors;
- ESS and ESS ratio;
- practical support coverage;
- maximum importance weight;
- importance-weight coefficient of variation.

**Boundary**

The repository does not claim that β\*-IPS solves hidden confounding, missing propensities, or arbitrary support violations. The verifier abstains when overlap diagnostics are weak.

---

## 2. Advertising optimization is becoming uncertainty-aware and hierarchical

### WWW 2026 · Auto-bidding under Return-on-Spend Constraints with Uncertainty Quantification

- Jiale Han et al.
- arXiv: https://arxiv.org/abs/2509.16324

**Research signal**

Industrial auto-bidding needs uncertainty-aware value prediction while satisfying budget and Return-on-Spend constraints. The paper uses conformal prediction to quantify uncertainty and derives constraint-aware bidding guarantees.

**GrowthEvo mapping**

Implemented in `growthevo/rl/conformal.py` and `growthevo/verifier/counterfactual.py`:

- one-sided split-conformal residual calibration from matured shadow cohorts;
- value lower bound;
- ROI lower bound;
- spend/fatigue/churn upper bounds;
- conservative intersection with the existing statistical LCB.

**Boundary**

Split-conformal coverage requires an exchangeability assumption. Under detected distribution shift, GrowthEvo should recalibrate or abstain; it does not present conformal calibration as shift-proof.

### WWW 2026 · DARA: Few-shot Budget Allocation in Online Advertising via In-Context Decision Making with RL-Finetuned LLMs

- Mingxuan Song et al.
- arXiv: https://arxiv.org/abs/2601.14711

**Research signal**

Few-shot semantic reasoning and precise numerical allocation are different subproblems. DARA separates high-level reasoning from fine-grained optimization and uses RL-finetuned LLMs for adaptive budget allocation.

**GrowthEvo mapping**

The runtime keeps `GrowthHypothesisPlanner` separate from `HierarchicalGrowthPolicy`. The planner owns semantic intent; the policy owns channel/offer/budget numeric decisions.

### WWW 2026 · LBM: Hierarchical Large Auto-Bidding Model via Reasoning and Acting

- Yewen Li et al.
- arXiv: https://arxiv.org/abs/2603.05134

**Research signal**

LBM explicitly separates a high-level `Think` model from a low-level `Act` model and uses offline reinforcement fine-tuning to reduce hallucination and improve generalization in dynamic auctions.

**GrowthEvo mapping**

CausalLift-HRL follows the same systems principle: semantic reasoning and numerically precise growth control are different policy layers. GrowthEvo does **not** currently reproduce GQPO; a learned planner backend remains future work.

---

## 3. Agentic RL is shifting from sparse outcomes to trajectory/process credit

### ACL 2026 · SOAR: Supervision from Observation for Agentic Reinforcement Learning

- Meng Li et al.
- ACL Anthology: https://aclanthology.org/2026.acl-long.1624/

**Research signal**

Agentic RL should learn from environment observations, not only final outcome rewards. SOAR assigns learning signal to observation tokens based on the confidence/entropy of preceding actions.

**GrowthEvo mapping**

Implemented in `growthevo/rl/process_reward.py`:

- normalized action entropy;
- evidence gain from environment/tool observation;
- confidence-weighted observation credit;
- explicit tool failure, duplicate evidence, cost and side-effect penalties.

GrowthEvo's implementation is a runtime-level process reward contract, not a reproduction of SOAR's token-level training objective.

### Findings of ACL 2026 · ToolPRMBench

- Dawei Li et al.
- ACL Anthology: https://aclanthology.org/2026.findings-acl.602/
- Code: https://github.com/David-Li0406/ToolPRMBench

**Research signal**

Process reward models for tool-using agents need dedicated local-step and full-trajectory evaluation; generic outcome reward is insufficient.

**GrowthEvo mapping**

`GrowthProcessRewardModel` makes tool validity and intermediate evidence progress explicit and testable. A Growth-specific PRM benchmark is planned for `GrowthAgentBench`.

### Findings of ACL 2026 · AgentV-RL: Scaling Reward Modeling with Agentic Verifier

- Jiazheng Zhang et al.
- ACL Anthology: https://aclanthology.org/2026.findings-acl.1156/

**Research signal**

A verifier itself can become an agentic, tool-using reasoning process. Forward and backward verification can improve reward modeling beyond static outcome judges.

**GrowthEvo mapping**

Current `CounterfactualVerifier` remains intentionally frozen and statistical. A future verifier-agent may gather additional evidence, but it must not obtain permission to rewrite constraints or promotion semantics.

### ACL 2026 · Plan-RewardBench

- Jiaxuan Wang et al.
- ACL Anthology: https://aclanthology.org/2026.acl-long.1062/

**Research signal**

Reward models degrade on longer agent trajectories and need hard negatives covering planning and recovery failures.

**GrowthEvo mapping**

GrowthAgentBench should include preference pairs that differ only in attribution quality, unnecessary tool calls, constraint handling, recovery quality, and unsupported extrapolation.

---

## 4. Search-agent work provides reusable credit/refinement patterns

### SIGIR 2026 · SmartSearch: Process Reward-Guided Query Refinement for Search Agents

- Tongyu Wen, Guanting Dong, Zhicheng Dou.
- arXiv: https://arxiv.org/abs/2601.04888
- Code: https://github.com/RUC-NLPIR/SmartSearch

**Research signal**

Intermediate tool/query quality can be optimized with process rewards and selective refinement rather than restarting an entire trajectory.

**GrowthEvo mapping**

Failure-Driven Evolution should prefer local coordinate repair: bad audience query, evidence retrieval, tool routing, or reward proxy should generate a typed patch rather than a full Harness rewrite.

### SIGIR 2026 · Tool-Star: Empowering Multi-Tool Collaborative Web Agent via Reinforcement Learning

- Guanting Dong et al.
- arXiv: https://arxiv.org/abs/2505.16410
- Code: https://github.com/RUC-NLPIR/Tool-Star

**Research signal**

Multi-tool agents benefit from dedicated tool-integrated data synthesis, curriculum and hierarchical reward design.

**GrowthEvo mapping**

The runtime already separates tool registration, legal action checks and process credit. Future Agent-RL training should preserve these runtime boundaries rather than train against an unconstrained flat tool list.

---

## 5. User simulation is becoming an auditable artifact

### SIGIR 2026 Tutorial · Verifiable User Simulation for Search and Recommendation Systems

- Chenglong Ma et al.
- arXiv: https://arxiv.org/abs/2606.14474
- SIGIR listing: https://sigir2026.org/en-AU/pages/program/accepted-tutorials

**Research signal**

A user simulator should be inspectable through persona/contract/execution/trace/verification/feedback/refinement rather than treated as an unquestioned synthetic oracle.

**GrowthEvo mapping**

`UserWorldModel` and `RiskSensitiveMPC` are explicitly labelled replay/stress components. Their returns are never sufficient for policy promotion. Promotion still requires logged/experimental evidence through OPE and the Counterfactual Verifier.

---

## 6. Model-based long-horizon safety

Growth marketing is not a one-step conversion problem. Repeated interventions change fatigue, churn risk, budget state and future uplift.

Implemented in `growthevo/rl/model_based.py`:

- long-horizon belief transitions;
- fatigue decay and accumulation;
- churn recovery / deterioration;
- budget accumulation;
- repeated-touch constraints;
- stress scenarios for lower uplift, higher cost and stronger fatigue;
- multi-seed stochastic rollout;
- downside CVaR return;
- constraint-violation probability;
- risk-sensitive MPC ranking.

The robust score is:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation)
\]

This is deliberately a **candidate-ranking and stress-test layer**, not a replacement for offline/online causal evaluation.

---

## 7. Open-source systems to integrate, not reimplement blindly

The project keeps its core dependency-free. Heavy training and causal libraries should be plugged in behind stable contracts.

| Project | Use in a future GrowthEvo backend | Link |
|---|---|---|
| verl | scalable PPO/GRPO and RL post-training | https://github.com/volcengine/verl |
| Agent Lightning | separate agent execution from RL training / credit assignment | https://github.com/microsoft/agent-lightning |
| Tool-Star | multi-tool agentic RL recipe and datasets | https://github.com/RUC-NLPIR/Tool-Star |
| SmartSearch | process-reward-guided local refinement | https://github.com/RUC-NLPIR/SmartSearch |
| Open Bandit Pipeline | logged bandit data and OPE baselines | https://github.com/st-tech/zr-obp |
| CausalML | uplift / treatment-effect modeling | https://github.com/uber/causalml |
| EconML | heterogeneous treatment effects / DML | https://github.com/py-why/EconML |
| RecSim NG | probabilistic multi-agent recommender simulation | https://github.com/google-research/recsim_ng |

**Rule:** GrowthEvo should wrap these systems through typed adapters. Runtime facts, consent, budget, event history and verifier semantics remain owned by GrowthEvo.

---

## 8. What v0.2 still does not claim

The following are intentionally **not** described as completed:

- a trained IQL/CQL production policy;
- reproduced DARA GRPO-Adaptive or LBM GQPO;
- a learned neural user world model;
- calibrated CATE on real GrowthEvo datasets;
- real online A/B lift;
- production ad auction latency;
- full Agent Lightning / verl integration;
- causal validity under hidden confounding;
- distribution-free guarantees under arbitrary non-stationarity.

Those belong in the next experiment/training layer and must be supported by code plus reproducible evaluation before appearing as project results.

---

## 9. Next research-grade milestones

1. **GrowthAgentBench v1**: OBD/Criteo adapters, delayed outcomes, support mismatch and fatigue scenarios.
2. **CATE backend**: DR-Learner / causal forest / neural uplift with calibrated uncertainty.
3. **Offline RL backend**: discrete/constrained IQL or CQL with behavior support regularization.
4. **Planner Agent-RL**: trajectory collection from the real Harness, GrowthPRM step rewards, external verl/Agent-Lightning trainer.
5. **World-model audit**: held-out next-state calibration, rollout-error growth curves, stress coverage and real-vs-sim discrepancy reports.
6. **Sequential promotion**: replay → OPE → conformal gate → deterministic shadow cohort → canary → rollback.
