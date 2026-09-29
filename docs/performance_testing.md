# GrowthEvo Performance & Pressure Testing

GrowthEvo treats performance testing as a product-contract check, not as a single `/health` benchmark. The test surface covers read APIs, state-changing workflows, realtime decision semantics, idempotency, guardrails, the static Web/PWA shell, and concurrent retry behavior.

## What is exercised

The CI stress run launches the same production Docker image used by the deployable FastAPI surface and sends mixed concurrent traffic to:

- `/api/health` and `/api/ready`
- `/api/v1/dashboard`
- `/api/v1/opportunities`
- `/api/v1/campaigns`
- `/api/v1/experiments`
- `/api/v1/approvals`
- `/api/v1/harness/runs`
- `/api/v1/evolution/candidates`
- `/api/v1/actions`
- `/api/v1/decisions/recent`
- `/api/v1/decide`
- `/api/v1/agent/plan`
- `/api/v1/campaigns/draft`
- `/api/v1/approvals/{id}/decision`
- `/` and `/service-worker.js`

The decision workload validates semantics while under pressure: behavior propensity must remain valid, `NO_TREATMENT` must remain in the action distribution, consent-denied traffic must deterministically fall back to `NO_TREATMENT`, and a concurrent burst using the same `Idempotency-Key` must return exactly one `decision_id`.

## Concurrency contracts

`tests/test_product_concurrency.py` separately validates in-process race-sensitive paths:

- 512 concurrent first hits for one idempotency key resolve to one decision.
- The reference idempotency cache is bounded under unique-key pressure.
- Guardrail fallback remains deterministic under concurrent traffic.
- Agent plan run IDs remain unique.
- Approval retry mutation remains thread-safe.

The reference decision engine uses a bounded in-memory LRU-like idempotency cache. This is intentionally a **single-process reference contract**, not the final multi-replica implementation. A real production deployment must move idempotency and decision logs to durable shared persistence before horizontally scaling the API.

## Stress profiles

Run locally against a started API:

```bash
python scripts/stress_product.py --profile quick
python scripts/stress_product.py --profile ci
python scripts/stress_product.py --profile standard
python scripts/stress_product.py --profile soak
```

The profiles increase concurrency and request count while preserving the same semantic assertions.

| Profile | Concurrency | Intended use |
| --- | ---: | --- |
| `quick` | 16 | local development sanity check |
| `ci` | 48 | every product-surface PR / push |
| `standard` | 96 | deliberate pre-release pressure run |
| `soak` | 128 | longer single-container stress exercise |

The runner writes machine-readable JSON and a Markdown report when `--json-out` / `--markdown-out` are supplied.

## CI acceptance gates

The `ci` profile fails the workflow if any of these conditions are violated:

- HTTP error count is non-zero.
- Semantic error count is non-zero.
- Global p95 exceeds 1000 ms.
- Global p99 exceeds 2000 ms.
- Throughput falls below 25 requests/second on the GitHub-hosted runner.
- The concurrent idempotency burst produces more than one decision ID.

These limits are intentionally broad enough to avoid pretending a shared CI runner is a calibrated benchmark host, while still catching severe regressions, deadlocks, races, accidental blocking, and broken API contracts.

## What the numbers do **not** prove

Current pressure results characterize the credential-free reference product surface in one FastAPI container. They do **not** establish capacity for future integrations such as:

- managed PostgreSQL / Supabase transaction latency;
- S3-compatible object storage;
- real OpenAI / Anthropic / Gemini calls;
- Meta / Google Ads / SMS / Push / Email connectors;
- Redis, queue workers, or multi-replica deployments;
- warehouse queries against Snowflake / BigQuery;
- real customer traffic distributions or PII-heavy payloads.

Those adapters should receive their own load profiles when credentials and infrastructure exist. The current CI deliberately does not fake their performance.

## Recommended production progression

For a solo project, keep the sequence simple:

1. Keep the PR-level `ci` profile mandatory.
2. Run `standard` before tagged releases or infrastructure changes.
3. Add database-backed stress only after durable persistence lands.
4. Add external-provider tests with provider-specific rate-limit budgets rather than flooding paid APIs.
5. Before adding a second API replica, move decision idempotency and logs out of process memory into shared durable storage.

This keeps the repository enterprise-shaped without turning a personal project into an infrastructure benchmark lab.
