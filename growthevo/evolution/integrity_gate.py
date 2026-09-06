from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import blake2b, sha256
import json
from math import exp, isfinite, lgamma, log
from typing import Any, Mapping

from .online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryObservation,
    CanaryPlan,
    CanaryRoute,
    CanarySnapshot,
    CanaryStatus,
    OnlinePromotionController,
    PromotionAuditEvent,
)
from .sequential_causal import (
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
    HighPowerExposureTicket,
    HighPowerOnlinePromotionController,
)


class IntegrityStatus(str, Enum):
    CLEAR = "clear"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ExperimentIntegritySpec:
    """Pre-registered family-wise allocation-integrity monitoring contract."""

    family_alpha: float = 0.001
    enrollment_alpha: float = 0.0005
    matured_population_alpha: float = 0.0005
    minimum_enrollment_observations: int = 64
    minimum_matured_observations: int = 64
    beta_prior_alpha: float = 0.5
    beta_prior_beta: float = 0.5

    def __post_init__(self) -> None:
        for name, value in (
            ("family_alpha", self.family_alpha),
            ("enrollment_alpha", self.enrollment_alpha),
            ("matured_population_alpha", self.matured_population_alpha),
            ("beta_prior_alpha", self.beta_prior_alpha),
            ("beta_prior_beta", self.beta_prior_beta),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("family_alpha", "enrollment_alpha", "matured_population_alpha"):
            if getattr(self, name) >= 1:
                raise ValueError(f"{name} must be below 1")
        if self.enrollment_alpha + self.matured_population_alpha > self.family_alpha + 1e-15:
            raise ValueError("integrity stream alphas cannot exceed family_alpha")
        if self.minimum_enrollment_observations <= 0:
            raise ValueError("minimum_enrollment_observations must be positive")
        if self.minimum_matured_observations <= 0:
            raise ValueError("minimum_matured_observations must be positive")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {"schema": "growthevo.experiment-integrity-spec.v1", **asdict(self)}
        )


@dataclass(frozen=True, slots=True)
class AssignmentRatioEvidence:
    observations: int
    challenger_observations: int
    control_observations: int
    expected_challenger_probability: float
    challenger_share: float
    e_value: float
    max_e_value: float
    threshold: float
    eligible_to_trip: bool
    tripped: bool


class BetaBinomialAssignmentEProcess:
    """Two-sided anytime-valid likelihood-ratio e-process for a Bernoulli split.

    Under the randomized assignment null A_t ~ Bernoulli(p0), mixing the
    alternative likelihood over Beta(a, b) gives

        E_n = B(a+S, b+n-S) / B(a,b)
              / (p0**S * (1-p0)**(n-S)).

    This is a non-negative martingale under the assignment null. The mixture is
    two-sided because its alternative prior spans probabilities on both sides of
    p0. We maintain the calculation in log space for numerical stability.
    """

    def __init__(
        self,
        *,
        expected_probability: float,
        prior_alpha: float,
        prior_beta: float,
    ) -> None:
        if not 0 < expected_probability < 1:
            raise ValueError("expected_probability must lie in (0, 1)")
        if not isfinite(prior_alpha) or prior_alpha <= 0:
            raise ValueError("prior_alpha must be positive and finite")
        if not isfinite(prior_beta) or prior_beta <= 0:
            raise ValueError("prior_beta must be positive and finite")
        self.expected_probability = float(expected_probability)
        self.prior_alpha = float(prior_alpha)
        self.prior_beta = float(prior_beta)
        self.observations = 0
        self.challenger_observations = 0
        self._log_e = 0.0
        self._max_log_e = 0.0

    @staticmethod
    def _exp(log_value: float) -> float:
        return float("inf") if log_value >= 709.0 else exp(log_value)

    def _compute_log_e(self) -> float:
        s = self.challenger_observations
        f = self.observations - s
        a = self.prior_alpha
        b = self.prior_beta
        log_beta_posterior = lgamma(a + s) + lgamma(b + f) - lgamma(a + b + self.observations)
        log_beta_prior = lgamma(a) + lgamma(b) - lgamma(a + b)
        log_null = s * log(self.expected_probability) + f * log(1.0 - self.expected_probability)
        value = log_beta_posterior - log_beta_prior - log_null
        if value != value:  # NaN guard without importing another helper.
            raise ValueError("assignment e-process became non-finite")
        return value

    def update(self, assigned_to_challenger: bool) -> float:
        self.observations += 1
        self.challenger_observations += int(bool(assigned_to_challenger))
        self._log_e = self._compute_log_e()
        self._max_log_e = max(self._max_log_e, self._log_e)
        return self.e_value

    @property
    def e_value(self) -> float:
        return self._exp(self._log_e)

    @property
    def max_e_value(self) -> float:
        return self._exp(self._max_log_e)

    @property
    def challenger_share(self) -> float:
        return (
            self.challenger_observations / self.observations
            if self.observations
            else self.expected_probability
        )

    def evidence(
        self,
        *,
        alpha: float,
        minimum_observations: int,
        sticky_tripped: bool = False,
    ) -> AssignmentRatioEvidence:
        threshold = 1.0 / alpha
        eligible = self.observations >= minimum_observations
        current_trip = eligible and self.e_value >= threshold
        return AssignmentRatioEvidence(
            observations=self.observations,
            challenger_observations=self.challenger_observations,
            control_observations=self.observations - self.challenger_observations,
            expected_challenger_probability=self.expected_probability,
            challenger_share=self.challenger_share,
            e_value=self.e_value,
            max_e_value=self.max_e_value,
            threshold=threshold,
            eligible_to_trip=eligible,
            tripped=sticky_tripped or current_trip,
        )


@dataclass(frozen=True, slots=True)
class ExperimentIntegritySnapshot:
    status: IntegrityStatus
    enrollment: AssignmentRatioEvidence
    matured_population: AssignmentRatioEvidence
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntegrityAuditEvent:
    sequence: int
    kind: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str


class ExperimentIntegrityGate:
    """Independent assignment/data-quality authority for one canary plan."""

    def __init__(self, plan: CanaryPlan, spec: ExperimentIntegritySpec) -> None:
        self.plan = plan
        self.spec = spec
        self.status = IntegrityStatus.CLEAR
        self._enrollment = BetaBinomialAssignmentEProcess(
            expected_probability=plan.challenger_probability,
            prior_alpha=spec.beta_prior_alpha,
            prior_beta=spec.beta_prior_beta,
        )
        self._matured = BetaBinomialAssignmentEProcess(
            expected_probability=plan.challenger_probability,
            prior_alpha=spec.beta_prior_alpha,
            prior_beta=spec.beta_prior_beta,
        )
        self._seen_enrollment: set[bytes] = set()
        self._seen_matured: set[bytes] = set()
        self._events: list[IntegrityAuditEvent] = []
        self._append(
            "integrity_gate_registered",
            {
                "canary_plan_fingerprint": plan.fingerprint,
                "integrity_spec_fingerprint": spec.fingerprint,
                "expected_challenger_probability": plan.challenger_probability,
            },
        )

    def _token(self, analysis_unit_id: str, stream: str) -> bytes:
        if not analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        return blake2b(
            f"{self.plan.experiment_id}|{stream}|{analysis_unit_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    @staticmethod
    def _digest(sequence: int, kind: str, payload: Mapping[str, Any], previous_hash: str) -> str:
        encoded = json.dumps(
            {
                "sequence": sequence,
                "kind": kind,
                "payload": payload,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _append(self, kind: str, payload: Mapping[str, Any]) -> IntegrityAuditEvent:
        sequence = len(self._events)
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        primitive = json.loads(json.dumps(payload, sort_keys=True))
        event = IntegrityAuditEvent(
            sequence=sequence,
            kind=kind,
            payload=primitive,
            previous_hash=previous_hash,
            event_hash=self._digest(sequence, kind, primitive, previous_hash),
        )
        self._events.append(event)
        return event

    def _evaluate(self) -> ExperimentIntegritySnapshot:
        enrollment = self._enrollment.evidence(
            alpha=self.spec.enrollment_alpha,
            minimum_observations=self.spec.minimum_enrollment_observations,
            sticky_tripped=self.status is IntegrityStatus.BLOCKED,
        )
        matured = self._matured.evidence(
            alpha=self.spec.matured_population_alpha,
            minimum_observations=self.spec.minimum_matured_observations,
            sticky_tripped=self.status is IntegrityStatus.BLOCKED,
        )
        reasons: list[str] = []
        if enrollment.eligible_to_trip and enrollment.e_value >= enrollment.threshold:
            reasons.append("enrollment_sample_ratio_mismatch")
        if matured.eligible_to_trip and matured.e_value >= matured.threshold:
            reasons.append("matured_population_sample_ratio_mismatch")
        if reasons and self.status is IntegrityStatus.CLEAR:
            self.status = IntegrityStatus.BLOCKED
            self._append(
                "integrity_gate_blocked",
                {
                    "reasons": reasons,
                    "enrollment": asdict(enrollment),
                    "matured_population": asdict(matured),
                },
            )
        if self.status is IntegrityStatus.BLOCKED and not reasons:
            reasons.append("integrity_gate_previously_blocked")
        return ExperimentIntegritySnapshot(
            status=self.status,
            enrollment=enrollment,
            matured_population=matured,
            reasons=tuple(reasons),
        )

    def observe_enrollment(self, analysis_unit_id: str, *, assigned_to_challenger: bool) -> ExperimentIntegritySnapshot:
        if self.status is IntegrityStatus.BLOCKED:
            raise RuntimeError("experiment integrity gate is blocked")
        token = self._token(analysis_unit_id, "enrollment")
        if token in self._seen_enrollment:
            raise ValueError("analysis_unit_id has already been registered for enrollment integrity")
        self._seen_enrollment.add(token)
        self._enrollment.update(assigned_to_challenger)
        return self._evaluate()

    def observe_matured_population(self, analysis_unit_id: str, *, assigned_to_challenger: bool) -> ExperimentIntegritySnapshot:
        if self.status is IntegrityStatus.BLOCKED:
            raise RuntimeError("experiment integrity gate is blocked")
        enrollment_token = self._token(analysis_unit_id, "enrollment")
        if enrollment_token not in self._seen_enrollment:
            raise ValueError("matured analysis unit was not registered at enrollment")
        token = self._token(analysis_unit_id, "matured")
        if token in self._seen_matured:
            raise ValueError("analysis_unit_id has already been registered as matured")
        self._seen_matured.add(token)
        self._matured.update(assigned_to_challenger)
        return self._evaluate()

    def snapshot(self) -> ExperimentIntegritySnapshot:
        return self._evaluate()

    def events(self) -> tuple[IntegrityAuditEvent, ...]:
        return tuple(self._events)

    def verify_audit_chain(self) -> bool:
        previous_hash = "0" * 64
        for expected_sequence, event in enumerate(self._events):
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            if self._digest(event.sequence, event.kind, event.payload, event.previous_hash) != event.event_hash:
                return False
            previous_hash = event.event_hash
        return True


@dataclass(frozen=True, slots=True)
class IntegrityEnrollment:
    route: CanaryRoute | HighPowerExposureTicket
    integrity: ExperimentIntegritySnapshot


@dataclass(frozen=True, slots=True)
class IntegrityGuardedSnapshot:
    status: CanaryStatus
    decision: CanaryDecision
    canary: CanarySnapshot
    integrity: ExperimentIntegritySnapshot
    reasons: tuple[str, ...]


class _IntegrityAuthority:
    def __init__(self, plan: CanaryPlan, spec: ExperimentIntegritySpec) -> None:
        self.plan = plan
        self.integrity = ExperimentIntegrityGate(plan, spec)
        self._blocked = False
        self._tickets: dict[bytes, tuple[int, bool, float, float]] = {}

    def _ticket_token(self, analysis_unit_id: str) -> bytes:
        return blake2b(
            f"{self.plan.experiment_id}|ticket|{analysis_unit_id}".encode("utf-8"),
            digest_size=16,
        ).digest()

    def _register_ticket(
        self,
        analysis_unit_id: str,
        *,
        stage_index: int,
        assigned_to_challenger: bool,
        traffic_fraction: float,
        challenger_probability: float,
    ) -> ExperimentIntegritySnapshot:
        token = self._ticket_token(analysis_unit_id)
        existing = self._tickets.get(token)
        signature = (
            stage_index,
            bool(assigned_to_challenger),
            float(traffic_fraction),
            float(challenger_probability),
        )
        if existing is not None:
            if existing != signature:
                raise ValueError("analysis unit routing signature changed after enrollment")
            return self.integrity.snapshot()
        self._tickets[token] = signature
        snapshot = self.integrity.observe_enrollment(
            analysis_unit_id,
            assigned_to_challenger=assigned_to_challenger,
        )
        if snapshot.status is IntegrityStatus.BLOCKED:
            self._blocked = True
        return snapshot

    def _preflight_matured(
        self,
        analysis_unit_id: str,
        *,
        stage_index: int,
        assigned_to_challenger: bool,
        traffic_fraction: float,
        challenger_probability: float,
    ) -> ExperimentIntegritySnapshot:
        token = self._ticket_token(analysis_unit_id)
        registered = self._tickets.get(token)
        if registered is None:
            raise ValueError("analysis unit has no integrity enrollment ticket")
        expected = (
            stage_index,
            bool(assigned_to_challenger),
            float(traffic_fraction),
            float(challenger_probability),
        )
        if registered != expected:
            raise ValueError("matured population record does not match integrity enrollment ticket")
        snapshot = self.integrity.observe_matured_population(
            analysis_unit_id,
            assigned_to_challenger=assigned_to_challenger,
        )
        if snapshot.status is IntegrityStatus.BLOCKED:
            self._blocked = True
        return snapshot

    def _combined(self, canary: CanarySnapshot, integrity: ExperimentIntegritySnapshot) -> IntegrityGuardedSnapshot:
        if integrity.status is IntegrityStatus.BLOCKED or self._blocked:
            reasons = integrity.reasons or ("experiment_integrity_gate_blocked",)
            return IntegrityGuardedSnapshot(
                status=CanaryStatus.ROLLED_BACK,
                decision=CanaryDecision.ROLLBACK,
                canary=canary,
                integrity=integrity,
                reasons=reasons,
            )
        return IntegrityGuardedSnapshot(
            status=canary.status,
            decision=canary.decision,
            canary=canary,
            integrity=integrity,
            reasons=canary.reasons,
        )


class IntegrityGuardedOnlinePromotionController(_IntegrityAuthority):
    """Optional wrapper that makes integrity a non-tradeable promotion authority."""

    def __init__(
        self,
        *,
        champion_name: str,
        candidate: CanaryCandidate,
        plan: CanaryPlan,
        integrity_spec: ExperimentIntegritySpec = ExperimentIntegritySpec(),
    ) -> None:
        super().__init__(plan, integrity_spec)
        self.controller = OnlinePromotionController(
            champion_name=champion_name,
            candidate=candidate,
            plan=plan,
        )

    @property
    def champion_name(self) -> str:
        return self.controller.champion_name

    def start(self) -> IntegrityGuardedSnapshot:
        canary = self.controller.start()
        return self._combined(canary, self.integrity.snapshot())

    def route(self, analysis_unit_id: str) -> CanaryRoute:
        if self._blocked:
            raise RuntimeError("experiment integrity gate is blocked")
        return self.controller.route(analysis_unit_id)

    def enroll(self, analysis_unit_id: str) -> IntegrityEnrollment:
        route = self.route(analysis_unit_id)
        integrity = self.integrity.snapshot()
        if route.in_canary:
            integrity = self._register_ticket(
                analysis_unit_id,
                stage_index=self.controller.monitor.stage_index,
                assigned_to_challenger=route.assigned_to_challenger,
                traffic_fraction=route.traffic_fraction,
                challenger_probability=route.challenger_probability,
            )
        return IntegrityEnrollment(route=route, integrity=integrity)

    def observe(self, observation: CanaryObservation) -> IntegrityGuardedSnapshot:
        if self._blocked:
            raise RuntimeError("experiment integrity gate is blocked")
        stage_index = self.controller.monitor.stage_index
        integrity = self._preflight_matured(
            observation.analysis_unit_id,
            stage_index=stage_index,
            assigned_to_challenger=observation.assigned_to_challenger,
            traffic_fraction=observation.traffic_fraction,
            challenger_probability=observation.assignment_probability,
        )
        if integrity.status is IntegrityStatus.BLOCKED:
            canary = self.controller.monitor.snapshot(
                CanaryDecision.HOLD,
                ("integrity_blocked_before_metric_update",),
            )
            return self._combined(canary, integrity)
        canary = self.controller.observe(observation)
        return self._combined(canary, integrity)

    def promotion_events(self) -> tuple[PromotionAuditEvent, ...]:
        return self.controller.events()


class IntegrityGuardedHighPowerPromotionController(_IntegrityAuthority):
    """Integrity wrapper for the frozen-CUPED/group-sequential controller."""

    def __init__(
        self,
        *,
        champion_name: str,
        candidate: CanaryCandidate,
        plan: HighPowerCanaryPlan,
        integrity_spec: ExperimentIntegritySpec = ExperimentIntegritySpec(),
    ) -> None:
        super().__init__(plan.base_plan, integrity_spec)
        self.high_power_plan = plan
        self.controller = HighPowerOnlinePromotionController(
            champion_name=champion_name,
            candidate=candidate,
            plan=plan,
        )

    @property
    def champion_name(self) -> str:
        return self.controller.champion_name

    def start(self) -> IntegrityGuardedSnapshot:
        canary = self.controller.start()
        return self._combined(canary, self.integrity.snapshot())

    def enroll(self, analysis_unit_id: str) -> IntegrityEnrollment:
        if self._blocked:
            raise RuntimeError("experiment integrity gate is blocked")
        ticket = self.controller.enroll(analysis_unit_id)
        integrity = self.integrity.snapshot()
        if ticket.in_canary:
            integrity = self._register_ticket(
                analysis_unit_id,
                stage_index=ticket.routing_stage_index,
                assigned_to_challenger=ticket.assigned_to_challenger,
                traffic_fraction=ticket.traffic_fraction,
                challenger_probability=ticket.challenger_probability,
            )
        return IntegrityEnrollment(route=ticket, integrity=integrity)

    def route(self, analysis_unit_id: str) -> IntegrityEnrollment:
        return self.enroll(analysis_unit_id)

    def observe(self, observation: HighPowerCanaryObservation) -> IntegrityGuardedSnapshot:
        if self._blocked:
            raise RuntimeError("experiment integrity gate is blocked")
        integrity = self._preflight_matured(
            observation.analysis_unit_id,
            stage_index=observation.routing_stage_index,
            assigned_to_challenger=observation.assigned_to_challenger,
            traffic_fraction=observation.traffic_fraction,
            challenger_probability=observation.assignment_probability,
        )
        if integrity.status is IntegrityStatus.BLOCKED:
            canary = self.controller.monitor.snapshot(
                CanaryDecision.HOLD,
                ("integrity_blocked_before_metric_update",),
            )
            return self._combined(canary, integrity)
        canary = self.controller.observe(observation)
        return self._combined(canary, integrity)

    def promotion_events(self) -> tuple[PromotionAuditEvent, ...]:
        return self.controller.events()
