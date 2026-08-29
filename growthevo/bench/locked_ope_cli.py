from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from hashlib import blake2b
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from growthevo.rl.ope import LoggedBanditRecord

from .locked_evaluation import OPECandidate
from .ope_evidence_gate import EvidenceGatedOPEProtocol, OPEEvidenceGate
from .ope_experiment_plan import OPEExperimentPlan, load_ope_experiment_plan


_ALLOWED_ESTIMATORS = {
    "direct_method",
    "ips",
    "self_normalized_ips",
    "doubly_robust",
    "switch_dr",
    "dr_os",
    "beta_ips",
    "meta_blue",
}


def _json_cluster_identity(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return tuple(_json_cluster_identity(item) for item in value)
    raise ValueError("cluster_id must be a JSON scalar or nested array of scalars")


def _load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid {label} JSON: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    return payload


def _json_object_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _load_ope_jsonl(path: str | Path) -> tuple[LoggedBanditRecord, ...]:
    resolved = Path(path)
    rows: list[LoggedBanditRecord] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid JSON on {resolved}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object on {resolved}:{line_number}")
            try:
                raw_record_id = payload["record_id"]
                if not isinstance(raw_record_id, str) or not raw_record_id:
                    raise ValueError("record_id must be a non-empty JSON string")
                rows.append(
                    LoggedBanditRecord(
                        reward=float(payload["reward"]),
                        behavior_propensity=float(payload["behavior_propensity"]),
                        target_action_probability=float(payload["target_action_probability"]),
                        baseline_q=float(payload["baseline_q"]),
                        target_q=float(payload["target_q"]),
                        cluster_id=_json_cluster_identity(payload.get("cluster_id")),
                        record_id=raw_record_id,
                    )
                )
            except KeyError as exc:
                raise ValueError(
                    f"missing required field {exc.args[0]!r} on {resolved}:{line_number}"
                ) from exc
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid OPE row on {resolved}:{line_number}: {exc}") from exc
    if not rows:
        raise ValueError(f"{resolved} produced no OPE records")
    return tuple(rows)


def _load_candidates(path: str | Path) -> tuple[OPECandidate, ...]:
    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid candidate JSON: {resolved}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("candidate JSON must be a non-empty array")

    candidates: list[OPECandidate] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"candidate {index} must be a JSON object")
        estimator = item.get("estimator")
        if estimator not in _ALLOWED_ESTIMATORS:
            raise ValueError(f"candidate {index} has unsupported estimator: {estimator!r}")
        try:
            raw_name = item["name"]
            if not isinstance(raw_name, str) or not raw_name:
                raise ValueError(f"candidate {index} name must be a non-empty string")
            candidates.append(
                OPECandidate(
                    name=raw_name,
                    estimator=estimator,
                    switch_threshold=(
                        float(item["switch_threshold"])
                        if item.get("switch_threshold") is not None
                        else None
                    ),
                    dr_os_lambda=(
                        float(item["dr_os_lambda"])
                        if item.get("dr_os_lambda") is not None
                        else None
                    ),
                    beta_folds=int(item.get("beta_folds", 5)),
                )
            )
        except KeyError as exc:
            raise ValueError(f"candidate {index} is missing {exc.args[0]!r}") from exc
    return tuple(candidates)


def _load_and_validate_plan(
    *,
    experiment_plan_json: str | Path | None,
    export_manifest_json: str | Path | None,
    benchmark: str,
    dataset: str,
    candidates: Sequence[OPECandidate],
    support_propensity_floor: float,
    evidence_gate: OPEEvidenceGate,
) -> tuple[OPEExperimentPlan | None, dict[str, Any] | None]:
    if (experiment_plan_json is None) != (export_manifest_json is None):
        raise ValueError(
            "experiment_plan_json and export_manifest_json must be provided together"
        )
    if experiment_plan_json is None:
        return None, None

    plan = load_ope_experiment_plan(experiment_plan_json)
    manifest = _load_json_object(export_manifest_json, label="export manifest")
    plan.validate_runtime_contract(
        benchmark=benchmark,
        dataset=dataset,
        candidates=candidates,
        support_propensity_floor=support_propensity_floor,
        evidence_gate=evidence_gate,
    )
    plan.validate_export_manifest(manifest)
    return plan, manifest


def run_locked_ope_benchmark(
    *,
    tuning_jsonl: str | Path,
    test_jsonl: str | Path,
    candidates_json: str | Path,
    tuning_reference: float,
    test_reference: float,
    benchmark: str,
    dataset: str,
    commit_sha: str,
    output: str | Path,
    support_propensity_floor: float = 1e-3,
    min_support_coverage: float = 0.0,
    min_effective_sample_ratio: float = 0.0,
    experiment_plan_json: str | Path | None = None,
    export_manifest_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run evidence-gated validation selection and one frozen holdout reveal.

    When a pre-registered experiment plan is supplied, the plan and realized
    exporter manifest are checked before the validation JSONL is opened. This
    prevents changing Q/split/policy/candidate/gate settings after evidence has
    been generated while still preserving backwards-compatible ad-hoc runs.
    """

    if not isfinite(tuning_reference) or not isfinite(test_reference):
        raise ValueError("reference values must be finite")
    candidates = _load_candidates(candidates_json)
    evidence_gate = OPEEvidenceGate(
        min_support_coverage=min_support_coverage,
        min_effective_sample_ratio=min_effective_sample_ratio,
        require_positive_importance_mass=True,
    )
    plan, export_manifest = _load_and_validate_plan(
        experiment_plan_json=experiment_plan_json,
        export_manifest_json=export_manifest_json,
        benchmark=benchmark,
        dataset=dataset,
        candidates=candidates,
        support_propensity_floor=support_propensity_floor,
        evidence_gate=evidence_gate,
    )

    # Plan/runtime/manifest agreement is checked before the validation evidence
    # itself is read. A mismatched preregistration therefore does not consume a
    # validation reveal.
    tuning_records = _load_ope_jsonl(tuning_jsonl)
    protocol = EvidenceGatedOPEProtocol(
        candidates,
        support_propensity_floor=support_propensity_floor,
        evidence_gate=evidence_gate,
    )
    protocol.tune(tuning_records, reference_value=float(tuning_reference))

    # Deliberately defer even reading the holdout until selection is frozen.
    test_records = _load_ope_jsonl(test_jsonl)
    holdout = protocol.evaluate_once(test_records, reference_value=float(test_reference))
    artifact = protocol.artifact(
        holdout,
        benchmark=benchmark,
        dataset=dataset,
        commit_sha=commit_sha,
    )

    experiment_plan_payload: dict[str, Any] | None = None
    export_manifest_fingerprint: str | None = None
    if plan is not None and export_manifest is not None:
        export_manifest_fingerprint = _json_object_fingerprint(export_manifest)
        metrics = dict(artifact.metrics)
        metrics.update(
            {
                "experiment_plan_fingerprint": plan.fingerprint,
                "export_manifest_fingerprint": export_manifest_fingerprint,
                "dataset_source": plan.dataset_source,
            }
        )
        artifact = replace(
            artifact,
            protocol_fingerprint=plan.bind_protocol_fingerprint(
                artifact.protocol_fingerprint
            ),
            metrics=metrics,
        )
        experiment_plan_payload = {
            "fingerprint": plan.fingerprint,
            "plan": plan.canonical_payload(),
            "export_manifest_fingerprint": export_manifest_fingerprint,
        }

    bundle: dict[str, Any] = {
        "schema_version": (
            "growthevo.locked-ope-run.v3"
            if plan is not None
            else "growthevo.locked-ope-run.v2"
        ),
        "artifact": loads(artifact.to_json()),
        "evidence_gate": asdict(protocol.evidence_gate),
        "experiment_plan": experiment_plan_payload,
        "validation_scores": [
            {
                "candidate": asdict(score.candidate),
                "estimate": score.estimate,
                "reference_value": score.reference_value,
                "absolute_error": score.absolute_error,
                "standard_error": score.standard_error,
                "effective_sample_ratio": score.effective_sample_ratio,
                "support_coverage": score.support_coverage,
                "max_importance_weight": score.max_importance_weight,
            }
            for score in protocol.validation_scores
        ],
    }
    Path(output).write_text(
        dumps(bundle, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Gate OPE evidence, select an estimator on validation, then evaluate "
            "the frozen winner once on holdout."
        ),
    )
    parser.add_argument("--tuning-jsonl", required=True)
    parser.add_argument("--test-jsonl", required=True)
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--tuning-reference", required=True, type=float)
    parser.add_argument("--test-reference", required=True, type=float)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--support-propensity-floor", type=float, default=1e-3)
    parser.add_argument("--min-support-coverage", type=float, default=0.0)
    parser.add_argument("--min-effective-sample-ratio", type=float, default=0.0)
    parser.add_argument("--experiment-plan-json")
    parser.add_argument("--export-manifest-json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_locked_ope_benchmark(
        tuning_jsonl=args.tuning_jsonl,
        test_jsonl=args.test_jsonl,
        candidates_json=args.candidates_json,
        tuning_reference=args.tuning_reference,
        test_reference=args.test_reference,
        benchmark=args.benchmark,
        dataset=args.dataset,
        commit_sha=args.commit_sha,
        output=args.output,
        support_propensity_floor=args.support_propensity_floor,
        min_support_coverage=args.min_support_coverage,
        min_effective_sample_ratio=args.min_effective_sample_ratio,
        experiment_plan_json=args.experiment_plan_json,
        export_manifest_json=args.export_manifest_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
