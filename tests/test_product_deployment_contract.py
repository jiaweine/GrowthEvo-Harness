from __future__ import annotations

from pathlib import Path

from growthevo.web.cli import (
    _default_graceful_shutdown_seconds,
    _default_limit_concurrency,
    _default_workers,
)
from growthevo.web.runtime import postgres_pool_config_from_env


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_is_fail_closed_and_capacity_explicit() -> None:
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "name: growthevo-api" in blueprint
    assert "runtime: docker" in blueprint
    assert "region: singapore" in blueprint
    assert "plan: 1c-2g" in blueprint
    assert "numInstances: 2" in blueprint
    assert "autoDeployTrigger: checksPass" in blueprint
    assert "healthCheckPath: /api/ready" in blueprint
    assert "maxShutdownDelaySeconds: 60" in blueprint

    assert "key: GROWTHEVO_MODE\n        value: production" in blueprint
    assert "key: GROWTHEVO_CORS_ORIGINS\n        value: https://jiaweine.github.io" in blueprint
    assert "key: GROWTHEVO_DATABASE_URL" in blueprint
    assert "fromDatabase:" in blueprint
    assert "property: connectionPoolString" in blueprint

    for key in (
        "GROWTHEVO_AUTH_ISSUER",
        "GROWTHEVO_AUTH_JWKS_URL",
        "GROWTHEVO_AUTH_AUDIENCE",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
    ):
        marker = f"- key: {key}\n        sync: false"
        assert marker in blueprint

    assert "connectionPool: pgbouncer" in blueprint
    assert "ipAllowList: []" in blueprint
    assert 'postgresMajorVersion: "17"' in blueprint
    assert "OPENAI_API_KEY\n        value:" not in blueprint
    assert "ANTHROPIC_API_KEY\n        value:" not in blueprint
    assert "GEMINI_API_KEY\n        value:" not in blueprint


def test_self_host_compose_forwards_documented_runtime_controls() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.self-host.example").read_text(encoding="utf-8")
    forwarded = (
        "GROWTHEVO_DB_POOL_MIN_SIZE",
        "GROWTHEVO_DB_POOL_MAX_SIZE",
        "GROWTHEVO_DB_POOL_TIMEOUT_SECONDS",
        "GROWTHEVO_WEB_WORKERS",
        "GROWTHEVO_HTTP_LIMIT_CONCURRENCY",
        "GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS",
        "GROWTHEVO_LLM_ROUTES",
        "OPENAI_API_KEY",
        "GROWTHEVO_OPENAI_MODEL",
        "ANTHROPIC_API_KEY",
        "GROWTHEVO_ANTHROPIC_MODEL",
        "GEMINI_API_KEY",
        "GROWTHEVO_GEMINI_MODEL",
        "GROWTHEVO_LLM_TIMEOUT_SECONDS",
        "GROWTHEVO_LLM_MAX_RETRIES",
        "GROWTHEVO_LLM_MAX_CONCURRENCY",
        "GROWTHEVO_LLM_MAX_QUEUE_SIZE",
        "GROWTHEVO_LLM_ACQUIRE_TIMEOUT_SECONDS",
        "GROWTHEVO_LLM_FAILURE_THRESHOLD",
        "GROWTHEVO_LLM_COOLDOWN_SECONDS",
        "GROWTHEVO_LLM_MAX_PROVIDER_ATTEMPTS",
    )
    for key in forwarded:
        assert f"{key}=" in env_example
        assert f"{key}: ${{{key}" in compose
    assert "GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS: ${GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS:-55}" in compose
    assert "stop_grace_period: 60s" in compose


def test_default_process_capacity_does_not_inherit_platform_web_concurrency(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    monkeypatch.delenv("GROWTHEVO_WEB_WORKERS", raising=False)
    monkeypatch.delenv("GROWTHEVO_HTTP_LIMIT_CONCURRENCY", raising=False)
    monkeypatch.delenv("GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS", raising=False)
    assert _default_workers() == 1
    assert _default_limit_concurrency() == 512
    assert _default_graceful_shutdown_seconds() == 55


def test_render_database_pool_defaults_are_bounded(monkeypatch) -> None:
    for name in (
        "GROWTHEVO_DB_POOL_MIN_SIZE",
        "GROWTHEVO_DB_POOL_MAX_SIZE",
        "GROWTHEVO_DB_POOL_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    config = postgres_pool_config_from_env()
    assert config.min_size == 1
    assert config.max_size == 8
    assert config.timeout_seconds == 5.0
