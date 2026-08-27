from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from growthevo.bench import (
    bootstrap_randomized_targeting,
    deterministic_stratified_split,
    kuairand_to_offline_rl,
    load_criteo_uplift,
    load_kuairand,
    load_open_bandit,
    open_bandit_to_ope,
    ordered_split,
)
from growthevo.causal.dr_learner import CrossFittedDRLearner
from growthevo.models import Channel
from growthevo.rl.ope import estimate_beta_coefficient, evaluate_policy


def _parse_fractions(value: str) -> tuple[float, ...]:
    try:
        fractions = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("fractions must be comma-separated numbers") from exc
    if not fractions or any(not 0 < fraction <= 1 for fraction in fractions):
        raise argparse.ArgumentTypeError("each targeting fraction must be in (0, 1]")
    return fractions


def _timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Open Bandit timestamp is not ISO-compatible: {value!r}") from exc


def run_criteo(args: argparse.Namespace) -> None:
    data = load_criteo_uplift(
        args.path,
        outcome=args.criteo_outcome,
        max_rows=args.max_rows,
        treatment_propensity=args.criteo_treatment_propensity,
    )
    split = deterministic_stratified_split(
        data.records,
        identity=lambda row: row.unit_id,
        stratum=lambda row: row.action.value,
        train_fraction=args.train_fraction,
        validation_fraction=args.validation_fraction,
        seed=args.split_seed,
    )
    model = CrossFittedDRLearner(n_folds=args.crossfit_folds).fit(
        split.train,
        treatment=Channel.ADS,
    )
    scores = [model.predict(row.features).effect for row in split.test]

    print(
        f"rows={len(data.records)} train={len(split.train)} "
        f"validation={len(split.validation)} test={len(split.test)} "
        f"treatment_propensity={data.treatment_propensity:.6f} "
        f"observed_treatment_share={data.observed_treatment_share:.6f} "
        f"propensity_source={data.propensity_source}"
    )
    for fraction in args.targeting_fractions:
        result = bootstrap_randomized_targeting(
            split.test,
            scores,
            selected_fraction=fraction,
            replicates=args.bootstrap_replicates,
            seed=args.bootstrap_seed,
        )
        print(
            f"target={fraction:.0%} policy_value={result.point.policy_value:.6f} "
            f"incremental_vs_none={result.point.incremental_value_vs_none:.6f} "
            f"ci=[{result.lower_incremental_value:.6f}, {result.upper_incremental_value:.6f}]"
        )


def run_open_bandit(args: argparse.Namespace) -> None:
    rows = load_open_bandit(args.path, max_rows=args.max_rows)
    indexed = tuple(enumerate(rows))
    split = ordered_split(
        indexed,
        order_key=lambda pair: _timestamp(pair[1].timestamp),
        identity=lambda pair: f"open-bandit-{pair[0]}",
        train_fraction=args.train_fraction,
        validation_fraction=args.validation_fraction,
    )
    train = tuple(row for _, row in split.train)
    validation = tuple(row for _, row in split.validation)
    test = tuple(row for _, row in split.test)

    train_click = sum(row.click for row in train) / len(train)
    cluster_key = (
        (lambda row: _timestamp(row.timestamp).date().isoformat())
        if args.open_bandit_cluster_by_date
        else None
    )

    def adapt(source: tuple) -> tuple:
        return open_bandit_to_ope(
            source,
            target_action_probability=lambda row: row.propensity_score,
            baseline_q=lambda row: train_click,
            target_q=lambda row: train_click,
            cluster_key=cluster_key,
        )

    validation_records = adapt(validation) if validation else ()
    beta_coefficient = (
        estimate_beta_coefficient(validation_records)
        if validation_records
        else None
    )
    test_records = adapt(test)
    estimate = evaluate_policy(
        test_records,
        beta_coefficient=beta_coefficient,
        support_propensity_floor=args.ope_support_propensity_floor,
    )
    print(
        f"rows={len(rows)} train={len(train)} validation={len(validation)} "
        f"test={len(test)} train_click={train_click:.6f}"
    )
    print(
        "behavior-policy OPE "
        f"DM={estimate.direct_method:.6f} IPS={estimate.ips:.6f} "
        f"SNIPS={estimate.self_normalized_ips:.6f} DR={estimate.doubly_robust:.6f} "
        f"SWITCH-DR={estimate.switch_dr:.6f} DRos={estimate.dr_os:.6f} "
        f"beta-IPS={estimate.beta_ips:.6f} beta={estimate.beta_coefficient} "
        f"ESS/N={estimate.effective_sample_ratio:.4f} "
        f"SE={estimate.standard_error_method}"
    )


def run_kuairand(args: argparse.Namespace) -> None:
    rows = load_kuairand(args.path, max_rows=args.max_rows)
    dataset = kuairand_to_offline_rl(
        rows,
        max_steps_per_segment=args.kuairand_max_steps_per_segment,
    )
    print(
        f"rows={len(rows)} transitions={len(dataset.transitions)} "
        f"trajectories={dataset.trajectory_count} actions={dataset.action_count} "
        f"random_intervention_rate={dataset.random_intervention_rate:.6f} "
        f"truncation_rate={dataset.truncation_rate:.6f}"
    )
    print(dataset.to_jsonl().splitlines()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GrowthEvo real-world benchmark adapters")
    parser.add_argument("dataset", choices=("criteo", "open-bandit", "kuairand"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-rows", type=int, default=100_000)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--split-seed", type=int, default=17)

    parser.add_argument("--criteo-outcome", choices=("visit", "conversion"), default="visit")
    parser.add_argument("--criteo-treatment-propensity", type=float)
    parser.add_argument("--crossfit-folds", type=int, default=5)
    parser.add_argument("--targeting-fractions", type=_parse_fractions, default=(0.10, 0.20, 0.30))
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    parser.add_argument("--bootstrap-seed", type=int, default=29)

    parser.add_argument("--ope-support-propensity-floor", type=float, default=1e-3)
    parser.add_argument("--open-bandit-cluster-by-date", action="store_true")

    parser.add_argument("--kuairand-max-steps-per-segment", type=int, default=100)
    args = parser.parse_args()

    if args.dataset == "criteo":
        run_criteo(args)
    elif args.dataset == "open-bandit":
        run_open_bandit(args)
    else:
        run_kuairand(args)


if __name__ == "__main__":
    main()
