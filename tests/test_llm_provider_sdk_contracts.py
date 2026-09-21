"""Validate optional provider SDK request types without credentials or network calls."""

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openai")
pytest.importorskip("anthropic")
pytest.importorskip("google.genai")

from pydantic import TypeAdapter
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from google.genai.types import GenerateContentConfig
from openai.types.responses.response_create_params import ResponseCreateParamsNonStreaming

from growthevo.llm import (
    AnthropicToolClient,
    GeminiStructuredClient,
    GuardedLLMGrowthPlanner,
    OpenAIResponsesClient,
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
