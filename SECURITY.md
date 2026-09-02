# Security Policy

GrowthEvo-Harness treats runtime security and research-evidence integrity as separate but complementary maintenance responsibilities.

## Supported versions

During the current pre-release development line, security fixes target the latest `main` branch. Tagged-release support information will be published alongside the release series.

Historical accepted evidence commits remain immutable research records, while runtime, packaging, CI, and dependency fixes continue on current mainline code.

## Reporting a vulnerability

Please keep exploit details, credentials, private data, and working proof-of-concept material out of public issues and pull requests.

Preferred reporting path:

1. Open the repository's **Security** tab.
2. If GitHub shows **Report a vulnerability**, use that private vulnerability-reporting flow.
3. If the private flow is unavailable, open a minimal public issue titled `Security contact request` with no vulnerability details and request a private reporting channel from the repository owner.

A useful private report includes:

- affected commit or version;
- expected security impact;
- reproduction conditions;
- relevant environment information;
- proposed mitigation when available.

Please minimize real user data and secrets in reproductions.

## Coordinated disclosure

Security reports are triaged privately so remediation and disclosure can be coordinated. When appropriate, a GitHub Security Advisory can document affected versions, remediation, and disclosure timing.

## Research-evidence integrity

Runtime security maintenance does not rewrite accepted locked benchmark artifacts. When a security fix materially changes a benchmark dependency, source, model, split, estimator configuration, or evidence gate, subsequent headline benchmark evidence receives a new preregistered experiment identity under `docs/RESEARCH_RERUN_POLICY.md`.

This preserves both objectives: current software can receive security fixes, and accepted research evidence remains tied to the exact environment and commit that produced it.
