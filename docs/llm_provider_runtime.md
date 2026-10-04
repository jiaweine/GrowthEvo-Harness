# LLM Provider Runtime

GrowthEvo's model-provider layer is designed for bounded production concurrency rather than unbounded fan-out. The semantic proposal plane remains structured-output only and still sits upstream of deterministic policy and legal gates.

## Built-in providers

The same runtime controls apply to:

- `OpenAIResponsesClient` — Responses API + strict JSON Schema;
- `AnthropicToolClient` — forced schema tool call;
- `GeminiStructuredClient` — JSON-schema structured output.

Every adapter keeps the existing synchronous `generate(...)` method and also exposes `await agenerate(...)`. The async path uses the provider's native async SDK when available. An injected custom sync-only client remains compatible through a worker-thread fallback, but capacity is acquired before dispatch so overload cannot create an unbounded thread queue.

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
        acquire_timeout_seconds=1.0,
    ),
)
```

`max_concurrency` is one process-local hard cap per adapter instance. Sync and async calls share the same capacity semaphore, so mixed workloads cannot silently double the provider fan-out.

When all slots are occupied, a call waits only for `acquire_timeout_seconds`. If capacity still is not available, GrowthEvo raises `ProviderBusyError`. This is intentional load shedding: callers can fail closed to the deterministic planner instead of accumulating an unbounded in-memory request queue.

## Retry policy

GrowthEvo does **not** add an outer network retry loop. Retry multiplication is dangerous during provider throttling or outage: an SDK retry budget of three attempts wrapped by another three-attempt loop can become nine upstream requests for one logical decision.

Instead, `max_retries` is configured once on the provider SDK:

- OpenAI receives `timeout` and `max_retries` on `OpenAI` / `AsyncOpenAI`;
- Anthropic receives `timeout` and `max_retries` on `Anthropic` / `AsyncAnthropic`;
- Google receives `HttpOptions.timeout` and `HttpRetryOptions.attempts`; GrowthEvo converts `max_retries=N` to `attempts=N+1` because Google counts the initial request.

The local capacity gate remains independent from SDK retry behavior, which prevents retries from bypassing the provider concurrency budget.

## Metrics

`runtime_metrics()` returns a redacted `ProviderRuntimeMetrics` snapshot with:

- submitted calls;
- provider calls actually started;
- successes and failures;
- local overload rejections;
- current and peak in-flight calls;
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
- overload rejection after a bounded queue wait;
- capacity release after provider exceptions;
- native async request-shape tests for OpenAI, Anthropic and Gemini;
- concurrent planner trace-isolation tests;
- exact optional provider SDK floor validation without credentials or network calls;
- the existing Product Stress gate, which runs these race-sensitive provider tests alongside the product API pressure suite.
