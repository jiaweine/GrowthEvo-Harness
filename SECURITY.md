# Security Policy

## Supported versions

GrowthEvo-Harness does not yet have a tagged public release series. Until one is published, security fixes target the current `main` branch. Historical evidence commits are immutable research records and may not receive unrelated maintenance changes.

## Reporting a vulnerability

Please do **not** publish exploit details, credentials, private data, or a working proof of concept in a public issue or pull request.

Preferred reporting path:

1. Open the repository's **Security** tab.
2. If GitHub shows **Report a vulnerability**, use that private vulnerability-reporting flow.
3. If that private flow is not available, open a minimal public issue titled `Security contact request` with **no vulnerability details** and ask the repository owner for a private reporting channel.

When reporting privately, include the affected commit/version, impact, reproduction conditions, and any proposed mitigation. Minimize real user data and secrets in reproductions.

## Coordinated disclosure

Please allow time for triage and remediation before public disclosure. Once a fix is available, the maintainer may use a GitHub Security Advisory to coordinate disclosure and document affected versions.

## Research-evidence boundary

Security fixes to runtime, packaging, CI, or dependencies must not silently rewrite accepted locked benchmark artifacts. If a vulnerability materially changes a benchmark dependency, source, model, split, estimator configuration, or evidence gate, any new headline result requires a new preregistered experiment identity under `docs/RESEARCH_RERUN_POLICY.md`.
