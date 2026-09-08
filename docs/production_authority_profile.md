# Strict production authority profile

Phase 21 closes the production control-plane loop for GrowthEvo. It adds a strict evidence-contract policy, typed online evidence emitters, and a deployable authority profile that plugs directly into the Phase-20 governed high-power controller.

The design goal is simple:

> No production traffic increase is authorized merely because one statistical test, one signature, or one generic `passed=true` field exists.

Every transition is bound to the exact candidate, plan, source commit, evidence implementation and current ledger state.

## Exact evidence contracts instead of independent allowlists

Phase 14 intentionally introduced independent allowlists for evidence type, protocol and producer. That is useful as a general governance primitive, but it is not the strongest representation when one authority accepts multiple alternative implementations.

For example, supply-chain authority may accept either:

- direct Phase-18 `slsa_build_provenance.v1`; or
- delegated Phase-19 `slsa_vsa_delegated_verification.v1`.

Three independent allowlists can theoretically accept a recombination such as:

`direct evidence type + delegated protocol + unrelated allowed producer`

Phase 21 therefore introduces `EvidenceContract`:

`(evidence_type, protocol_fingerprint, producer)`

A `StrictAuthorityRequirement` accepts one or more **complete tuples**. Matching is exact. Alternative tuples are OR alternatives; fields from different alternatives cannot be recombined.

This behavior receives a separate v2 policy identity rather than silently changing the Phase-14 v1 semantics.

## Strict policy schema

`StrictPromotionEvidencePolicy` contains transition-specific `StrictAuthorityRequirement` objects, plus the existing veto and sticky-block concepts.

Its fingerprint is schema-versioned as:

`growthevo.strict-promotion-evidence-policy.v2`

A policy change to any evidence type, protocol, producer, minimum epoch, authority composition, veto, sticky block or supply-chain alternative changes the fingerprint.

`StrictPromotionManifestGate` uses the existing append-only `PromotionEvidenceLedger` and `PromotionEvidenceManifest`, but evaluates evidence through exact contracts.

The gate has the same control-plane interface consumed by the Phase-20 governed controller:

- `ledger`;
- `policy`;
- `expected_plan_fingerprint`;
- `fingerprint`;
- `evaluate(transition)`.

This keeps the governed controller independent from one policy implementation while retaining exact subject/plan binding.

## Default production authority composition

`ProductionAuthorityProfile.compile_policy(...)` creates this default composition.

### Enter canary

All are required:

1. `offline_causal`
2. `integrity`
3. `supply_chain`

Supply-chain verification is intentionally required **before the first experimental exposure**. A release artifact should not be canaried first and verified only before final promotion.

### Advance stage

All are required:

1. `integrity`
2. `maturity`
3. `online_safety`
4. `supply_chain`

### Final promotion

All are required:

1. `offline_causal`
2. `integrity`
3. `maturity`
4. `online_safety`
5. `primary_success`
6. `supply_chain`

`integrity` and `online_safety` are veto authorities. `integrity` is sticky by default: once the same promotion subject has an integrity block, a later success statement cannot silently clear it under the same strict profile.

Products can construct a different strict policy explicitly, but changing the production composition changes the policy fingerprint.

## Supply-chain OR alternatives

`ProductionAuthorityProfile` accepts one or more exact supply-chain contracts.

A deployment can therefore trust direct SLSA verification and/or a delegated VSA verifier without giving either one wildcard authority.

A direct SLSA evidence object and a VSA evidence object normally have different:

- evidence types;
- protocol fingerprints;
- producers.

Each complete triple is frozen separately.

## Typed online-safety evidence

`emit_online_safety_evidence(...)` converts the current **aggregate** high-power monitor state into Phase-14 evidence only when the normal safety gates are already established.

The emitter independently verifies:

- monitor is running or already promoted;
- current-stage matured-observation minimum;
- every relative non-inferiority e-value passes the ramp threshold;
- absolute safety e-values pass where configured;
- harm/violation maximum e-values have not crossed rollback thresholds;
- deterministic cumulative challenger cost remains within the pre-registered cap;
- requested authority scope matches the current rollout stage.

It emits:

- authority id `online_safety`;
- evidence type `online_safety.v1`;
- a protocol fingerprint bound to the exact high-power plan;
- producer identity from `OnlineAuthorityEvidenceSpec`;
- logical evidence epoch equal to the aggregate observation count;
- an artifact fingerprint over plan, stage, traffic, counts, cumulative cost and metric evidence.

No raw analysis-unit id or raw outcome is stored in the authority statement.

The emitter cannot be called at stage zero before safety is established, cannot claim final-promotion safety from a non-final stage, and cannot claim stage-advance safety after reaching the final stage.

## Typed primary-success evidence

`emit_primary_success_evidence(...)` emits `primary_success.v1` only when:

- the monitor is at the final rollout stage;
- a planned group-sequential look exists;
- the current/latest planned look is successful;
- the primary monitor's current success state is true.

Its artifact fingerprint binds the high-power plan, final stage, aggregate observation count and complete group-sequential evidence record.

It does not assert safety. Safety and primary success remain independent authorities so a strong primary metric cannot compensate for a failed guardrail.

## Reference-evidence profile construction

`ProductionAuthorityProfile.from_reference_evidence(...)` is a convenience for freezing the exact contracts already produced by reviewed upstream implementations.

The function extracts only type/protocol/producer identities. It does **not** treat a reference artifact fingerprint as a wildcard proof for future subjects.

Expected reference authority ids are fixed:

- `offline_causal`
- `integrity`
- `maturity`
- `supply_chain`

Online contracts are generated from the exact high-power canary plan and frozen producer identities.

## End-to-end lifecycle

The production path is now:

1. locked offline causal evaluation qualifies a candidate;
2. exact `PromotionSubject` binds experiment, candidate, artifact, plan and commit;
3. integrity/maturity services append provenance-bound authority statements;
4. direct SLSA or delegated VSA appends strict supply-chain authority;
5. strict profile authorizes `ENTER_CANARY`;
6. stable randomized routing begins;
7. anytime-valid safety monitoring accumulates matured outcomes;
8. typed online-safety evidence is emitted after the statistical safety gate passes;
9. strict profile authorizes `ADVANCE_STAGE`;
10. final pre-registered group-sequential look evaluates primary success;
11. typed final safety + primary-success evidence enter the ledger;
12. strict final manifest requires offline causal + integrity + maturity + safety + success + supply chain;
13. only then does the governed controller replace the champion.

If final statistical analysis completes before governance evidence arrives, no extra outcomes are accepted merely to trigger the control plane. Authority can be re-evaluated against the changed ledger with the observation count unchanged.

Rollback remains unconditional throughout.

## Threats covered

The Phase-21 tests specifically attack:

- cross-product evidence-contract forgery;
- direct/delegated supply-chain alternative handling;
- online-safety evidence before safety exists;
- primary-success evidence before the final planned success;
- incorrect plan binding;
- final authority without current transition scope;
- governance delays that could otherwise create extra peeking.

The full lifecycle test exercises strict external contracts, governed canary entry, delayed ramp authority, typed online evidence emission, final planned success and authority-only promotion.

## What remains external by design

The following are deployment inputs, not missing framework code:

- real OpenAI/Anthropic/Gemini credentials and pinned model snapshots;
- the product's real semantic `GrowthOption` Tier-A randomized evidence or explicitly mapped Tier-B OPE evidence;
- product-specific consent/legal policy and budgets;
- trusted integrity and maturity producers;
- trusted SLSA builders or VSA verifiers;
- production KMS/HSM/Sigstore identities;
- product-specific rollout stages, metric bounds and safety margins.

GrowthEvo deliberately cannot invent these facts. A framework claiming a real model winner or production authorization without them would be fabricating evidence.

## Completion boundary

With Phase 21, the repository contains a closed engineering path from guarded semantic LLM proposals through locked causal evaluation, staged sequential online experimentation, supply-chain verification and exact authority-gated production promotion.

Future work can improve power, support more trusted builders, or benchmark new model snapshots, but those are extensions or empirical runs. They are not required to connect the existing control plane end to end.
