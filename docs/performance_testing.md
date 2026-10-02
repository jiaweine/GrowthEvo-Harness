# GrowthEvo Performance & Pressure Testing

GrowthEvo treats performance testing as a product-contract check, not as a single `/health` benchmark. The test surface covers read APIs, state-changing workflows, realtime decision semantics, idempotency, guardrails, the static Web/PWA shell, concurrent retries, causal estimation, OPE, Safe Policy Improvement, and locked-evidence integrity.

## Product/API pressure surface

The product stress run launches the same Docker image used by the deployable FastAPI surface and sends mixed concurrent traffic to:

- `/api/health` and `/api/ready`
- `/api/dashboard`
- `/api/opportunities`
- `/api/campaigns`
- `/api/experiments`
- `/api/approvals`
- `/api/harness/runs`
- `/api/evolution/candidates`
- `/api/actions`
- `/api/decisions/recent`
- `/api/decide`
- `/api/agent/plan`
- `/api/campaigns/draft`
- `/api/approvals/{id}/decision`
- `/` and `/service-worker.js`

The decision workload validates semantics while under pressure: behavior propensity must remain valid, `NO_TREATMENT` must remain in the action distribution, consent-denied traffic must deterministically fall back to `NO_TREATMENT`, and a concurrent burst using the same `Idempotency-Key` must return exactly one `decision_id`.

## Concurrency and memory-safety contracts

`tests/test_product_concurrency.py` separately validates race-sensitive paths:

- 512 concurrent first hits for one idempotency key resolve to one decision.
- The reference idempotency cache is bounded under unique-key pressure.
- Guardrail fallback remains deterministic under concurrent traffic.
- Agent plan run IDs remain unique.
- Approval retry mutation remains thread-safe.
- 1,500 concurrent Campaign Draft writes keep reference state bounded to the newest 1,000 campaigns.

The reference decision engine uses a bounded in-memory LRU-like idempotency cache. This is intentionally a single-process reference contract. A real production deployment must move idempotency and decision logs to durable shared persistence before horizontally scaling the API.

Production readiness is fail-closed: configuration presence is not treated as an active database or identity integration.

## Product stress profiles

```bash
python scripts/stress_product.py --profile quick
python scripts/stress_product.py --profile ci
python scripts/stress_product.py --profile standard
python scripts/stress_product.py --profile soak
```

| Profile | Concurrency | Intended use |
| --- | ---: | --- |
| `quick` | 16 | local development sanity check |
| `ci` | 48 | every product-surface PR / push |
| `standard` | 96 | deliberate pre-release pressure run |
| `soak` | 128 | longer single-container stress exercise |

The `Product Stress` workflow runs `standard` on relevant pull requests, supports all profiles through `workflow_dispatch`, and runs `soak` weekly. Reports are uploaded as JSON and Markdown artifacts.

## Research-core pressure surface

`scripts/stress_core.py` independently exercises synthetic contextual-bandit generation, cross-fitted DR CATE, batch prediction, multi-estimator OPE, parallel determinism, locked-evidence fingerprints, Safe Policy Improvement constraints, and peak RSS.

| Profile | CATE rows | OPE rows | Safe-PI iterations | Intended use |
| --- | ---: | ---: | ---: | --- |
| `quick` | 1,500 | 10,000 | 5,000 | local sanity |
| `ci` | 4,000 | 50,000 | 20,000 | moderate CI |
| `standard` | 10,000 | 100,000 | 50,000 | PR / pre-release |
| `soak` | 30,000 | 500,000 | 250,000 | weekly computational pressure |

## Acceptance gates

The product CI profile fails when HTTP or semantic errors are non-zero, latency ceilings are exceeded, throughput falls below the shared-runner floor, or concurrent reuse of one idempotency key produces multiple decision IDs. The decision semantics runner also checks action-distribution calibration across independent entities.

The core stress runner additionally gates numerical and safety semantics: finite outputs, synthetic CATE quality, OPE support and effective sample size, deterministic parallel results, order-independent evidence fingerprints, and Safe-PI support/cost/trust-region constraints.

## What the numbers do not prove

Current pressure results characterize the credential-free reference product surface and deterministic research core. They do not establish capacity for managed databases, object storage, external LLMs, paid channel APIs, Redis/queues, multi-replica deployments, warehouse queries, native-device rendering, or real customer traffic distributions. Those adapters receive dedicated load profiles only when they actually exist.

## Recommended production progression

1. Keep PR-level product CI and concurrency contracts mandatory.
2. Run `standard` Product Stress and Core Stress before release or infrastructure changes.
3. Let weekly `soak` profiles catch long-running regressions.
4. Add database-backed stress only after durable persistence is wired.
5. Add provider tests with provider-specific rate-limit budgets rather than flooding paid APIs.
6. Before adding a second API replica, move decision idempotency and logs into shared durable storage.
7. Add native mobile performance tests only when an intentional device/emulator runner exists.

Public API routes and product identities stay stable across these improvements; performance evolution does not create numbered public generations.
