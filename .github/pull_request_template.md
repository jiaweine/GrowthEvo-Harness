## Summary

Describe what changes and why.

## Scope

- [ ] This PR does not change accepted real-world evidence files, or any such change is explicitly justified below.
- [ ] Public API / CLI / schema changes are documented.
- [ ] New or changed semantics have regression tests.

## Causal / policy contract

If this PR changes CATE, OPE, policy improvement, conformal verification, or planning:

- [ ] Statistical assumptions and diagnostics remain explicit.
- [ ] Positivity / overlap / clipping / support semantics are not silently conflated.
- [ ] Feasibility and safety constraints are evaluated before final policy ranking where required.
- [ ] A newer estimator is not promoted solely because it is newer.

## Real-world evidence contract

If this PR changes a benchmark, research dependency, model/Q protocol, candidate grid, split, source, or evidence gate:

- [ ] I classified this as either an exact replication or a new experiment identity.
- [ ] A new experiment has a new preregistered plan/fingerprint before validation is opened.
- [ ] Validation selects and freezes the winner before final holdout.
- [ ] Only the frozen winner reaches final holdout.
- [ ] The accepted full-data workflows are not re-enabled as automatic PR jobs.
- [ ] Metric units and comparison boundaries are stated explicitly.

## Verification

- [ ] `pytest`
- [ ] runtime demo
- [ ] training demo
- [ ] package build / clean-install checks pass in CI
- [ ] pinned small-OBD integration passes when relevant
- [ ] README display equations remain fenced `math`

## Evidence / provenance notes

If applicable, list plan fingerprint, source identity, candidate-config fingerprint, manifest fingerprint, commit SHA, and why this run is admissible under `docs/RESEARCH_RERUN_POLICY.md`.
