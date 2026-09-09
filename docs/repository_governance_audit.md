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

The checker calls the public GitHub branch and repository-ruleset APIs and exits nonzero unless the full contract is satisfied. It fails closed on API/schema errors.

For machine-readable output:

```bash
python tools/repository_governance_audit.py --json
```

## GitHub Actions

`.github/workflows/repository-governance-audit.yml` runs the same live audit every day and through `workflow_dispatch`.

This workflow is a **detector**, not a replacement for the ruleset. Before #63 is actually completed, a manual/scheduled run is expected to fail because GitHub currently reports `main` as unprotected and the repository rulesets list is empty.

Once an administrator creates the ruleset described in #63, the workflow should become green without any code changes. If the ruleset is later weakened or deleted, the audit should fail again.

## Verification sequence for closing #63

1. Create the active `main` ruleset using an administration-capable GitHub account/token.
2. Confirm `GET /repos/jiaweine/GrowthEvo-Harness/branches/main` reports `protected: true`.
3. Confirm the rulesets API returns an active ruleset matching the contract above.
4. Trigger `Repository Governance Audit` and require a green result.
5. Open a normal code PR and confirm the six checks are required.
6. Confirm direct push, branch deletion, and force-push attempts are rejected for non-bypass actors.
7. Only then close issue #63.
