# Real-World Benchmark Protocol

GrowthEvo should not treat one public dataset as proof of an end-to-end autonomous growth agent. The benchmark is split by the causal question each dataset can actually answer.

## Benchmark matrix

| Dataset | What is real | Primary use in GrowthEvo | What must not be claimed |
| --- | --- | --- | --- |
| Criteo Uplift | randomized advertising incrementality experiment | CATE / uplift ranking, treatment-vs-holdout policy value, calibration | sequential RL performance or exact business ROI |
| Open Bandit Dataset | production fashion recommendation logs with logged propensity scores | contextual-bandit OPE and estimator stress testing | long-horizon user-state control |
| KuaiRand | production sequential recommendation logs with randomized interventions and rich feedback | sequential offline RL, reward design, history-state modeling | exact IPS/OPE from `is_rand` alone |

The synthetic GrowthAgentBench remains useful only because it exposes ground-truth potential outcomes. It is retained as an algorithmic regression test, not as a headline real-world result.

---

## Criteo Uplift

The Criteo benchmark is produced from randomized advertising incrementality tests. The public table contains twelve anonymized dense features (`f0` through `f11`), randomized treatment assignment, visit and conversion labels, and a post-assignment exposure flag.

GrowthEvo uses:

```text
state/context = f0..f11
action = ADS or NO_TREATMENT
reward/outcome = visit or conversion
behavior propensity = randomized assignment probability
```

### Critical causal rule

`exposure` is **not** the treatment variable. It occurs after randomized assignment and can be affected by delivery. Conditioning the treatment definition on exposure would destroy the clean intent-to-treat interpretation.

`load_criteo_uplift()` therefore maps only the randomized `treatment` field to `Channel.ADS` and maps control to `NO_TREATMENT`.

When the exact assignment probability is not supplied, the loader uses the empirical randomized arm share in the loaded cohort. For final paper experiments, prefer the documented experimental assignment probability when it is available and report the empirical share as a diagnostic.

### Evaluation

Do not report ordinary ROC-AUC as the main metric for targeting. A response model answers who is likely to convert, while the growth decision asks who changes behavior because of treatment.

The repository provides `evaluate_randomized_targeting()`, which evaluates a top-score treatment policy by inverse weighting under the randomized assignment. Recommended reporting:

- policy value for top 10%, 20%, and 30% targeting budgets;
- incremental value versus treat-none;
- treat-all and treat-none references;
- treatment-effect ranking curves such as Qini/AUUC when using an external research stack;
- bootstrap confidence intervals on all headline real-data metrics;
- treatment/control counts inside each reported top-k slice.

For CATE baselines, compare at minimum:

- S-Learner;
- T-Learner;
- X-Learner;
- R-Learner;
- doubly robust learner;
- causal forest / generalized random forest where dependencies permit.

GrowthEvo's dependency-free `CrossFittedDRLearner` is a correctness/reference implementation. It should not be advertised as a state-of-the-art predictive backbone simply because the causal cross-fitting contract is sound.

Official source and benchmark paper:

- Criteo AI Lab dataset page: https://ailab.criteo.com/criteo-uplift-prediction-dataset/
- Diemert, Betlei, Renaudin, Amini, *A Large Scale Benchmark for Uplift Modeling*, AdKDD 2018.

---

## Open Bandit Dataset

Open Bandit Dataset contains real recommendation impressions from ZOZOTOWN. The useful property for GrowthEvo is that each logged action includes a real behavior-policy propensity score. The data was collected with uniform-random and Bernoulli Thompson Sampling behavior policies on the same platform.

GrowthEvo preserves:

```text
timestamp
item_id
position
click
propensity_score
user features
user-item affinity features
```

`open_bandit_to_ope()` then converts a target policy and reward-model predictions into `LoggedBanditRecord` without replacing the observed propensity.

### OPE estimator suite

The benchmark should compare estimators rather than silently picking one:

- Direct Method when a reward model is available;
- IPS;
- Doubly Robust;
- SWITCH-DR, following Wang, Agarwal, and Dudik, ICML 2017;
- Doubly Robust with optimistic shrinkage, following Su, Dimakopoulou, Krishnamurthy, and Dudik, ICML 2020;
- beta-IPS additive control variate already implemented in GrowthEvo;
- self-normalized IPS as an additional ablation when using an external OPE package.

GrowthEvo now implements IPS, DR, SWITCH-DR, optimistic DR shrinkage, and beta-IPS in one output object so the same cohort exposes estimator disagreement.

Every OPE table should include:

```text
point estimate
standard error
relative estimation error when a ground-truth policy cohort is available
ESS / N
support coverage
maximum importance weight
importance-weight coefficient of variation
```

Thresholds for SWITCH-DR and the shrinkage coefficient must be tuned on validation data, never chosen from final-test error.

Primary references:

- Saito, Aihara, Matsutani, Narita, *Open Bandit Dataset and Pipeline: Towards Realistic and Reproducible Off-Policy Evaluation*, 2020/2021.
- Wang, Agarwal, Dudik, *Optimal and Adaptive Off-policy Evaluation in Contextual Bandits*, ICML 2017.
- Su, Dimakopoulou, Krishnamurthy, Dudik, *Doubly Robust Off-policy Evaluation with Shrinkage*, ICML 2020.

Dataset/pipeline resources:

- https://github.com/sb-ai-lab/sb-obp
- https://huggingface.co/datasets/zozonext/open-bandit

---

## KuaiRand

KuaiRand is the sequential benchmark. It provides production recommendation trajectories, explicit users and timestamps, many feedback channels, and randomized interventions interleaved with the standard recommender.

GrowthEvo uses it to test the part of the system that Criteo and Open Bandit cannot test: state evolution and long-horizon credit assignment.

The adapter keeps the logged video action and constructs history-only observations. Current feedback is used as reward and only becomes state information at the next step. This prevents a common leakage bug in offline sequence benchmarks.

Default research reward:

```text
+ 1.00 click
+ 0.35 long view
+ 0.25 like
+ 0.50 follow
+ 0.20 comment
+ 0.20 forward
- 0.50 hate
```

These weights are an explicit benchmark choice, not a claim about Kuaishou's production objective. Paper experiments should report sensitivity to reward weights and also report individual feedback metrics.

### Important propensity rule

`is_rand` only says whether the displayed item came from the random intervention mechanism. It is **not** itself the probability of the displayed item. GrowthEvo therefore never converts `is_rand` into a propensity score.

If exact per-action probabilities are unavailable for a sequential experiment, use methods that do not require fabricated IPS weights and keep evaluation claims correspondingly limited.

### Offline RL baselines

For the sequential track, compare against methods designed for distribution shift rather than only PPO on static logs:

- Behavior Cloning as the indispensable lower-complexity baseline;
- Conservative Q-Learning (CQL), NeurIPS 2020;
- Implicit Q-Learning (IQL), ICLR 2022;
- Decision Transformer, NeurIPS 2021;
- a sequence-aware advertising method such as MTORL, KDD 2025, where its task assumptions can be reproduced fairly.

The reason for these baselines is structural. Offline advertising/recommendation data is dominated by behavior-policy support, extrapolation error, delayed reward, and budget constraints. CQL and IQL explicitly target out-of-distribution action/value problems; Decision Transformer tests whether conditional sequence modeling is competitive; MTORL is directly motivated by channel and budget decisions in online advertising.

Primary resources:

- KuaiRand: https://kuairand.com/
- CQL: https://papers.neurips.cc/paper/2020/hash/0d2b2061826a5df3221116a5085a6052-Abstract.html
- IQL: https://openreview.net/forum?id=68n2s9ZJWF8
- Decision Transformer: https://arxiv.org/abs/2106.01345
- MTORL: https://arxiv.org/abs/2506.23090

---

## Experiment protocol

### Splits

Criteo:

1. Split by rows with a fixed seed while stratifying treatment and outcome for development experiments.
2. Fit nuisance and CATE models only on training folds.
3. Tune model/targeting hyperparameters on validation data.
4. Report policy metrics once on the untouched test data.
5. Bootstrap the test evaluation with treatment-arm stratification.

Open Bandit Dataset:

1. Keep campaign and behavior-policy identity explicit.
2. Use a logged behavior cohort for OPE.
3. When reproducing the cross-policy protocol, use a separately collected policy cohort as empirical ground truth.
4. Tune OPE hyperparameters without using the final ground-truth comparison.
5. Report estimator error together with importance-weight diagnostics.

KuaiRand:

1. Split chronologically rather than randomly whenever future-policy evaluation is intended.
2. Keep all steps from a user in temporal order.
3. Never let current feedback enter the current state.
4. Compare behavior cloning before claiming an RL gain.
5. Report action-support diagnostics and performance by random-intervention versus standard-recommender subsets.

---

## Paper-facing result tables

A credible paper should have separate tables rather than one aggregate "GrowthEvo score".

### Incrementality table

```text
Method | Criteo outcome | top-10% incremental value | top-20% | top-30% | bootstrap CI
```

### OPE table

```text
Estimator | Open Bandit policy pair | estimate | ground truth | relative error | ESS/N | max weight
```

### Sequential offline RL table

```text
Method | KuaiRand reward | click | long-view | hate | support metric | seeds
```

### Ablation table

```text
full system
- causal cross-fitting
- support anchor
- robust OPE
- legal action gate
- process reward
- dynamics credit boundary
- risk-sensitive planning
```

Do not turn missing real-world evidence into a synthetic proxy. If a dataset cannot validate a component, mark that cell as not identified by that dataset.
