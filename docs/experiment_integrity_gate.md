# Anytime-valid experiment integrity gate

GrowthEvo's causal promotion logic assumes the randomized assignment stream and the analyzed outcome population are trustworthy. A statistically significant treatment effect is not meaningful when assignment, exposure, telemetry, or outcome maturation has corrupted the intended treatment/control ratio.

This layer makes experiment integrity an independent, non-tradeable authority. It is optional and does not modify the existing `OnlinePromotionController` or `HighPowerOnlinePromotionController`; the integrity-aware controllers wrap them by composition.

## Why SRM must be separate from treatment effects

Sample Ratio Mismatch (SRM) means the observed treatment/control composition is incompatible with the preregistered randomization probability. Mature experimentation platforms treat unexplained SRM as a trust failure rather than another product metric. The effect estimate does not get to compensate for it.

Operational references include Microsoft ExP's SRM diagnostics and PlayFab experimentation guidance: assignment/execution/logging/analysis bugs can create SRM, and an experiment with unexplained SRM should not be interpreted as trustworthy.

GrowthEvo therefore evaluates integrity before allowing a matured observation to mutate business-effect evidence.

## Two independent integrity streams

The gate keeps two assignment-ratio processes.

### Enrollment stream

Every admitted canary analysis unit is registered once with its randomized arm. This stream answers:

> Does the population that entered the experiment still resemble the planned randomization split?

It catches routing, assignment, admission, and early logging corruption.

### Matured-analysis-population stream

A unit may enter this stream only after it was registered in enrollment. This stream answers:

> Among the units whose outcomes actually became analyzable, is the arm composition still compatible with the planned randomization split?

This can expose treatment-dependent telemetry loss, differential maturity, outcome ingestion bugs, or other post-assignment selection.

A matured-population SRM alarm does **not** identify or repair the missing-data mechanism. It blocks causal interpretation. Fixing informative missingness requires a separately preregistered estimand and estimator such as a validated censoring/observation model, IPCW, survival analysis, or targeted-learning procedure.

## Anytime-valid Beta-mixture assignment e-process

For arm indicator

`A_t ~ Bernoulli(p0)`

under the assignment null, let `S_n` be the number of challenger assignments after `n` units. With a frozen `Beta(a,b)` mixing distribution over alternative assignment probabilities, GrowthEvo computes

`E_n = B(a + S_n, b + n - S_n) / B(a,b) / [p0^S_n (1-p0)^(n-S_n)]`.

Under the null this likelihood-ratio mixture is a non-negative martingale. Therefore it can be inspected continuously without converting repeated peeking into an uncontrolled sequence of fixed-horizon SRM tests.

The alternative is two-sided because the Beta mixing distribution covers probabilities below and above `p0`. The implementation uses `lgamma` and log likelihoods for numerical stability and adds no statistics dependency to the baseline package.

The default prior is Jeffreys-like `Beta(0.5, 0.5)`. Any change to prior parameters or alpha allocation changes `ExperimentIntegritySpec.fingerprint`.

## Alpha allocation

`ExperimentIntegritySpec` preregisters:

- a family integrity alpha;
- enrollment-stream alpha;
- matured-population-stream alpha;
- minimum observations before either stream may trip;
- Beta-mixture prior parameters.

The two stream alphas must sum to no more than the family alpha. Each stream uses threshold `1 / alpha_stream`.

A minimum observation threshold is a conservative operational guard against noisy very-small-sample alarms. Crossings before that minimum are not retrospectively used as authority. Once an eligible stream trips, the gate is sticky `BLOCKED` for that experiment instance.

## Atomic ordering

For an integrity-aware online controller, one matured record follows this order:

1. verify that the unit has a registered enrollment ticket;
2. verify stage, arm, traffic fraction, and propensity against that frozen ticket;
3. update the matured-population integrity stream;
4. if integrity blocks, return effective rollback **before** product metric counters, e-processes, CUPED moments, or group-sequential evidence mutate;
5. only when integrity remains clear, pass the observation to the original controller.

This makes the integrity-triggering record atomic with respect to causal evidence. For example, if the eighth matured record trips SRM, the original online statistic remains at seven observations.

## Route preview versus enrollment

The ordinary integrity wrapper distinguishes `route()` from `enroll()`:

- `route()` previews the stable deterministic assignment and does not change integrity state;
- `enroll()` records the admitted analysis unit exactly once in the enrollment integrity stream.

The high-power controller already has explicit exposure enrollment semantics, so its integrity wrapper registers the returned `HighPowerExposureTicket`.

Only admitted canary units enter either integrity stream.

## Privacy and audit

The integrity gate stores only keyed experiment-scoped 16-byte BLAKE2 tokens for deduplication/ticket lookup. Raw analysis-unit IDs and outcomes are not written into integrity audit events.

The control-plane integrity audit is an append-only SHA-256 hash chain. It records:

- integrity-gate registration;
- the canary-plan and integrity-spec fingerprints;
- an aggregate `integrity_gate_blocked` event containing the two ratio-evidence snapshots and blocker reasons.

It remains separate from the existing promotion audit chain so data-quality authority does not silently rewrite historical promotion events.

## Effective rollback semantics

When integrity blocks, the wrapper returns an `IntegrityGuardedSnapshot` with effective status `ROLLED_BACK` and decision `ROLLBACK`. The original champion remains champion and further enrollment/observation through the wrapper is rejected.

The underlying legacy controller is intentionally not modified. This keeps the new authority opt-in and makes backward compatibility explicit.

## Assumptions and limitations

The assignment e-process assumes the planned per-unit arm probability is correct and that the monitored assignment indicators form the intended randomized stream. It does not by itself solve:

- cluster interference or duplicated logical randomization units;
- arbitrary adaptive randomization whose propensities change by unit;
- informative censoring once detected;
- bot traffic or identity corruption that preserves the aggregate arm ratio;
- metric schema errors that do not affect assignment counts.

Those require separate integrity or causal contracts.

## Relationship to the stress lab

The adversarial stress lab in the separate research PR intentionally creates differential logging/SRM. This production-oriented gate is the first targeted mitigation extracted from that failure mode.

The development sequence is intentional:

`stress DGP -> demonstrated failure -> isolated mitigation -> unit/CI validation -> future stress re-evaluation`.

The next integrity layers should follow the same rule rather than adding complex estimators without an observed failure mode.
