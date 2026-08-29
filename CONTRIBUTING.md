# Contributing to GrowthEvo-Harness

Contributions are welcome when they preserve the repository's causal, safety, and evidence contracts.

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

The dependency-light core is tested on Python 3.11–3.14. See `docs/PYTHON_SUPPORT.md` for the separate frozen research-environment policy.

## Pull-request expectations

A normal code change should:

1. keep existing tests green;
2. add regression tests for changed semantics;
3. preserve public CLI behavior unless the change is intentionally documented;
4. avoid weakening support/feasibility/evidence checks merely to make a benchmark pass;
5. keep README display equations in GitHub fenced `math` blocks;
6. update documentation when a public contract changes.

CI builds and installs the distribution in a clean environment in addition to running the source-tree tests.

## Causal-method changes

For changes to CATE, OPE, Safe Policy Improvement, conformal verification, or planning:

- distinguish statistical assumptions from implementation conveniences;
- do not silently convert diagnostics into confidence guarantees;
- keep positivity, practical overlap, clipping, and support semantics explicit;
- keep final-feasible policy constraints in the ranking path rather than applying them only after an unconstrained argmax;
- add deterministic/synthetic regression tests for new mathematical behavior.

A newer method is not automatically promoted as the default. If multiple credible methods exist, selection should follow the component-specific rationale in `docs/FRONTIER_ALGORITHM_STACK.md` and, for empirical claims, the locked validation protocol.

## Real-world benchmark changes

Accepted final holdouts are not tuning sets.

Do **not** automatically rerun the promoted full Criteo or full OBD workflows on an ordinary pull request. Those workflows are manual-only and require an explicit experiment reason.

If a contribution changes any material benchmark input—including source release, outcome/reward, split, propensity/Q protocol, candidate configuration, support/evidence gate, target-policy simulation protocol, or selection objective—it creates a **new experiment identity**. Follow `docs/RESEARCH_RERUN_POLICY.md` and `docs/REAL_WORLD_BENCHMARKS.md`.

A promotable new result requires:

- a preregistered plan before validation evidence is opened;
- a realized manifest matching the plan;
- validation-only candidate selection;
- one frozen winner;
- a single final-holdout evaluation for that winner;
- required uncertainty/support diagnostics;
- exact source/code/environment provenance;
- persisted compact evidence and fingerprints/digests.

Never replace or edit the numeric contents of an accepted evidence directory to make a new run look like the same experiment.

## Research dependencies

The core stays dependency-light. Heavy research stacks belong in optional extras or isolated scripts and must have an explicit reproducibility purpose.

Do not upgrade a frozen evidence dependency stack in place and then reinterpret the historical result. If a dependency upgrade is intended to produce new headline evidence, preregister it as a new experiment environment.

## Before requesting review

Run at least:

```bash
pytest
python examples/demo.py
python examples/training_demo.py
python -m build
python -m twine check dist/*
```

For changes to the Open Bandit bridge, also run the pinned small-OBD integration path or rely on the repository CI job that does so.

For changes to a full-data research workflow or plan, explain why the change is a replication versus a new experiment and how holdout leakage is prevented.
