# GrowthEvo Product Surface v0.2

This layer turns the research harness into a runnable product surface without weakening the causal, audit and evidence boundaries already present in the repository.

## Implemented

- Responsive Growth OS: incremental KPI cockpit, Opportunity Map, Campaign Studio, experiments, approvals, Agent Harness, Evolution Lab, data plane and realtime decision console.
- Growth Agent sidecar that compiles natural-language goals into typed claims (`FACT / ESTIMATE / HYPOTHESIS / IDEA`) and structured artifacts.
- Versioned FastAPI contract under `/api/v1/*`.
- Reference decision boundary with first-class `NO_TREATMENT`, Action Registry validation, strict consent/frequency/budget/context-freshness guards, request-bound idempotency and behavior-propensity logging.
- Installable PWA plus responsive phone layout.
- Expo / React Native companion for KPI, campaign health and evidence-aware approvals.
- GitHub Pages demo mode and strict API mode using the same Web product surface.

The realtime endpoint is intentionally identified as `reference-contract`. It validates product semantics and audit contracts but does **not** claim to replace the repository's locked CATE/OPE/Safe-PI policy stack.

## Live API vs reference fixtures

In `MODE=api`, these workbenches now read the backend directly:

- Opportunity Map → `/api/v1/opportunities`
- Experiment Center → `/api/v1/experiments`
- Realtime Decision → `/api/v1/actions`, `/api/v1/decisions/recent`, `/api/v1/decide`
- Agent Harness → `/api/v1/harness/runs`
- Governance / Approval → `/api/v1/approvals` and approval decisions
- Evolution Lab → `/api/v1/evolution/candidates`

Remaining design-only workbenches are visibly labelled `Reference UI Fixture` in API mode. They are not represented as current server state.

Strict API mode never silently replaces an outage with synthetic data. `/api/ready` is probed at runtime, and an unavailable backend renders an explicit error state.

## Architecture

```text
Desktop Web / PWA                 Expo Mobile
        \                            /
         +------- /api/v1/* --------+
                     |
                 FastAPI
                     |
       +-------------+--------------+
       |             |              |
   Agent Plane   Product State  Decision Boundary
   typed plan     reference     registry + guards
       |                            |
       +-------- Causal Harness ----+
                 CATE / OPE /
                 Safe PI / Evidence
```

Reference product state is intentionally per-app and bounded. Durable production state remains an adapter boundary.

## Decision contract

`POST /api/v1/decide` always returns a decision ID, chosen action, behavior propensity, complete action distribution, policy/version, evidence tier, expiry, guardrail snapshot and audit reasons.

The reference policy uses stable hash bucketing to sample from the exact distribution it logs. Therefore a non-fallback response maintains:

```text
propensity == action_distribution[action_id]
sum(action_distribution) ~= 1
```

Guardrail fallbacks return a one-hot `NO_TREATMENT: 1.0` distribution. This makes the reference logging contract internally coherent for OPE-oriented telemetry without claiming that the reference scorer is a learned causal production policy.

Unknown candidate action IDs fail validation. Explicitly empty candidate input remains conservative and results in `NO_TREATMENT` only. Reusing one idempotency key with a materially different request returns HTTP 409.

## Governance / state semantics

- Approval first decision is atomic.
- Repeating the same approval decision is idempotent.
- Attempting a different decision after finalization returns HTTP 409 instead of overwriting audit history.
- Campaign draft reference state and decision/idempotency caches are bounded.
- Independent `create_app()` instances do not share mutable decision/campaign/approval state.
- API responses are not browser-cacheable.
- Production business APIs fail closed until production readiness is satisfied.

## Production boundary

`GROWTHEVO_MODE=production` requires both:

1. active durable persistence;
2. active authentication/identity.

A configured `DATABASE_URL`, Supabase URL, issuer or JWKS URL does not count as an active adapter. The current branch deliberately remains not-ready in production because those durable/auth adapters are not yet implemented.

## PWA / transport behavior

- The service worker never intercepts API or cross-origin requests.
- Navigations may fall back to the precached shell only when the network fails.
- Stable-named shell assets use network-first behavior while online, preventing an old `config.js` from temporarily reopening Demo Mode after an API deployment.
- Remote GitHub Pages API bases must use HTTPS; cleartext HTTP is accepted only for loopback development.
- API request bodies are limited to 1 MB based on actual bytes received, not only `Content-Length`.

## Mobile

The Expo client uses a committed `package-lock.json`; CI installs with `npm ci` for deterministic dependency resolution. The API client validates the configured URL, applies a timeout, preserves upstream cancellation and surfaces API errors.

On a real device, configure a LAN-accessible API because `127.0.0.1` points to the device itself:

```bash
cd apps/mobile
npm ci
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```

## API

```http
GET  /api/v1/dashboard
GET  /api/v1/opportunities
GET  /api/v1/campaigns
POST /api/v1/campaigns/draft
GET  /api/v1/experiments
GET  /api/v1/approvals
POST /api/v1/approvals/{id}/decision
GET  /api/v1/harness/runs
GET  /api/v1/evolution/candidates
POST /api/v1/agent/plan
GET  /api/v1/actions
POST /api/v1/decide
GET  /api/v1/decisions/recent
```

## Scientific boundary

Existing GrowthEvo cross-fitted CATE, safe policy improvement, OPE, conformal/locked evidence, holdout and canary modules remain authoritative. Durable side effects should be executed through deterministic workflow/state-machine boundaries rather than a one-shot model request.

The evolution path remains controlled: candidate memory/prompt/skill/tool-routing changes pass replay, evaluation, shadow and canary before promotion.

## Run

```bash
pip install -e '.[web]'
growthevo-web
# http://127.0.0.1:8765
# http://127.0.0.1:8765/api/docs
```

For deployment details and production gates, see `docs/deployment_architecture.md`. For load/soak methodology, see `docs/performance_testing.md`.
