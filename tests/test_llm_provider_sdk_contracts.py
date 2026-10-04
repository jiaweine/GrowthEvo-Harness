"""Validate optional provider SDK request/runtime types without network calls."""

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openai")
pytest.importorskip("anthropic")
pytest.importorskip("google.genai")

import anthropic
from google import genai
from google.genai.types import GenerateContentConfig
import openai
from pydantic import TypeAdapter
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from openai.types.responses.response_create_params import ResponseCreateParamsNonStreaming

from growthevo.llm import (
    AnthropicToolClient,
    GeminiStructuredClient,
    GuardedLLMGrowthPlanner,
    OpenAIResponsesClient,
    ProviderRuntimeConfig,
)


class _Capture:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.result

    def generate_content(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.result


@pytest.mark.parametrize(
    "schema",
    [
        GuardedLLMGrowthPlanner.proposal_schema(),
        GuardedLLMGrowthPlanner.critic_schema(),
    ],
)
def test_openai_request_matches_real_sdk_schema(schema) -> None:
    capture = _Capture(SimpleNamespace(output_text='{"fixture":true}'))
    adapter = OpenAIResponsesClient(
        model="fixture-snapshot",
        client=SimpleNamespace(responses=capture),
        reasoning_effort="medium",
    )

    assert adapter.generate(system="fixture", user="{}", schema=schema) == {"fixture": True}
    assert capture.kwargs is not None

    validated = TypeAdapter(ResponseCreateParamsNonStreaming).validate_python(capture.kwargs)
    assert validated["store"] is False
    assert validated["reasoning"] == {"effort": "medium"}
    assert validated["text"]["format"]["type"] == "json_schema"
    assert validated["text"]["format"]["schema"] == schema
    assert validated["text"]["format"]["strict"] is True


@pytest.mark.parametrize(
    "schema",
    [
        GuardedLLMGrowthPlanner.proposal_schema(),
        GuardedLLMGrowthPlanner.critic_schema(),
    ],
)
def test_anthropic_request_matches_real_sdk_schema(schema) -> None:
    block = SimpleNamespace(
        type="tool_use",
        name="emit_growthevo_structured_output",
        input={"fixture": True},
    )
    capture = _Capture(SimpleNamespace(content=[block]))
    adapter = AnthropicToolClient(
        model="fixture-snapshot",
        client=SimpleNamespace(messages=capture),
    )

    assert adapter.generate(system="fixture", user="{}", schema=schema) == {"fixture": True}
    assert capture.kwargs is not None

    validated = TypeAdapter(MessageCreateParamsNonStreaming).validate_python(capture.kwargs)
    assert validated["max_tokens"] == 900
    assert validated["tool_choice"] == {
        "type": "tool",
        "name": "emit_growthevo_structured_output",
    }
    tools = list(validated["tools"])
    assert tools[0]["input_schema"] == schema


@pytest.mark.parametrize(
    "schema",
    [
        GuardedLLMGrowthPlanner.proposal_schema(),
        GuardedLLMGrowthPlanner.critic_schema(),
    ],
)
def test_gemini_request_matches_real_sdk_config_schema(schema) -> None:
    validated = []

    def generate_content(**request):
        # Real SDK validation catches unsupported fields that permissive fake
        # clients would otherwise accept. No genai.Client or transport is created.
        config = GenerateContentConfig.model_validate(request["config"])
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema == schema
        assert config.temperature == 0
        validated.append(config)
        return SimpleNamespace(parsed={"fixture": True})

    adapter = GeminiStructuredClient(
        model="fixture-snapshot",
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )
    assert adapter.generate(system="fixture", user="{}", schema=schema) == {"fixture": True}
    assert len(validated) == 1


def test_sdk_floor_supports_explicit_timeout_retry_and_async_clients(monkeypatch) -> None:
    """Keep the runtime contract valid at each optional dependency's declared floor."""

    assert hasattr(openai, "AsyncOpenAI")
    assert hasattr(anthropic, "AsyncAnthropic")

    openai_ctor: dict[str, Any] = {}
    anthropic_ctor: dict[str, Any] = {}
    gemini_ctor: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> Any:
        openai_ctor.update(kwargs)
        return SimpleNamespace(responses=_Capture(SimpleNamespace(output_text='{"fixture":true}')))

    def fake_anthropic(**kwargs: Any) -> Any:
        anthropic_ctor.update(kwargs)
        block = SimpleNamespace(
            type="tool_use",
            name="emit_growthevo_structured_output",
            input={"fixture": True},
        )
        return SimpleNamespace(messages=_Capture(SimpleNamespace(content=[block])))

    def fake_gemini(**kwargs: Any) -> Any:
        gemini_ctor.update(kwargs)
        return SimpleNamespace(models=_Capture(SimpleNamespace(parsed={"fixture": True})))

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    monkeypatch.setattr(anthropic, "Anthropic", fake_anthropic)
    monkeypatch.setattr(genai, "Client", fake_gemini)

    runtime = ProviderRuntimeConfig(timeout_seconds=12.5, max_retries=1)
    OpenAIResponsesClient(model="fixture", runtime=runtime)
    AnthropicToolClient(model="fixture", runtime=runtime)
    GeminiStructuredClient(model="fixture", runtime=runtime)

    assert openai_ctor == {"timeout": 12.5, "max_retries": 1}
    assert anthropic_ctor == {"timeout": 12.5, "max_retries": 1}

    http_options = gemini_ctor["http_options"]
    assert http_options.timeout == 12_500
    assert http_options.retry_options is not None
    # Google counts the initial attempt inside `attempts`; GrowthEvo exposes
    # max_retries as retries-after-first-attempt consistently across providers.
    assert http_options.retry_options.attempts == 2
