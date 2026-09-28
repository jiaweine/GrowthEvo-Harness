# GrowthEvo Deployment Architecture

This repository supports two deployment profiles. The default profile is intentionally usable by a solo maintainer with **no enterprise credentials**; the upgrade path keeps enterprise boundaries without forcing enterprise infrastructure on day one.

## Profile A — GitHub-only public demo (default)

```text
GitHub repository
  ├─ Pull Requests + branch review
  ├─ GitHub Actions
  │   ├─ Python 3.11–3.14 core tests
  │   ├─ Product Surface CI
  │   ├─ Mobile TypeScript check
  │   └─ Pages build + deploy
  ├─ GitHub Pages
  │   ├─ high-fidelity Web UI
  │   ├─ PWA shell
  │   ├─ demo causal / campaign fixtures
  │   └─ local simulated mutations
  └─ release provenance / attestations already present in the repository
```

This mode requires **no API keys, database, LLM key, cloud account, or enterprise identity provider**. It is the correct public portfolio / research demo mode.

The browser config is generated during the Pages build:

```js
window.GROWTHEVO_CONFIG = {
  MODE: "demo",
  API_BASE: ""
}
```

No fake external integrations are presented as real. Campaign sends, approvals and agent execution are clearly demo state transitions.

## Profile B — Solo production, enterprise-shaped

When a real backend is needed, keep GitHub as the control plane and add only two runtime services:

```text
                         GitHub
                 source / PR / Actions
                       /        \
                      /          \
            GitHub Pages        GHCR
              Web / PWA        API image
                   |               |
                   | HTTPS         v
                   +---------- FastAPI service
                                 |
                    +------------+------------+
                    |                         |
                PostgreSQL                Object store
          product/event/evidence       large artifacts only
```

Recommended responsibilities:

| Layer | Default | Why |
| --- | --- | --- |
| Source / review | GitHub | one control plane |
| CI/CD | GitHub Actions | existing CI stays authoritative |
| Web / PWA | GitHub Pages | zero-server frontend hosting |
| API | existing FastAPI app in an OCI container | keeps research + product API in Python |
| Container registry | GitHub Container Registry | release image remains attached to repository |
| Durable state | managed PostgreSQL | approvals, campaigns, decision / exposure / outcome logs |
| Large artifacts | S3-compatible object storage | model/evidence bundles, creative assets |
| Async work | Postgres outbox + worker initially | avoids operating Kafka/Temporal for a solo project |
| Observability | structured JSON + OpenTelemetry interface | portable to Sentry/Grafana/OTel collector later |
| Secrets | GitHub Environment + OIDC where the cloud supports it | avoids long-lived cloud deploy keys |

For a personal project, **do not start with Kubernetes, Kafka, a service mesh, a separate feature store, or a full Temporal cluster**. Keep those as adapter boundaries. The repository's scientific evidence and policy contracts matter more than infrastructure theatre.

## Runtime environments

Use three logical environments even if only production is publicly hosted:

```text
local       -> localhost FastAPI + deterministic fixture state
preview     -> PR CI artifact / optional temporary API
production  -> GitHub Pages + configured API_BASE
```

Production Pages can switch from demo mode to a real API without rebuilding application code. Set the repository/environment variable:

```text
GROWTHEVO_API_BASE=https://api.example.com
```

The Pages build then emits:

```js
window.GROWTHEVO_CONFIG = {
  MODE: "api",
  API_BASE: "https://api.example.com"
}
```

## Security baseline

- Keep `NO_TREATMENT` a first-class action.
- Never allow the browser to hold channel, database, LLM or cloud provider secrets.
- External side effects remain server-side and pass Action Registry, consent, budget, frequency, approval and canary gates.
- Use GitHub Environments for production deployment policy.
- Prefer GitHub Actions OIDC to long-lived cloud credentials when adding a cloud runtime.
- Keep build provenance / attestations for released packages and images.
- Do not put production PII in Pages, Actions artifacts, issues or public benchmark files.

## GitHub Pages setup

After this branch lands on `main`:

1. Repository **Settings → Pages**.
2. Set **Source** to **GitHub Actions**.
3. Run `GrowthEvo Pages` or push a web change to `main`.
4. The site will be published at the repository's Pages URL.

No secrets are needed for demo mode.

## Why GitHub Pages is not the backend

GitHub Pages serves static files. It does not run FastAPI, background workers or a database. Therefore GrowthEvo deliberately has:

- a credential-free, fully navigable **demo mode** for Pages;
- the existing FastAPI application for real API mode;
- a small configuration boundary between them.

This prevents a static portfolio deployment from being misrepresented as a real campaign execution backend.
