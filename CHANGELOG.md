# Changelog

Notable GrowthEvo-Harness changes are recorded here. The current development line is tracked under **Unreleased** until its release version is tagged.

## Unreleased

### Causal and policy-learning stack

- Added group-aware cross-fitted Doubly Robust CATE with pluggable nuisance/effect learners, explicit positivity/overlap semantics, and distributional-support diagnostics.
- Added calibrated final-feasible Safe Policy Improvement with support anchoring, explicit feasibility controls, and calibrated/inferential bound support.
- Added cross-fitted β*-IPS as the flagship efficient OPE estimator together with DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, and Meta-OPE/BLUE-style candidates.
- Preserved dynamics-aware GAE, conformal verification, risk-sensitive MPC/CVaR planning, and first-class `NO_TREATMENT` behavior.

### Locked real-world evaluation

- Added preregistered train/validation/final-holdout protocols for OPE and randomized targeting.
- Added evidence fingerprints binding source/model outputs, protocol identity, selected candidate, and code commit.
- Added evidence gates that run before OPE estimator ranking.
- Added executable locked OPE and locked targeting command-line entry points.

### Accepted full-data evidence

- Persisted the accepted full Open Bandit Dataset OPE artifact from evidence commit `7d538cea9698b5f0a48c585eed85e3ae526e5af6`.
  - Frozen validation winner: IPS.
  - Final relative estimation error: `9.20045%`.
  - Final support coverage: `1.0`.
  - Final ESS ratio: about `0.16123`.
- Persisted the accepted full Criteo Uplift v2.1 top-10% targeting artifact from evidence commit `7ac26a5aebde2c70e1b43264b89f08dddcff0245`.
  - Frozen validation winner: S-Learner over the predeclared S/T/X/R/DR candidate set.
  - Final population incremental visit value: `0.0093791024` = `+0.93791` percentage points.
  - Population 95% CI: `[0.0089584420, 0.0097997628]`.
  - Selected top-10% incremental visit value: `0.0937910242` = `+9.37910` percentage points.
- Aligned project-facing benchmark claims to the accepted locked artifacts and their explicit metric definitions.

### Benchmark and data bridges

- Added deterministic real-world adapters for Criteo, Open Bandit Dataset, and KuaiRand.
- Added KuaiRand offline-RL and planner-sequence exports with explicit terminal/truncation semantics.
- Added process-isolated Open Bandit export paths, compact cross-fitted reward-model predictions, pinned source identities, and full-data streaming support.
- Added a preregistered full Criteo LightGBM S/T/X/R/DR evaluation runner with train-only model fitting and frozen-winner final scoring.

### Reproducibility and CI

- Standardized GitHub README display mathematics on fenced `math` blocks.
- Added tests that continuously validate persisted accepted evidence and current README evidence identities/metrics.
- Made accepted full-data Criteo/OBD research workflows manual research workflows with an explicit experiment reason and locked holdout handling.
- Migrated official GitHub Actions to Node-24-native v7 releases and pinned external actions to verified full-length commit SHAs.
- Added weekly Dependabot updates for GitHub Actions while keeping frozen research-package environments separate.
- Added a security reporting policy with private-reporting guidance and locked-evidence integrity rules.
- Added wheel/sdist build, `twine check`, clean-wheel installation, and installed CLI smoke tests.
- Expanded the tested core Python matrix to Python 3.11, 3.12, 3.13, and 3.14 while preserving benchmark-specific frozen environments.

### Documentation

- Redesigned the repository README around project positioning, capabilities, locked evidence, reproducibility, and implementation structure.
- Refreshed implementation status, architecture, algorithm, frontier, and benchmark documentation to match the current mainline stack.
- Replaced decorative arrow-flow diagrams with tables and numbered execution stages across public-facing documentation.
- Added locked evaluation schemas, Open Bandit export documentation, research rerun policy, development-cohort governance, Python support policy, and evidence-acceptance documentation.
- Standardized explicit metric units, evidence identities, and benchmark-selection terminology across project-facing docs.

## Release-note discipline

When a release version is chosen, move the relevant **Unreleased** entries into a dated version section. Historical locked-evidence values remain tied to their evidence commits and persisted artifact directories.
