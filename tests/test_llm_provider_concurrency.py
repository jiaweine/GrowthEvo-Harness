from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time
from typing import Any

import pytest

from growthevo.llm import (
    AnthropicToolClient,
    GeminiStructuredClient,
    OpenAIResponsesClient,
    ProviderBusyError,
    ProviderRuntimeConfig,
)
from growthevo.llm.provider_runtime import ProviderRuntime


SCHEMA = {
    "type": "object",
    "properties": {"option": {"type": "string"}},
    "required": ["option"],
    "additionalProperties": False,
}


class _AsyncCapture:
    def __init__(self, result: Any, *, delay: float = 0.0) -> None:
        self.result = result
        self.delay = delay
        self.calls = 0
        self.kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


class _SyncCapture:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls = 0
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
        return self.result

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
        return self.result


def test_sync_runtime_caps_high_concurrency_and_records_metrics() -> None:
    runtime = ProviderRuntime(
        "fake",
        ProviderRuntimeConfig(max_concurrency=8, acquire_timeout_seconds=2.0),
    )
    state_lock = threading.Lock()
    in_flight = 0
    observed_peak = 0

    def work(value: int) -> int:
        nonlocal in_flight, observed_peak
        with state_lock:
            in_flight += 1
            observed_peak = max(observed_peak, in_flight)
        try:
            time.sleep(0.005)
            return value
        finally:
            with state_lock:
                in_flight -= 1

    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = [pool.submit(runtime.run_sync, lambda value=value: work(value)) for value in range(160)]
        assert [future.result() for future in futures] == list(range(160))

    metrics = runtime.snapshot()
    assert observed_peak <= 8
    assert metrics.peak_in_flight <= 8
    assert metrics.submitted_total == 160
    assert metrics.started_total == 160
    assert metrics.succeeded_total == 160
    assert metrics.failed_total == 0
    assert metrics.rejected_total == 0
    assert metrics.in_flight == 0
    assert metrics.average_latency_ms > 0


def test_async_runtime_caps_high_concurrency_without_blocking_event_loop() -> None:
    runtime = ProviderRuntime(
        "fake",
        ProviderRuntimeConfig(max_concurrency=16, acquire_timeout_seconds=2.0),
    )
    in_flight = 0
    observed_peak = 0

    async def work(value: int) -> int:
        nonlocal in_flight, observed_peak
        in_flight += 1
        observed_peak = max(observed_peak, in_flight)
        try:
            await asyncio.sleep(0.005)
            return value
        finally:
            in_flight -= 1

    async def scenario() -> list[int]:
        return await asyncio.gather(
            *(runtime.run_async(lambda value=value: work(value)) for value in range(320))
        )

    assert asyncio.run(scenario()) == list(range(320))
    metrics = runtime.snapshot()
    assert observed_peak <= 16
    assert metrics.peak_in_flight <= 16
    assert metrics.succeeded_total == 320
    assert metrics.rejected_total == 0
    assert metrics.in_flight == 0


def test_runtime_rejects_overload_after_bounded_queue_wait() -> None:
    runtime = ProviderRuntime(
        "fake",
        ProviderRuntimeConfig(max_concurrency=1, acquire_timeout_seconds=0.02),
    )
    entered = threading.Event()
    release = threading.Event()

    def hold_capacity() -> str:
        entered.set()
        assert release.wait(timeout=2.0)
        return "done"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.run_sync, hold_capacity)
        assert entered.wait(timeout=1.0)
        with pytest.raises(ProviderBusyError):
            runtime.run_sync(lambda: "should-not-run")
        release.set()
        assert first.result(timeout=1.0) == "done"

    metrics = runtime.snapshot()
    assert metrics.submitted_total == 2
    assert metrics.started_total == 1
    assert metrics.succeeded_total == 1
    assert metrics.rejected_total == 1
    assert metrics.in_flight == 0


def test_runtime_releases_capacity_after_provider_failure() -> None:
    runtime = ProviderRuntime(
        "fake",
        ProviderRuntimeConfig(max_concurrency=1, acquire_timeout_seconds=0.1),
    )

    def fail() -> None:
        raise TimeoutError("fixture")

    with pytest.raises(TimeoutError):
        runtime.run_sync(fail)
    assert runtime.run_sync(lambda: "recovered") == "recovered"

    metrics = runtime.snapshot()
    assert metrics.failed_total == 1
    assert metrics.succeeded_total == 1
    assert metrics.in_flight == 0


def test_openai_async_adapter_uses_native_async_client_and_shared_runtime() -> None:
    sync_capture = _SyncCapture(SimpleNamespace(output_text='{"option":"retain"}'))
    async_capture = _AsyncCapture(SimpleNamespace(output_text='{"option":"retain"}'))
    adapter = OpenAIResponsesClient(
        model="pinned-openai-model",
        client=SimpleNamespace(responses=sync_capture),
        async_client=SimpleNamespace(responses=async_capture),
        runtime=ProviderRuntimeConfig(max_concurrency=4),
    )

    result = asyncio.run(adapter.agenerate(system="system", user="{}", schema=SCHEMA))

    assert result == {"option": "retain"}
    assert async_capture.calls == 1
    assert sync_capture.calls == 0
    assert adapter.runtime_metrics().succeeded_total == 1
    assert async_capture.kwargs is not None
    assert async_capture.kwargs["text"]["format"]["strict"] is True


def test_anthropic_async_adapter_uses_native_async_client() -> None:
    block = SimpleNamespace(
        type="tool_use",
        name="emit_growthevo_structured_output",
        input={"option": "retain"},
    )
    sync_capture = _SyncCapture(SimpleNamespace(content=[block]))
    async_capture = _AsyncCapture(SimpleNamespace(content=[block]))
    adapter = AnthropicToolClient(
        model="pinned-anthropic-model",
        client=SimpleNamespace(messages=sync_capture),
        async_client=SimpleNamespace(messages=async_capture),
    )

    result = asyncio.run(adapter.agenerate(system="system", user="{}", schema=SCHEMA))

    assert result == {"option": "retain"}
    assert async_capture.calls == 1
    assert sync_capture.calls == 0
    assert async_capture.kwargs is not None
    assert async_capture.kwargs["tool_choice"]["type"] == "tool"


def test_gemini_async_adapter_uses_client_aio_models() -> None:
    sync_capture = _SyncCapture(SimpleNamespace(parsed={"option": "retain"}, text=None))
    async_capture = _AsyncCapture(SimpleNamespace(parsed={"option": "retain"}, text=None))
    client = SimpleNamespace(
        models=sync_capture,
        aio=SimpleNamespace(models=async_capture),
    )
    adapter = GeminiStructuredClient(model="pinned-gemini-model", client=client)

    result = asyncio.run(adapter.agenerate(system="system", user="{}", schema=SCHEMA))

    assert result == {"option": "retain"}
    assert async_capture.calls == 1
    assert sync_capture.calls == 0
    assert async_capture.kwargs is not None
    assert async_capture.kwargs["config"]["response_json_schema"] == SCHEMA


def test_async_custom_sync_client_fallback_is_bounded_before_thread_dispatch() -> None:
    capture = _SyncCapture(SimpleNamespace(output_text='{"option":"retain"}'))
    adapter = OpenAIResponsesClient(
        model="pinned-openai-model",
        client=SimpleNamespace(responses=capture),
        runtime=ProviderRuntimeConfig(max_concurrency=3, acquire_timeout_seconds=1.0),
    )

    async def scenario() -> list[dict[str, str]]:
        return await asyncio.gather(
            *(adapter.agenerate(system="system", user="{}", schema=SCHEMA) for _ in range(20))
        )

    results = asyncio.run(scenario())
    assert results == [{"option": "retain"}] * 20
    assert capture.calls == 20
    assert adapter.runtime_metrics().peak_in_flight <= 3
