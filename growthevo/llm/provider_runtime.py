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

    ``max_concurrency`` is the hard process-local provider-call cap per adapter
    instance. ``max_queue_size`` separately caps calls allowed to wait for one
    of those slots. Once both budgets are occupied, new work is rejected
    immediately; admitted waiters still wait for at most
    ``acquire_timeout_seconds`` before failing with ``ProviderBusyError``.

    ``timeout_seconds`` and ``max_retries`` are forwarded to the provider SDK.
    GrowthEvo deliberately does not add another network retry loop around the
    SDK because multiplying retry layers can create retry storms under 429/5xx
    load.
    """

    timeout_seconds: float = 45.0
    max_retries: int = 2
    max_concurrency: int = 64
    max_queue_size: int = 256
    acquire_timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.max_queue_size < 0:
            raise ValueError("max_queue_size must be non-negative")
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
    waiting: int
    peak_waiting: int
    average_latency_ms: float


class ProviderRuntime:
    """Bounded concurrency, bounded queueing and metrics for one adapter.

    Sync and async paths share both semaphores. ``_admission`` bounds the total
    number of calls that may be executing or waiting; ``_capacity`` bounds only
    provider calls actually in flight. This means a burst cannot create an
    unbounded waiter population even when callers create very large task sets.

    The async path polls the thread-safe capacity semaphore non-blockingly, so
    waiting never blocks the event loop or consumes worker threads.
    """

    _ASYNC_POLL_SECONDS = 0.005

    def __init__(self, provider_name: str, config: ProviderRuntimeConfig) -> None:
        self.provider_name = provider_name
        self.config = config
        self._capacity = threading.BoundedSemaphore(config.max_concurrency)
        self._admission = threading.BoundedSemaphore(
            config.max_concurrency + config.max_queue_size
        )
        self._metrics_lock = threading.Lock()
        self._submitted_total = 0
        self._started_total = 0
        self._succeeded_total = 0
        self._failed_total = 0
        self._rejected_total = 0
        self._in_flight = 0
        self._peak_in_flight = 0
        self._waiting = 0
        self._peak_waiting = 0
        self._total_latency_ms = 0.0

    def run_sync(self, call: Callable[[], _T]) -> _T:
        self._record_submitted()
        if not self._admission.acquire(blocking=False):
            self._reject()

        acquired_capacity = False
        try:
            if self._capacity.acquire(blocking=False):
                acquired_capacity = True
            else:
                self._record_waiting_started()
                try:
                    acquired_capacity = self._capacity.acquire(
                        timeout=self.config.acquire_timeout_seconds
                    )
                finally:
                    self._record_waiting_finished()

            if not acquired_capacity:
                self._reject()

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
            if acquired_capacity:
                self._capacity.release()
            self._admission.release()

    async def run_async(self, call: Callable[[], Awaitable[_T]]) -> _T:
        self._record_submitted()
        if not self._admission.acquire(blocking=False):
            self._reject()

        acquired_capacity = False
        try:
            if self._capacity.acquire(blocking=False):
                acquired_capacity = True
            else:
                self._record_waiting_started()
                try:
                    acquired_capacity = await self._acquire_async()
                finally:
                    self._record_waiting_finished()

            if not acquired_capacity:
                self._reject()

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
            if acquired_capacity:
                self._capacity.release()
            self._admission.release()

    async def _acquire_async(self) -> bool:
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
                waiting=self._waiting,
                peak_waiting=self._peak_waiting,
                average_latency_ms=average,
            )

    def _reject(self) -> None:
        self._record_rejected()
        raise ProviderBusyError(
            f"{self.provider_name} provider capacity exhausted "
            f"(max_concurrency={self.config.max_concurrency}, "
            f"max_queue_size={self.config.max_queue_size})"
        )

    def _record_submitted(self) -> None:
        with self._metrics_lock:
            self._submitted_total += 1

    def _record_rejected(self) -> None:
        with self._metrics_lock:
            self._rejected_total += 1

    def _record_waiting_started(self) -> None:
        with self._metrics_lock:
            self._waiting += 1
            self._peak_waiting = max(self._peak_waiting, self._waiting)

    def _record_waiting_finished(self) -> None:
        with self._metrics_lock:
            self._waiting -= 1

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
