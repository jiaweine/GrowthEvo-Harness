from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from growthevo.llm.providers import AnthropicToolClient, GeminiStructuredClient, OpenAIResponsesClient


SCHEMA = {
    "type": "object",
    "properties": {"option": {"type": "string"}},
    "required": ["option"],
    "additionalProperties": False,
}


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


def test_openai_adapter_uses_strict_responses_json_schema_and_no_storage_by_default() -> None:
    capture = _Capture(SimpleNamespace(output_text='{"option":"retain"}'))
    client = SimpleNamespace(responses=capture)
    adapter = OpenAIResponsesClient(model="pinned-openai-model", client=client, reasoning_effort="medium")

    result = adapter.generate(system="system", user="{}", schema=SCHEMA)

    assert result == {"option": "retain"}
    assert capture.kwargs is not None
    assert capture.kwargs["model"] == "pinned-openai-model"
    assert capture.kwargs["store"] is False
    assert capture.kwargs["text"]["format"]["type"] == "json_schema"
    assert capture.kwargs["text"]["format"]["schema"] == SCHEMA
    assert capture.kwargs["text"]["format"]["strict"] is True
    assert capture.kwargs["reasoning"] == {"effort": "medium"}


def test_anthropic_adapter_forces_schema_tool_call() -> None:
    block = SimpleNamespace(
        type="tool_use",
        name="emit_growthevo_structured_output",
        input={"option": "retain"},
    )
    capture = _Capture(SimpleNamespace(content=[block]))
    client = SimpleNamespace(messages=capture)
    adapter = AnthropicToolClient(model="pinned-anthropic-model", client=client)

    result = adapter.generate(system="system", user="{}", schema=SCHEMA)

    assert result == {"option": "retain"}
    assert capture.kwargs is not None
    assert capture.kwargs["model"] == "pinned-anthropic-model"
    assert capture.kwargs["tool_choice"] == {
        "type": "tool",
        "name": "emit_growthevo_structured_output",
    }
    assert capture.kwargs["tools"][0]["input_schema"] == SCHEMA


def test_gemini_adapter_uses_current_response_format_json_schema_contract() -> None:
    capture = _Capture(SimpleNamespace(parsed=None, text='{"option":"retain"}'))
    client = SimpleNamespace(models=capture)
    adapter = GeminiStructuredClient(model="pinned-gemini-model", client=client)

    result = adapter.generate(system="system", user="{}", schema=SCHEMA)

    assert result == {"option": "retain"}
    assert capture.kwargs is not None
    assert capture.kwargs["model"] == "pinned-gemini-model"
    config = capture.kwargs["config"]
    assert config["temperature"] == 0
    assert config["response_format"]["text"]["mime_type"] == "application/json"
    assert config["response_format"]["text"]["schema"] == SCHEMA
    assert "response_schema" not in config
    assert "response_json_schema" not in config
