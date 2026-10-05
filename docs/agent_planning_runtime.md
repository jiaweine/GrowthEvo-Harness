# Guarded Agent Planning

GrowthEvo can use an activated model-provider pool to assist `/api/agent/plan` without giving a model execution authority.

## Product contract

When no provider pool is active, the endpoint returns the existing deterministic reference plan unchanged. Demo mode never initializes external model providers.

When the provider pool is active, planning is native async and uses two sequential structured-output calls:

1. **Proposal** — select exactly one opportunity already present in the GrowthEvo Opportunity Map and draft only a strategy title, falsifiable hypothesis, experiment direction and confidence.
2. **Critic** — approve or veto that exact proposal. The critic cannot replace it, add an executable action, change budget, change rollout, or relax a guardrail.

GrowthEvo itself deterministically compiles workspace facts and estimates from the selected opportunity record. The model does not author evidence tier, population, causal lift, incremental value, budget, guardrails, rollout percentage, approval state, or the next gate.

The returned campaign remains a draft, the rollout remains `5% Canary` / `awaiting_shadow`, approval remains `not_submitted`, and the next gate remains `Shadow preflight`.

## Failure semantics

Malformed model output, unknown opportunity references, low confidence, critic veto, provider failure and semantic circuit-open state all return the deterministic baseline plan. Raw provider errors are never returned to the API caller.

Invalid workspace data also fails closed before any provider call. Client cancellation is propagated immediately and does not count as a semantic failure or trigger a hidden retry.

The semantic planner has a process-local circuit breaker with single-probe half-open recovery. The provider pool retains its own per-route health, concurrency, backpressure and bounded failover controls underneath it.

## Concurrency

`/api/agent/plan` is an async FastAPI handler and calls the provider pool through `agenerate(...)`. Proposal and critic calls are sequential for each logical plan; GrowthEvo does not race multiple providers or proposal/critic requests in parallel for the same plan.

Request-local audit state uses `ContextVar`, so concurrent plans cannot read another request's selected opportunity, provider identity or confidence.

## Audit surface

When model-assisted planning is attempted, the response includes redacted `planner_audit` metadata such as acceptance reason, selected opportunity ID, provider/model identity, critic identity/confidence and latency. Prompts, credentials, raw provider responses and private exception messages are not exposed.

Runtime diagnostics expose whether agent planning and critic are active plus redacted provider-pool counters. LLM health is not a global production-readiness dependency because deterministic fallback remains available.
