"""Validate optional SDK request types without credentials or network calls."""

from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai")
from google.genai.types import GenerateContentConfig

from growthevo.llm import GeminiStructuredClient, GuardedLLMGrowthPlanner


@pytest.mark.parametrize("schema", [
    GuardedLLMGrowthPlanner.proposal_schema(),
    GuardedLLMGrowthPlanner.critic_schema(),
])
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
