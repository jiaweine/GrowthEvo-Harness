# Guarded LLM Proposal Plane

GrowthEvo's LLM integration is intentionally **not** an LLM-controlled execution loop.
The original causal/RL harness remains authoritative. The model is an optional semantic
proposal layer that can be removed without changing the policy, OPE, verifier, benchmark,
or evidence contracts.

## Design objective

Preserve the original control path:

```text
Causal belief
   -> deterministic GrowthHypothesisPlanner
   -> HierarchicalGrowthPolicy
   -> LegalActionGate
   -> world / real executor
   -> causal reward + OPE + verification
```

Add an optional proposal plane:

```text
                         +-----------------------------+
                         | optional LLM proposal plane |
                         | structured output only      |
                         | optional critic             |
                         +--------------+--------------+
                                        |
Causal belief -> baseline planner ------+----> semantic GrowthHypothesis
                                             |
                                             v
                                  HierarchicalGrowthPolicy
                                             |
                                             v
                                      LegalActionGate
                                             |
                                             v
                                  execution / NO_TREATMENT
```

The LLM cannot emit `Channel`, `offer_value`, `budget`, `frequency_cost`, `creative_id`,
or `send_hour`. It can only propose a `GrowthOption`, a bounded rationale, confidence,
and exploration priority. The target metric is copied from the locked `GrowthGoal` rather
than accepted from model output.

## Why this boundary

Frontier agent systems increasingly separate the reasoning layer from the execution layer,
use typed tool/structured-output contracts, keep explicit guardrails around side effects,
and invest heavily in traces/evals. GrowthEvo already has unusually strong downstream
controls (causal uplift, safe policy improvement, legal gates, OPE, conformal checks and
locked holdouts), so replacing them with an LLM would reduce reliability rather than improve it.

The implementation therefore borrows the useful agent-era ideas while keeping GrowthEvo's
causal control plane intact:

- **OpenAI-style structured outputs, guardrails and tracing:** model output is schema-constrained;
  the local harness still validates it and records only redacted audit metadata.
- **Anthropic-style brain/hand separation and context engineering:** the model sees a compact,
  high-signal causal context and has no direct action/execution interface.
- **Generator/evaluator pattern:** an optional second model can act as a conservative critic;
  the critic can veto but cannot replace the proposal.
- **Google/AWS-style approval/evaluation posture:** risky execution stays behind deterministic
  controls, while model behavior is introduced through shadow/canary evaluation rather than
  a flag-day cutover.

Useful references:

- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- OpenAI tracing / guardrails: https://openai.github.io/openai-agents-python/tracing/
- Anthropic context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic managed-agent brain/hand separation: https://www.anthropic.com/engineering/managed-agents
- Anthropic long-running generator/evaluator harness: https://www.anthropic.com/engineering/harness-design-long-running-apps
- Google Agent Development Kit: https://google.github.io/adk-docs/
- Amazon Bedrock AgentCore: https://aws.amazon.com/bedrock/agentcore/

## Safety invariants

1. **Original baseline remains available.** `GrowthHypothesisPlanner` is still the default.
2. **Fail closed to baseline.** Provider errors, malformed JSON, low confidence, critic vetoes,
   and circuit-breaker activation return the original deterministic hypothesis.
3. **Hard-stop short circuit.** If the original planner emits `HOLDOUT` or `STOP`, no remote LLM
   call is made.
4. **No executable action fields in the schema.** A model cannot directly choose the channel,
   price/offer, budget, frequency, creative or send time.
5. **No user identifier in model context.** The proposal context deliberately excludes `user_id`.
6. **Raw prompts/responses are not persisted.** The event chain stores only provider/model,
   acceptance reason, confidence, latency, critic metadata and returned/proposed options.
7. **LegalActionGate remains non-learnable.** Consent, fatigue, churn, touch and budget checks
   still run after policy selection.
8. **NO_TREATMENT stays first-class.** The LLM cannot remove holdout/stop semantics.

## Provider-neutral interface

Any provider can implement:

```python
class StructuredLLMClient(Protocol):
    provider_name: str
    model: str

    def generate(self, *, system: str, user: str, schema: Mapping[str, Any]) -> Mapping[str, Any]: ...
```

Built-in optional adapters:

- `OpenAIResponsesClient` — Responses API + strict JSON Schema, `store=False` by default.
- `AnthropicToolClient` — forced tool call using the same locked JSON schema.
- `GeminiStructuredClient` — Google Gen AI JSON-schema structured output.

Provider SDKs are optional extras, so installing/running the original harness does not pull
LLM dependencies:

```bash
pip install -e '.[llm-openai]'
pip install -e '.[llm-anthropic]'
pip install -e '.[llm-gemini]'
# or all three
pip install -e '.[llm]'
```

## OpenAI example

Pin a model identifier that has passed your own evals; do not silently move production traffic
between model snapshots.

```python
from growthevo.llm import GuardedLLMGrowthPlanner, LLMPlannerConfig, OpenAIResponsesClient
from growthevo.runtime.engine import GrowthEvoRuntime

client = OpenAIResponsesClient(
    model="<evaluated-pinned-model-id>",
    reasoning_effort="medium",
)
planner = GuardedLLMGrowthPlanner(
    client,
    config=LLMPlannerConfig(
        shadow_mode=True,
        min_confidence=0.75,
    ),
)
runtime = GrowthEvoRuntime(planner=planner)
```

`shadow_mode=True` means the model runs and is audited, but the original planner's output is
returned. This is the recommended first deployment mode.

## Optional proposer + critic

A stronger configuration can use a second model/provider as a conservative evaluator:

```python
from growthevo.llm import (
    AnthropicToolClient,
    GuardedLLMGrowthPlanner,
    LLMPlannerConfig,
    OpenAIResponsesClient,
)

proposer = OpenAIResponsesClient(model="<evaluated-proposer-snapshot>")
critic = AnthropicToolClient(model="<evaluated-critic-snapshot>")

planner = GuardedLLMGrowthPlanner(
    proposer,
    critic=critic,
    config=LLMPlannerConfig(
        min_confidence=0.75,
        critic_min_confidence=0.70,
        shadow_mode=True,
    ),
)
```

The critic is a **veto-only** component. It cannot replace a proposal with a different objective.
This avoids turning a two-model setup into an uncontrolled multi-agent action loop.

## Context engineering

Only compact causal state is sent to the provider. The model sees:

- natural conversion probability;
- count and maximum of positive channel uplift (not channel choice);
- uplift uncertainty;
- LTV;
- fatigue and churn risk;
- recent touch counts and spend;
- inactivity and lifecycle stage;
- goal horizon/metric/target delta;
- locked constraints;
- the enum of allowed semantic options.

It does **not** see `user_id`, raw event history, raw messages, creative content or execution tools.
This makes the model a semantic classifier/reasoner over causal state rather than a general
operator with a large context and large blast radius.

## Reliability controls

### Local validation

Provider-side structured output is not trusted by itself. GrowthEvo validates:

- exact key set;
- valid `GrowthOption` enum;
- finite `[0, 1]` confidence values;
- bounded rationale length;
- exploration policy configuration.

### Circuit breaker

Repeated provider/schema failures open a local circuit. While it is open, requests bypass the
model and immediately use the original planner. This prevents an external model outage from
becoming a growth-control outage.

### Redacted audit trail

When an LLM planner is injected into `GrowthEvoRuntime`, the existing
`HYPOTHESIS_PLANNED` event gains a `planner_audit` field. No additional event is created, so the
original event-count semantics remain stable. The hash chain therefore records which provider
and model participated without storing raw prompts or responses.

## Recommended production rollout

### Stage 0 — frozen baseline

Keep `main` / the existing locked benchmark evidence unchanged. Record the baseline commit SHA.
Do not reinterpret old locked results as evidence for the LLM-enhanced policy.

### Stage 1 — shadow mode

Run the LLM planner with `shadow_mode=True` and collect:

- proposal agreement with the deterministic planner;
- proposal entropy / option distribution;
- low-confidence and failure rates;
- latency and cost;
- critic veto rate;
- stability across repeated runs and pinned model versions.

No user-facing action changes at this stage.

### Stage 2 — offline policy evaluation

Convert accepted LLM proposals into candidate policy definitions and evaluate them using the
existing GrowthEvo OPE stack. Treat each provider/model/prompt/config combination as a distinct,
versioned candidate. Do not select configurations using the final holdout.

### Stage 3 — validation winner freeze

Use a predeclared candidate grid, select the winner on validation, freeze model snapshot +
planner config + schema + prompt version, then evaluate once on an independent final holdout.
This mirrors GrowthEvo's existing locked-evidence philosophy.

### Stage 4 — canary / rainbow deployment

Start with a small cohort and keep the deterministic planner available as immediate fallback.
Roll traffic gradually while watching causal value, ROI, support coverage, fatigue, churn risk,
provider failure rate, latency and drift in semantic option distribution.

### Stage 5 — optional online learning

Only after stable causal evidence should LLM proposal metadata become a feature for learned
policy improvement. The LLM itself should not self-modify legal gates or verifier thresholds.

## What not to do

- Do not give the LLM a `send_push`, `issue_coupon` or `set_budget` tool in the same control loop.
- Do not let natural-language output directly mutate `GrowthConstraints`.
- Do not use an LLM-as-judge result as a replacement for causal OPE or final holdout evidence.
- Do not feed raw PII/event history just because a large context window exists.
- Do not auto-upgrade model aliases without a replay/eval gate.
- Do not use multi-agent orchestration merely for architectural fashion; add specialists only
  when an eval demonstrates a measurable gain.

The intended role of the LLM is therefore **semantic proposal and bounded reasoning**, while
GrowthEvo remains the causal, safety, evaluation and execution authority.
