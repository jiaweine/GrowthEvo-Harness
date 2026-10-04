from __future__ import annotations

import asyncio
import inspect
import json
import threading
from typing import Any, Mapping

from .provider_runtime import (
    ProviderRuntime,
    ProviderRuntimeConfig,
    ProviderRuntimeMetrics,
)


def _mapping_from_json(text: str) -> Mapping[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("structured model output must be a JSON object")
    return value


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class OpenAIResponsesClient:
    """OpenAI Responses adapter with bounded sync/async concurrency.

    ``model`` is intentionally required instead of silently following a moving
    alias. Production deployments should pin the model snapshot they have
    evaluated. ``store=False`` is the default to minimize provider-side state.

    Network retries are delegated to the OpenAI SDK exactly once; GrowthEvo adds
    local capacity/backpressure rather than another retry layer.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        async_client: Any | None = None,
        reasoning_effort: str | None = None,
        store: bool = False,
        runtime: ProviderRuntimeConfig | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.runtime_config = runtime or ProviderRuntimeConfig()
        self._runtime = ProviderRuntime(self.provider_name, self.runtime_config)
        self._async_client_lock = threading.Lock()
        self._client_injected = client is not None
        self._async_client_injected = async_client is not None

        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "OpenAI adapter requires the optional 'openai' package"
                ) from exc
            client = OpenAI(
                timeout=self.runtime_config.timeout_seconds,
                max_retries=self.runtime_config.max_retries,
            )
        self._client = client
        self._async_client = async_client

    def _request(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "store": self.store,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "growthevo_structured_output",
                    "schema": dict(schema),
                    "strict": True,
                }
            },
        }
        if self.reasoning_effort is not None:
            request["reasoning"] = {"effort": self.reasoning_effort}
        return request

    @staticmethod
    def _parse_response(response: Any) -> Mapping[str, Any]:
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("OpenAI response did not contain structured output text")
        return _mapping_from_json(output_text)

    def _generate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        response = self._client.responses.create(**self._request(system=system, user=user, schema=schema))
        return self._parse_response(response)

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._runtime.run_sync(
            lambda: self._generate_raw(system=system, user=user, schema=schema)
        )

    def _get_async_client(self) -> Any | None:
        if self._async_client is not None:
            return self._async_client
        if self._client_injected:
            return None
        with self._async_client_lock:
            if self._async_client is None:
                try:
                    from openai import AsyncOpenAI
                except ImportError as exc:  # pragma: no cover - depends on optional SDK
                    raise RuntimeError(
                        "OpenAI adapter requires the optional 'openai' package"
                    ) from exc
                self._async_client = AsyncOpenAI(
                    timeout=self.runtime_config.timeout_seconds,
                    max_retries=self.runtime_config.max_retries,
                )
            return self._async_client

    async def _agenerate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        async_client = self._get_async_client()
        if async_client is None:
            # Custom sync clients remain usable without pretending they expose an
            # async transport. Capacity is acquired before a worker thread exists.
            return await asyncio.to_thread(
                self._generate_raw, system=system, user=user, schema=schema
            )
        response = await async_client.responses.create(
            **self._request(system=system, user=user, schema=schema)
        )
        return self._parse_response(response)

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return await self._runtime.run_async(
            lambda: self._agenerate_raw(system=system, user=user, schema=schema)
        )

    def runtime_metrics(self) -> ProviderRuntimeMetrics:
        return self._runtime.snapshot()

    def close(self) -> None:
        if not self._client_injected:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    async def aclose(self) -> None:
        self.close()
        if self._async_client is not None and not self._async_client_injected:
            close = getattr(self._async_client, "close", None)
            if callable(close):
                await _await_if_needed(close())


class AnthropicToolClient:
    """Anthropic Messages adapter with forced schema tool output and backpressure."""

    provider_name = "anthropic"
    _TOOL_NAME = "emit_growthevo_structured_output"

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        async_client: Any | None = None,
        max_tokens: int = 900,
        runtime: ProviderRuntimeConfig | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.model = model
        self.max_tokens = max_tokens
        self.runtime_config = runtime or ProviderRuntimeConfig()
        self._runtime = ProviderRuntime(self.provider_name, self.runtime_config)
        self._async_client_lock = threading.Lock()
        self._client_injected = client is not None
        self._async_client_injected = async_client is not None

        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "Anthropic adapter requires the optional 'anthropic' package"
                ) from exc
            client = anthropic.Anthropic(
                timeout=self.runtime_config.timeout_seconds,
                max_retries=self.runtime_config.max_retries,
            )
        self._client = client
        self._async_client = async_client

    def _request(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": self._TOOL_NAME,
                    "description": "Return the GrowthEvo decision object matching the locked schema.",
                    "input_schema": dict(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": self._TOOL_NAME},
        }

    @classmethod
    def _parse_response(cls, message: Any) -> Mapping[str, Any]:
        for block in getattr(message, "content", ()):  # pragma: no branch - tiny loop
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == cls._TOOL_NAME:
                value = getattr(block, "input", None)
                if isinstance(value, Mapping):
                    return dict(value)
                raise ValueError("Anthropic tool call input was not an object")
        raise ValueError("Anthropic response did not contain the required tool call")

    def _generate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        message = self._client.messages.create(**self._request(system=system, user=user, schema=schema))
        return self._parse_response(message)

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._runtime.run_sync(
            lambda: self._generate_raw(system=system, user=user, schema=schema)
        )

    def _get_async_client(self) -> Any | None:
        if self._async_client is not None:
            return self._async_client
        if self._client_injected:
            return None
        with self._async_client_lock:
            if self._async_client is None:
                try:
                    import anthropic
                except ImportError as exc:  # pragma: no cover - depends on optional SDK
                    raise RuntimeError(
                        "Anthropic adapter requires the optional 'anthropic' package"
                    ) from exc
                self._async_client = anthropic.AsyncAnthropic(
                    timeout=self.runtime_config.timeout_seconds,
                    max_retries=self.runtime_config.max_retries,
                )
            return self._async_client

    async def _agenerate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        async_client = self._get_async_client()
        if async_client is None:
            return await asyncio.to_thread(
                self._generate_raw, system=system, user=user, schema=schema
            )
        message = await async_client.messages.create(
            **self._request(system=system, user=user, schema=schema)
        )
        return self._parse_response(message)

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return await self._runtime.run_async(
            lambda: self._agenerate_raw(system=system, user=user, schema=schema)
        )

    def runtime_metrics(self) -> ProviderRuntimeMetrics:
        return self._runtime.snapshot()

    def close(self) -> None:
        if not self._client_injected:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    async def aclose(self) -> None:
        self.close()
        if self._async_client is not None and not self._async_client_injected:
            close = getattr(self._async_client, "close", None)
            if callable(close):
                await _await_if_needed(close())


class GeminiStructuredClient:
    """Google Gen AI adapter using JSON-schema structured output and bounded load."""

    provider_name = "google"

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        runtime: ProviderRuntimeConfig | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        self.model = model
        self.runtime_config = runtime or ProviderRuntimeConfig()
        self._runtime = ProviderRuntime(self.provider_name, self.runtime_config)
        self._client_injected = client is not None

        if client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "Gemini adapter requires the optional 'google-genai' package"
                ) from exc
            client = genai.Client(
                http_options=types.HttpOptions(
                    timeout=max(1, int(self.runtime_config.timeout_seconds * 1000)),
                    retry_options=types.HttpRetryOptions(
                        attempts=self.runtime_config.max_retries + 1,
                    ),
                )
            )
        self._client = client

    def _request(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "contents": user,
            "config": {
                "system_instruction": system,
                "response_mime_type": "application/json",
                "response_json_schema": dict(schema),
                "temperature": 0,
            },
        }

    @staticmethod
    def _parse_response(response: Any) -> Mapping[str, Any]:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, Mapping):
            return dict(parsed)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini response did not contain structured output text")
        return _mapping_from_json(text)

    def _generate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        response = self._client.models.generate_content(
            **self._request(system=system, user=user, schema=schema)
        )
        return self._parse_response(response)

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._runtime.run_sync(
            lambda: self._generate_raw(system=system, user=user, schema=schema)
        )

    async def _agenerate_raw(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        aio = getattr(self._client, "aio", None)
        models = getattr(aio, "models", None)
        generate_content = getattr(models, "generate_content", None)
        if not callable(generate_content):
            return await asyncio.to_thread(
                self._generate_raw, system=system, user=user, schema=schema
            )
        response = await generate_content(
            **self._request(system=system, user=user, schema=schema)
        )
        return self._parse_response(response)

    async def agenerate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return await self._runtime.run_async(
            lambda: self._agenerate_raw(system=system, user=user, schema=schema)
        )

    def runtime_metrics(self) -> ProviderRuntimeMetrics:
        return self._runtime.snapshot()

    def close(self) -> None:
        if not self._client_injected:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    async def aclose(self) -> None:
        if self._client_injected:
            return
        aio = getattr(self._client, "aio", None)
        aclose = getattr(aio, "aclose", None)
        if callable(aclose):
            await _await_if_needed(aclose())
        self.close()
