from __future__ import annotations

import argparse
from pathlib import Path

from growthevo.bench import (
    bootstrap_randomized_targeting,
    kuairand_to_offline_rl,
    load_criteo_uplift,
    load_kuairand,
    load_open_bandit,
    open_bandit_to_ope,
)
from growthevo.causal.dr_learner import CrossFittedDRLearner
from growthevo.models import Channel
from growthevo.rl.ope import evaluate_policy


def run_criteo(path: Path, max_rows: int) -> None:
    data = load_criteo_uplift(path, outcome="visit", max_rows=max_rows)
    split = max(8, int(len(data.records) * 0.75))
    split = min(split, len(data.records) - 1)
    train = data.records[:split]
    test = data.records[split:]
    model = CrossFittedDRLearner(n_folds=5).fit(train, treatment=Channel.ADS)
    scores = [model.predict(row.features).effect for row in test]

    print(f"rows={len(data.records)} treatment_propensity={data.treatment_propensity:.6f}")
    for fraction in (0.10, 0.20, 0.30):
        result = bootstrap_randomized_targeting(
            test,
            scores,
            selected_fraction=fraction,
            replicates=200,
        )
        print(
            f"target={fraction:.0%} policy_value={result.point.policy_value:.6f} "
            f"incremental_vs_none={result.point.incremental_value_vs_none:.6f} "
            f"ci=[{result.lower_incremental_value:.6f}, {result.upper_incremental_value:.6f}]"
        )


def run_open_bandit(path: Path, max_rows: int) -> None:
    rows = load_open_bandit(path, max_rows=max_rows)
    empirical_click = sum(row.click for row in rows) / len(rows)
    records = open_bandit_to_ope(
        rows,
        target_action_probability=lambda row: row.propensity_score,
        baseline_q=lambda row: empirical_click,
        target_q=lambda row: empirical_click,
    )
    estimate = evaluate_policy(records)
    print(f"rows={len(rows)} empirical_click={empirical_click:.6f}")
    print(
        "behavior-policy OPE "
        f"DM={estimate.direct_method:.6f} IPS={estimate.ips:.6f} "
        f"SNIPS={estimate.self_normalized_ips:.6f} DR={estimate.doubly_robust:.6f} "
        f"SWITCH-DR={estimate.switch_dr:.6f} DRos={estimate.dr_os:.6f} "
        f"beta-IPS={estimate.beta_ips:.6f} ESS/N={estimate.effective_sample_ratio:.4f}"
    )


def run_kuairand(path: Path, max_rows: int) -> None:
    rows = load_kuairand(path, max_rows=max_rows)
    dataset = kuairand_to_offline_rl(rows)
    print(
        f"rows={len(rows)} transitions={len(dataset.transitions)} "
        f"trajectories={dataset.trajectory_count} actions={dataset.action_count} "
        f"random_intervention_rate={dataset.random_intervention_rate:.6f}"
    )
    print(dataset.to_jsonl().splitlines()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GrowthEvo real-world benchmark adapters")
    parser.add_argument("dataset", choices=("criteo", "open-bandit", "kuairand"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-rows", type=int, default=100_000)
    args = parser.parse_args()

    if args.dataset == "criteo":
        run_criteo(args.path, args.max_rows)
    elif args.dataset == "open-bandit":
        run_open_bandit(args.path, args.max_rows)
    else:
        run_kuairand(args.path, args.max_rows)


if __name__ == "__main__":
    main()
