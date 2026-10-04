# LLM Provider Runtime

GrowthEvo's model-provider layer is designed for bounded production concurrency rather than unbounded fan-out. The semantic proposal plane remains structured-output only and still sits upstream of deterministic policy and legal gates.

## Built-in providers

The same runtime controls apply to:

- `OpenAIResponsesClient` — Responses API + strict JSON Schema;
- `AnthropicToolClient` — forced schema tool call;
- `GeminiStructuredClient` — JSON-schema structured output.

Every adapter keeps the existing synchronous `generate(...)` method and also exposes `await agenerate(...)`. The async path uses the provider's native async SDK when available. An injected custom sync-only client remains compatible through a worker-thread fallback, but both admission and provider capacity are acquired before dispatch so overload cannot create an unbounded thread queue.

## Product runtime activation

The web/API runtime can own one process-long provider pool. Activation is explicit: a route requires both the provider's normal API-key environment variable and a pinned GrowthEvo model ID.

| Route | Credential | Required pinned model |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `GROWTHEVO_OPENAI_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY` | `GROWTHEVO_ANTHROPIC_MODEL` |
| Gemini | `GEMINI_API_KEY` | `GROWTHEVO_GEMINI_MODEL` |

If `GROWTHEVO_LLM_ROUTES` is omitted, complete route pairs are discovered in deterministic `openai,anthropic,gemini` order. A key without a pinned model is treated as configured-but-not-active rather than silently following a moving model alias.

Set `GROWTHEVO_LLM_ROUTES` to make route order explicit, for example `anthropic,openai`. An explicit route list is fail-closed: unknown names, duplicate routes, or a named route missing either its key or pinned model make startup fail instead of silently reducing intended redundancy.

Demo mode never constructs external model clients, even if provider credentials accidentally exist in its environment. API/production mode creates configured provider SDK clients once and reuses their connection pools until application shutdown. Partial provider construction is cleaned up if a later route fails to initialize.

The production container includes exact provider SDK roots matching the versions exercised by the repository's SDK-floor contract. This prevents a runtime with valid credentials from advertising an LLM connector that cannot actually import its driver.

Runtime controls are configurable with bounded environment values:

- `GROWTHEVO_LLM_TIMEOUT_SECONDS` — default `45`;
- `GROWTHEVO_LLM_MAX_RETRIES` — default `2`;
- `GROWTHEVO_LLM_MAX_CONCURRENCY` — default `64` per provider adapter;
- `GROWTHEVO_LLM_MAX_QUEUE_SIZE` — default `256` per provider adapter;
- `GROWTHEVO_LLM_ACQUIRE_TIMEOUT_SECONDS` — default `1`;
- `GROWTHEVO_LLM_FAILURE_THRESHOLD` — default `3`;
- `GROWTHEVO_LLM_COOLDOWN_SECONDS` — default `30`;
- `GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS` — default `2`, hard-bounded to at most the three built-in provider routes.

`/api/system/runtime` reports only redacted activation state, provider names, route counts, available-route count and aggregate pool metrics. Credentials, prompts, responses, raw exception messages and configured model IDs are not exposed by that public runtime payload.

LLM health is deliberately **not** a global production-readiness dependency. If every model route is unavailable, the LLM connector can report `error` while the service remains ready because the guarded planning path falls back to deterministic GrowthEvo behavior. Authentication and durable persistence remain the fail-closed production readiness boundaries.

## Capacity and backpressure

Configure the provider boundary with `ProviderRuntimeConfig`:

```python
from growthevo.llm import OpenAIResponsesClient, ProviderRuntimeConfig

provider = OpenAIResponsesClient(
    model="<evaluated-pinned-model-id>",
    runtime=ProviderRuntimeConfig(
        timeout_seconds=45,
        max_retries=2,
        max_concurrency=64,
        max_queue_size=256,
        acquire_timeout_seconds=1.0,
    ),
)
```

`max_concurrency` is one process-local hard cap per adapter instance. Sync and async calls share the same capacity semaphore, so mixed workloads cannot silently double the provider fan-out.

`max_queue_size` is a separate hard cap on requests allowed to wait for provider capacity. At most `max_concurrency + max_queue_size` calls may be admitted into one adapter at a time. Once that budget is occupied, the next call is rejected immediately with `ProviderBusyError`; admitted waiters may wait only for `acquire_timeout_seconds` before they are also rejected. This gives the provider layer two-stage overload protection: a finite queue for short bursts and immediate load shedding once the queue budget is full.

The queue cap is process-local and should be sized together with the upstream worker count, provider account rate limits, request latency, and deployment replica count. Increasing it does not increase provider throughput; it only allows a larger short-lived burst to wait in memory.

## Multi-provider failover

`ProviderFailoverClient` composes multiple structured providers without racing them in parallel:

```python
from growthevo.llm import (
    ProviderFailoverClient,
    ProviderFailoverConfig,
    ProviderRoute,
)

client = ProviderFailoverClient(
    [
        ProviderRoute("openai-primary", openai_client),
        ProviderRoute("anthropic-backup", anthropic_client),
        ProviderRoute("gemini-tertiary", gemini_client),
    ],
    config=ProviderFailoverConfig(
        failure_threshold=3,
        cooldown_seconds=30,
        max_provider_attempts=2,
    ),
)
```

Routes are evaluated in order. GrowthEvo deliberately does **not** race OpenAI, Anthropic and Gemini for the same logical decision because parallel racing would multiply spend, provider traffic and the number of external systems receiving the same request context.

A local `ProviderBusyError` causes immediate spillover to the next route but does not count as a provider-health failure: local saturation is not evidence that the upstream provider is unhealthy. Real provider/response failures increment that route's health state. Once `failure_threshold` is reached, only that route opens; healthy routes remain available.

After `cooldown_seconds`, the circuit enters half-open recovery. Exactly one request is allowed to probe the recovering route while concurrent requests skip it, preventing a thundering herd when a provider comes back. A successful probe closes the route; a failed probe reopens it.

`max_provider_attempts` bounds real upstream provider attempts per logical decision. Circuit skips, local busy rejections and routes that do not implement async do not consume the upstream-attempt budget because they make no provider request. With the default of two, one logical decision cannot cascade through all configured providers after repeated network failures, which bounds cross-provider latency and retry multiplication.

Async cancellation is terminal for that logical request: it is propagated immediately, never converted into failover, and never counted as a provider failure. This keeps user/client cancellations from poisoning circuit health.

The pool stores the actually selected provider/model in a request-local `ContextVar`. A shared pool can therefore serve many concurrent tasks while `GuardedLLMGrowthPlanner` audit traces still report the provider that actually answered that request rather than a shared mutable "last provider" value.

`metrics()` exposes redacted pool-level counts for submissions, successes, failures, cancellations, real provider attempts, successful failovers, circuit skips and busy-route skips. `health_snapshot()` exposes per-route circuit state and counters without prompts, responses, user identifiers, credentials or raw exception messages.

## Retry policy

GrowthEvo does **not** add an outer network retry loop. Retry multiplication is dangerous during provider throttling or outage: an SDK retry budget of three attempts wrapped by another three-attempt loop can become nine upstream requests for one logical decision.

Instead, `max_retries` is configured once on the provider SDK:

- OpenAI receives `timeout` and `max_retries` on `OpenAI` / `AsyncOpenAI`;
- Anthropic receives `timeout` and `max_retries` on `Anthropic` / `AsyncAnthropic`;
- Google receives `HttpOptions.timeout` and `HttpRetryOptions.attempts`; GrowthEvo converts `max_retries=N` to `attempts=N+1` because Google counts the initial request.

The local admission/capacity gates remain independent from SDK retry behavior, which prevents retries from bypassing GrowthEvo's process-local fan-out budget. Provider-pool failover is a separate, bounded layer: it changes route after a completed provider failure but does not repeat the same provider call outside that provider SDK's retry budget.

## Metrics

`runtime_metrics()` returns a redacted `ProviderRuntimeMetrics` snapshot with:

- submitted calls;
- provider calls actually started;
- successes and failures;
- local overload rejections;
- current and peak in-flight calls;
- current and peak waiting calls;
- average provider-call latency.

No prompt, response, user identifier, API key or model context is stored in these metrics.

## Client lifecycle

Adapters expose `close()` and `await aclose()` for owned provider clients. Long-running services should create provider adapters once, reuse their underlying connection pools, and close them during application shutdown rather than constructing a new SDK client per request.

## Why the proposal plane is not streaming

The GrowthEvo proposal plane consumes one small schema-constrained decision object. Partial token streaming would not be actionable until the full JSON object validates, and it would complicate cancellation and safety semantics without improving decision correctness. High throughput is therefore achieved with native async request concurrency and connection reuse, not partial JSON streaming.

A conversational UI can use a separate streaming transport if needed; it should not weaken the structured proposal contract.

## Concurrency-safe planner state

`GuardedLLMGrowthPlanner` protects its shared circuit-breaker state with a lock and stores the latest audit trace in a `ContextVar`. This keeps fail-closed circuit behavior shared across requests while preventing one concurrent request from reading another request's trace.

## Verification

The repository continuously verifies this design through:

- high-volume sync provider-runtime calls under a bounded thread pool;
- hundreds of concurrent async calls with a strict peak-in-flight cap;
- a hard queue-size test proving an extra burst is rejected immediately once one in-flight slot and one waiting slot are occupied;
- overload rejection after a bounded queue wait;
- capacity release after provider exceptions;
- native async request-shape tests for OpenAI, Anthropic and Gemini;
- ordered provider failover with request-local provider identity;
- local-overload spillover without circuit poisoning;
- bounded cross-provider attempt budgets and redacted aggregate errors;
- single-probe half-open recovery under concurrent load;
- cancellation propagation without health-state mutation;
- concurrent async failover identity isolation;
- explicit product-runtime activation and redacted connector-state tests;
- partial provider-construction cleanup and application shutdown cleanup;
- concurrent planner trace-isolation tests;
- exact optional provider SDK floor validation without credentials or network calls;
- production-container builds that include the provider SDK roots;
- the existing Product Stress gate, which runs these race-sensitive provider tests alongside the product API pressure suite.
