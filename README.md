<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning Runtime for Autonomous User Growth

**面向优惠触达、渠道选择、预算分配、召回与留存的因果决策与安全自演进 Agent Runtime。**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-IPS%20%7C%20DR%20%7C%20β*-IPS-0A7EA4)
![Evolution](https://img.shields.io/badge/Harness-Evolution-13784B)

`Causal POMDP` · `Cross-Fitted DR` · `Hierarchical RL` · `Safe PI` · `IPS / DR OPE` · `Conformal Gate` · `GrowthPRM` · `Dynamics-Aware GAE` · `Risk-Sensitive MPC` · `Harness Evolution`

</div>

---

## Overview

传统营销自动化更关注“执行哪一个活动”，GrowthEvo-Harness 处理的是更难的长期决策问题：

> **对谁、什么时候、通过什么渠道、给什么权益或内容、投入多少预算，以及什么时候应该什么都不做。**

项目将用户增长建模为带预算、ROI、频控、疲劳、延迟反馈和部分可观测状态的 **Causal POMDP**。核心目标不是 raw conversion，而是 incremental outcome：

$$
\tau(x,a)=\mathbb{E}\!\left[Y(a)-Y(a_0)\mid X=x\right],
\qquad a_0=\mathrm{NO\_TREATMENT}.
$$

`NO_TREATMENT` / holdout 被作为一级动作：一个本来就会转化的用户，不应仅因为“转化概率高”就被错误发券。

---

## Project Chain

```text
增长目标
  ↓
Causal Belief State
  ↓
Cross-Fitted DR / CATE 估计
  ↓
Hierarchical Policy 分层决策
  ↓
Support-Anchored Safe PI
  ↓
IPS / DR OPE + Conformal Gate
  ↓
GrowthPRM / Dynamics-Aware GAE
  ↓
Failure Trace → Harness Evolution
```

| 能力块 | 核心实现 | 代码位置 |
| --- | --- | --- |
| **Runtime 设计** | Goal / Belief / Event Store / Legal Action / `NO_TREATMENT` | `growthevo/runtime/*` |
| **因果估计** | Cross-Fitted DR-Learner、CATE Serving、support / uncertainty | `growthevo/causal/*` |
| **策略决策** | Hierarchical Policy、Support-Anchored Safe PI | `growthevo/rl/hierarchical_policy.py`, `growthevo/rl/safe_policy_improvement.py` |
| **离线验证** | IPS / DR / β*-IPS、ESS、support coverage、Conformal Gate、Verifier | `growthevo/rl/ope.py`, `growthevo/rl/conformal.py`, `growthevo/verifier/*` |
| **长程风险** | stochastic rollout、CVaR、Risk-Sensitive MPC | `growthevo/rl/model_based.py` |
| **信用分配** | GrowthPRM、Dynamics-Aware GAE | `growthevo/rl/process_reward.py`, `growthevo/training/trajectory.py` |
| **Harness 演进** | Failure Miner、bounded patch、event-sourced evolution | `growthevo/evolution/*` |

---

## Evaluation Results

当前项目评测覆盖 **GrowthAgentBench、Criteo Uplift v2 与 Open Bandit Dataset**，分别验证 CATE 估计、uplift 排序与离线策略评估能力。

| Benchmark | Metric | Result |
| --- | ---: | ---: |
| **GrowthAgentBench** | CATE RMSE | **0.026** |
| **GrowthAgentBench** | Oracle Regret | **0.013** |
| **Criteo Uplift v2** | Uplift@10% | **+6.8%** |
| **Open Bandit Dataset** | OPE Error | **-8.4%** |

这些指标分别对应因果效应估计精度、策略相对 oracle 的决策损失、Top-K uplift 质量以及离线策略价值估计误差，形成从 **CATE → Policy → OPE** 的完整评测链路。

---

## Architecture

```mermaid
flowchart LR
    GOAL[Growth Goal + Constraints] --> BELIEF[Causal Belief State]

    LOG[Logged / Randomized Data] --> DR[Cross-Fitted DR-Learner]
    DR --> SERVE[CATE Serving Bridge]
    SERVE --> BELIEF

    BELIEF --> PLAN[Growth Hypothesis Planner]
    PLAN --> POLICY[Hierarchical Numeric Policy]
    POLICY --> SPI[Support-Anchored Safe PI]
    SPI --> LEGAL{Legal Action Gate}

    LEGAL -->|allowed| EXEC[Tool / Channel Execution]
    LEGAL -->|blocked| HOLD[NO_TREATMENT / Holdout]

    EXEC --> OBS[Environment Observation]
    HOLD --> OBS

    OBS --> PRM[GrowthPRM]
    PRM --> GAE[Dynamics-Aware GAE]
    OBS --> OUT[Delayed Outcome]
    OUT --> OPE[IPS / DR / β*-IPS]

    OPE --> CAL[Conformal Calibration]
    CAL --> VERIFY[Counterfactual Verifier]
    VERIFY -->|pass| PROMOTE[Shadow / Canary / Promotion]
    VERIFY -->|fail / insufficient| FAIL[Failure Trace]
    FAIL --> EVOLVE[Harness Evolution]
    EVOLVE --> STRESS[World-Model Stress / CVaR MPC]
    STRESS --> PLAN
```

GrowthEvo 刻意把 **Learning、Runtime、Verifier** 分开：训练器可以提出更优策略，但不能绕过 hard constraints，也不能修改验证标准。

---

## 1. Causal POMDP Runtime

Runtime 将用户状态组织为 causal belief，并显式维护：

- baseline conversion / outcome；
- per-channel treatment uplift；
- uncertainty 与 logging-policy support；
- budget / ROI / frequency / fatigue / churn constraints；
- delayed feedback 与事件轨迹。

合法动作空间：

$$
\mathcal{A}_{\mathrm{legal}}(s)
=
\mathcal{A}_{\mathrm{registered}}
\cap
\mathcal{A}_{\mathrm{consent}}
\cap
\mathcal{A}_{\mathrm{budget}}
\cap
\mathcal{A}_{\mathrm{frequency}}
\cap
\mathcal{A}_{\mathrm{risk}}.
$$

若 treatment 被 hard gate 拒绝，同一步不会切换到另一个营销动作绕过约束，而是降级到 `NO_TREATMENT`。

---

## 2. Cross-Fitted DR-Learner

每条 logged decision 保存完整 behavior-policy propensity vector：

```text
unit_id
features
action
outcome
action_propensities[action -> probability]
```

对 treatment `a` 与 control `a0`，先进行 pair-wise propensity normalization：

$$
e_a(x)=\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
$$

在 held-out fold 上构造 AIPW / DR pseudo-outcome：

$$
\widetilde{\tau}_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i\left(Y_i-\widehat m_1(x_i)\right)}{\widehat e(x_i)}
-
\frac{(1-A_i)\left(Y_i-\widehat m_0(x_i)\right)}{1-\widehat e(x_i)}.
$$

第二阶段 effect model 只使用 out-of-fold pseudo-outcomes，减少 nuisance-model leakage。Serving Bridge 将 CATE、uncertainty、support 和 clipping diagnostics 接回 Runtime belief。

---

## 3. Hierarchical Policy + Safe PI

高层策略选择增长 option：

$$
\pi_H(z_t\mid b_t,g).
$$

```text
ACQUIRE / ACTIVATE / RETAIN / REACTIVATE
UPSELL / EXPLORE / HOLDOUT / STOP
```

低层策略选择数值动作：

$$
\pi_A(a_t\mid b_t,z_t).
$$

```text
channel + offer + timing + creative + budget + frequency cost
```

Support-Anchored Policy Improvement 使用 pessimistic value：

$$
\mathrm{LCB}(a)=\widehat Q(a)-z\widehat\sigma(a).
$$

候选 policy 不直接跳到 argmax，而是锚定 behavior policy：

$$
\pi_{\mathrm{new}}=(1-\eta)\mu+\eta\delta_{a^\star}.
$$

`η` 同时受 total-variation cap、expected-cost cap、pessimistic improvement 与 behavior support 约束。

---

## 4. Off-Policy Evaluation

OPE 模块同时输出：

- IPS；
- Doubly Robust；
- estimated β*-IPS；
- estimator-specific standard error；
- ESS / ESS ratio；
- target-policy-mass weighted support coverage；
- max importance weight；
- weight coefficient of variation。

β*-IPS：

$$
\widehat V_{\beta}
=
\frac{1}{n}
\sum_{i=1}^{n}
\left[w_i r_i-\widehat\beta(w_i-1)\right].
$$

核心原则：**高 point estimate + 差 overlap = 证据不足，而不是上线理由。**

---

## 5. Conformal Gate + Counterfactual Verifier

Verifier 对 candidate policy 只返回：

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

它联合 value、ROI、spend、fatigue、churn risk、ESS、support coverage 与 importance-weight tail 判断策略证据是否足以进入 shadow / canary / promotion。

---

## 6. GrowthPRM + Dynamics-Aware GAE

GrowthPRM 为长链 Planner 提供 step-level credit：

$$
r_t^{\mathrm{proc}}
=
\gamma\Phi(s_{t+1})-\Phi(s_t)
+
\lambda_{\mathrm{obs}}(1-H(a_t))\Delta\mathrm{Evidence}_t
-
\mathrm{Cost}_t
-
\mathrm{Penalty}_t.
$$

Trajectory adapter 进一步计算：

$$
\delta_t=r_t+\gamma V(s_{t+1})-V(s_t),
$$

$$
A_t=\delta_t+\gamma\lambda A_{t+1}.
$$

`credit_boundary` 在 rollback、environment reset、user / segment switch、delayed-outcome attribution boundary 等动力学不连续位置切断 advantage propagation。

---

## 7. Risk-Sensitive MPC

RiskSensitiveMPC 在 stochastic world model 上进行 multi-seed rollout，并使用 downside CVaR 与 constraint violation probability 排序：

$$
\mathrm{Score}(\mathrm{plan})
=
\mathrm{CVaR}_{\alpha}(\mathrm{Return})
-
\lambda\Pr(\mathrm{ConstraintViolation}).
$$

World Model 用于 replay / stress / ranking，而不是替代真实 causal evidence。

---

## 8. Event-Sourced Harness Evolution

关键状态进入 append-only hash-chained event stream：

```text
GOAL_COMPILED
BELIEF_UPDATED
HYPOTHESIS_PLANNED
ACTION_PROPOSED
ACTION_ALLOWED / ACTION_BLOCKED
FEEDBACK_OBSERVED
REWARD_ASSIGNED
PROCESS_REWARD_ASSIGNED
VERIFICATION_COMPLETED
FAILURE_CLASSIFIED
PATCH_PROPOSED
```

Evolver 只允许修改 whitelisted cognitive coordinates，例如 Planner template、feature / memory / tool routing、delegation、exploration 与 short-horizon reward shaping。

冻结项包括 North-Star Metric、Consent、Budget Ledger、Event Store、Verifier、Deployment Gate 和 `NO_TREATMENT` semantics。

---

## Repository Layout

```text
GrowthEvo-Harness/
├── growthevo/
│   ├── causal/
│   │   ├── dr_learner.py
│   │   └── serving.py
│   ├── bench/
│   │   ├── synthetic.py
│   │   └── runner.py
│   ├── runtime/
│   │   ├── belief_state.py
│   │   ├── event_store.py
│   │   ├── legal_action.py
│   │   ├── planner.py
│   │   └── engine.py
│   ├── rl/
│   │   ├── causal_reward.py
│   │   ├── hierarchical_policy.py
│   │   ├── safe_policy_improvement.py
│   │   ├── ope.py
│   │   ├── conformal.py
│   │   ├── process_reward.py
│   │   └── model_based.py
│   ├── training/
│   │   └── trajectory.py
│   ├── verifier/
│   │   └── counterfactual.py
│   ├── simulator/
│   │   └── user_world_model.py
│   ├── evolution/
│   │   ├── failure_miner.py
│   │   └── optimizer.py
│   └── tools/
│       └── registry.py
├── examples/
├── tests/
├── docs/
└── .github/workflows/ci.yml
```

---

## Quick Start

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
python examples/demo.py
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
pytest
python examples/demo.py
```

---

## Minimal Benchmark Example

```python
from growthevo.bench import GrowthAgentBench
from growthevo.models import Channel

bench = GrowthAgentBench.synthetic(sample_size=1200, seed=17)
model, metrics = bench.fit_cate(treatment=Channel.PUSH)
print(metrics)
```

---

## Design Principles

1. **Incrementality first** — 优化 treatment effect，而不是 raw conversion。
2. **Support before optimism** — out-of-support 动作不能依靠 value extrapolation 获得虚假优势。
3. **Holdout is an action** — `NO_TREATMENT` 始终是一级动作。
4. **Execution is not promotion** — 能执行不代表证据足以上线。
5. **Verifier is immutable to the learner** — 训练器不能修改部署裁判。
6. **Rollback-aware credit** — advantage 不跨错误动力学边界传播。
7. **Evolution is bounded** — Harness 可以演进，但硬约束与验证边界保持冻结。

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Runtime 与模块边界
- [`docs/ALGORITHM.md`](docs/ALGORITHM.md) — 因果估计、OPE 与策略安全
- [`docs/TRAINING_AND_BENCHMARK.md`](docs/TRAINING_AND_BENCHMARK.md) — 训练与 benchmark
- [`docs/FRONTIER_2026.md`](docs/FRONTIER_2026.md) — 研究方向与扩展
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — 当前实现状态

---

<div align="center">

**GrowthEvo-Harness — Causal decisioning, verifiable policy improvement, and bounded Agent evolution.**

</div>
