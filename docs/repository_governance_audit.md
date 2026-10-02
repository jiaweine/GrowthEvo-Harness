# Repository governance audit

GrowthEvo's scientific and production evidence gates are only fully enforceable when GitHub itself prevents direct changes to `main`. Issue #63 is the canonical tracker for that server-side requirement.

This repository includes a read-only audit that verifies the expected GitHub governance contract. The audit is intentionally separate from the code, causal, statistical, and promotion evidence planes: it does not change experiment state, evidence artifacts, candidates, holdouts, or model behavior.

## Required contract

Exactly one active branch ruleset must target only `main` (or `~DEFAULT_BRANCH`) with no routine bypass actors. The audited ruleset must contain exactly these four rule types: `pull_request`, `required_status_checks`, `deletion`, and `non_fast_forward`.

The pull-request rule must preserve the solo-maintainer workflow without creating a hidden self-review deadlock:

- pull request required before merge;
- allowed merge methods are exactly `merge`, `squash`, and `rebase`;
- required approving reviews = `0`;
- stale-review dismissal on push = `false`;
- Code Owner review requirement = `false`;
- last-push approval requirement = `false`;
- review-thread resolution requirement = `false`.

The required-status-check rule must enforce:

- strict/up-to-date required status checks;
- exactly these GitHub Actions checks:
  - `test (3.11)`
  - `test (3.12)`
  - `test (3.13)`
  - `test (3.14)`
  - `package`
  - `obd-integration`
- each required check must be bound to GitHub Actions integration id `15368`.

The remaining two rules must block branch deletion and force pushes / non-fast-forward updates.

The audit deliberately rejects extra manual full-data Criteo/OBD workflows as ordinary required checks. Those workflows remain explicit manual research/evidence operations and are not normal PR merge gates. It also rejects a second active ruleset targeting `main`, extra rule types, duplicate contract rules, or a ruleset that targets additional branches. Those cases can change effective merge behavior even when one individually valid ruleset is present, so they are not accepted as equivalent to the repository contract.

## Local/live checker

Run:

```bash
python tools/repository_governance_audit.py \
  --repo jiaweine/GrowthEvo-Harness \
  --branch main
```

The checker calls the public GitHub branch and repository-ruleset APIs and exits nonzero unless exactly one active ruleset matches the full contract. It fails closed on API/schema errors.

For bootstrap scheduling only, `--allow-unconfigured-while-issue-open 63` may be used. In that mode a repository with **no active ruleset targeting the branch** is reported as `PENDING` while issue #63 remains open. The exception does not apply if an active targeting ruleset exists but is incomplete, incorrect, too broad, duplicated, or accompanied by another active ruleset targeting `main`; it stops applying automatically when #63 is closed.

The branch API's `protected` flag is retained as diagnostic context, but the audit does not require that legacy flag to be `true` when a matching active ruleset is present. GitHub rulesets and traditional branch-protection rules are separate protection mechanisms. Conversely, traditional branch protection alone does not satisfy issue #63 because the repository's target governance contract explicitly requires an active ruleset.

For machine-readable output:

```bash
python tools/repository_governance_audit.py --json
```

## GitHub Actions

`.github/workflows/repository-governance-audit.yml` runs the same live audit every day and through `workflow_dispatch`.

This workflow is a **detector**, not a replacement for the ruleset. Manual `workflow_dispatch` runs are always strict and therefore fail until the required ruleset exists.

Scheduled runs use the bootstrap exception tied to issue #63: while #63 is open and there is no active ruleset targeting `main`, they report `PENDING` without creating a daily red workflow. If someone creates a partial, overly broad, duplicate, or otherwise incorrect active main ruleset, the scheduled audit fails immediately. After #63 is closed, the bootstrap exception switches off automatically, so weakening or deleting the ruleset makes the scheduled audit fail again.

## Verification sequence for closing #63

1. Create the active `main` ruleset using an administration-capable GitHub account/token.
2. Confirm the rulesets API returns exactly one active ruleset targeting only `main` / `~DEFAULT_BRANCH`, with no bypass actors and the exact four rule types above.
3. Confirm its pull-request parameters preserve zero-approval solo maintenance and its six required checks are strict and bound to GitHub Actions integration id `15368`.
4. Treat `GET /repos/jiaweine/GrowthEvo-Harness/branches/main` reporting `protected: true` as additional confirmation when available, not as a substitute for the required ruleset.
5. Trigger `Repository Governance Audit` manually and require a green result.
6. Open a normal code PR and confirm the six checks are required.
7. Confirm direct push, branch deletion, and force-push attempts are rejected for non-bypass actors.
8. Only then close issue #63.
