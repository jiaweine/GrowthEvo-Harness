# GrowthEvo Performance & Pressure Testing

GrowthEvo treats performance testing as a product-contract check, not as a single `/health` benchmark. The test surface covers read APIs, state-changing workflows, realtime decision semantics, idempotency, guardrails, the static Web/PWA shell, concurrent retries, causal estimation, OPE, Safe Policy Improvement, and locked-evidence integrity.

## Product/API pressure surface

The product stress run launches the same Docker image used by the deployable FastAPI surface and sends mixed concurrent traffic to:

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

## Concurrency and memory-safety contracts

`tests/test_product_concurrency.py` separately validates race-sensitive paths:

- 512 concurrent first hits for one idempotency key resolve to one decision.
- The reference idempotency cache is bounded under unique-key pressure.
- Guardrail fallback remains deterministic under concurrent traffic.
- Agent plan run IDs remain unique.
- Approval retry mutation remains thread-safe.
- 1,500 concurrent Campaign Draft writes keep reference state bounded to the newest 1,000 campaigns.

The reference decision engine uses a bounded in-memory LRU-like idempotency cache. This is intentionally a **single-process reference contract**, not the final multi-replica implementation. A real production deployment must move idempotency and decision logs to durable shared persistence before horizontally scaling the API.

Production readiness is also fail-closed: a `DATABASE_URL` is treated only as **configuration present**. Until a durable persistence adapter is actually initialized and used by product state, `GROWTHEVO_MODE=production` remains not-ready. This prevents an environment variable from being misrepresented as a working database integration.

## Product stress profiles

Run locally against a started API:

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

The `Product Stress` GitHub Actions workflow runs `standard` on relevant pull requests, supports all profiles through `workflow_dispatch`, and runs `soak` weekly. Reports are uploaded as JSON and Markdown artifacts.

## Research-core pressure surface

`scripts/stress_core.py` exercises the causal / RL / evidence layer independently of HTTP:

- synthetic contextual-bandit generation;
- five-fold cross-fitted DR CATE fitting;
- CATE quality and batch prediction;
- large OPE evaluation across DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, cross-fitted beta*-IPS, and Meta-BLUE;
- parallel deterministic OPE evaluation;
- order-independent locked-evidence fingerprints;
- Safe Policy Improvement under explicit support, provided bounds, total-variation trust region, and expected-cost hard caps;
- process peak-RSS tracking.

Core profiles scale independently from the HTTP profiles:

| Profile | CATE rows | OPE rows | Safe-PI iterations | Intended use |
| --- | ---: | ---: | ---: | --- |
| `quick` | 1,500 | 10,000 | 5,000 | local sanity |
| `ci` | 4,000 | 50,000 | 20,000 | moderate CI |
| `standard` | 10,000 | 100,000 | 50,000 | PR / pre-release |
| `soak` | 30,000 | 500,000 | 250,000 | weekly computational pressure |

The `Core Stress` workflow runs `standard` when causal/RL/stress code changes, can be launched manually with any profile, and runs `soak` weekly.

## Observed standard results

These are **observations from GitHub-hosted runners, not service-level objectives or capacity promises**. Shared runners vary, so regression gates remain intentionally broader than one sample's measurements.

### Product/API standard

A standard run on 2026-09-29 used 96 concurrent workers and completed 9,500 mixed business requests plus a 256-request same-key idempotency burst:

- throughput: **586.42 req/s**;
- HTTP errors: **0**;
- semantic errors: **0**;
- global p95: **206.62 ms**;
- global p99: **241.84 ms**;
- 3,000 realtime decisions: p95 **197.40 ms**;
- 800 Agent Plan requests: p95 **198.51 ms**;
- 400 Campaign Draft requests: p95 **202.50 ms**;
- 256 concurrent requests sharing one idempotency key: **1 unique decision ID**.

### Causal / RL core standard

A standard core run on 2026-09-29 completed in **4.229 s** with **123.97 MB** peak RSS:

- 10,000-row cross-fitted DR workload;
- synthetic CATE RMSE: **0.000493**;
- 100,000-record multi-estimator OPE: **0.571 s**;
- OPE support coverage: **1.0**;
- OPE effective sample ratio: **0.8696**;
- eight parallel OPE jobs remained deterministic;
- 120,000 canonical fingerprint row operations preserved order-independent evidence identity;
- 50,000 Safe-PI improvements: **21,630 ops/s**;
- Safe-PI stayed inside the `0.20` total-variation cap and `0.20` expected-cost cap, while the unsupported ADS action did not gain mass.

## Acceptance gates

The product `ci` profile fails if any of these conditions are violated:

- HTTP error count is non-zero;
- semantic error count is non-zero;
- global p95 exceeds 1000 ms;
- global p99 exceeds 2000 ms;
- throughput falls below 25 requests/second on the GitHub-hosted runner;
- the concurrent idempotency burst produces more than one decision ID.

The core stress runner additionally gates numerical / safety semantics, including:

- all stage outputs remain finite and semantically valid;
- synthetic CATE RMSE stays below the reference quality ceiling;
- OPE maintains support and effective-sample requirements;
- parallel OPE results remain deterministic;
- evidence fingerprints remain order independent;
- Safe-PI probabilities sum to one and stay inside support, cost, and trust-region constraints;
- profile-specific runtime and peak-memory ceilings are not exceeded.

## What the numbers do **not** prove

Current pressure results characterize the credential-free reference product surface and deterministic research core. They do **not** establish capacity for future integrations such as:

- managed PostgreSQL / Supabase transaction latency;
- S3-compatible object storage;
- real OpenAI / Anthropic / Gemini calls;
- Meta / Google Ads / SMS / Push / Email connectors;
- Redis, queue workers, or multi-replica deployments;
- warehouse queries against Snowflake / BigQuery;
- native iOS / Android device rendering under memory/thermal pressure;
- real customer traffic distributions or PII-heavy payloads.

Those adapters should receive their own load profiles when credentials and infrastructure exist. The current CI deliberately does not fake their performance.

## Recommended production progression

For a solo project, keep the sequence simple:

1. Keep the PR-level product CI and concurrency contracts mandatory.
2. Run `standard` Product Stress and Core Stress before tagged releases or infrastructure changes.
3. Let the weekly `soak` profiles catch long-running regressions without burning Actions minutes on every commit.
4. Add database-backed stress only after durable persistence is actually wired.
5. Add external-provider tests with provider-specific rate-limit budgets rather than flooding paid APIs.
6. Before adding a second API replica, move decision idempotency and logs out of process memory into shared durable storage.
7. Add native mobile performance tests only when an iOS/Android device or emulator runner is intentionally available.

This keeps the repository enterprise-shaped without turning a personal project into an infrastructure benchmark lab.
