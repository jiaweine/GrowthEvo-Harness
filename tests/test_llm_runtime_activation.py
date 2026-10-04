from __future__ import annotations

import asyncio
from typing import Any, Mapping

import pytest

from growthevo.llm.configuration import (
    build_provider_pool_from_env,
    close_provider_pool,
    configured_routes_from_env,
    provider_failover_config_from_env,
    provider_runtime_config_from_env,
)
from growthevo.llm.provider_pool import ProviderFailoverClient, ProviderRoute


_LLM_ENV_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROWTHEVO_OPENAI_MODEL",
    "GROWTHEVO_ANTHROPIC_MODEL",
    "GROWTHEVO_GEMINI_MODEL",
    "GROWTHEVO_LLM_ROUTES",
    "GROWTHEVO_LLM_TIMEOUT_SECONDS",
    "GROWTHEVO_LLM_MAX_RETRIES",
    "GROWTHEVO_LLM_MAX_CONCURRENCY",
    "GROWTHEVO_LLM_MAX_QUEUE_SIZE",
    "GROWTHEVO_LLM_ACQUIRE_TIMEOUT_SECONDS",
    "GROWTHEVO_LLM_FAILURE_THRESHOLD",
    "GROWTHEVO_LLM_COOLDOWN_SECONDS",
    "GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LLM_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class _FakeClient:
    def __init__(self, provider_name: str, *, model: str, runtime: Any) -> None:
        self.provider_name = provider_name
        self.model = model
        self.runtime_config = runtime
        self.close_calls = 0

    def generate(self, **_: Any) -> Mapping[str, Any]:
        return {"ok": True}

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        return {"ok": True}

    async def aclose(self) -> None:
        self.close_calls += 1


def _factory(provider_name: str):
    def create(*, model: str, runtime: Any) -> _FakeClient:
        return _FakeClient(provider_name, model=model, runtime=runtime)

    return create


def _factories() -> dict[str, Any]:
    return {
        "openai": _factory("openai"),
        "anthropic": _factory("anthropic"),
        "gemini": _factory("google"),
    }


def test_implicit_activation_requires_complete_key_and_pinned_model_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    assert configured_routes_from_env() == ()

    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "openai-snapshot")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    monkeypatch.setenv("GROWTHEVO_ANTHROPIC_MODEL", "claude-snapshot")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    monkeypatch.setenv("GROWTHEVO_GEMINI_MODEL", "gemini-snapshot")
    assert configured_routes_from_env() == ("openai", "anthropic", "gemini")

    pool = build_provider_pool_from_env(factories=_factories())
    assert pool is not None
    assert [route.name for route in pool.routes] == ["openai", "anthropic", "gemini"]
    assert [route.client.model for route in pool.routes] == [
        "openai-snapshot",
        "claude-snapshot",
        "gemini-snapshot",
    ]


def test_explicit_routes_are_authoritative_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROWTHEVO_LLM_ROUTES", "anthropic,openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GROWTHEVO_ANTHROPIC_MODEL", "claude-snapshot")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    with pytest.raises(ValueError, match="GROWTHEVO_OPENAI_MODEL"):
        configured_routes_from_env()

    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "openai-snapshot")
    assert configured_routes_from_env() == ("anthropic", "openai")

    monkeypatch.setenv("GROWTHEVO_LLM_ROUTES", "openai,openai")
    with pytest.raises(ValueError, match="duplicates"):
        configured_routes_from_env()

    monkeypatch.setenv("GROWTHEVO_LLM_ROUTES", "unknown")
    with pytest.raises(ValueError, match="unknown"):
        configured_routes_from_env()


def test_runtime_limits_are_bounded_before_provider_clients_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROWTHEVO_LLM_MAX_CONCURRENCY", "4097")
    with pytest.raises(ValueError, match="GROWTHEVO_LLM_MAX_CONCURRENCY"):
        provider_runtime_config_from_env()

    monkeypatch.setenv("GROWTHEVO_LLM_MAX_CONCURRENCY", "512")
    monkeypatch.setenv("GROWTHEVO_LLM_MAX_QUEUE_SIZE", "1024")
    monkeypatch.setenv("GROWTHEVO_LLM_TIMEOUT_SECONDS", "30")
    runtime = provider_runtime_config_from_env()
    assert runtime.max_concurrency == 512
    assert runtime.max_queue_size == 1024
    assert runtime.timeout_seconds == 30

    monkeypatch.setenv("GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS", "4")
    with pytest.raises(ValueError, match="GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS"):
        provider_failover_config_from_env()


def test_pool_shutdown_closes_shared_clients_once() -> None:
    client = _FakeClient("openai", model="snapshot", runtime=provider_runtime_config_from_env())
    pool = ProviderFailoverClient(
        [ProviderRoute("primary", client), ProviderRoute("same-client-backup", client)]
    )

    asyncio.run(close_provider_pool(pool))

    assert client.close_calls == 1


def test_web_runtime_activates_pool_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-openai-key")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "evaluated-openai-snapshot")
    fake_pool = ProviderFailoverClient(
        [ProviderRoute("openai", _FakeClient("openai", model="evaluated-openai-snapshot", runtime=provider_runtime_config_from_env()))]
    )
    monkeypatch.setattr(web_app, "build_provider_pool_from_env", lambda: fake_pool)

    with TestClient(web_app.create_app()) as client:
        payload = client.get("/api/system/runtime").json()
        assert payload["ready"] is True
        assert payload["llm"]["configured"] is True
        assert payload["llm"]["active"] is True
        assert payload["llm"]["backend"] == "provider-failover"
        assert payload["llm"]["route_count"] == 1
        assert payload["llm"]["available_routes"] == 1
        assert payload["llm"]["providers"] == ["openai"]
        connector = next(item for item in payload["connectors"] if item["id"] == "llm")
        assert connector["state"] == "connected"
        assert "super-secret-openai-key" not in client.get("/api/system/runtime").text


def test_demo_never_activates_external_models_even_when_credentials_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "demo")
    monkeypatch.setenv("OPENAI_API_KEY", "leaked-key")
    monkeypatch.setenv("GROWTHEVO_OPENAI_MODEL", "evaluated-openai-snapshot")

    def forbidden_builder() -> None:
        raise AssertionError("demo mode must not initialize external model providers")

    monkeypatch.setattr(web_app, "build_provider_pool_from_env", forbidden_builder)
    with TestClient(web_app.create_app()) as client:
        payload = client.get("/api/system/runtime").json()
        assert payload["llm"]["configured"] is True
        assert payload["llm"]["active"] is False
        connector = next(item for item in payload["connectors"] if item["id"] == "llm")
        assert connector["state"] == "demo"


def test_partial_llm_configuration_is_visible_but_not_fake_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("OPENAI_API_KEY", "configured-key-without-model")
    with TestClient(web_app.create_app()) as client:
        payload = client.get("/api/system/runtime").json()
        assert payload["llm"]["configured"] is True
        assert payload["llm"]["active"] is False
        connector = next(item for item in payload["connectors"] if item["id"] == "llm")
        assert connector["state"] == "configured_not_active"


def test_explicit_broken_llm_route_fails_startup_in_api_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    import growthevo.web.app as web_app

    monkeypatch.setenv("GROWTHEVO_MODE", "api")
    monkeypatch.setenv("GROWTHEVO_LLM_ROUTES", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "configured-key")
    with pytest.raises(RuntimeError, match="LLM provider runtime"):
        web_app.create_app()
