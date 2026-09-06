# Causal Option Evidence Layer

GrowthEvo's LLM benchmark is intentionally split into two independent planes:

1. the **proposal plane** chooses a semantic `GrowthOption` from planner-visible state;
2. the **evidence plane** supplies hidden causal value labels used only by the evaluator.

The two planes must not share hidden outcome labels. A model can observe `CausalBelief`, `GrowthGoal`, and constraints, but it cannot observe the per-option causal value, standard error, support coverage, or effective sample ratio used to score its decision.

## Evidence tiers

`EvidenceTier` makes evidence strength explicit rather than leaving it in prose:

| Tier | Source | Promotion use |
|---|---|---|
| A | randomized experiment | eligible, subject to support/safety gates |
| B | pre-registered DR/OPE | eligible, subject to support/safety gates |
| C | model-based / simulator | diagnostic only |
| D | heuristic / proxy | diagnostic only |

A diagnostic benchmark can retain Tier C/D evidence for research. Its artifact is forcibly marked `promotion_eligible=false`, even if the diagnostic lower confidence bound is positive.

## Context binding

Every `EvidenceCaseSpec` has a stable context fingerprint over:

- `case_id`;
- causal belief;
- growth goal and constraints;
- deterministic baseline option;
- case weight.

A `CausalEvidenceBundle` must carry exactly that fingerprint. Reusing a causal label after the user state, goal, baseline policy, or case weight changes is rejected before model evaluation.

This prevents a subtle class of benchmark bugs where stale evidence is attached to a newly transformed state while retaining the same logical case identifier.

## Estimand discipline

Each bundle declares one `estimand`. All option estimates inside a bundle must be interpreted on the same numerical scale.

Examples:

- `incremental_value_vs_no_treatment`;
- `30d_incremental_ltv_vs_no_treatment`;
- `frozen_policy_value`.

GrowthEvo deliberately does **not** infer semantic equivalence between a public dataset's treatment arm and a semantic option such as `RETAIN` or `UPSELL`. Such a mapping must be established by the upstream experiment protocol. This avoids turning convenient proxy labels into causal claims.

## Existing adapters

### Randomized targeting

`randomized_targeting_estimate(...)` converts a frozen `TargetingInferenceResult` into Tier-A evidence. The value and standard error come from the randomized policy-minus-treat-none contrast. Support coverage and effective sample ratio remain explicit inputs because they belong to the evidence protocol rather than the point estimate alone.

### Pre-registered OPE

`preregistered_ope_estimate(...)` converts a selected `OPEEstimate` field into Tier-B evidence. Supported estimators include DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, cross-fitted beta-IPS, and Meta-BLUE. The adapter carries the OPE support coverage and effective-sample ratio into the LLM benchmark gates.

### Frozen external result

`fixed_reference_estimate(...)` is the narrow escape hatch for a precomputed external causal result. The caller must still declare the tier, source identifier, protocol fingerprint, uncertainty, and support diagnostics.

## Evidence producer interface

```python
class CausalOptionEvidenceProducer(Protocol):
    name: str
    version: str

    def produce(self, spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
        ...
```

`StaticCausalOptionEvidenceProducer` serves already-frozen bundles and verifies context binding. A production integration can replace it with an internal experiment service, artifact store, or warehouse-backed implementation without changing the LLM benchmark protocol.

## Locked shadow runner

`run_locked_shadow_benchmark(...)` composes the evidence plane with the existing LLM policy protocol:

```text
pre-registered candidates
        |
        v
validation evidence producer
        |
        +--> hidden Tier A/B option labels
        |
        v
all candidates run in shadow on validation
        |
        v
conservative LCB selection
        |
        v
freeze one winner
        |
        v
holdout evidence producer
        |
        v
ONLY the frozen winner is invoked on holdout
        |
        v
one-shot holdout reveal
        |
        v
promotion gate
```

The final artifact binds:

- experiment plan fingerprint;
- model + harness candidate identity;
- validation evidence fingerprint;
- holdout evidence fingerprint;
- combined evidence manifest fingerprint;
- evidence producer name/version;
- code commit SHA.

The intent is to make the statement "model X created incremental value" traceable to the exact model snapshot, prompt/schema contract, causal evidence, split, support diagnostics, and code revision that produced the claim.

## Production posture

Recommended order:

```text
contract tests
-> adversarial tests
-> production shadow logging
-> frozen evidence extraction
-> locked validation selection
-> one-shot causal holdout
-> tiny randomized canary
-> OPE + online guardrails
-> gradual expansion / rollback
```

Synthetic and model-based evidence remains useful for pre-screening, debugging, and power analysis. It must not be relabeled as real-world promotion evidence.
