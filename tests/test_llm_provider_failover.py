from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Any, Mapping

import pytest

from growthevo.llm import (
    ProviderBusyError,
    ProviderFailoverClient,
    ProviderFailoverConfig,
    ProviderRoute,
    ProviderUnavailableError,
)


SCHEMA = {
    "type": "object",
    "properties": {"route": {"type": "string"}},
    "required": ["route"],
    "additionalProperties": False,
}


class _SuccessClient:
    def __init__(self, provider_name: str, model: str) -> None:
        self.provider_name = provider_name
        self.model = model
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        return {"route": self.provider_name}

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        await asyncio.sleep(0)
        return {"route": self.provider_name}


class _FailureClient(_SuccessClient):
    def __init__(self, provider_name: str, model: str, message: str) -> None:
        super().__init__(provider_name, model)
        self.message = message

    def generate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        raise TimeoutError(self.message)

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        await asyncio.sleep(0)
        raise TimeoutError(self.message)


class _BusyClient(_SuccessClient):
    def generate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        raise ProviderBusyError("local adapter saturated")

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        raise ProviderBusyError("local adapter saturated")


class _RecoveringClient(_SuccessClient):
    def __init__(self, provider_name: str, model: str) -> None:
        super().__init__(provider_name, model)
        self.fail = True
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def generate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        if self.fail:
            raise TimeoutError("provider unavailable")
        if self.block:
            self.entered.set()
            assert self.release.wait(timeout=2.0)
        return {"route": self.provider_name}


class _CancellableClient(_SuccessClient):
    def __init__(self) -> None:
        super().__init__("openai", "cancel-model")
        self.started = asyncio.Event()

    async def agenerate(self, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _ConditionalAsyncClient(_SuccessClient):
    async def agenerate(self, *, user: str, **_: Any) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
        await asyncio.sleep(0.002)
        if user == "fallback":
            raise TimeoutError("primary timeout")
        return {"route": self.provider_name}


def _pool(primary: Any, backup: Any, **config: Any) -> ProviderFailoverClient:
    return ProviderFailoverClient(
        [ProviderRoute("primary", primary), ProviderRoute("backup", backup)],
        config=ProviderFailoverConfig(**config),
    )


def test_failover_uses_backup_and_exposes_actual_request_local_identity() -> None:
    primary = _FailureClient("openai", "openai-model", "sensitive upstream text")
    backup = _SuccessClient("anthropic", "anthropic-model")
    pool = _pool(
        primary,
        backup,
        failure_threshold=1,
        cooldown_seconds=30.0,
        max_provider_attempts=2,
    )

    result = pool.generate(system="system", user="{}", schema=SCHEMA)

    assert result == {"route": "anthropic"}
    assert pool.provider_name == "anthropic"
    assert pool.model == "anthropic-model"
    assert pool.selected_route_name == "backup"
    health = pool.health_snapshot()
    assert health[0].circuit_state == "open"
    assert health[0].failed_total == 1
    assert health[1].succeeded_total == 1
    metrics = pool.metrics()
    assert metrics.provider_attempts_total == 2
    assert metrics.failover_succeeded_total == 1


def test_busy_primary_spills_over_without_poisoning_provider_health() -> None:
    primary = _BusyClient("openai", "openai-model")
    backup = _SuccessClient("google", "gemini-model")
    pool = _pool(
        primary,
        backup,
        failure_threshold=1,
        cooldown_seconds=30.0,
        max_provider_attempts=1,
    )

    assert pool.generate(system="system", user="{}", schema=SCHEMA) == {"route": "google"}

    primary_health = pool.health_snapshot()[0]
    assert primary_health.circuit_state == "closed"
    assert primary_health.consecutive_failures == 0
    assert primary_health.failed_total == 0
    assert primary_health.busy_total == 1
    metrics = pool.metrics()
    assert metrics.provider_attempts_total == 1
    assert metrics.busy_skipped_total == 1
    assert metrics.failover_succeeded_total == 1


def test_provider_attempt_budget_is_bounded_and_errors_do_not_leak_messages() -> None:
    first = _FailureClient("openai", "m1", "API_KEY=super-secret")
    second = _FailureClient("anthropic", "m2", "customer@example.com")
    third = _SuccessClient("google", "m3")
    pool = ProviderFailoverClient(
        [
            ProviderRoute("first", first),
            ProviderRoute("second", second),
            ProviderRoute("third", third),
        ],
        config=ProviderFailoverConfig(
            failure_threshold=5,
            cooldown_seconds=30.0,
            max_provider_attempts=2,
        ),
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        pool.generate(system="system", user="{}", schema=SCHEMA)

    message = str(exc_info.value)
    assert "first:TimeoutError" in message
    assert "second:TimeoutError" in message
    assert "super-secret" not in message
    assert "customer@example.com" not in message
    assert third.calls == 0
    assert pool.metrics().provider_attempts_total == 2


def test_half_open_recovery_allows_only_one_probe_under_concurrency() -> None:
    primary = _RecoveringClient("openai", "openai-model")
    backup = _SuccessClient("anthropic", "anthropic-model")
    pool = _pool(
        primary,
        backup,
        failure_threshold=1,
        cooldown_seconds=0.02,
        max_provider_attempts=2,
    )

    assert pool.generate(system="system", user="first", schema=SCHEMA) == {
        "route": "anthropic"
    }
    primary.fail = False
    primary.block = True
    time.sleep(0.03)

    with ThreadPoolExecutor(max_workers=24) as executor:
        probe = executor.submit(pool.generate, system="system", user="probe", schema=SCHEMA)
        assert primary.entered.wait(timeout=1.0)
        burst = [
            executor.submit(pool.generate, system="system", user=f"burst-{i}", schema=SCHEMA)
            for i in range(20)
        ]
        assert [future.result(timeout=1.0) for future in burst] == [
            {"route": "anthropic"}
        ] * 20
        assert primary.calls == 2
        primary.release.set()
        assert probe.result(timeout=1.0) == {"route": "openai"}

    assert pool.health_snapshot()[0].circuit_state == "closed"
    assert pool.metrics().circuit_skipped_total >= 20


def test_async_cancellation_does_not_failover_or_poison_health() -> None:
    primary = _CancellableClient()
    backup = _SuccessClient("anthropic", "backup-model")
    pool = _pool(
        primary,
        backup,
        failure_threshold=1,
        cooldown_seconds=30.0,
        max_provider_attempts=2,
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            pool.agenerate(system="system", user="cancel", schema=SCHEMA)
        )
        await primary.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    health = pool.health_snapshot()[0]
    assert health.circuit_state == "closed"
    assert health.consecutive_failures == 0
    assert health.failed_total == 0
    assert backup.calls == 0
    metrics = pool.metrics()
    assert metrics.cancelled_total == 1
    assert metrics.failed_total == 0
    assert metrics.provider_attempts_total == 0


def test_concurrent_async_failover_identity_is_context_local() -> None:
    primary = _ConditionalAsyncClient("openai", "primary-model")
    backup = _SuccessClient("google", "backup-model")
    pool = _pool(
        primary,
        backup,
        failure_threshold=10,
        cooldown_seconds=30.0,
        max_provider_attempts=2,
    )

    async def one(user: str) -> tuple[Mapping[str, Any], str, str, str | None]:
        result = await pool.agenerate(system="system", user=user, schema=SCHEMA)
        return result, pool.provider_name, pool.model, pool.selected_route_name

    async def scenario() -> list[tuple[Mapping[str, Any], str, str, str | None]]:
        return await asyncio.gather(one("primary"), one("fallback"))

    direct, fallback = asyncio.run(scenario())
    assert direct == ({"route": "openai"}, "openai", "primary-model", "primary")
    assert fallback == ({"route": "google"}, "google", "backup-model", "backup")
