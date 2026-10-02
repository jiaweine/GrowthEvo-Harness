# GrowthEvo Deployment Architecture

GrowthEvo supports a credential-free public demo and an enterprise-shaped solo-production upgrade path. The goal is **enterprise discipline without enterprise infrastructure overhead** while keeping one stable product identity.

## GitHub-only public demo

```text
GitHub repository
  ├─ Pull Requests + review
  ├─ GitHub Actions
  │   ├─ Python 3.11–3.14 core tests
  │   ├─ Product Surface CI
  │   ├─ Product / Core stress tests
  │   ├─ CodeQL
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

This mode requires no API key, database, LLM credential, cloud account, or enterprise IdP. The sidebar explicitly labels it `Demo Workspace · Synthetic Data`; no external connector is presented as live.

The Pages build emits `MODE: "demo"` with an empty API base. A configured HTTPS API base switches the same UI into strict API mode without changing the product surface.

## Solo production architecture

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

Recommended defaults: GitHub for source/review and CI/CD, Pages for Web/PWA, the repository Dockerfile for the FastAPI runtime, GitHub Container Registry for images, managed PostgreSQL for durable product/audit state, managed OIDC/JWT for identity, S3-compatible storage for large artifacts, and a Postgres outbox plus worker before introducing heavier workflow infrastructure.

Do not begin a solo project with Kubernetes, Kafka, a service mesh, a separate feature store, or a full Temporal cluster. The scientific evidence, audit, policy, and execution contracts matter more than infrastructure theatre.

## Runtime modes

```text
demo        -> synthetic/reference product data; credential-free
api         -> strict reference-contract backend; no silent demo substitution
production  -> readiness requires active persistence AND active authentication
```

System endpoints:

```text
GET /api/health
GET /api/ready
GET /api/system/runtime
GET /api/system/connectors
```

`/api/health` is process liveness. `/api/ready` is traffic readiness. In production, business APIs fail closed with HTTP 503 until durable persistence and authentication are actually active. Configuration variables alone mean configured, not active.

External side effects remain disabled in the reference runtime. LLM, object-store, and channel variables are exposed only as safe connector states until real adapters initialize. Public runtime payloads expose state, not credentials or private host details.

## Stable API and anti-fake-data rule

GitHub Pages demo mode may use synthetic fixtures. API/production mode may not silently substitute synthetic data when the backend fails. The browser probes `/api/ready`; failures render an explicit API-unavailable state. The PWA service worker never caches API responses or replaces API failures with `index.html`.

Live workbenches use the stable `/api/*` contract directly: Opportunity Map, Experiment Center, realtime Action Registry and Decision Log, Harness Runs, Governance/Approval, and Evolution candidates. Pages that still contain static product-design fixtures display a `Reference UI Fixture` banner.

Public API paths are semantic and do not contain release-generation prefixes. Action, policy, agent, and harness identities are also semantic stable IDs.

## Cross-origin Pages to API

Configure the API with the exact Pages origin:

```text
GROWTHEVO_CORS_ORIGINS=https://jiaweine.github.io
GROWTHEVO_API_BASE=https://api.example.com
```

Wildcards, credential-bearing origins, and origins containing path/query/fragment are rejected. Remote Pages API bases must use HTTPS. Cleartext HTTP is limited to loopback development.

## Container runtime

The production base image is pinned by digest. Dependabot watches the Docker ecosystem so base-image security updates arrive as explicit reviewable PRs instead of tag drift.

The Python 3.13 Web runtime graph is constrained by `constraints/web-container-py313.txt`. The production image copies checked-in source, installs the constrained FastAPI/Uvicorn runtime, and starts `python -m growthevo.web.cli`. Product Surface and Product Stress use the same Python/runtime constraints for boundary tests before exercising the container.

Reference/local container:

```bash
docker build -t growthevo-api .
docker run --rm -p 8765:8765 \
  -e GROWTHEVO_MODE=api \
  -e GROWTHEVO_ENV=local-container \
  growthevo-api
```

Inspect `/api/health`, `/api/ready`, and `/api/docs` on port 8765.

## Request and state safety

The reference runtime includes production-shaped protections:

- 1 MB request-body limit based on bytes actually received;
- unknown request fields fail validation;
- consent requires a real JSON boolean;
- unknown Action Registry IDs fail closed;
- `NO_TREATMENT` remains in the candidate set;
- `Idempotency-Key` is normalized, bounded, duplicate-header protected, and conflicting reuse returns HTTP 409;
- reference idempotency/campaign state is bounded;
- approval decisions are first-write atomic and retry-safe;
- independent FastAPI app instances do not share mutable reference state;
- API responses use `Cache-Control: no-store`;
- runtime environment labels are validated before entering response headers.

## Decision/OPE semantics

The reference decision endpoint does not claim causal optimality. It samples from the exact distribution it logs using stable hash bucketing. Non-fallback decisions maintain:

```text
propensity == action_distribution[selected_action]
sum(action_distribution) ~= 1
```

Guardrail fallbacks log one-hot `NO_TREATMENT`. The locked CATE/OPE/Safe-PI stack remains authoritative for real policy work.

## Mobile reproducibility and transport safety

`apps/mobile/package-lock.json` is committed and CI uses `npm ci`. Production mobile builds require `EXPO_PUBLIC_GROWTHEVO_API` and HTTPS. Development devices may use an explicit LAN HTTP endpoint. The client validates its endpoint, has a timeout, preserves caller cancellation, and surfaces failures rather than replacing them with demo data.

Python research/evidence dependencies remain outside automated dependency updates so accepted evidence identities cannot drift automatically.

## Logical environments

```text
local       -> localhost FastAPI + deterministic reference state
preview     -> PR CI artifact / optional temporary API
production  -> Pages + HTTPS API + active durable persistence + active authentication
```

A solo maintainer can physically run only local plus public demo until real users or private data appear.

## Security baseline

- Never put provider/database secrets in browser or mobile public config.
- Do not place production PII in Pages, Actions artifacts, issues, or public benchmarks.
- Keep exact CORS origins and require authentication before production readiness.
- Keep `NO_TREATMENT`, consent, budget, frequency, approval, and canary gates explicit.
- Prefer GitHub Actions OIDC over long-lived deployment credentials.
- Keep release provenance/attestations and immutable Action/image pins.
- Run CodeQL for Python and JavaScript/TypeScript.
- Keep Pages production deployment main-only.

## GitHub Pages setup

After the branch lands on `main`, set Repository **Settings → Pages → Source** to **GitHub Actions** and run `GrowthEvo Pages` from `main` (or push a relevant web change). Feature-branch runs may build and validate but cannot deploy production Pages.

GitHub Pages is only the static frontend. FastAPI, background workers, authentication enforcement, and durable state remain separate runtime responsibilities.
