# Contributing to GrowthEvo-Harness

Contributions are welcome across causal estimation, policy learning, OPE, benchmark tooling, trajectory learning, documentation, and runtime infrastructure. The main requirement is that changes preserve GrowthEvo's causal, safety, and evidence contracts.

## Development setup

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
pytest
```

The dependency-light core is tested across Python 3.11–3.14. Research benchmark environments use separately pinned dependency sets; see `docs/PYTHON_SUPPORT.md`.

## Pull-request checklist

A normal code change should:

1. keep the existing regression suite green;
2. add focused tests for changed semantics;
3. preserve public CLI behavior unless the change intentionally updates that contract;
4. preserve support, feasibility, and evidence checks;
5. keep display equations in GitHub fenced `math` blocks;
6. update documentation when a public contract changes.

CI builds the distribution in a clean environment in addition to running source-tree tests.

## Causal-method changes

Changes to CATE, OPE, Safe Policy Improvement, conformal verification, or planning should keep statistical meaning explicit.

Useful review questions include:

- What quantity is being estimated or bounded?
- Which data are used to fit nuisance terms or hyperparameters?
- How is support/overlap represented?
- Are final policy constraints included before candidate ranking?
- Is uncertainty aligned with the quantity it is intended to describe?
- Which deterministic or synthetic regression test protects the new behavior?

When multiple credible methods exist, the canonical library choice follows `docs/FRONTIER_ALGORITHM_STACK.md`. Real-data winners are selected through the corresponding locked validation protocol.

## Real-world benchmark changes

Full Criteo and full OBD evidence workflows are manual research workflows rather than ordinary PR jobs. This keeps accepted final holdouts stable and gives each new research comparison a clear experiment identity.

A material change to any of the following defines a new experiment identity:

- dataset source or release;
- outcome or reward;
- split definition or seed;
- propensity or Q protocol;
- target-policy simulation protocol;
- candidate/model configuration;
- support/evidence gate;
- selection objective.

Follow `docs/RESEARCH_RERUN_POLICY.md` and `docs/REAL_WORLD_BENCHMARKS.md` when changing those inputs.

### Small OBD development cohort

The existing small-OBD cohort is retained as a **regression and integration baseline**. Its development history is recorded in `benchmarks/ope/development/obd-small-all-random-to-bts.v1.json` and `docs/OPE_DEVELOPMENT_GOVERNANCE.md`.

New promotion research uses a fresh preregistered development identity so validation selection remains independent of earlier method-screening history. The existing small-OBD job continues to provide valuable CI coverage for exporter, Q-model, OPE, and evidence-chain semantics.

### Promotable result contract

A new promoted benchmark result includes:

- a preregistered plan before validation scoring;
- a realized manifest matching the plan;
- validation-only candidate selection;
- one frozen winner;
- independent final-holdout evaluation;
- uncertainty and support diagnostics required by the plan;
- exact source, code, and environment provenance;
- persisted compact evidence and fingerprints.

Accepted evidence directories are historical research records. New experiments receive new identities rather than rewriting the numerical contents of an existing accepted artifact.

## Research dependencies

The core package stays dependency-light. Heavy research stacks belong in optional extras or isolated research scripts with explicit reproducibility value.

Frozen evidence environments remain tied to their accepted artifacts. A dependency upgrade intended to produce new benchmark evidence should be represented as a new experiment environment and plan identity.

## Documentation style

Public-facing documentation should favor:

- a clear project-first hierarchy;
- capability and result summaries before implementation detail;
- tables or numbered stages instead of decorative arrow flows;
- precise metric units;
- concise scope language rather than defensive caveat blocks;
- links from overview documents into detailed protocol and evidence files.

Audit-oriented evidence files can remain more formal and provenance-heavy than the repository landing pages.

## Before requesting review

Run at least:

```bash
pytest
python examples/demo.py
python examples/training_demo.py
python -m build
python -m twine check dist/*
```

For Open Bandit bridge changes, run the pinned small-OBD integration path or rely on the corresponding CI job.

For changes to a full-data workflow or experiment plan, document whether the change is a replication or a new experiment identity and describe how validation/final isolation is preserved.
