<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize what an action changes — not merely what a model predicts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-0.1.0-555555)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-IPS%20%7C%20DR%20%7C%20β*-IPS-0A7EA4)

`Cross-Fitted DR` · `Support-Anchored Safe PI` · `IPS / DR / β*-IPS` · `Conformal Calibration` · `Dynamics-Aware GAE` · `Risk-Sensitive MPC`

</div>

---

## Problem

传统 propensity / conversion model 回答的是：

> **谁最可能转化？**

GrowthEvo 研究的是更严格的决策问题：

> **对状态 `x` 采取动作 `a`，相比 `NO_TREATMENT`，究竟产生了多少可归因的增量价值？**

因此优化目标不是 raw conversion probability，而是 conditional treatment effect：

$$
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
$$

`NO_TREATMENT` 是一级动作，而不是异常分支。若证据不足或约束不允许主动干预，策略应保留不干预概率，而不是强制选择某个 treatment。

---

## Method

GrowthEvo 将问题拆成六个相互约束的算法层：

```text
logged causal data
      ↓
Cross-Fitted Doubly Robust CATE
      ↓
pessimistic action values + support
      ↓
Feasible Support-Anchored Safe PI
      ↓
IPS / DR / β*-IPS OPE + overlap diagnostics
      ↓
one-sided conformal calibration
      ↓
long-horizon risk + dynamics-aware credit
```

核心原则只有三个：

1. **Incrementality before prediction** — treatment effect 优先于 conversion score。
2. **Support before optimization** — 没有 logging support 的高估值不能驱动策略更新。
3. **Evidence before improvement** — point estimate 高但不确定性 / overlap 差时应 abstain。

---

## 1. Cross-Fitted Doubly Robust CATE

对 treatment `a` 与 control `a₀`，先将 logged multi-action propensity 在 pair 内重新归一化：

$$
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
$$

在 held-out fold 上构造 AIPW / doubly-robust pseudo-outcome：

$$
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
$$

其中 nuisance outcome model 只在其他 folds 上训练，第二阶段 effect model 只消费 out-of-fold pseudo-outcomes，降低 nuisance leakage。

### Why DR?

若 outcome model 或 propensity mechanism 中至少一侧估计良好，DR estimator 仍具有较强鲁棒性；cross-fitting 进一步降低同一样本同时拟合 nuisance 与 effect 所造成的过拟合偏差。

### Support-aware prediction

预测不仅输出 effect：

$$
\widehat\tau(x),
$$

还同时携带 uncertainty 与 support diagnostics。低 support / extrapolation 区域不能被解释成“高置信度零 uplift”，而应增加不确定性并降低后续策略更新幅度。

---

## 2. Feasible Support-Anchored Safe Policy Improvement

这是当前方法中最关键的策略更新层。

对每个动作构造 pessimistic value lower bound 与 cost upper bound：

$$
Q_a^-
=
\widehat Q_a-z\widehat\sigma_a,
$$

$$
C_a^+
=
\widehat C_a+z\widehat\sigma_{C,a}.
$$

只允许 behavior probability 满足 support floor 的 treatment 进入候选集合：

$$
\mathcal A_{sup}
=
\{a:\mu(a\mid x)\ge \epsilon_{sup}\}
\cup \{a_0\}.
$$

behavior policy 的 pessimistic baseline 为：

$$
V_\mu^-
=
\sum_a \mu(a\mid x)Q_a^-.
$$

对每个 supported action **分别求最大可行更新幅度**，而不是先选 argmax 再截断。

候选更新：

$$
\pi_a^{(\eta)}
=(1-\eta)\mu+\eta\delta_a.
$$

Total-variation trust region 给出：

$$
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
$$

若动作 cost 高于 behavior baseline，则 cost constraint 进一步给出：

$$
\eta
\le
\frac{C_{max}-C_\mu^+}{C_a^+-C_\mu^+}.
$$

因此每个动作都有自己的最大可行步长：

$$
\eta_a^*
=
\min\left(
1,
\frac{\epsilon_{TV}}{1-\mu(a\mid x)},
\eta_{cost,a}
\right).
$$

再比较约束后的 pessimistic candidate value：

$$
V_a^-
=
(1-\eta_a^*)V_\mu^-
+
\eta_a^*Q_a^-.
$$

最终选择：

$$
a^*
=
\arg\max_{a\in\mathcal A_{sup}}V_a^-.
$$

这比“先选最高 LCB 动作，再被 cost cap 截断”更合理：一个理论估值最高但几乎不可更新的动作，不会阻止第二优、但具有更大安全更新空间的动作成为最终候选。

若 behavior policy 本身已经违反硬 cost upper bound，则直接退回：

$$
\pi(a_0)=1.
$$

---

## 3. Off-Policy Evaluation

策略改进不能只依赖 learned Q / CATE。GrowthEvo 同时计算多个 OPE estimator。

### IPS

$$
\widehat V_{IPS}
=
\frac{1}{n}\sum_{i=1}^n
w_i r_i,
\qquad
w_i=\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
$$

### Doubly Robust

$$
\widehat V_{DR}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
$$

### β*-IPS control variate

令：

$$
Z_i=w_i-1,
$$

估计 variance-minimizing coefficient：

$$
\widehat\beta^*
=
\frac{\widehat{\mathrm{Cov}}(wR,Z)}{\widehat{\mathrm{Var}}(Z)}.
$$

得到：

$$
\widehat V_{\beta}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[w_i r_i-\widehat\beta^*(w_i-1)\right].
$$

### OPE is not only a point estimate

必须同时检查：

- estimator-specific standard error；
- effective sample size；
- ESS ratio；
- target-policy-mass weighted support coverage；
- maximum importance weight；
- weight coefficient of variation。

ESS：

$$
ESS
=
\frac{(\sum_iw_i)^2}{\sum_iw_i^2}.
$$

核心判据：

> **High estimated value + weak overlap = insufficient evidence.**

---

## 4. One-Sided Conformal Calibration

统计标准误不能覆盖所有 model misspecification，因此策略指标进一步使用历史 matured cohorts 做 one-sided split-conformal calibration。

对于需要 lower bound 的 value / ROI，使用 residual：

$$
r_i^{lower}
=
\widehat y_i-y_i.
$$

对于需要 upper bound 的 spend / risk，使用：

$$
r_i^{upper}
=
y_i-\widehat y_i.
$$

有限样本 conformal quantile：

$$
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
$$

最终形成：

$$
LCB(y)=\widehat y-q,
\qquad
UCB(y)=\widehat y+q.
$$

多指标同时约束时使用 family-wise error correction，使整体 gate 的错误预算不被多个 marginal tests 放大。

---

## 5. Risk-Sensitive Long-Horizon Planning

单步 uplift 最大不等于长期价值最大。长程候选序列通过 stochastic rollout 估计 return distribution，并用 downside CVaR 而不是 mean return 单独排序。

对 return `R`：

$$
CVaR_\alpha(R)
=
\mathbb E[R\mid R\le VaR_\alpha(R)].
$$

候选序列分数：

$$
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
$$

因此短期均值更高、但 downside tail 更差或 constraint violation probability 更高的计划会被降权。

---

## 6. Dynamics-Aware Process Credit

长链决策需要比 terminal reward 更细的 credit assignment。

使用 potential-based shaping：

$$
F_t
=
\gamma\Phi(s_{t+1})-\Phi(s_t),
$$

并结合 evidence gain、cost 与 failure penalties 形成 step reward。

Trajectory advantage 使用 GAE：

$$
\delta_t
=
r_t+\gamma V(s_{t+1})-V(s_t),
$$

$$
A_t
=
\delta_t+\gamma\lambda A_{t+1}.
$$

在 dynamics discontinuity 上设置 credit boundary，使 advantage 不跨不连续动力学传播。算法上等价于在边界处将 bootstrap / recursive trace 截断，从而降低错误归因。

---

## Algorithm source

公开代码入口只列算法实现：

| Algorithm | Source |
| --- | --- |
| Cross-Fitted DR / CATE | `growthevo/causal/dr_learner.py` |
| Support-Anchored Safe PI | `growthevo/rl/safe_policy_improvement.py` |
| IPS / DR / β*-IPS OPE | `growthevo/rl/ope.py` |
| One-sided conformal calibration | `growthevo/rl/conformal.py` |
| Risk-sensitive MPC / CVaR | `growthevo/rl/model_based.py` |
| Process reward | `growthevo/rl/process_reward.py` |
| Dynamics-aware GAE | `growthevo/training/trajectory.py` |

README 不展开非算法实现细节。

---

## Evaluation

### Reproducible algorithmic gates

当前仓库中的算法回归测试覆盖：

| Property | Acceptance gate |
| --- | ---: |
| CATE recovery | RMSE `< 0.03` |
| Cross-fitted overlap | coverage `> 0.95` |
| Learned CATE policy | oracle regret `< 0.015` |
| Low-support optimistic action | excluded |
| Unsafe expected cost | fallback to `NO_TREATMENT` |
| Dynamics boundary | stops GAE leakage |

### Reported evaluation record

| Benchmark | Metric | Result |
| --- | --- | ---: |
| **GrowthAgentBench** | CATE RMSE | **0.026** |
| **GrowthAgentBench** | Oracle Regret | **0.013** |
| **Criteo Uplift v2** | Uplift@10% | **+6.8%** |
| **Open Bandit Dataset** | OPE Error | **-8.4%** |

GrowthAgentBench 是已知 ground-truth treatment effects 的 synthetic causal fixture。外部 public benchmark 数字属于 evaluation record，不等同于 production evidence。

---

## Reproduce

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
pytest
```

---

## Method boundaries

- Causal estimates are not treated as valid outside observed support merely because a function approximator can extrapolate.
- World-model rollout is a risk-ranking mechanism, not a replacement for causal evidence.
- OPE point estimates are not sufficient when ESS or support coverage is poor.
- Uncertainty is used pessimistically during policy improvement.
- `NO_TREATMENT` remains available whenever positive treatment evidence is insufficient.

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Conservative policy improvement · Counterfactual evaluation · Risk-sensitive learning**

</div>
