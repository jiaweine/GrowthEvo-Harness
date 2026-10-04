from __future__ import annotations

from dataclasses import dataclass
import inspect
import os
from typing import Any, Callable, Mapping

from .provider_pool import ProviderFailoverClient, ProviderFailoverConfig, ProviderRoute
from .provider_runtime import ProviderRuntimeConfig
from .providers import AnthropicToolClient, GeminiStructuredClient, OpenAIResponsesClient


_PROVIDER_ORDER = ("openai", "anthropic", "gemini")
_PROVIDER_ENV: Mapping[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "GROWTHEVO_OPENAI_MODEL"),
    "anthropic": ("ANTHROPIC_API_KEY", "GROWTHEVO_ANTHROPIC_MODEL"),
    "gemini": ("GEMINI_API_KEY", "GROWTHEVO_GEMINI_MODEL"),
}


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _value(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _bounded_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = _value(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def llm_environment_configured() -> bool:
    """Return whether any LLM activation setting is present, without exposing it."""

    names = {"GROWTHEVO_LLM_ROUTES"}
    for key_name, model_name in _PROVIDER_ENV.values():
        names.add(key_name)
        names.add(model_name)
    return any(_value(name) for name in names)


def configured_routes_from_env() -> tuple[str, ...]:
    """Return routes that are complete enough to activate.

    An explicit ``GROWTHEVO_LLM_ROUTES`` list is authoritative and fail-closed:
    every named provider must have both its standard API key and an explicitly
    pinned GrowthEvo model ID. Without an explicit route list, complete provider
    pairs are discovered in a deterministic OpenAI -> Anthropic -> Gemini order;
    partial pairs remain visible as configured-but-not-active at the web layer.
    """

    explicit = _value("GROWTHEVO_LLM_ROUTES")
    if explicit:
        routes = tuple(part.strip().lower() for part in explicit.split(",") if part.strip())
        if not routes:
            raise ValueError("GROWTHEVO_LLM_ROUTES must contain at least one provider")
        unknown = sorted(set(routes).difference(_PROVIDER_ORDER))
        if unknown:
            raise ValueError(f"unknown GROWTHEVO_LLM_ROUTES providers: {unknown}")
        if len(set(routes)) != len(routes):
            raise ValueError("GROWTHEVO_LLM_ROUTES cannot contain duplicates")
        for provider in routes:
            key_name, model_name = _PROVIDER_ENV[provider]
            if not _value(key_name) or not _value(model_name):
                raise ValueError(
                    f"{provider} route requires both {key_name} and {model_name}"
                )
        return routes

    complete: list[str] = []
    for provider in _PROVIDER_ORDER:
        key_name, model_name = _PROVIDER_ENV[provider]
        if _value(key_name) and _value(model_name):
            complete.append(provider)
    return tuple(complete)


def provider_runtime_config_from_env() -> ProviderRuntimeConfig:
    return ProviderRuntimeConfig(
        timeout_seconds=_bounded_float(
            "GROWTHEVO_LLM_TIMEOUT_SECONDS", 45.0, minimum=0.1, maximum=600.0
        ),
        max_retries=_bounded_int(
            "GROWTHEVO_LLM_MAX_RETRIES", 2, minimum=0, maximum=10
        ),
        max_concurrency=_bounded_int(
            "GROWTHEVO_LLM_MAX_CONCURRENCY", 64, minimum=1, maximum=4096
        ),
        max_queue_size=_bounded_int(
            "GROWTHEVO_LLM_MAX_QUEUE_SIZE", 256, minimum=0, maximum=16384
        ),
        acquire_timeout_seconds=_bounded_float(
            "GROWTHEVO_LLM_ACQUIRE_TIMEOUT_SECONDS", 1.0, minimum=0.0, maximum=60.0
        ),
    )


def provider_failover_config_from_env() -> ProviderFailoverConfig:
    return ProviderFailoverConfig(
        failure_threshold=_bounded_int(
            "GROWTHEVO_LLM_FAILURE_THRESHOLD", 3, minimum=1, maximum=100
        ),
        cooldown_seconds=_bounded_float(
            "GROWTHEVO_LLM_COOLDOWN_SECONDS", 30.0, minimum=0.0, maximum=3600.0
        ),
        max_provider_attempts=_bounded_int(
            "GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS", 2, minimum=1, maximum=3
        ),
    )


@dataclass(frozen=True, slots=True)
class LLMActivationSummary:
    configured: bool
    active: bool
    route_count: int
    providers: tuple[str, ...]
    backend: str


def _close_constructed_sync_clients(routes: list[ProviderRoute]) -> None:
    """Best-effort cleanup for a pool that failed before async clients existed."""

    seen: set[int] = set()
    for route in reversed(routes):
        client = route.client
        identity = id(client)
        if identity in seen:
            continue
        seen.add(identity)
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # Preserve the original construction failure. Shutdown-time cleanup
                # uses close_provider_pool and surfaces its errors explicitly.
                pass


def build_provider_pool_from_env(
    *,
    factories: Mapping[str, Callable[..., Any]] | None = None,
) -> ProviderFailoverClient | None:
    """Build one process-long provider pool from explicit environment config.

    The function does not make a model request. Provider SDK clients are created
    once so their connection pools can be reused across concurrent requests.
    Tests may inject factories to verify activation without credentials/network.
    """

    route_names = configured_routes_from_env()
    if not route_names:
        return None

    runtime = provider_runtime_config_from_env()
    failover = provider_failover_config_from_env()
    client_factories: Mapping[str, Callable[..., Any]] = factories or {
        "openai": OpenAIResponsesClient,
        "anthropic": AnthropicToolClient,
        "gemini": GeminiStructuredClient,
    }

    routes: list[ProviderRoute] = []
    try:
        for provider in route_names:
            _, model_name = _PROVIDER_ENV[provider]
            factory = client_factories.get(provider)
            if factory is None:
                raise RuntimeError(f"no client factory is registered for LLM provider {provider!r}")
            client = factory(model=_value(model_name), runtime=runtime)
            routes.append(ProviderRoute(provider, client))
    except BaseException:
        _close_constructed_sync_clients(routes)
        raise

    return ProviderFailoverClient(routes, config=failover)


async def close_provider_pool(pool: ProviderFailoverClient | None) -> None:
    """Close each owned route client exactly once at application shutdown."""

    if pool is None:
        return
    seen: set[int] = set()
    errors: list[BaseException] = []
    for route in pool.routes:
        client = route.client
        identity = id(client)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            aclose = getattr(client, "aclose", None)
            if callable(aclose):
                result = aclose()
                if inspect.isawaitable(result):
                    await result
                continue
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except BaseException as exc:  # close remaining clients before surfacing shutdown failure
            errors.append(exc)
    if errors:
        raise ExceptionGroup("one or more LLM provider clients failed to close", errors)


def activation_summary(pool: ProviderFailoverClient | None) -> LLMActivationSummary:
    providers = tuple(route.client.provider_name for route in pool.routes) if pool else ()
    return LLMActivationSummary(
        configured=llm_environment_configured(),
        active=pool is not None,
        route_count=len(providers),
        providers=providers,
        backend="provider-failover" if pool is not None else "none",
    )
