# GrowthEvo Deployment Architecture

GrowthEvo supports a credential-free public demo and an enterprise-shaped solo-production upgrade path. The goal is **enterprise discipline without enterprise infrastructure overhead**.

## Profile A — GitHub-only public demo

```text
GitHub repository
  ├─ Pull Requests + review
  ├─ GitHub Actions
  │   ├─ Python 3.11–3.14 core tests
  │   ├─ Product Surface CI
  │   ├─ Product / Core stress tests
  │   ├─ CodeQL (Python + JavaScript/TypeScript)
  │   ├─ container smoke + readiness
  │   ├─ real Chrome screenshots
  │   ├─ API-mode browser integration
  │   ├─ Mobile npm-ci + TypeScript
  │   └─ Pages build + main-only deploy
  └─ GitHub Pages
      ├─ high-fidelity Web UI
      ├─ PWA shell
      └─ clearly labelled synthetic/reference fixtures
```

This mode requires **no API key, database, LLM credential, cloud account, or enterprise IdP**. The sidebar explicitly labels it `Demo Workspace · Synthetic Data` and no external connector is presented as live.

The Pages build emits:

```js
window.GROWTHEVO_CONFIG = {
  MODE: "demo",
  API_BASE: ""
}
```

## Profile B — solo production, enterprise-shaped

When private/real state is introduced, keep GitHub as the control plane and add a small OCI API runtime plus managed services:

```text
                         GitHub
                 source / PR / Actions
                       /        \
                      /          \
            GitHub Pages        OCI image
              Web / PWA        FastAPI API
                   |               |
                   | HTTPS         |
                   +---------------+
                                   |
                    +--------------+--------------+
                    |              |              |
                PostgreSQL      Identity       Object store
               durable state   auth / JWT      large artifacts
```

Recommended responsibilities:

| Layer | Default | Why |
| --- | --- | --- |
| Source / review | GitHub | one control plane |
| CI/CD | GitHub Actions | existing CI stays authoritative |
| Web / PWA | GitHub Pages | zero-server frontend hosting |
| API | repository `Dockerfile` + FastAPI | keeps research + product API in Python |
| Container registry | GitHub Container Registry | image stays attached to repository |
| Durable state | managed PostgreSQL | approvals, campaigns, idempotency, decision/exposure/outcome logs |
| Authentication | managed OIDC/JWT provider (for example Supabase Auth) | identity must be active before production readiness |
| Large artifacts | S3-compatible object storage | model/evidence bundles and creative assets |
| Async work | Postgres outbox + worker initially | avoids premature Kafka/Temporal operations |
| Observability | structured JSON + OpenTelemetry interface | portable to Sentry/Grafana/OTel later |
| Secrets | GitHub Environment + OIDC where supported | avoids long-lived deploy credentials |

For a personal project, **do not begin with Kubernetes, Kafka, a service mesh, a separate feature store, or a full Temporal cluster**. Keep those as adapter boundaries. The scientific evidence, audit and policy contracts matter more than infrastructure theatre.

## Runtime modes

```text
demo        -> synthetic/reference product data; credential-free
api         -> strict reference-contract backend; no silent demo substitution
production  -> real-production declaration; readiness requires active persistence AND active authentication
```

System endpoints:

```text
GET /api/health
GET /api/ready
GET /api/v1/system/runtime
GET /api/v1/system/connectors
```

`/api/health` is process liveness. `/api/ready` is traffic readiness. The container healthcheck follows `/api/ready`.

In `production`, business APIs fail closed with HTTP 503 until both of these are **actually active**:

1. a durable persistence adapter;
2. an authentication/identity adapter.

A `DATABASE_URL`, `SUPABASE_URL`, issuer URL, JWKS URL, or other configuration variable only means **configured**. It does not make a connector **active**. The current branch intentionally reports:

```text
persistence.backend = reference-memory
persistence.active = false
authentication.backend = none
authentication.active = false
```

Therefore the current reference branch cannot accidentally become production-ready just because credentials were added to the environment.

External side effects are also disabled in the current reference runtime. LLM, object-store and channel variables are exposed only as safe `configured_not_active` connector states until real adapters are initialized. Public readiness/runtime payloads expose state, not database credentials or database hostnames.

## Strict API / anti-fake-data rule

GitHub Pages demo mode may use synthetic fixtures. API/production mode may **not** silently substitute synthetic data when the backend fails.

The browser probes `/api/ready`; failures render an explicit API-unavailable state. The PWA service worker never caches API responses or replaces API failures with `index.html`. Product Surface CI also kills the API during a real Chrome run and requires the UI to remain visibly unavailable rather than reveal Demo or Reference Fixture content.

In API mode these workbenches are wired directly to `/api/v1/*`:

- Opportunity Map;
- Experiment Center;
- realtime Action Registry + Decision Log;
- Harness Runs;
- Governance / Approval;
- Evolution candidates.

Pages that still contain static product-design fixtures display an explicit `Reference UI Fixture` banner rather than masquerading as live state.

## Cross-origin Pages → API

Configure the API with the **exact** Pages origin:

```text
GROWTHEVO_CORS_ORIGINS=https://jiaweine.github.io
```

Wildcards, credential-bearing origins and origins containing paths/query/fragment are rejected. CORS remains exact even on body-limit and fail-closed error responses.

The Pages build gets its API base from:

```text
GROWTHEVO_API_BASE=https://api.example.com
```

Remote Pages API bases must use HTTPS. Cleartext `http://` is accepted only for loopback development addresses because GitHub Pages itself is HTTPS and browsers block insecure mixed-content APIs.

The build emits:

```js
window.GROWTHEVO_CONFIG = {
  MODE: "api",
  API_BASE: "https://api.example.com"
}
```

## Container run

The production base image is pinned by digest in `Dockerfile`, so rebuilding the same commit does not silently resolve a different `python:3.13-slim` image. Dependabot watches the Docker ecosystem separately so base-image security updates arrive as explicit reviewable PRs rather than tag drift.

The Python 3.13 Web runtime graph is independently constrained by `constraints/web-container-py313.txt`. The production image intentionally **does not build/install the local project through PEP 517**: it copies the checked-in `growthevo/` source tree, installs the exact constrained FastAPI/Uvicorn runtime, and starts `python -m growthevo.web.cli`. This removes a separate floating setuptools/wheel build-isolation resolver from the production image. Product Surface and Product Stress use Python 3.13 with the same runtime constraints for product boundary tests before exercising the same Docker image.

This Web runtime lock remains separate from research/evidence pins. Changes to it trigger Product Surface and Product Stress CI; scientific Python dependency updates continue to follow the repository's evidence/provenance process.

Reference/local container:

```bash
docker build -t growthevo-api .
docker run --rm -p 8765:8765 \
  -e GROWTHEVO_MODE=api \
  -e GROWTHEVO_ENV=local-container \
  growthevo-api
```

Then inspect:

```text
http://127.0.0.1:8765/api/health
http://127.0.0.1:8765/api/ready
http://127.0.0.1:8765/api/docs
```

A future production configuration will look roughly like:

```text
GROWTHEVO_MODE=production
GROWTHEVO_ENV=production
DATABASE_URL=<managed PostgreSQL URL>
GROWTHEVO_AUTH_ISSUER=<OIDC issuer>
GROWTHEVO_AUTH_JWKS_URL=<JWKS URL>
GROWTHEVO_CORS_ORIGINS=https://jiaweine.github.io
```

Those variables alone still **do not** make this branch ready. The persistence and auth adapters must be implemented, initialized and report active state first.

## Request / state safety boundaries

The reference runtime intentionally includes production-shaped protections even before durable adapters exist:

- 1 MB API request-body limit is enforced against bytes actually received, not only `Content-Length`;
- unknown request fields fail validation instead of being silently ignored;
- consent requires a real JSON boolean;
- unknown Action Registry IDs fail closed;
- `NO_TREATMENT` stays in the candidate set;
- decision `Idempotency-Key` values are trimmed, bounded, duplicate headers are rejected, and conflicting request reuse returns HTTP 409;
- reference idempotency/campaign state is bounded in memory;
- approval decisions are first-write atomic: identical retries are idempotent, conflicting later decisions return HTTP 409;
- independent FastAPI app instances do not share reference campaign, approval or decision state;
- API responses are `Cache-Control: no-store`;
- runtime environment labels are length/character validated before being reflected into response headers.

## Decision/OPE semantics

The reference decision endpoint is not presented as causal optimality. Its reference policy now **actually samples from the distribution it logs** using stable hash bucketing. For every non-fallback decision:

```text
propensity == action_distribution[selected_action]
sum(action_distribution) ~= 1
```

Guardrail fallbacks log a one-hot `NO_TREATMENT: 1.0` distribution. This makes the reference contract internally coherent for behavior-propensity logging while the repository's locked CATE/OPE/Safe-PI stack remains authoritative for real production policy work.

The product stress suite also checks assignment calibration across many independent entities: observed action frequencies must remain statistically consistent with the accumulated logged action distributions. This prevents a future deterministic-argmax implementation from passing merely by writing plausible-looking propensity fields.

## Mobile reproducibility and transport safety

`apps/mobile/package-lock.json` is committed and CI uses `npm ci`. This prevents the same commit from resolving a different transitive npm dependency graph on a later date. Dependabot covers GitHub Actions, the pinned Docker base image and the mobile npm project weekly.

Python research/evidence dependencies are intentionally **not** managed by Dependabot. Changes to locked scientific/runtime pins stay behind the repository's evidence/provenance review so an automated dependency PR cannot silently change an accepted benchmark identity or research runtime.

For a physical Expo device during development, explicitly set the API address; `127.0.0.1` points to the device itself:

```bash
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```

Cleartext remote HTTP is a development-only allowance. Production mobile builds require `EXPO_PUBLIC_GROWTHEVO_API` to be configured and require an HTTPS endpoint. The mobile API client validates the configured URL, has a request timeout, preserves caller cancellation and surfaces API failures instead of replacing them with demo data.

## Logical environments

```text
local       -> localhost FastAPI + deterministic reference state
preview     -> PR CI artifact / optional temporary API
production  -> Pages + HTTPS API + active durable persistence + active authentication
```

It is reasonable for a solo maintainer to physically run only `local + public demo` until real users/private data appear.

## Security baseline

- Never put channel, database, LLM or cloud-provider secrets in browser/mobile public config.
- Do not put production PII in Pages, Actions artifacts, issues or public benchmark files.
- Keep exact CORS origins.
- Require authentication before production readiness.
- Keep `NO_TREATMENT`, consent, budget, frequency, approval and canary gates explicit.
- Use GitHub Environments for production deployment policy.
- Prefer GitHub Actions OIDC over long-lived cloud deployment credentials.
- Keep provenance/attestations for released packages and images.
- Pin external GitHub Actions and the production base image to immutable SHAs/digests.
- Lock the Python 3.13 Web container runtime separately from research/evidence dependencies.
- Run CodeQL for Python and JavaScript/TypeScript.
- Let Dependabot update Actions, the Docker base image and mobile npm dependencies; keep Python research pins under evidence-aware review.
- Keep Pages production deployment main-only; feature branches and pull requests may build/validate but cannot receive `pages: write` or deploy the production site.

### Repository-governance caveat

The code/workflow controls above do **not** replace server-side protection of `main`. Repository issue #63 is the canonical tracker for enabling an active GitHub ruleset that requires pull requests and the six GrowthEvo evidence checks, with no routine bypass and force-push/deletion blocked. Until that repository-admin action is completed, CI can detect an invalid direct push after landing but cannot prevent the push from landing first.

## GitHub Pages setup

After this branch lands on `main`:

1. Repository **Settings → Pages**.
2. Set **Source** to **GitHub Actions**.
3. Run `GrowthEvo Pages` from `main`, or push a relevant web change to `main`.
4. The site publishes at the repository Pages URL.

A manual `GrowthEvo Pages` run from a feature branch only builds/validates; configure/upload/deploy steps are gated to `refs/heads/main`.

No secrets are needed for demo mode.

## Why GitHub Pages is not the backend

GitHub Pages serves static files. It does not run FastAPI, background workers, authentication enforcement or a database. GrowthEvo therefore separates:

- credential-free public demo/PWA;
- FastAPI reference API/container;
- future authenticated durable production adapters;
- explicit readiness and connector activation contracts.

This keeps the project inexpensive without misrepresenting a static portfolio deployment or a configured-but-unwired connector as a real production execution platform.
