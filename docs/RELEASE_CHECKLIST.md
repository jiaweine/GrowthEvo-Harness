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
- [x] accepted full-data workflows are manual-only and require an experiment reason;
- [x] every external GitHub Action reference is pinned to a verified 40-character commit SHA;
- [x] Dependabot tracks GitHub Actions weekly without automatically changing frozen research-package pins;
- [x] `SECURITY.md` provides non-public vulnerability-reporting guidance and preserves the locked-evidence boundary.

These gates prove repository/package behavior. They do not choose legal terms, a release version, or a GitHub governance policy.

## Owner/admin decisions required before public package/release publication

### 1. Choose and add a LICENSE

The repository currently has no `LICENSE` file. An automated maintainer must not guess whether the intended terms are MIT, Apache-2.0, BSD, proprietary, or another license.

Before publishing a public package/release intended for reuse, the repository owner should deliberately choose the license and then:

- add the `LICENSE` file;
- add matching PEP 639 license metadata to `pyproject.toml` if appropriate;
- ensure third-party dataset/model licenses remain separately respected;
- rerun package build and `twine check`.

Until that choice is made, release tooling should not pretend that reuse rights have been granted merely because the GitHub repository is public.

### 2. Protect `main`

Repository-governance detection is now implemented on `main` through `.github/workflows/repository-governance-audit.yml` and `tools/repository_governance_audit.py`, but the server-side ruleset is still an explicit owner/admin action tracked by issue #63.

Issue #63 contains the exact ruleset contract plus a ready-to-run `gh api` Administration command. The required policy is:

- require pull requests before merging to `main`;
- require zero approving reviews for the current single-maintainer model;
- require exactly the six GrowthEvo CI job contexts with strict/up-to-date checks;
- bind those checks to GitHub Actions where supported;
- prevent force pushes and branch deletion;
- keep full-data Criteo/OBD research workflows manual-only rather than making final holdouts normal PR gates.

The audit is intentionally split into two modes:

- manual `workflow_dispatch` is always strict and must fail until the ruleset exists;
- scheduled runs may report `PENDING` only while #63 is open and no active ruleset targets `main`, avoiding guaranteed bootstrap noise without accepting a partial/incorrect ruleset.

Do not mark this checklist item complete until the strict manual audit passes against the real active ruleset.

### 3. Verify repository security features

GitHub recommends Dependabot alerts, secret scanning / push protection, and code scanning for public repositories. The repository files can configure version updates and reporting policy, but this maintenance connector cannot reliably verify or mutate every Security setting.

Before a public release, an administrator should verify in **Settings → Advanced Security / Code security** that the intended controls are enabled, especially:

- dependency graph and Dependabot alerts;
- secret scanning and push protection;
- CodeQL/default code scanning, or an intentionally chosen equivalent;
- private vulnerability reporting if the repository should expose a direct **Report a vulnerability** flow.

Do not add a second advanced CodeQL workflow merely to satisfy this checklist if GitHub default setup is already enabled; choose one coherent code-scanning configuration.

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
- [ ] repository security features verified by admin;
- [ ] release version chosen;
- [ ] changelog version section created;
- [ ] exact release commit CI is green;
- [ ] package metadata URLs and Python classifiers are correct;
- [ ] no open release-blocking issues or PRs;
- [ ] no accidental benchmark/evidence changes in release diff;
- [ ] README current claims still match persisted artifacts;
- [ ] release tag points to the exact audited commit.
