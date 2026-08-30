# Changelog

All notable repository changes intended for a future public release are recorded here.

The project has not assigned a new release tag as part of this maintenance work. Until a version/tag is intentionally chosen, the current mainline changes remain under **Unreleased**.

## Unreleased

### Causal and policy-learning stack

- Added group-aware cross-fitted doubly robust CATE with pluggable nuisance/effect learners, explicit positivity/overlap semantics, and distributional support diagnostics.
- Added calibrated final-feasible Safe Policy Improvement with support anchoring, fail-closed feasibility, and explicit reference-vs-inferential uncertainty modes.
- Added cross-fitted β*-IPS as the default efficient OPE estimator together with DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, and Meta-OPE/BLUE-style diagnostics.
- Preserved dynamics-aware GAE, conformal verification, risk-sensitive MPC/CVaR planning, and explicit `NO_TREATMENT` behavior.

### Locked real-world evaluation

- Added preregistered train/validation/final-holdout protocols for OPE and randomized targeting.
- Added evidence fingerprints binding source/model outputs, protocol identity, selected candidate, and code commit.
- Added evidence gates that run before OPE estimator ranking.
- Added executable locked OPE and locked targeting command-line entry points.

### Promoted full-data evidence

- Persisted the accepted full Open Bandit Dataset OPE artifact from evidence commit `7d538cea9698b5f0a48c585eed85e3ae526e5af6`.
  - Frozen validation winner: IPS.
  - Final relative estimation error: `9.20045%`.
  - Final support coverage: `1.0`.
  - Final ESS ratio: about `0.16123`.
- Persisted the accepted full Criteo Uplift v2.1 top-10% targeting artifact from evidence commit `7ac26a5aebde2c70e1b43264b89f08dddcff0245`.
  - Frozen validation winner: S-Learner over X/DR/R/T on that preregistered cohort.
  - Final population incremental visit value: `0.0093791024` = `+0.93791` percentage points.
  - Population 95% CI: `[0.0089584420, 0.0097997628]`.
  - Selected top-10% incremental visit value: `0.0937910242` = `+9.37910` percentage points.
- Kept older Criteo `+6.8%` and OBD `-8.4%` numbers as legacy provenance only; they are not treated as comparable current claims.

### Benchmark/data bridges

- Added deterministic real-world adapters for Criteo, Open Bandit Dataset, and KuaiRand.
- Added KuaiRand offline-RL and planner-sequence exports with correct terminal/truncation semantics.
- Added process-isolated and maintained-`sb-obp` Open Bandit export paths, compact cross-fitted reward-model predictions, pinned source identities, and full-data streaming support.
- Added a preregistered full Criteo LightGBM S/T/X/R/DR evaluation runner with train-only nuisance fitting and winner-only final scoring.

### Reproducibility and CI

- Fixed GitHub README display mathematics by using fenced `math` blocks.
- Added tests that continuously validate persisted accepted evidence and README promotion boundaries.
- Made accepted full-data Criteo/OBD research workflows manual-only with a required experiment reason, preventing unrelated PRs from automatically reopening final holdouts.
- Migrated official GitHub Actions to Node-24-native v7 releases and pinned every external action to its verified full-length commit SHA.
- Added weekly Dependabot updates for GitHub Actions while intentionally excluding frozen research-package pins.
- Added a security reporting policy with private-reporting guidance and an explicit locked-evidence boundary.
- Added wheel/sdist build, `twine check`, clean-wheel installation, and installed CLI smoke tests.
- Expanded the tested core Python matrix to Python 3.11, 3.12, 3.13, and 3.14 while keeping frozen research environments separate.

### Documentation

- Added frontier algorithm-selection rationale, locked evaluation schemas, Open Bandit export documentation, real-world benchmark protocol, research rerun policy, and Python support policy.
- Added explicit metric-unit and method-boundary language for promoted real-world results.

## Release-note discipline

When a release version is chosen, move the relevant Unreleased entries into a dated version section. Do not rewrite historical locked-evidence values during that move; those values remain tied to their evidence commits and persisted artifact directories.
