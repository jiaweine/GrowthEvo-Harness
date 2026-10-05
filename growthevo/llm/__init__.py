"""Optional LLM proposal plane for GrowthEvo.

The LLM layer is deliberately upstream of the deterministic policy and legal
safety gates. Importing this package does not require any model-provider SDK.
"""

from .agent_planner import AgentPlannerConfig, AgentPlannerTrace, GuardedLLMAgentPlanner
from .contracts import planner_contract_fingerprint, planner_contract_payload
from .planner import (
    AsyncStructuredLLMClient,
    GuardedLLMGrowthPlanner,
    LLMPlannerConfig,
    LLMPlannerTrace,
    StructuredLLMClient,
)
from .provider_pool import (
    ProviderFailoverClient,
    ProviderFailoverConfig,
    ProviderPoolMetrics,
    ProviderRoute,
    ProviderRouteHealth,
    ProviderUnavailableError,
)
from .provider_runtime import (
    ProviderBusyError,
    ProviderRuntimeConfig,
    ProviderRuntimeMetrics,
)
from .providers import AnthropicToolClient, GeminiStructuredClient, OpenAIResponsesClient

__all__ = [
    "AgentPlannerConfig",
    "AgentPlannerTrace",
    "AnthropicToolClient",
    "AsyncStructuredLLMClient",
    "GeminiStructuredClient",
    "GuardedLLMAgentPlanner",
    "GuardedLLMGrowthPlanner",
    "LLMPlannerConfig",
    "LLMPlannerTrace",
    "OpenAIResponsesClient",
    "ProviderBusyError",
    "ProviderFailoverClient",
    "ProviderFailoverConfig",
    "ProviderPoolMetrics",
    "ProviderRoute",
    "ProviderRouteHealth",
    "ProviderRuntimeConfig",
    "ProviderRuntimeMetrics",
    "ProviderUnavailableError",
    "StructuredLLMClient",
    "planner_contract_fingerprint",
    "planner_contract_payload",
]
