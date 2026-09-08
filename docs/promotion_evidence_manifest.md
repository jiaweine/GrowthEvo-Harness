# Promotion Evidence Manifest / Authority Composition

GrowthEvo separates **producing evidence** from **granting authority**.

A causal estimate, SRM check, maturity seal, safety monitor, or sequential test may be individually valid and still be insufficient to authorize a production transition. This module provides a read-only control-plane contract that composes independent authority statements without replacing the existing runtime or online controller.

## Design goal

The promotion path is modeled as a set of explicit transitions:

1. `enter_canary`
2. `advance_stage`
3. `final_promotion`

Each transition has its own frozen list of required authorities. A proof scoped to an earlier transition cannot be replayed as final-promotion authority.

The default posture is fail closed:

- missing authority -> blocked;
- blocked authority -> blocked;
- stale authority -> blocked;
- wrong evidence type -> blocked;
- wrong protocol fingerprint -> blocked;
- unapproved producer -> blocked;
- wrong subject -> blocked;
- stale ledger head -> blocked;
- caller-modified evidence view -> blocked;
- invalid audit chain -> blocked.

## Promotion subject

`PromotionSubject` freezes the exact object whose authority is being evaluated:

- experiment id;
- candidate name;
- candidate contract fingerprint;
- offline promotion artifact fingerprint;
- online plan fingerprint;
- source commit SHA.

Every authority statement carries the subject fingerprint. Evidence for another model snapshot, another canary plan, another promotion artifact, or another source commit is rejected before it enters the ledger.

This prevents cross-candidate and cross-experiment evidence laundering.

## Authority evidence

`AuthorityEvidence` is a provenance statement, not raw experiment data. It binds:

- `authority_id`;
- evidence type;
- trusted producer identity;
- subject fingerprint;
- protocol fingerprint;
- artifact fingerprint;
- verdict (`satisfied` or `blocked`);
- authorized transitions;
- monotone logical evidence epoch;
- optional upstream chain-head fingerprint;
- optional details fingerprint.

The ledger therefore does not need raw user ids, raw outcomes, prompts, or model responses.

### Logical evidence epoch

Freshness is represented by `evidence_epoch`, not wall-clock timestamps.

For one authority and one promotion subject:

- a lower epoch than the current one is rejected as stale;
- an exact replay at the same epoch is idempotent;
- a different statement at the same epoch is rejected as a conflict;
- a higher epoch becomes the latest statement.

This makes freshness deterministic and auditable even when evidence arrives asynchronously.

## Policy as code

`PromotionEvidencePolicy` defines transition-specific requirements.

Each `AuthorityRequirement` is an exact allowlist over:

- acceptable evidence types;
- acceptable protocol fingerprints;
- acceptable producers;
- minimum logical evidence epoch.

This is intentionally stricter than accepting a generic `passed=true` field. A new statistical implementation, producer, or protocol version cannot silently inherit authority from an older allowlist.

Changing the policy changes its fingerprint.

## Veto authorities

Some authorities are safety vetoes even when they are not positive requirements for a particular transition.

`veto_authorities` blocks a transition when its latest statement is `blocked`.

Production policies should normally also list important veto authorities as explicit transition requirements whenever producer/protocol allowlisting must be enforced for that transition.

## Sticky blocks

`sticky_block_authorities` are stronger than ordinary vetoes.

Once a sticky authority has emitted `blocked` for a promotion subject, a later `satisfied` statement cannot clear the block under the same policy and subject identity.

This is useful for integrity failures where simply rerunning the same analysis is not sufficient remediation. Recovery requires a deliberately new subject identity (for example, a new experiment or plan) or an explicitly changed and re-fingerprinted policy.

Sticky authorities must also be veto authorities.

## Append-only evidence ledger

`PromotionEvidenceLedger` stores the authority statements in an append-only SHA-256 hash chain.

Each event binds:

- sequence number;
- promotion-subject fingerprint;
- authority-evidence fingerprint;
- previous event hash.

The ledger can independently verify its own chain before building or evaluating a manifest.

The chain is tamper-evident, but it is **not** a digital-signature system. Producer authenticity remains the responsibility of the trusted upstream verification boundary named by policy.

## Canonical latest view

A manifest includes the latest evidence statement for every authority.

The evaluator does not trust that caller-provided list. It reconstructs the canonical latest view from the verified ledger and requires the manifest evidence fingerprints to match it exactly.

Therefore a caller cannot create an apparently valid manifest by omitting a blocking authority from `latest_evidence` while keeping the same ledger head.

## Manifest

`PromotionEvidenceManifest` freezes:

- promotion subject;
- requested transition;
- policy fingerprint;
- exact ledger head;
- exact ledger event count;
- canonical latest evidence view.

The manifest itself receives a 256-bit BLAKE2 fingerprint.

Once the ledger advances, an older manifest becomes stale and evaluation fails closed.

## Evaluation

`PromotionEvidenceLedger.evaluate()` verifies, in order:

1. ledger hash-chain integrity;
2. policy fingerprint;
3. subject identity;
4. ledger head and event count;
5. canonical evidence-view equality;
6. sticky blocks;
7. veto authorities;
8. each transition requirement:
   - present;
   - satisfied;
   - correctly scoped;
   - fresh enough;
   - approved evidence type;
   - approved protocol;
   - approved producer.

Only an empty failure set yields `authorized`.

`ManifestEvaluation` records selected evidence fingerprints and the exact manifest/subject/ledger identities used by the decision.

## Example authority composition

A production policy might require:

### Enter canary

- offline causal promotion eligibility;
- experiment integrity / assignment contract.

### Advance stage

- current integrity evidence;
- online safety / guardrail authority.

### Final promotion

- offline causal qualification;
- integrity authority;
- outcome maturity/censoring authority;
- randomization-unit/cluster authority where applicable;
- online safety authority;
- primary-success authority.

This module does not hard-code those names. The policy owns the composition so product-specific requirements stay explicit and fingerprinted.

## Relationship to the existing GrowthEvo stack

The module intentionally does **not**:

- choose growth actions;
- call an LLM;
- alter numeric RL policy;
- bypass legal-action gates;
- change canary routing;
- update e-processes;
- perform group-sequential inference;
- decide SRM itself;
- decide censoring itself;
- aggregate repeated events;
- mutate champion state;
- ramp traffic;
- merge code or deploy anything.

Instead, those independent components may produce provenance-bound artifacts whose fingerprints are admitted by policy.

The authority layer answers one narrower question:

> Given this exact candidate, experiment, plan, commit, ledger state, and promotion policy, are all required independent authorities currently satisfied for this transition?

## Security boundary

The current reference implementation provides deterministic hashing, allowlisting, freshness, scope control, sticky veto semantics, and tamper-evident chaining.

It does not provide cryptographic producer signatures, hardware attestation, remote transparency logs, or identity federation. Those can be layered on later by binding signature/transparency-log fingerprints into `artifact_fingerprint`, `source_chain_head`, or a future signed-attestation schema.

A future signature implementation must receive a new protocol/schema identity rather than silently changing the semantics of v1.

## Tests

`tests/test_promotion_manifest.py` covers:

- subject identity binding;
- cross-subject replay rejection;
- idempotent exact replay;
- stale and same-epoch-conflicting evidence;
- fully green final authorization;
- missing authorities;
- ordinary vetoes;
- sticky vetoes;
- transition-scope escalation attempts;
- minimum evidence epoch;
- type/protocol/producer allowlists;
- stale manifests after ledger advancement;
- forged manifest evidence subsets;
- policy and subject mismatch;
- audit-chain tampering;
- policy fingerprint sensitivity.

## Deployment posture

Phase 14 is a read-only authority-composition plane. It is deliberately not wired into the current `OnlinePromotionController` as an automatic production prerequisite in the same change.

That separation avoids self-authorizing a new governance layer. A later integration should require a separately reviewed policy, explicit trusted producers, and exact manifest verification before granting controller authority.
