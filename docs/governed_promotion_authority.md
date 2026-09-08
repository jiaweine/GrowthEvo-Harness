# Governed online promotion authority

Phase 20 wires the Phase-14 promotion evidence manifest into the high-power online canary as an **opt-in production control plane**. The original `HighPowerOnlinePromotionController` is unchanged; existing users retain the previous statistical behavior unless they explicitly construct the governed controller.

## Core rule

GrowthEvo now separates two questions before increasing production exposure:

1. **Does the online experiment statistically justify the transition?**
2. **Do all independent authorities currently authorize the transition for this exact candidate, plan and commit?**

Both must be true.

The governed path applies manifest authorization to exactly three transitions:

- `ENTER_CANARY` before the first randomized exposure;
- `ADVANCE_STAGE` before increasing the traffic fraction;
- `FINAL_PROMOTION` before replacing the champion.

Rollback is deliberately not gated. A harm signal, absolute guardrail violation or deterministic cost kill switch can always stop exposure immediately.

## Exact controller/subject binding

`GovernedHighPowerOnlinePromotionController` rejects construction unless the Phase-14 `PromotionSubject` exactly matches:

- experiment id;
- candidate name;
- candidate contract fingerprint;
- offline promotion artifact fingerprint;
- high-power canary plan fingerprint;
- candidate source commit SHA.

This prevents a valid authority ledger for one model, plan or source revision from authorizing another controller instance.

The governance gate also freezes the exact `PromotionEvidencePolicy` fingerprint and exact high-power plan fingerprint.

## Fresh manifest before transition

`PromotionManifestGate` does not cache a long-lived authorization token. It builds a manifest at the current ledger head and evaluates that exact head every time a transition needs authority.

The resulting `GovernanceAuthorizationRecord` binds:

- transition;
- authorized / blocked decision;
- exact reasons;
- manifest fingerprint;
- promotion policy fingerprint;
- subject fingerprint;
- evidence ledger head;
- ledger event count.

An invalid evidence-ledger hash chain always returns a blocked authorization record.

## Enter-canary gate

The governed monitor remains `REGISTERED` until `ENTER_CANARY` is authorized.

While registered:

- no routing/exposure is allowed;
- missing or blocked authority returns `HOLD`;
- the champion remains unchanged.

When the necessary authority evidence arrives, the caller may retry `start()` or re-evaluate the pending authority transition. No treatment outcome is needed to unlock the control-plane decision.

## Stage-advance gate

A stage is eligible for authority evaluation only after the normal statistical safety requirements pass:

- current-stage matured-observation minimum;
- relative non-inferiority evidence;
- absolute safety evidence;
- no anytime-valid harm trigger;
- no deterministic cumulative-cost trip.

If those statistical conditions are met but the manifest is not authorized, the stage remains unchanged and the monitor returns `HOLD` with a `promotion_authority_blocked:advance_stage` reason.

When new authority evidence arrives, `reevaluate_authority()` can advance the stage **without ingesting another outcome**. This is important: governance latency must not become a reason to keep sampling a trial merely to trigger the control plane again.

## Final-promotion gate and no extra peeking

The final stage keeps the Phase-6 high-power rule: primary success is evaluated only at pre-registered group-sequential looks, with the existing safety layer evaluated separately.

If a planned final look establishes primary success and current safety but final authority is missing, the monitor records a pending `FINAL_PROMOTION` transition and returns `HOLD`.

When that planned analysis has no future look, the governed monitor refuses additional outcomes while final authority is pending. The only valid next operation is `reevaluate_authority()` after the ledger changes.

This prevents a subtle governance bug:

> a slow approval or supply-chain verification service must not accidentally create extra statistical peeks or additional experimental exposure after the final analysis was already complete.

Once final authority is present, `reevaluate_authority()` promotes without changing the observation count.

## Rollback remains unconditional

Governance cannot veto a rollback.

The code checks normal harm/cost rollback conditions before any pending stage/final authorization is released. If the safety state has become invalid, the pending authority transition is discarded and the canary moves to `ROLLED_BACK`.

This preserves the safety invariant that external control-plane unavailability cannot keep a harmful challenger running.

## Audit chain

The governed controller extends the existing append-only promotion audit chain with aggregate control-plane events:

- `promotion_governance_registered`;
- `promotion_authority_evaluated`;
- existing `canary_started` / stage advance / rollback / promotion events.

Authority audit payloads contain fingerprints, transition names and reason codes. They do not contain raw analysis-unit ids, raw outcomes, prompts or model responses.

The original audit hash-chain verification remains authoritative.

## Relationship to direct SLSA and VSA

The manifest gate does not special-case supply-chain evidence. The Phase-14 policy must explicitly allow the evidence producer and protocol it trusts.

A deployment may use direct Phase-18 `slsa_build_provenance.v1` evidence or Phase-19 `slsa_vsa_delegated_verification.v1` evidence. They are not silently interchangeable: the policy fingerprint changes when accepted types, protocols or producers change.

Likewise, a valid supply-chain proof does not replace offline causal qualification, online safety or final success authority.

## Opt-in compatibility

No existing default runtime/controller path is modified.

- original deterministic planner remains unchanged;
- original numeric RL and legal action gates remain unchanged;
- original `OnlinePromotionController` remains unchanged;
- original `HighPowerOnlinePromotionController` remains unchanged.

Only callers that construct `GovernedHighPowerOnlinePromotionController` activate manifest-gated transitions.

## Tests

`tests/test_promotion_governance.py` covers:

- no first exposure without `ENTER_CANARY` authority;
- statistical stage eligibility held until `ADVANCE_STAGE` authority arrives;
- authority-only re-evaluation advances without a new outcome;
- final planned success held until `FINAL_PROMOTION` authority arrives;
- no extra outcomes after the final planned analysis while authority is pending;
- final promotion after authority arrival without additional peeking;
- immediate safety rollback independent of governance;
- cross-subject / wrong-plan rejection;
- aggregate-only governance audit records.

## Deployment recommendation

Production should run the governed controller with a frozen Phase-14 policy whose authorities are independently produced. Keep evidence acquisition separate from the gate itself. The gate should be able to read and evaluate evidence, but should not be able to manufacture the evidence that authorizes its own transition.
