"""Optional LLM proposal plane for GrowthEvo.

The LLM layer is deliberately upstream of the deterministic policy and legal
safety gates. Importing this package does not require any model-provider SDK.
"""

from .planner import (
    GuardedLLMGrowthPlanner,
    LLMPlannerConfig,
    LLMPlannerTrace,
    StructuredLLMClient,
)
from .providers import AnthropicToolClient, GeminiStructuredClient, OpenAIResponsesClient

__all__ = [
    "AnthropicToolClient",
    "GeminiStructuredClient",
    "GuardedLLMGrowthPlanner",
    "LLMPlannerConfig",
    "LLMPlannerTrace",
    "OpenAIResponsesClient",
    "StructuredLLMClient",
]
