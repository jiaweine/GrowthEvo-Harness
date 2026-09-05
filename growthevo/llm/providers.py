from __future__ import annotations

import json
from typing import Any, Mapping


def _mapping_from_json(text: str) -> Mapping[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("structured model output must be a JSON object")
    return value


class OpenAIResponsesClient:
    """OpenAI Responses API adapter using strict JSON-schema output.

    ``model`` is intentionally required instead of silently following a moving
    alias. Production deployments should pin the model snapshot they have
    evaluated. ``store=False`` is the default to minimize provider-side state.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        reasoning_effort: str | None = None,
        store: bool = False,
    ) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "OpenAI adapter requires the optional 'openai' package"
                ) from exc
            client = OpenAI()
        self._client = client

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
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

        response = self._client.responses.create(**request)
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("OpenAI response did not contain structured output text")
        return _mapping_from_json(output_text)


class AnthropicToolClient:
    """Anthropic Messages adapter that forces one schema-validated tool call.

    Tool input is used as the structured transport because it keeps the local
    GrowthEvo contract stable even when free-form response wording changes.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        max_tokens: int = 900,
    ) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "Anthropic adapter requires the optional 'anthropic' package"
                ) from exc
            client = anthropic.Anthropic()
        self._client = client

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        tool_name = "emit_growthevo_structured_output"
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": tool_name,
                    "description": "Return the GrowthEvo decision object matching the locked schema.",
                    "input_schema": dict(schema),
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in getattr(message, "content", ()):  # pragma: no branch - tiny loop
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                value = getattr(block, "input", None)
                if isinstance(value, Mapping):
                    return dict(value)
                raise ValueError("Anthropic tool call input was not an object")
        raise ValueError("Anthropic response did not contain the required tool call")


class GeminiStructuredClient:
    """Google Gen AI adapter using JSON-schema structured output."""

    provider_name = "google"

    def __init__(self, *, model: str, client: Any | None = None) -> None:
        if not model.strip():
            raise ValueError("model cannot be empty")
        self.model = model
        if client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "Gemini adapter requires the optional 'google-genai' package"
                ) from exc
            client = genai.Client()
        self._client = client

    def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config={
                "system_instruction": system,
                "response_format": {
                    "text": {
                        "mime_type": "application/json",
                        "schema": dict(schema),
                    }
                },
                "temperature": 0,
            },
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, Mapping):
            return dict(parsed)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini response did not contain structured output text")
        return _mapping_from_json(text)
