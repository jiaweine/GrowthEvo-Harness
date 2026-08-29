<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize what an action changes — not merely what a model predicts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-Cross--Fitted%20β*--IPS%20%7C%20DR%20%7C%20Robust-0A7EA4)

`Group-Aware Cross-Fitted DR` · `Calibrated Feasible Safe PI` · `Cross-Fitted β*-IPS` · `Locked Holdout Evaluation` · `Risk-Sensitive MPC` · `Dynamics-Aware GAE`

</div>

---

## What GrowthEvo optimizes

普通 propensity / conversion model 回答：

> **谁最可能转化？**

GrowthEvo 研究的是更严格的问题：

> **对状态 `x` 采取动作 `a`，相比 `NO_TREATMENT`，究竟产生了多少可归因的增量价值？**

核心对象是 conditional treatment effect：

```math
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
```

`NO_TREATMENT` 是一级动作。没有足够支持、校准或反事实证据时，系统允许 abstain / holdout，而不是强迫选一个 treatment。

---

## Canonical frontier stack

```text
logged causal / bandit data
        ↓
group-aware cross-fitting
        ↓
Doubly Robust CATE + pluggable nuisance/effect learners
        ↓
strict positivity + practical overlap + distributional support
        ↓
calibrated / inferential lower & upper bounds
        ↓
final-feasible Support-Anchored Safe PI
        ↓
cross-fitted β*-IPS + robust OPE estimator panel
        ↓
locked validation selection → one frozen holdout reveal
        ↓
conformal verification + risk-sensitive planning
        ↓
dynamics-aware trajectory credit
```

设计原则：

1. **Incrementality before prediction** — uplift / causal effect 优先于 raw conversion score。
2. **Support before optimization** — function approximator 能外推，不代表数据支持该动作。
3. **Calibration before confidence** — model residual 不是自动成立的 causal confidence interval。
4. **Feasibility before ranking** — 比较最终可执行策略，不比较被约束前的 raw action score。
5. **Validation before holdout** — estimator / hyperparameter 只能在 validation 上选；final test 不用于挑赢家。
6. **Evidence before promotion** — 没有可审计 artifact 的数字不升级为当前 benchmark claim。

---

## 1. Group-Aware Cross-Fitted Doubly Robust CATE

对于 treatment `a` 与 control `a₀`，multi-action logging propensity 先在 pair 内归一化：

```math
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

在 held-out fold 上构造 doubly-robust pseudo-outcome：

```math
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

当前实现的关键点：

- repeated user / cluster 可通过 `group_id` 进行 group-aware fold assignment，减少跨 fold 泄漏；
- nuisance outcome learner 与 second-stage effect learner 都可替换，dependency-free Ridge 只是 reference backend；
- **strict positivity**、**practical overlap threshold**、**propensity clipping** 是三个不同概念，不再被一个参数混在一起；
- 默认不靠隐式 clipping 把缺乏支持的数据伪装成稳定数据。

### OOF uncertainty

第二阶段 uncertainty 使用 held-out effect predictions，而不是同一批 pseudo-outcome 的 in-sample residual：

```math
\widehat\sigma_{OOF}
=
\sqrt{
\frac{1}{n}
\sum_{i=1}^{n}
\left(
\widetilde\tau_i-\widehat\tau_{-f(i)}(x_i)
\right)^2
}.
```

它是 model / extrapolation diagnostic，不被自动宣称成 causal confidence interval。

### Distributional support

除 feature min/max 外，使用正则化 Mahalanobis distance 检测包围盒内部的低密度区域：

```math
d_M(x)
=
\sqrt{
(x-\bar x)^\top
(\Sigma+\lambda I)^{-1}
(x-\bar x)
}.
```

令训练分布 support radius 为 `r_q`，则：

```math
\xi(x)
=
\max\left(0,\frac{d_M(x)}{r_q}-1\right),
```

```math
S(x)
=
\frac{\mathrm{OverlapCoverage}}{1+\xi(x)}.
```

所以“落在 feature min/max 内”不再等于“具有高支持”。

---

## 2. Calibrated Final-Feasible Safe Policy Improvement

对每个动作需要 pessimistic value 与 conservative cost。强模式直接接收上游校准 / 推断得到的 bound：

```math
Q_a^- = L_a,
\qquad
C_a^+ = U_a,
```

其中 `L_a` / `U_a` 可以来自 conformal、独立统计推断或其他明确的 confidence protocol。

历史 Gaussian heuristic 仍保留为 **reference mode**：

```math
Q_a^-
=
\widehat Q_a-z\widehat\sigma_a,
\qquad
C_a^+
=
\widehat C_a+z\widehat\sigma_{C,a}.
```

但 generic model uncertainty 不会被默认包装成“真实置信区间”。

### Explicit support

生产 / paper-facing 模式可以直接给每个 treatment 一个 `support_eligible` 决策。缺少 explicit support 时可 fail closed；behavior-probability floor 只作为兼容 reference protocol。

### Per-action feasible update

从 behavior policy `μ` 向动作 `a` 的 point-mass policy 移动：

```math
\pi_a^{(\eta)}
=(1-\eta)\mu+\eta\delta_a.
```

TV trust region 给出：

```math
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
```

若该方向增加 conservative expected cost：

```math
\eta
\le
\frac{C_{max}-C_\mu^+}{C_a^+-C_\mu^+}.
```

最终比较的是每个动作 **截断后的 feasible candidate value**，以及可选的 support-anchored learned proposal，而不是先 raw argmax 再事后裁剪。

若 behavior policy 已违反硬 cost limit，并且 `NO_TREATMENT` 满足 hard bound，则安全 fallback 为：

```math
\pi(a_0)=1.
```

---

## 3. Frontier Off-Policy Evaluation

当前 flagship OPE estimator 是 **cross-fitted β*-IPS**。DM / IPS / SNIPS / DR / SWITCH-DR / DR-OS / Meta-OPE 同时返回，用于 robustness、disagreement 与效率诊断。

### Importance weight

```math
w_i
=
\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
```

### Doubly Robust

```math
\widehat V_{DR}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
```

### Cross-fitted β*-IPS

令：

```math
Z_i=w_i-1.
```

β coefficient 只使用不包含当前 evaluation fold 的数据：

```math
\widehat\beta^*_{-f(i)}
=
\frac{\widehat{\mathrm{Cov}}_{-f(i)}(wR,Z)}
{\widehat{\mathrm{Var}}_{-f(i)}(Z)}.
```

最终：

```math
\widehat V_{\beta,CF}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
w_i r_i
-\widehat\beta^*_{-f(i)}(w_i-1)
\right].
```

same-sample β*-IPS 保留为 diagnostic，不是默认 promotion estimator。

### Robust panel

同一次 evaluation 可以看到：

- Direct Method；
- IPS；
- SNIPS；
- Doubly Robust；
- SWITCH-DR；
- DR optimistic shrinkage / DR-OS；
- cross-fitted β*-IPS；
- same-sample β*-IPS diagnostic；
- Meta-OPE / BLUE-style correlated-estimator diagnostic。

SWITCH threshold 与 DR-OS λ 必须在 validation 上固定，不能看 final-test error 后再调。

### Uncertainty + overlap diagnostics

若实验定义了 defensible clusters，可使用 cluster-robust SE；adapter 不会擅自从 timestamp / user string 猜 cluster。

同时报告：

- estimator-specific SE；
- ESS / ESS ratio；
- target-policy-mass support coverage；
- max importance weight；
- weight CV；
- mean importance weight / normalization error。

```math
ESS
=
\frac{(\sum_i w_i)^2}{\sum_i w_i^2}.
```

**High estimated value + weak overlap = insufficient evidence.**

---

## 4. Locked Real-World Evaluation

真正比较“哪个 estimator / model 性能更好”时，不能在 final test 上把所有方法跑一遍再挑最好看的。

`growthevo/bench/locked_evaluation.py` 提供：

- `LockedOPEProtocol`
- `LockedTargetingProtocol`
- immutable evidence fingerprints
- `LockedBenchmarkArtifact`

核心约束：

1. candidates / hyperparameters 预先声明；
2. validation 上选择；
3. winner 冻结后才允许 final holdout；
4. validation/test stable IDs 任意重叠都 fail closed；
5. 一个 protocol object 只允许一次 holdout reveal；
6. artifact 绑定 commit SHA、protocol fingerprint、tuning evidence、test evidence 与最终 winner。

OPE fingerprint 绑定 reward、propensity、target-policy probability、Q predictions、record ID 与 cluster ID。Criteo-style targeting fingerprint 还绑定模型 score，因此换模型输出会得到新的 evidence identity。

### Executable Open Bandit-style runner

安装后可使用：

```bash
growthevo-locked-ope \
  --tuning-jsonl validation.jsonl \
  --test-jsonl holdout.jsonl \
  --candidates-json ope_candidates.json \
  --tuning-reference 0.01234 \
  --test-reference 0.01210 \
  --benchmark open-bandit-ope \
  --dataset obd-all-random-vs-bts \
  --commit-sha "$(git rev-parse HEAD)" \
  --output benchmark-result.json
```

CLI 的代码路径会先完成 validation selection，**之后才打开 test JSONL**。完整输入 schema 与 promotion rule 见 `docs/LOCKED_OPE_RUN.md`。

---

## 5. One-Sided Conformal Verification

对需要 lower bound 的量：

```math
r_i^{lower}
=
\widehat y_i-y_i.
```

对需要 upper bound 的量：

```math
r_i^{upper}
=
y_i-\widehat y_i.
```

有限样本 quantile：

```math
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

形成 one-sided margin，并可对多个约束做 family-wise correction。

---

## 6. Risk-Sensitive Long-Horizon Planning

单步 uplift 最大不代表长期价值最大。候选 sequence 通过 stochastic rollout 估计 return distribution，并使用 downside CVaR：

```math
CVaR_\alpha(R)
=
\mathbb E[R\mid R\le VaR_\alpha(R)].
```

```math
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
```

高均值但 downside tail / violation probability 更差的方案会被降权。

---

## 7. Dynamics-Aware Process Credit

Potential shaping：

```math
F_t
=
\gamma\Phi(s_{t+1})-\Phi(s_t).
```

GAE：

```math
\delta_t
=
r_t+\gamma V(s_{t+1})-V(s_t),
```

```math
A_t
=
\delta_t+\gamma\lambda A_{t+1}.
```

只有真实 dynamics discontinuity 才切断 bootstrap / recursive trace。普通 export window 是 truncation metadata，不会仅因切窗改变训练 target。

---

## Implementation map

| Component | Source |
| --- | --- |
| Group-aware Cross-Fitted DR / support-aware CATE | `growthevo/causal/dr_learner.py` |
| CATE serving bridge | `growthevo/causal/serving.py` |
| Calibrated feasible Safe PI | `growthevo/rl/safe_policy_improvement.py` |
| Cross-fitted β*-IPS + robust OPE panel | `growthevo/rl/ope.py` |
| Locked benchmark protocol | `growthevo/bench/locked_evaluation.py` |
| Locked OPE CLI | `growthevo/bench/locked_ope_cli.py` |
| Real-world dataset adapters | `growthevo/bench/real_world.py`, `growthevo/bench/criteo.py` |
| One-sided conformal verification | `growthevo/rl/conformal.py` |
| Risk-sensitive MPC / CVaR | `growthevo/rl/model_based.py` |
| Process reward | `growthevo/rl/process_reward.py` |
| Dynamics-aware GAE | `growthevo/training/trajectory.py` |

算法版本选择 rationale：`docs/FRONTIER_ALGORITHM_STACK.md`  
真实数据证据边界：`docs/REAL_WORLD_BENCHMARKS.md`  
Locked OPE 执行格式：`docs/LOCKED_OPE_RUN.md`

---

## Evaluation status

### CI-verified acceptance gates

这些 gate 由仓库测试直接执行；它们是当前代码可以复现的证据：

| Property | Gate |
| --- | ---: |
| Synthetic CATE recovery | RMSE `< 0.03` |
| Logged propensity overlap | coverage `> 0.95` |
| Synthetic learned CATE policy | oracle regret `< 0.015` |
| Unsupported optimistic treatment | cannot increase without support |
| Unsafe expected cost | `NO_TREATMENT` fallback |
| Dynamics boundary | stops GAE leakage |
| Locked holdout protocol | validation/test overlap fails closed |
| Locked OPE runner | only frozen validation winner reaches holdout |

### Real-world benchmark evidence

第三方大数据集不 vendored 到仓库，因此 CI **不会**伪装成已经重跑 Criteo / Open Bandit full benchmark。

之前 README 曾记录：

| Dataset | Historical record | Current status |
| --- | ---: | --- |
| Criteo Uplift v2 | Uplift@10% `+6.8%` | **legacy / pre-locked-protocol** |
| Open Bandit Dataset | OPE Error `-8.4%` | **legacy / pre-frontier-OPE + pre-locked-protocol** |

这两个数字现在只保留 provenance，**不是当前 frontier stack 的确认性能 claim**。下一次 promotion 必须由当前 commit 上的 locked protocol 产生 artifact，并公开 validation scoreboard、唯一 final winner、support diagnostics 与 evidence fingerprints。

换句话说：当前代码的算法栈已经升级，但在真实 full datasets 重新跑完之前，不把旧数字冒充成新算法性能。

---

## Reproduce code-level verification

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

- Causal estimates are not trusted outside observed support merely because a function approximator can extrapolate.
- Strict positivity, practical overlap and propensity clipping are not interchangeable concepts.
- Model residual diagnostics are not called causal confidence bounds unless calibration/inference gives them that meaning.
- OPE point estimates are insufficient when ESS/support are weak.
- Cross-fitted β*-IPS is the flagship efficient OPE estimator; robustness estimators do not authorize final-test shopping.
- Safe PI ranks final feasible pessimistic policies and can consume externally calibrated bounds.
- Long-horizon rollout ranks risk; it does not replace causal identification.
- `NO_TREATMENT` remains available whenever positive treatment evidence is insufficient.
- Dataset adapter availability is not the same thing as a reproduced benchmark result.

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Calibrated feasible improvement · Locked counterfactual evaluation · Risk-sensitive learning**

</div>
