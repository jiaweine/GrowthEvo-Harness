from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import threading
import time
from typing import Any, Mapping, Sequence

from .provider_runtime import ProviderBusyError


class ProviderUnavailableError(RuntimeError):
    """Raised when no configured provider route can serve a request safely."""


@dataclass(frozen=True, slots=True)
class ProviderFailoverConfig:
    """Health and failover controls for a provider pool.

    ``failure_threshold`` opens one route's circuit after that many consecutive
    provider failures. ``cooldown_seconds`` controls how long the route remains
    open before exactly one half-open probe is admitted. ``max_provider_attempts``
    bounds real provider attempts per logical request; local ``ProviderBusyError``
    rejections and unsupported async routes do not consume this budget because
    no upstream request was made.
    """

    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    max_provider_attempts: int = 2

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if self.max_provider_attempts <= 0:
            raise ValueError("max_provider_attempts must be positive")


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """Named provider route used by ``ProviderFailoverClient``."""

    name: str
    client: Any

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("provider route name cannot be empty")
        if not isinstance(getattr(self.client, "provider_name", None), str):
            raise TypeError("provider route client must expose provider_name")
        if not isinstance(getattr(self.client, "model", None), str):
            raise TypeError("provider route client must expose model")
        if not callable(getattr(self.client, "generate", None)):
            raise TypeError("provider route client must expose generate(...)")


@dataclass(frozen=True, slots=True)
class ProviderRouteHealth:
    name: str
    provider: str
    model: str
    circuit_state: str
    consecutive_failures: int
    attempts_total: int
    succeeded_total: int
    failed_total: int
    busy_total: int
    open_for_seconds: float


@dataclass(frozen=True, slots=True)
class ProviderPoolMetrics:
    submitted_total: int
    succeeded_total: int
    failed_total: int
    cancelled_total: int
    provider_attempts_total: int
    failover_succeeded_total: int
    circuit_skipped_total: int
    busy_skipped_total: int


@dataclass(slots=True)
class _RouteState:
    consecutive_failures: int = 0
    open_until: float = 0.0
    half_open_in_flight: bool = False
    attempts_total: int = 0
    succeeded_total: int = 0
    failed_total: int = 0
    busy_total: int = 0


@dataclass(frozen=True, slots=True)
class _Selection:
    route_name: str
    provider_name: str
    model: str


class ProviderFailoverClient:
    """Ordered, health-aware failover for structured model providers.

    Routes are tried in configured order. The pool never races providers in
    parallel: doing so would multiply cost, data exposure, and outage traffic.
    A locally saturated route may spill to the next route without being marked
    unhealthy. Provider failures open only that route's circuit, and after the
    cooldown exactly one half-open probe is allowed so recovery does not create
    a thundering herd.

    The selected provider identity is kept in a ``ContextVar``. Existing
    ``GuardedLLMGrowthPlanner`` audit traces therefore record the provider/model
    that actually served each concurrent request rather than the pool identity.
    """

    def __init__(
        self,
        routes: Sequence[ProviderRoute],
        *,
        config: ProviderFailoverConfig | None = None,
    ) -> None:
        self.routes = tuple(routes)
        if not self.routes:
            raise ValueError("at least one provider route is required")
        names = [route.name for route in self.routes]
        if len(set(names)) != len(names):
            raise ValueError("provider route names must be unique")

        self.config = config or ProviderFailoverConfig()
        self._state_lock = threading.Lock()
        self._states = {route.name: _RouteState() for route in self.routes}
        self._submitted_total = 0
        self._succeeded_total = 0
        self._failed_total = 0
        self._cancelled_total = 0
        self._provider_attempts_total = 0
        self._failover_succeeded_total = 0
        self._circuit_skipped_total = 0
        self._busy_skipped_total = 0
        self._selection: ContextVar[_Selection | None] = ContextVar(
            f"growthevo_provider_selection_{id(self)}", default=None
        )

    @property
    def provider_name(self) -> str:
        selection = self._selection.get()
        return selection.provider_name if selection is not None else "failover"

    @property
    def model(self) -> str:
        selection = self._selection.get()
        return selection.model if selection is not None else "provider-pool"

    @property
    def selected_route_name(self) -> str | None:
        selection = self._selection.get()
        return selection.route_name if selection is not None else None

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._begin_request()
        errors: list[tuple[str, str]] = []
        provider_attempts = 0
        used_failover = False

        for index, route in enumerate(self.routes):
            if provider_attempts >= self.config.max_provider_attempts:
                break
            reserved, is_probe = self._reserve_route(route.name)
            if not reserved:
                used_failover = True
                continue

            self._select(route)
            try:
                result = route.client.generate(system=system, user=user, schema=schema)
            except ProviderBusyError:
                self._record_busy(route.name, is_probe=is_probe)
                used_failover = True
                errors.append((route.name, "busy"))
                continue
            except Exception as exc:
                provider_attempts += 1
                self._record_failure(route.name, is_probe=is_probe)
                used_failover = True
                errors.append((route.name, type(exc).__name__))
                continue
            except BaseException:
                self._release_probe(route.name, is_probe=is_probe)
                raise
            else:
                provider_attempts += 1
                self._record_success(route.name)
                self._finish_request(succeeded=True, failover=used_failover or index > 0)
                return result

        self._finish_request(succeeded=False, failover=False)
        raise ProviderUnavailableError(self._unavailable_message(errors))

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._begin_request()
        errors: list[tuple[str, str]] = []
        provider_attempts = 0
        used_failover = False

        for index, route in enumerate(self.routes):
            if provider_attempts >= self.config.max_provider_attempts:
                break
            reserved, is_probe = self._reserve_route(route.name)
            if not reserved:
                used_failover = True
                continue

            agenerate = getattr(route.client, "agenerate", None)
            if not callable(agenerate):
                self._release_probe(route.name, is_probe=is_probe)
                used_failover = True
                errors.append((route.name, "AsyncUnsupported"))
                continue

            self._select(route)
            try:
                result = await agenerate(system=system, user=user, schema=schema)
            except asyncio.CancelledError:
                self._release_probe(route.name, is_probe=is_probe)
                self._cancel_request()
                raise
            except ProviderBusyError:
                self._record_busy(route.name, is_probe=is_probe)
                used_failover = True
                errors.append((route.name, "busy"))
                continue
            except Exception as exc:
                provider_attempts += 1
                self._record_failure(route.name, is_probe=is_probe)
                used_failover = True
                errors.append((route.name, type(exc).__name__))
                continue
            except BaseException:
                self._release_probe(route.name, is_probe=is_probe)
                raise
            else:
                provider_attempts += 1
                self._record_success(route.name)
                self._finish_request(succeeded=True, failover=used_failover or index > 0)
                return result

        self._finish_request(succeeded=False, failover=False)
        raise ProviderUnavailableError(self._unavailable_message(errors))

    def metrics(self) -> ProviderPoolMetrics:
        with self._state_lock:
            return ProviderPoolMetrics(
                submitted_total=self._submitted_total,
                succeeded_total=self._succeeded_total,
                failed_total=self._failed_total,
                cancelled_total=self._cancelled_total,
                provider_attempts_total=self._provider_attempts_total,
                failover_succeeded_total=self._failover_succeeded_total,
                circuit_skipped_total=self._circuit_skipped_total,
                busy_skipped_total=self._busy_skipped_total,
            )

    def health_snapshot(self) -> tuple[ProviderRouteHealth, ...]:
        now = time.monotonic()
        with self._state_lock:
            snapshots: list[ProviderRouteHealth] = []
            for route in self.routes:
                state = self._states[route.name]
                if state.open_until == 0:
                    circuit_state = "closed"
                elif now < state.open_until:
                    circuit_state = "open"
                else:
                    circuit_state = "half_open"
                snapshots.append(
                    ProviderRouteHealth(
                        name=route.name,
                        provider=route.client.provider_name,
                        model=route.client.model,
                        circuit_state=circuit_state,
                        consecutive_failures=state.consecutive_failures,
                        attempts_total=state.attempts_total,
                        succeeded_total=state.succeeded_total,
                        failed_total=state.failed_total,
                        busy_total=state.busy_total,
                        open_for_seconds=max(0.0, state.open_until - now),
                    )
                )
            return tuple(snapshots)

    def _begin_request(self) -> None:
        self._selection.set(None)
        with self._state_lock:
            self._submitted_total += 1

    def _select(self, route: ProviderRoute) -> None:
        self._selection.set(
            _Selection(
                route_name=route.name,
                provider_name=route.client.provider_name,
                model=route.client.model,
            )
        )

    def _reserve_route(self, name: str) -> tuple[bool, bool]:
        now = time.monotonic()
        with self._state_lock:
            state = self._states[name]
            if state.open_until == 0:
                return True, False
            if now < state.open_until:
                self._circuit_skipped_total += 1
                return False, False
            if state.half_open_in_flight:
                self._circuit_skipped_total += 1
                return False, False
            state.half_open_in_flight = True
            return True, True

    def _record_success(self, name: str) -> None:
        with self._state_lock:
            state = self._states[name]
            state.attempts_total += 1
            state.succeeded_total += 1
            state.consecutive_failures = 0
            state.open_until = 0.0
            state.half_open_in_flight = False
            self._provider_attempts_total += 1

    def _record_failure(self, name: str, *, is_probe: bool) -> None:
        now = time.monotonic()
        with self._state_lock:
            state = self._states[name]
            state.attempts_total += 1
            state.failed_total += 1
            state.consecutive_failures += 1
            self._provider_attempts_total += 1
            if is_probe or state.consecutive_failures >= self.config.failure_threshold:
                state.open_until = now + self.config.cooldown_seconds
                state.half_open_in_flight = False

    def _record_busy(self, name: str, *, is_probe: bool) -> None:
        with self._state_lock:
            state = self._states[name]
            state.busy_total += 1
            self._busy_skipped_total += 1
            if is_probe:
                state.half_open_in_flight = False

    def _release_probe(self, name: str, *, is_probe: bool) -> None:
        if not is_probe:
            return
        with self._state_lock:
            self._states[name].half_open_in_flight = False

    def _finish_request(self, *, succeeded: bool, failover: bool) -> None:
        with self._state_lock:
            if succeeded:
                self._succeeded_total += 1
                if failover:
                    self._failover_succeeded_total += 1
            else:
                self._failed_total += 1

    def _cancel_request(self) -> None:
        with self._state_lock:
            self._cancelled_total += 1

    @staticmethod
    def _unavailable_message(errors: Sequence[tuple[str, str]]) -> str:
        if not errors:
            return "no healthy provider route was available"
        summary = ", ".join(f"{name}:{kind}" for name, kind in errors)
        return f"no provider route completed successfully ({summary})"
