from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
import time
from typing import Awaitable, Callable, TypeVar


_T = TypeVar("_T")


class ProviderBusyError(RuntimeError):
    """Raised when local provider capacity is exhausted past the queue budget."""


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfig:
    """Bounded runtime controls shared by all model-provider adapters.

    ``max_concurrency`` is a hard process-local cap per adapter instance. Calls
    wait for at most ``acquire_timeout_seconds`` before failing fast with
    ``ProviderBusyError`` so overload cannot turn into an unbounded memory queue.

    ``timeout_seconds`` and ``max_retries`` are forwarded to the provider SDK.
    GrowthEvo deliberately does not add another network retry loop around the
    SDK because multiplying retry layers can create retry storms under 429/5xx
    load.
    """

    timeout_seconds: float = 45.0
    max_retries: int = 2
    max_concurrency: int = 64
    acquire_timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.acquire_timeout_seconds < 0:
            raise ValueError("acquire_timeout_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class ProviderRuntimeMetrics:
    """Redacted process-local provider health counters.

    The snapshot intentionally contains no prompt, response, user or credential
    data. It is safe to feed into ordinary service metrics/logging.
    """

    submitted_total: int
    started_total: int
    succeeded_total: int
    failed_total: int
    rejected_total: int
    in_flight: int
    peak_in_flight: int
    average_latency_ms: float


class ProviderRuntime:
    """Concurrency gate, overload backpressure and metrics for one adapter.

    A single ``threading.BoundedSemaphore`` is shared by the sync and async
    paths, so mixing ``generate`` and ``agenerate`` on the same adapter still
    obeys one global capacity limit. The async path polls non-blockingly rather
    than blocking the event loop or consuming worker threads while queued.
    """

    _ASYNC_POLL_SECONDS = 0.005

    def __init__(self, provider_name: str, config: ProviderRuntimeConfig) -> None:
        self.provider_name = provider_name
        self.config = config
        self._capacity = threading.BoundedSemaphore(config.max_concurrency)
        self._metrics_lock = threading.Lock()
        self._submitted_total = 0
        self._started_total = 0
        self._succeeded_total = 0
        self._failed_total = 0
        self._rejected_total = 0
        self._in_flight = 0
        self._peak_in_flight = 0
        self._total_latency_ms = 0.0

    def run_sync(self, call: Callable[[], _T]) -> _T:
        self._record_submitted()
        acquired = self._capacity.acquire(timeout=self.config.acquire_timeout_seconds)
        if not acquired:
            self._record_rejected()
            raise ProviderBusyError(
                f"{self.provider_name} provider capacity exhausted "
                f"(max_concurrency={self.config.max_concurrency})"
            )

        started = time.perf_counter()
        self._record_started()
        try:
            result = call()
        except BaseException:
            self._record_finished(started, succeeded=False)
            raise
        else:
            self._record_finished(started, succeeded=True)
            return result
        finally:
            self._capacity.release()

    async def run_async(self, call: Callable[[], Awaitable[_T]]) -> _T:
        self._record_submitted()
        acquired = await self._acquire_async()
        if not acquired:
            self._record_rejected()
            raise ProviderBusyError(
                f"{self.provider_name} provider capacity exhausted "
                f"(max_concurrency={self.config.max_concurrency})"
            )

        started = time.perf_counter()
        self._record_started()
        try:
            result = await call()
        except BaseException:
            self._record_finished(started, succeeded=False)
            raise
        else:
            self._record_finished(started, succeeded=True)
            return result
        finally:
            self._capacity.release()

    async def _acquire_async(self) -> bool:
        if self._capacity.acquire(blocking=False):
            return True
        if self.config.acquire_timeout_seconds == 0:
            return False

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.acquire_timeout_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(self._ASYNC_POLL_SECONDS, remaining))
            if self._capacity.acquire(blocking=False):
                return True

    def snapshot(self) -> ProviderRuntimeMetrics:
        with self._metrics_lock:
            finished = self._succeeded_total + self._failed_total
            average = self._total_latency_ms / finished if finished else 0.0
            return ProviderRuntimeMetrics(
                submitted_total=self._submitted_total,
                started_total=self._started_total,
                succeeded_total=self._succeeded_total,
                failed_total=self._failed_total,
                rejected_total=self._rejected_total,
                in_flight=self._in_flight,
                peak_in_flight=self._peak_in_flight,
                average_latency_ms=average,
            )

    def _record_submitted(self) -> None:
        with self._metrics_lock:
            self._submitted_total += 1

    def _record_rejected(self) -> None:
        with self._metrics_lock:
            self._rejected_total += 1

    def _record_started(self) -> None:
        with self._metrics_lock:
            self._started_total += 1
            self._in_flight += 1
            self._peak_in_flight = max(self._peak_in_flight, self._in_flight)

    def _record_finished(self, started: float, *, succeeded: bool) -> None:
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        with self._metrics_lock:
            self._in_flight -= 1
            self._total_latency_ms += elapsed_ms
            if succeeded:
                self._succeeded_total += 1
            else:
                self._failed_total += 1
