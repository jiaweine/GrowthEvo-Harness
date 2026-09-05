# GrowthEvo LLM Benchmark v1

## Purpose

The LLM benchmark is deliberately not a generic chatbot benchmark. It answers a
narrower production question:

> Does a fixed model + prompt/schema + safety configuration produce semantic
> growth choices that create more **causal incremental value** than the original
> deterministic planner, while preserving support, holdout and safety gates?

A model is not promoted because it sounds better, agrees with an expert more
often, or wins an LLM-as-a-judge score. Those are useful diagnostics, not causal
deployment evidence.

## Two separate evidence layers

### Layer A — agent/harness quality gates

Use ordinary evaluation to measure:

- structured-output validity;
- provider availability and fallback rate;
- latency and cost;
- hard-stop preservation;
- confidence calibration;
- prompt-injection / malformed-context robustness;
- deterministic legal/policy boundary preservation.

Failing this layer blocks promotion. Passing it does **not** prove incremental
business value.

### Layer B — hidden causal outcome evidence

Each benchmark case contains two surfaces:

1. **Planner-visible state:** `CausalBelief` + `GrowthGoal`.
2. **Evaluator-only labels:** `CausalOptionEvidence` for semantic options.

The option evidence is never sent to the LLM. It should be generated upstream
from pre-registered randomized experiments, DR/OPE, or another accepted causal
estimator and should carry:

- value estimate;
- standard error;
- feasibility;
- support coverage;
- effective-sample ratio.

This separation avoids turning the holdout answer key into prompt context.

## Candidate identity

Every candidate is frozen as:

```text
candidate name
provider
model snapshot
prompt/schema/safety contract fingerprint
optional critic provider + snapshot
```

Changing the system prompt, JSON schema, confidence threshold, critic posture,
or model snapshot creates a new candidate. Do not silently mutate a candidate
under the same name.

## Shadow-first collection

Recommended production sequence:

```text
original runtime executes normally
        |
        +--> LLM proposal runs in shadow
                 |
                 +--> proposal + redacted trace captured

no side effect is delegated to the LLM
```

`collect_planner_decisions()` understands the proposal-plane trace contract. If
`reason == "shadow_only"`, it scores the LLM proposal as the counterfactual
candidate choice while retaining the original planner's option as
`runtime_option`.

This lets the benchmark observe live-context model behavior without changing a
single customer action.

## Conservative causal scoring

For option `a` in case `i`, the default hidden score is:

```text
L_i(a) = value_i(a) - z * standard_error_i(a)
```

Only evidence that is feasible and passes the pre-registered support/ESS gates
is eligible.

If a candidate chooses an unsupported or infeasible option, the evaluator:

1. records an evidence violation;
2. scores the decision using the deterministic baseline fallback;
3. lets the evidence gate disqualify the candidate.

The benchmark therefore does not reward an unsupported large point estimate.

For every decision:

```text
incremental improvement = L_i(candidate) - L_i(original baseline)
regret = max_a L_i(a) - L_i(candidate)
```

Candidate selection uses the lower confidence bound of mean incremental
improvement on validation, with tie-breaks on regret, optimal rate, fallback,
latency and stable candidate name.

## Locked selection

`LockedLLMPolicyProtocol` intentionally follows the same governance pattern as
GrowthEvo's other locked benchmarks:

```text
pre-register candidates + gates
          |
validation cases + all candidate decisions
          |
select exactly one winner
          |
freeze winner
          |
independent holdout cases
          |
score only the frozen winner once
```

The holdout API rejects manifests containing losing candidates. Validation and
holdout case identifiers must be disjoint. A protocol object refuses a second
holdout reveal.

This makes casual "let's also check model B on test" behavior harder by API
design rather than relying on documentation alone.

## Promotion rule

The locked artifact reports `promotion_eligible=True` only when:

- the selected candidate still passes all holdout gates; and
- the holdout lower confidence bound of incremental improvement is strictly
  positive versus the original deterministic planner.

This flag means **eligible for the next controlled rollout stage**, not
"automatically deploy globally".

Recommended stages:

```text
1. offline contract tests
2. adversarial/safety eval suite
3. production shadow mode
4. locked validation selection
5. independent causal holdout
6. tiny canary / randomized rollout
7. OPE + online monitoring
8. gradual expansion with rollback
```

## What should supply CausalOptionEvidence?

### Preferred: randomized option-level evidence

When possible, derive option values from experiments where semantic objectives
(or their downstream policy bundles) have randomized support.

### Acceptable: pre-registered OPE / DR evidence

Use the existing GrowthEvo OPE stack when logged behavior contains adequate
support. Preserve estimator, propensity, ESS and support provenance in the
upstream evidence artifact.

### Diagnostic only: simulator or synthetic oracle

Synthetic and model-based values are useful for CI and failure injection but
must not be presented as real-world causal promotion evidence.

## Example

```python
from growthevo.bench import (
    CausalOptionEvidence,
    LLMBenchmarkCase,
    LLMExperimentPlan,
    LLMPolicyCandidate,
    LockedLLMPolicyProtocol,
    collect_planner_decisions,
)

candidate = LLMPolicyCandidate(
    name="provider-model-contract-v1",
    provider="provider",
    model="pinned-model-snapshot",
    contract_fingerprint="<fingerprint>",
)

plan = LLMExperimentPlan(
    benchmark="growth-semantic-policy",
    dataset="locked-option-evidence-v1",
    dataset_source="artifact:<fingerprint>",
    candidates=(candidate,),
    max_fallback_rate=0.05,
    min_support_coverage=0.95,
    min_effective_sample_ratio=0.05,
)

# `validation_cases` contain hidden CausalOptionEvidence. The planner receives
# only case.belief and case.goal.
validation_decisions = collect_planner_decisions(
    candidate_name=candidate.name,
    planner=shadow_planner,
    cases=validation_cases,
    trials_per_case=plan.trials_per_case,
)

protocol = LockedLLMPolicyProtocol(plan)
protocol.tune(validation_cases, validation_decisions)

# Generate holdout decisions only for protocol.selected_candidate.
holdout = protocol.evaluate_once(holdout_cases, frozen_winner_decisions)
artifact = protocol.artifact(holdout, commit_sha="<code-sha>")
```

## Metrics to watch

Headline:

- holdout conservative incremental LCB vs original planner;
- mean causal regret;
- evidence violation rate;
- hard-stop violation rate;
- fallback rate;
- decision coverage.

Secondary:

- optimal-option rate;
- confidence Brier score;
- mean / p95 model latency;
- provider/model/contract identity.

Do not collapse all of these into a single opaque "agent score". Safety and
support are gates, not weights that can be traded away for a little more value.

## Design principle

The LLM is a replaceable semantic policy proposal model. GrowthEvo remains the
causal control and evidence system.

That asymmetry is intentional: model generations may improve quickly, but the
interfaces for causal value, support, legal constraints, holdout governance and
auditability should remain stable.
