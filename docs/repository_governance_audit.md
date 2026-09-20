# Repository governance audit

GrowthEvo's scientific and production evidence gates are only fully enforceable when GitHub itself prevents direct changes to `main`. Issue #63 is the canonical tracker for that server-side requirement.

This repository includes a read-only audit that verifies the expected GitHub governance contract. The audit is intentionally separate from the code, causal, statistical, and promotion evidence planes: it does not change experiment state, evidence artifacts, candidates, holdouts, or model behavior.

## Required contract

An active branch ruleset must target `main` (or `~DEFAULT_BRANCH`) with no routine bypass actors and must enforce all of the following:

- pull request required before merge;
- required approving reviews = `0`;
- strict/up-to-date required status checks;
- exactly these GitHub Actions checks:
  - `test (3.11)`
  - `test (3.12)`
  - `test (3.13)`
  - `test (3.14)`
  - `package`
  - `obd-integration`
- each required check must be bound to GitHub Actions integration id `15368`;
- branch deletion blocked;
- force pushes / non-fast-forward updates blocked.

The audit deliberately rejects extra manual full-data Criteo/OBD workflows as ordinary required checks. Those workflows remain explicit manual research/evidence operations and are not normal PR merge gates.

## Local/live checker

Run:

```bash
python tools/repository_governance_audit.py \
  --repo jiaweine/GrowthEvo-Harness \
  --branch main
```

The checker calls the public GitHub branch and repository-ruleset APIs and exits nonzero unless an active ruleset matches the full contract. It fails closed on API/schema errors.

For bootstrap scheduling only, `--allow-unconfigured-while-issue-open 63` may be used. In that mode a repository with **no active ruleset targeting the branch** is reported as `PENDING` while issue #63 remains open. The exception does not apply if an active targeting ruleset exists but is incomplete or incorrect, and it stops applying automatically when #63 is closed.

The branch API's `protected` flag is retained as diagnostic context, but the audit does not require that legacy flag to be `true` when a matching active ruleset is present. GitHub rulesets and traditional branch-protection rules are separate protection mechanisms. Conversely, traditional branch protection alone does not satisfy issue #63 because the repository's target governance contract explicitly requires an active ruleset.

For machine-readable output:

```bash
python tools/repository_governance_audit.py --json
```

## GitHub Actions

`.github/workflows/repository-governance-audit.yml` runs the same live audit every day and through `workflow_dispatch`.

This workflow is a **detector**, not a replacement for the ruleset. Manual `workflow_dispatch` runs are always strict and therefore fail until the required ruleset exists.

Scheduled runs use the bootstrap exception tied to issue #63: while #63 is open and there is no active ruleset targeting `main`, they report `PENDING` without creating a daily red workflow. If someone creates a partial or incorrect active ruleset, the scheduled audit fails immediately. After #63 is closed, the bootstrap exception switches off automatically, so weakening or deleting the ruleset makes the scheduled audit fail again.

## Verification sequence for closing #63

1. Create the active `main` ruleset using an administration-capable GitHub account/token.
2. Confirm the rulesets API returns an active ruleset matching the contract above and targeting `main` / `~DEFAULT_BRANCH`.
3. Treat `GET /repos/jiaweine/GrowthEvo-Harness/branches/main` reporting `protected: true` as additional confirmation when available, not as a substitute for the required ruleset.
4. Trigger `Repository Governance Audit` and require a green result.
5. Open a normal code PR and confirm the six checks are required.
6. Confirm direct push, branch deletion, and force-push attempts are rejected for non-bypass actors.
7. Only then close issue #63.
