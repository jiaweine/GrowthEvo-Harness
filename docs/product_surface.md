# GrowthEvo Product Surface

GrowthEvo turns the research harness into a runnable growth operating system without weakening the causal, audit, safety, or evidence boundaries already present in the repository.

## Product principles

- **Incrementality first.** Opportunities, experiments, campaigns, and realtime decisions distinguish observed behavior from causal lift.
- **NO_TREATMENT is a first-class action.** Doing nothing is always allowed when evidence, consent, frequency, budget, or context quality is insufficient.
- **Stable identities, not numbered generations.** Public routes, action IDs, policies, agents, and harnesses use semantic stable identifiers. Product evolution is represented by evidence and state transitions rather than `v1/v2/v3` labels.
- **Evidence before execution.** High-impact actions pass explicit support, uncertainty, guardrail, approval, Shadow, and Canary boundaries.
- **No fake production state.** Demo mode may use synthetic fixtures; API/production mode fails visibly when the backend is unavailable.

## Implemented surface

- Responsive Growth OS with KPI cockpit, Opportunity Map, Campaign Studio, Experiment Center, Execution Center, approvals, Agent Harness, Evolution Lab, data plane, and realtime decision console.
- Growth Agent sidecar that compiles natural-language goals into typed claims (`FACT / ESTIMATE / HYPOTHESIS / IDEA`) and structured artifacts.
- Stable FastAPI contract under `/api/*`.
- Reference decision boundary with Action Registry validation, consent/frequency/budget/context-freshness guards, request-bound idempotency, and behavior-propensity logging.
- Installable PWA and responsive phone layout.
- Expo / React Native companion for KPI, campaign health, and evidence-aware approvals.
- GitHub Pages demo mode and strict API mode using the same Web product surface.

The realtime endpoint is intentionally identified as `reference-contract`. It validates product semantics and audit contracts but does **not** replace the repository's locked CATE/OPE/Safe-PI policy stack.

## Live API vs reference fixtures

In `MODE=api`, these workbenches read the backend directly:

- Opportunity Map → `/api/opportunities`
- Experiment Center → `/api/experiments`
- Realtime Decision → `/api/actions`, `/api/decisions/recent`, `/api/decide`
- Agent Harness → `/api/harness/runs`
- Governance / Approval → `/api/approvals` and approval decisions
- Evolution Lab → `/api/evolution/candidates`

Remaining design-only workbenches are visibly labelled `Reference UI Fixture` in API mode. They are not represented as current server state.

Strict API mode never silently replaces an outage with synthetic data. `/api/ready` is probed at runtime, and an unavailable backend renders an explicit error state.

## Architecture

```text
Desktop Web / PWA                 Expo Mobile
        \                            /
         +---------- /api/* --------+
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

`POST /api/decide` returns a decision ID, chosen action, behavior propensity, complete action distribution, stable policy identity, evidence tier, expiry, guardrail snapshot, and audit reasons.

The reference policy uses stable hash bucketing to sample from the exact distribution it logs. Therefore a non-fallback response maintains:

```text
propensity == action_distribution[action_id]
sum(action_distribution) ~= 1
```

Guardrail fallbacks return a one-hot `NO_TREATMENT: 1.0` distribution. Unknown candidate action IDs fail validation. Explicitly empty candidate input remains conservative and results in `NO_TREATMENT` only. Reusing one idempotency key with a materially different request returns HTTP 409.

Stable Action Registry IDs include `NO_TREATMENT`, `free_shipping`, `coupon_10`, `push_reminder`, and `email_guide`. They describe meaning rather than release generation.

## Governance and state semantics

- Approval first decision is atomic.
- Repeating the same approval decision is idempotent.
- Attempting a different decision after finalization returns HTTP 409 instead of overwriting audit history.
- Campaign draft reference state and decision/idempotency caches are bounded.
- Independent `create_app()` instances do not share mutable decision/campaign/approval state.
- API responses are not browser-cacheable.
- Production business APIs fail closed until production readiness is satisfied.
- Agent, Harness, and Policy are represented by stable semantic IDs in product state and audit views.

## Production boundary

`GROWTHEVO_MODE=production` requires both active durable persistence and active authentication/identity. Configuration variables alone do not count as active adapters. The reference runtime deliberately remains not-ready until those adapters are implemented and initialized.

## PWA and transport behavior

- The service worker never intercepts API or cross-origin requests.
- Navigations may fall back to the precached shell only when the network fails.
- Stable-named shell assets use network-first behavior while online.
- Remote GitHub Pages API bases must use HTTPS; cleartext HTTP is accepted only for loopback development.
- API request bodies are limited to 1 MB based on actual bytes received, not only `Content-Length`.

## Mobile

The Expo client uses a committed `package-lock.json`; CI installs with `npm ci` for deterministic dependency resolution. The API client validates the configured URL, applies a timeout, preserves upstream cancellation, and surfaces API errors.

On a real device, configure a LAN-accessible API because `127.0.0.1` points to the device itself:

```bash
cd apps/mobile
npm ci
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```

## Stable API

```http
GET  /api/health
GET  /api/ready
GET  /api/system/runtime
GET  /api/system/connectors
GET  /api/dashboard
GET  /api/opportunities
GET  /api/campaigns
POST /api/campaigns/draft
GET  /api/experiments
GET  /api/approvals
POST /api/approvals/{id}/decision
GET  /api/harness/runs
GET  /api/evolution/candidates
POST /api/agent/plan
GET  /api/actions
POST /api/decide
GET  /api/decisions/recent
```

## Scientific boundary

Existing GrowthEvo cross-fitted CATE, safe policy improvement, OPE, conformal/locked evidence, holdout, and canary modules remain authoritative. Durable side effects should be executed through deterministic workflow/state-machine boundaries rather than a one-shot model request.

The evolution path remains controlled: candidate memory/prompt/skill/tool-routing changes pass replay, evaluation, shadow, and canary before promotion. Improvements replace behavior under the same stable product identity instead of creating public numbered generations.

## Run

```bash
pip install -e '.[web]'
growthevo-web
# http://127.0.0.1:8765
# http://127.0.0.1:8765/api/docs
```

For deployment details and production gates, see `docs/deployment_architecture.md`. For load/soak methodology, see `docs/performance_testing.md`.
