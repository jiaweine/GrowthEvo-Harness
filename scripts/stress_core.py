from __future__ import annotations

import argparse
import json
import math
import random
import resource
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from growthevo.bench import (
    evaluate_cate,
    make_synthetic_growth_bandit,
    ope_records_fingerprint,
    treatment_records_fingerprint,
)
from growthevo.causal import CrossFittedDRLearner
from growthevo.models import Channel
from growthevo.rl import (
    ActionValueEstimate,
    LoggedBanditRecord,
    SafePolicyImprovementConfig,
    SupportAnchoredPolicyImprover,
    evaluate_policy,
)


@dataclass(frozen=True)
class CoreProfile:
    cate_rows: int
    ope_rows: int
    safe_iterations: int
    fingerprint_rows: int
    prediction_passes: int
    parallel_ope_jobs: int
    parallel_ope_rows: int
    max_total_seconds: float
    max_dr_fit_seconds: float
    max_ope_seconds: float
    min_safe_ops_per_second: float
    max_rss_mb: float


PROFILES: dict[str, CoreProfile] = {
    "quick": CoreProfile(1_500, 10_000, 5_000, 5_000, 1, 4, 2_000, 30, 10, 10, 500, 768),
    "ci": CoreProfile(4_000, 50_000, 20_000, 20_000, 2, 6, 4_000, 60, 20, 25, 500, 1024),
    "standard": CoreProfile(10_000, 100_000, 50_000, 50_000, 2, 8, 5_000, 120, 35, 45, 500, 1536),
    "soak": CoreProfile(30_000, 500_000, 250_000, 200_000, 3, 12, 10_000, 600, 120, 240, 300, 3072),
}


@dataclass
class Stage:
    name: str
    duration_seconds: float
    units: int
    unit_name: str
    ok: bool
    details: dict[str, Any]
    error: str | None = None

    @property
    def rate(self) -> float:
        return self.units / self.duration_seconds if self.duration_seconds > 0 else 0.0


def timed_stage(
    name: str,
    units: int,
    unit_name: str,
    fn: Callable[[], dict[str, Any]],
) -> Stage:
    started = time.perf_counter()
    try:
        details = fn()
        duration = time.perf_counter() - started
        return Stage(name, duration, units, unit_name, True, details)
    except Exception as exc:  # noqa: BLE001 - benchmark report must preserve failures
        duration = time.perf_counter() - started
        return Stage(
            name,
            duration,
            units,
            unit_name,
            False,
            {},
            error=f"{type(exc).__name__}: {exc}",
        )


def peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS reports bytes. GitHub Actions and the supported
    # container path are Linux, but keep local execution portable.
    if sys.platform == "darwin":
        return value / (1024 * 1024)
    return value / 1024


def build_ope_rows(count: int, seed: int = 29) -> list[LoggedBanditRecord]:
    rng = random.Random(seed)
    rows: list[LoggedBanditRecord] = []
    target_probs = (0.30, 0.45, 0.25)  # control, push, email
    for index in range(count):
        intent = rng.uniform(-1.0, 1.0)
        fatigue = rng.uniform(-1.0, 1.0)
        baseline = 0.22 + 0.06 * intent - 0.04 * fatigue
        effects = (0.0, 0.08 + 0.05 * intent - 0.03 * fatigue, 0.045 - 0.02 * intent - 0.01 * fatigue)
        push_prob = 0.30 + 0.08 * intent - 0.04 * fatigue
        email_prob = 0.25 - 0.03 * intent + 0.03 * fatigue
        behavior = (1.0 - push_prob - email_prob, push_prob, email_prob)

        draw = rng.random()
        action_index = 0 if draw <= behavior[0] else (1 if draw <= behavior[0] + behavior[1] else 2)
        reward_mean = baseline + effects[action_index]
        reward = max(0.0, min(1.0, reward_mean + rng.gauss(0.0, 0.02)))
        target_q = sum(
            target_probs[action] * (baseline + effects[action])
            for action in range(3)
        )
        rows.append(
            LoggedBanditRecord(
                reward=reward,
                behavior_propensity=behavior[action_index],
                target_action_probability=target_probs[action_index],
                baseline_q=baseline + effects[action_index],
                target_q=target_q,
                cluster_id=index // 20,
                record_id=f"core-ope-{index}",
            )
        )
    return rows


def safe_policy_rows() -> tuple[ActionValueEstimate, ...]:
    return (
        ActionValueEstimate(
            Channel.NO_TREATMENT, 0.220, 0.0, 0.35, 0.0, 0.0,
            value_lower_bound=0.215, cost_upper_bound=0.0, support_eligible=True,
        ),
        ActionValueEstimate(
            Channel.PUSH, 0.305, 0.0, 0.25, 0.08, 0.0,
            value_lower_bound=0.285, cost_upper_bound=0.10, support_eligible=True,
        ),
        ActionValueEstimate(
            Channel.EMAIL, 0.276, 0.0, 0.18, 0.03, 0.0,
            value_lower_bound=0.258, cost_upper_bound=0.04, support_eligible=True,
        ),
        ActionValueEstimate(
            Channel.IN_APP, 0.291, 0.0, 0.12, 0.02, 0.0,
            value_lower_bound=0.270, cost_upper_bound=0.03, support_eligible=True,
        ),
        ActionValueEstimate(
            Channel.ADS, 0.330, 0.0, 0.10, 1.20, 0.0,
            value_lower_bound=0.260, cost_upper_bound=1.50, support_eligible=False,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pressure-test GrowthEvo causal/RL/evidence core.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    stages: list[Stage] = []
    started_total = time.perf_counter()

    samples_holder: dict[str, Any] = {}

    def generate_cate() -> dict[str, Any]:
        samples = make_synthetic_growth_bandit(profile.cate_rows, seed=17)
        samples_holder["samples"] = samples
        return {"rows": len(samples)}

    stages.append(timed_stage("synthetic_bandit_generation", profile.cate_rows, "rows", generate_cate))
    if not stages[-1].ok:
        return finish(args, profile, stages, started_total, extra_checks={})

    def fit_dr() -> dict[str, Any]:
        samples = samples_holder["samples"]
        learner = CrossFittedDRLearner(n_folds=5, ridge=1e-3)
        fitted = learner.fit(
            (sample.record for sample in samples),
            treatment=Channel.PUSH,
        )
        samples_holder["fitted"] = fitted
        if fitted.sample_size <= 0 or fitted.overlap_coverage < 0.999999:
            raise AssertionError("DR fit lost strict overlap coverage")
        return {
            "sample_size": fitted.sample_size,
            "overlap_coverage": fitted.overlap_coverage,
            "practical_overlap_coverage": fitted.practical_overlap_coverage,
            "residual_scale": fitted.residual_scale,
            "support_radius": fitted.support_radius,
        }

    stages.append(timed_stage("cross_fitted_dr_fit", profile.cate_rows, "rows", fit_dr))
    if not stages[-1].ok:
        return finish(args, profile, stages, started_total, extra_checks={})

    def cate_eval() -> dict[str, Any]:
        benchmark = evaluate_cate(samples_holder["fitted"], samples_holder["samples"])
        samples_holder["cate_benchmark"] = benchmark
        if benchmark.rmse > 0.08:
            raise AssertionError(f"synthetic CATE RMSE regressed: {benchmark.rmse:.6f}")
        if benchmark.mean_support_score <= 0:
            raise AssertionError("CATE support score collapsed")
        return asdict(benchmark)

    stages.append(timed_stage("cate_quality_evaluation", profile.cate_rows, "predictions", cate_eval))

    def prediction_batch() -> dict[str, Any]:
        fitted = samples_holder["fitted"]
        samples = samples_holder["samples"]
        effects: list[float] = []
        for _ in range(profile.prediction_passes):
            effects.extend(fitted.predict(sample.record.features).effect for sample in samples)
        if not effects or any(not math.isfinite(value) for value in effects):
            raise AssertionError("non-finite CATE prediction under batch pressure")
        return {
            "prediction_count": len(effects),
            "mean_effect": statistics.fmean(effects),
            "min_effect": min(effects),
            "max_effect": max(effects),
        }

    prediction_units = profile.cate_rows * profile.prediction_passes
    stages.append(timed_stage("cate_prediction_batch", prediction_units, "predictions", prediction_batch))

    ope_holder: dict[str, Any] = {}

    def generate_ope() -> dict[str, Any]:
        rows = build_ope_rows(profile.ope_rows)
        ope_holder["rows"] = rows
        return {"rows": len(rows)}

    stages.append(timed_stage("ope_record_generation", profile.ope_rows, "rows", generate_ope))
    if not stages[-1].ok:
        return finish(args, profile, stages, started_total, extra_checks={})

    def run_ope() -> dict[str, Any]:
        estimate = evaluate_policy(
            ope_holder["rows"],
            support_propensity_floor=1e-3,
            switch_threshold=10.0,
            dr_os_lambda=1.0,
            beta_folds=5,
        )
        ope_holder["estimate"] = estimate
        numeric = (
            estimate.direct_method,
            estimate.ips,
            estimate.self_normalized_ips,
            estimate.doubly_robust,
            estimate.switch_dr,
            estimate.dr_os,
            estimate.beta_ips,
            estimate.meta_blue,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise AssertionError("OPE produced non-finite policy value")
        if estimate.sample_size != profile.ope_rows:
            raise AssertionError("OPE sample size mismatch")
        if estimate.support_coverage < 0.999:
            raise AssertionError(f"OPE support coverage regressed: {estimate.support_coverage}")
        if estimate.effective_sample_ratio <= 0.5:
            raise AssertionError(f"OPE ESS ratio collapsed: {estimate.effective_sample_ratio}")
        if estimate.importance_weight_normalization_error > 0.10:
            raise AssertionError(
                f"importance weights badly normalized: {estimate.importance_weight_normalization_error}"
            )
        return {
            "sample_size": estimate.sample_size,
            "beta_ips": estimate.beta_ips,
            "doubly_robust": estimate.doubly_robust,
            "meta_blue": estimate.meta_blue,
            "support_coverage": estimate.support_coverage,
            "effective_sample_ratio": estimate.effective_sample_ratio,
            "max_importance_weight": estimate.max_importance_weight,
            "importance_weight_normalization_error": estimate.importance_weight_normalization_error,
        }

    stages.append(timed_stage("ope_multi_estimator", profile.ope_rows, "records", run_ope))

    def parallel_ope() -> dict[str, Any]:
        subset = tuple(ope_holder["rows"][: profile.parallel_ope_rows])

        def evaluate(_: int) -> tuple[float, float, float]:
            result = evaluate_policy(subset, beta_folds=5, switch_threshold=10.0, dr_os_lambda=1.0)
            return result.beta_ips, result.doubly_robust, result.meta_blue

        with ThreadPoolExecutor(max_workers=profile.parallel_ope_jobs) as pool:
            values = list(pool.map(evaluate, range(profile.parallel_ope_jobs)))
        if len(set(values)) != 1:
            raise AssertionError("parallel OPE runs are not deterministic")
        return {
            "jobs": profile.parallel_ope_jobs,
            "rows_per_job": len(subset),
            "beta_ips": values[0][0],
        }

    parallel_units = profile.parallel_ope_jobs * profile.parallel_ope_rows
    stages.append(timed_stage("parallel_ope_determinism", parallel_units, "record-evals", parallel_ope))

    def evidence_fingerprints() -> dict[str, Any]:
        ope_rows = tuple(ope_holder["rows"][: profile.fingerprint_rows])
        forward = ope_records_fingerprint(ope_rows)
        reverse = ope_records_fingerprint(reversed(ope_rows))
        if forward != reverse:
            raise AssertionError("OPE locked-evidence fingerprint is order-sensitive")

        treatment_rows = tuple(sample.record for sample in samples_holder["samples"])
        treatment_forward = treatment_records_fingerprint(treatment_rows)
        treatment_reverse = treatment_records_fingerprint(reversed(treatment_rows))
        if treatment_forward != treatment_reverse:
            raise AssertionError("treatment evidence fingerprint is order-sensitive")
        return {
            "ope_rows": len(ope_rows),
            "ope_fingerprint": forward,
            "treatment_rows": len(treatment_rows),
            "treatment_fingerprint": treatment_forward,
        }

    fingerprint_units = min(profile.fingerprint_rows, profile.ope_rows) * 2 + profile.cate_rows * 2
    stages.append(timed_stage("locked_evidence_fingerprints", fingerprint_units, "canonical-rows", evidence_fingerprints))

    safe_holder: dict[str, Any] = {}

    def safe_policy_stress() -> dict[str, Any]:
        rows = safe_policy_rows()
        improver = SupportAnchoredPolicyImprover(
            SafePolicyImprovementConfig(
                max_total_variation=0.20,
                min_pessimistic_improvement=0.0,
                bound_mode="provided",
                support_mode="explicit",
                unsupported_action_mode="no_increase",
            )
        )
        proposal = {
            Channel.NO_TREATMENT: 0.15,
            Channel.PUSH: 0.42,
            Channel.EMAIL: 0.18,
            Channel.IN_APP: 0.15,
            Channel.ADS: 0.10,
        }
        last = None
        selected_counts: dict[str, int] = {}
        for _ in range(profile.safe_iterations):
            last = improver.improve(
                rows,
                max_expected_cost=0.20,
                proposal_probabilities=proposal,
            )
            selected_counts[last.selected_action.value] = selected_counts.get(last.selected_action.value, 0) + 1
        if last is None:
            raise AssertionError("Safe-PI produced no result")
        total_probability = sum(last.probabilities.values())
        if abs(total_probability - 1.0) > 1e-9:
            raise AssertionError("Safe-PI probabilities do not sum to one")
        if last.total_variation_distance > 0.20 + 1e-9:
            raise AssertionError("Safe-PI violated total-variation trust region")
        if last.expected_cost_ucb > 0.20 + 1e-9:
            raise AssertionError("Safe-PI violated expected-cost hard cap")
        if last.probabilities[Channel.ADS] > 0.10 + 1e-12:
            raise AssertionError("unsupported ADS action gained probability mass")
        safe_holder["last"] = last
        return {
            "iterations": profile.safe_iterations,
            "selected_action": last.selected_action.value,
            "changed": last.changed,
            "total_variation_distance": last.total_variation_distance,
            "expected_cost_ucb": last.expected_cost_ucb,
            "selected_counts": selected_counts,
            "reasons": list(last.reasons),
        }

    stages.append(timed_stage("safe_policy_improvement", profile.safe_iterations, "improvements", safe_policy_stress))

    extra_checks = {
        "cate_rmse": getattr(samples_holder.get("cate_benchmark"), "rmse", None),
        "ope_support_coverage": getattr(ope_holder.get("estimate"), "support_coverage", None),
        "ope_effective_sample_ratio": getattr(ope_holder.get("estimate"), "effective_sample_ratio", None),
        "safe_policy_selected_action": (
            safe_holder["last"].selected_action.value if safe_holder.get("last") is not None else None
        ),
    }
    return finish(args, profile, stages, started_total, extra_checks=extra_checks)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GrowthEvo Core Stress Report",
        "",
        f"- Profile: `{report['profile']}`",
        f"- Total duration: **{report['total_duration_seconds']} s**",
        f"- Peak RSS: **{report['peak_rss_mb']} MB**",
        f"- CATE RMSE: **{report['checks'].get('cate_rmse')}**",
        f"- OPE support coverage: **{report['checks'].get('ope_support_coverage')}**",
        f"- OPE ESS ratio: **{report['checks'].get('ope_effective_sample_ratio')}**",
        f"- Safe-PI selected action: **{report['checks'].get('safe_policy_selected_action')}**",
        f"- Result: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "## Stage performance",
        "",
        "| Stage | Units | Duration s | Rate / s | Result |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for stage in report["stages"]:
        lines.append(
            f"| {stage['name']} | {stage['units']} {stage['unit_name']} | {stage['duration_seconds']} | {stage['rate_per_second']} | {'PASS' if stage['ok'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            *[f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in report["gates"].items()],
            "",
            "> This benchmark is deterministic synthetic/reference pressure testing. It verifies computational scaling, numerical contracts and evidence integrity; it is not empirical evidence that any treatment or policy will work in production.",
            "",
        ]
    )
    return "\n".join(lines)


def finish(
    args: argparse.Namespace,
    profile: CoreProfile,
    stages: list[Stage],
    started_total: float,
    *,
    extra_checks: dict[str, Any],
) -> int:
    total_duration = time.perf_counter() - started_total
    rss = peak_rss_mb()
    by_name = {stage.name: stage for stage in stages}
    all_stages_ok = all(stage.ok for stage in stages)
    dr_duration = by_name.get("cross_fitted_dr_fit", Stage("", 0, 0, "", False, {})).duration_seconds
    ope_duration = by_name.get("ope_multi_estimator", Stage("", 0, 0, "", False, {})).duration_seconds
    safe_stage = by_name.get("safe_policy_improvement")
    safe_rate = safe_stage.rate if safe_stage and safe_stage.ok else 0.0
    gates = {
        "all semantic stages passed": all_stages_ok,
        f"total <= {profile.max_total_seconds}s": total_duration <= profile.max_total_seconds,
        f"DR fit <= {profile.max_dr_fit_seconds}s": dr_duration <= profile.max_dr_fit_seconds if "cross_fitted_dr_fit" in by_name else False,
        f"OPE <= {profile.max_ope_seconds}s": ope_duration <= profile.max_ope_seconds if "ope_multi_estimator" in by_name else False,
        f"Safe-PI >= {profile.min_safe_ops_per_second} ops/s": safe_rate >= profile.min_safe_ops_per_second,
        f"peak RSS <= {profile.max_rss_mb} MB": rss <= profile.max_rss_mb,
    }
    passed = all(gates.values())
    report = {
        "profile": args.profile,
        "total_duration_seconds": round(total_duration, 3),
        "peak_rss_mb": round(rss, 2),
        "profile_config": asdict(profile),
        "checks": extra_checks,
        "gates": gates,
        "stages": [
            {
                "name": stage.name,
                "duration_seconds": round(stage.duration_seconds, 4),
                "units": stage.units,
                "unit_name": stage.unit_name,
                "rate_per_second": round(stage.rate, 2),
                "ok": stage.ok,
                "details": stage.details,
                "error": stage.error,
            }
            for stage in stages
        ],
        "passed": passed,
    }
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2)
    rendered_markdown = render_markdown(report)
    print(rendered_markdown)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered_json + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered_markdown, encoding="utf-8")

    if not passed and not args.no_fail:
        print("Core stress thresholds failed. See report above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
