# Release Readiness Checklist

This checklist separates automated technical readiness from repository-owner choices that must not be invented by CI or an automated maintainer.

## Current automated gates

Before a release candidate is tagged, mainline should have all of the following green:

- [x] dependency-light core tests on Python 3.11, 3.12, 3.13, and 3.14;
- [x] runtime demo smoke test on every supported core interpreter;
- [x] training demo smoke test on every supported core interpreter;
- [x] wheel + sdist build;
- [x] `twine check` on built distributions;
- [x] clean-wheel installation outside the source tree on Python 3.14;
- [x] installed `growthevo-locked-ope --help` and `growthevo-locked-targeting --help`;
- [x] pinned real small-OBD integration with compact-Q equivalence and locked selection;
- [x] persisted full Criteo/OBD evidence integrity tests;
- [x] README math rendering regression tests;
- [x] accepted full-data workflows are manual-only and require an experiment reason.

These gates prove repository/package behavior. They do not choose legal terms, a release version, or a GitHub governance policy.

## Owner decisions required before public package/release publication

### 1. Choose and add a LICENSE

The repository currently has no `LICENSE` file. An automated maintainer must not guess whether the intended terms are MIT, Apache-2.0, BSD, proprietary, or another license.

Before publishing a public package/release intended for reuse, the repository owner should deliberately choose the license and then:

- add the `LICENSE` file;
- add matching PEP 639 license metadata to `pyproject.toml` if appropriate;
- ensure third-party dataset/model licenses remain separately respected;
- rerun package build and `twine check`.

Until that choice is made, release tooling should not pretend that reuse rights have been granted merely because the GitHub repository is public.

### 2. Protect `main`

At the latest release-readiness audit, `main` was not protected. The available repository connector in this maintenance session can read rules/protection state but cannot write branch-protection/ruleset configuration, so this is intentionally left as an explicit owner/admin action rather than being falsely marked complete.

Recommended minimum policy before a public release:

- require pull requests before merging to `main`;
- require the GrowthEvo CI checks to pass;
- prevent force pushes and branch deletion;
- require branches to be up to date before merge when practical;
- preserve manual-only full-data research workflows rather than making final holdouts required PR checks.

## Version and tag decision

`pyproject.toml` currently uses version `0.1.0`, and this maintenance work does not create a GitHub release or tag automatically.

When the owner chooses the first/next public version:

1. decide the semantic version intentionally;
2. move the relevant `CHANGELOG.md` **Unreleased** entries into a dated version section;
3. update `project.version` in `pyproject.toml`;
4. run the complete CI/package matrix on that exact release commit;
5. verify accepted real-world evidence directories are unchanged unless the release intentionally includes a separately preregistered new experiment;
6. tag the exact verified commit;
7. create release notes from the changelog without rewriting evidence metrics.

Do not choose a version merely because many commits have accumulated; the tag is a public compatibility statement.

## Real-world evidence release boundary

A software release may include historical accepted evidence without rerunning its final holdout. In fact, unrelated release preparation should **not** reopen accepted holdouts.

If a release intends to promote a new Criteo/OBD headline instead, follow `docs/RESEARCH_RERUN_POLICY.md` and `docs/REAL_WORLD_BENCHMARKS.md`: new material source/model/split/gate choices require a new experiment identity and evidence chain.

## Final pre-tag audit

- [ ] LICENSE choice completed by owner;
- [ ] `main` protection/ruleset configured by admin;
- [ ] release version chosen;
- [ ] changelog version section created;
- [ ] exact release commit CI is green;
- [ ] package metadata URLs and Python classifiers are correct;
- [ ] no open release-blocking issues or PRs;
- [ ] no accidental benchmark/evidence changes in release diff;
- [ ] README current claims still match persisted artifacts;
- [ ] release tag points to the exact audited commit.
