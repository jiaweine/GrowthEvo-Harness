# GrowthEvo Deployment Architecture

This repository supports two deployment profiles. The default profile is intentionally usable by a solo maintainer with **no enterprise credentials**; the upgrade path keeps enterprise boundaries without forcing enterprise infrastructure on day one.

## Profile A — GitHub-only public demo (default)

```text
GitHub repository
  ├─ Pull Requests + branch review
  ├─ GitHub Actions
  │   ├─ Python 3.11–3.14 core tests
  │   ├─ Product Surface CI
  │   ├─ container smoke test
  │   ├─ real Chrome UI screenshots
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

The sidebar labels this workspace `Demo Workspace · Synthetic Data`. No fake external integrations are presented as live. Campaign sends, approvals and agent execution are demo/reference state transitions.

## Profile B — Solo production, enterprise-shaped

When a real backend is needed, keep GitHub as the control plane and add only two runtime services:

```text
                         GitHub
                 source / PR / Actions
                       /        \
                      /          \
            GitHub Pages        OCI image
              Web / PWA        FastAPI API
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
| API | repository `Dockerfile` + existing FastAPI app | keeps research + product API in Python |
| Container registry | GitHub Container Registry | release image stays attached to repository |
| Durable state | managed PostgreSQL | approvals, campaigns, decision / exposure / outcome logs |
| Large artifacts | S3-compatible object storage | model/evidence bundles, creative assets |
| Async work | Postgres outbox + worker initially | avoids operating Kafka/Temporal for a solo project |
| Observability | structured JSON + OpenTelemetry interface | portable to Sentry/Grafana/OTel collector later |
| Secrets | GitHub Environment + OIDC where the cloud supports it | avoids long-lived cloud deploy keys |

For a personal project, **do not start with Kubernetes, Kafka, a service mesh, a separate feature store, or a full Temporal cluster**. Keep those as adapter boundaries. The repository's scientific evidence and policy contracts matter more than infrastructure theatre.

## Runtime modes

The API runtime has three explicit modes:

```text
demo        -> synthetic/reference product data; credential-free
api         -> strict API client mode / reference-contract backend
production  -> production declaration; readiness requires durable persistence configured
```

The backend exposes:

```text
GET /api/health
GET /api/ready
GET /api/v1/system/runtime
GET /api/v1/system/connectors
```

`/api/ready` returns HTTP 503 when `GROWTHEVO_MODE=production` but no durable database URL is configured. Runtime responses report only configuration presence and a safe database hostname; credentials are never returned.

The current product APIs still identify themselves as **reference-contract** implementations. Merely setting a database/channel environment variable does not claim that a connector is live; `side_effects_enabled` remains false until real adapters are wired.

## Critical anti-fake-data rule

GitHub Pages demo mode may use synthetic fixtures. Strict API/production mode may not silently fall back to them.

If a configured API is unavailable, the UI shows an explicit production API outage state instead of substituting synthetic values. This prevents a backend outage from looking like valid campaign or decision data.

## Cross-origin Pages → API

GitHub Pages and the API are different origins. Configure the API with the exact allowed Pages origin:

```text
GROWTHEVO_CORS_ORIGINS=https://jiaweine.github.io
```

Do not use `*` once authentication or user-specific data is introduced.

The Pages deployment gets the API base from a repository/environment variable:

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

## Container run

The repository includes a non-root production-shaped container. Local smoke run:

```bash
docker build -t growthevo-api .
docker run --rm -p 8765:8765 \
  -e GROWTHEVO_MODE=api \
  -e GROWTHEVO_ENV=local-container \
  growthevo-api
```

Then open:

```text
http://127.0.0.1:8765/api/health
http://127.0.0.1:8765/api/ready
http://127.0.0.1:8765/api/docs
```

For an eventual hosted production service, use at minimum:

```text
GROWTHEVO_MODE=production
GROWTHEVO_ENV=production
DATABASE_URL=<managed PostgreSQL URL>
GROWTHEVO_CORS_ORIGINS=https://jiaweine.github.io
```

Provider-specific credentials remain server-side only.

## Logical environments

Use three logical environments even if only production is publicly hosted:

```text
local       -> localhost FastAPI + deterministic fixture state
preview     -> PR CI artifact / optional temporary API
production  -> GitHub Pages + configured API_BASE
```

For a solo project it is reasonable to physically run only `local + public demo` first, then add a managed production database/runtime when real users or private data appear.

## Security baseline

- Keep `NO_TREATMENT` a first-class action.
- Never allow the browser to hold channel, database, LLM or cloud provider secrets.
- External side effects remain server-side and pass Action Registry, consent, budget, frequency, approval and canary gates.
- Use GitHub Environments for production deployment policy.
- Prefer GitHub Actions OIDC to long-lived cloud credentials when adding a cloud runtime.
- Keep build provenance / attestations for released packages and images.
- Do not put production PII in Pages, Actions artifacts, issues or public benchmark files.
- Keep exact CORS origins rather than permissive wildcards.
- Treat `/api/ready` as the deployment readiness probe and `/api/health` as process liveness.

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
- the FastAPI application plus container for real API mode;
- a small configuration boundary between them;
- an explicit readiness contract so `production` cannot pretend to be ready without durable persistence.

This prevents a static portfolio deployment from being misrepresented as a real campaign execution backend while keeping the project inexpensive to operate.
