from __future__ import annotations

import argparse
from importlib.util import find_spec
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from growthevo.bench.llm_candidate_factory import build_shadow_candidate
from growthevo.bench.llm_shadow_runner import run_locked_shadow_benchmark
from growthevo.models import to_primitive

from .operator_manifest import ProductionOperatorManifest, load_operator_manifest
from .operator_shadow import (
    DeferredFileCausalEvidenceProducer,
    context_fingerprints,
    load_context_specs,
)


_PROVIDER_MODULES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google.genai",
}
_OUTPUT_SCHEMA = "growthevo.operator-shadow-run.v1"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _manifest_summary(manifest: ProductionOperatorManifest) -> dict[str, Any]:
    llm_plan = manifest.llm_plan
    shadow_plan = manifest.shadow_plan
    return {
        "schema_version": manifest.schema_version,
        "manifest_fingerprint": manifest.fingerprint,
        "llm_plan_fingerprint": llm_plan.fingerprint,
        "shadow_plan_fingerprint": shadow_plan.fingerprint,
        "require_promotion_evidence": manifest.require_promotion_evidence,
        "evidence_contract": manifest.evidence_contract,
        "evidence_producer": {
            "name": manifest.evidence_producer_name,
            "version": manifest.evidence_producer_version,
        },
        "candidates": [
            {
                "name": candidate.name,
                "provider": candidate.provider,
                "model": candidate.model,
                "contract_fingerprint": candidate.contract_fingerprint,
                "critic_provider": candidate.critic_provider,
                "critic_model": candidate.critic_model,
            }
            for candidate in llm_plan.candidates
        ],
    }


def _module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _validate(args: argparse.Namespace) -> int:
    manifest = load_operator_manifest(args.manifest)
    print(json.dumps(_manifest_summary(manifest), indent=2, sort_keys=True))
    return 0


def _context_fingerprints(args: argparse.Namespace) -> int:
    specs = load_context_specs(args.contexts)
    payload = {
        "schema_version": "growthevo.operator-context-fingerprints.v1",
        "contexts_schema_version": "growthevo.operator-contexts.v1",
        "cases": [to_primitive(item) for item in context_fingerprints(specs)],
    }
    if args.output:
        _write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    manifest = load_operator_manifest(args.manifest)
    results: list[dict[str, Any]] = []
    healthy = True
    for spec in manifest.candidates:
        endpoints = [("planner", spec.endpoint)]
        if spec.critic_endpoint is not None:
            endpoints.append(("critic", spec.critic_endpoint))
        endpoint_results = []
        for role, endpoint in endpoints:
            module = _PROVIDER_MODULES[endpoint.provider]
            available = _module_available(module)
            healthy = healthy and available
            endpoint_results.append(
                {
                    "role": role,
                    "provider": endpoint.provider,
                    "model": endpoint.model,
                    "sdk_module": module,
                    "sdk_available": available,
                }
            )

        instantiated: bool | None = None
        instantiate_error: str | None = None
        if args.instantiate:
            try:
                build_shadow_candidate(spec)
            except Exception as exc:  # noqa: BLE001 - operator preflight boundary
                instantiated = False
                instantiate_error = type(exc).__name__
                healthy = False
            else:
                instantiated = True

        results.append(
            {
                "candidate": spec.name,
                "endpoints": endpoint_results,
                "client_instantiated": instantiated,
                "instantiate_error_type": instantiate_error,
            }
        )

    payload = {
        **_manifest_summary(manifest),
        "doctor": {
            "model_requests_made": False,
            "pure_offline_preflight": not bool(args.instantiate),
            "credential_values_logged": False,
            "instantiate_requested": bool(args.instantiate),
            "healthy": healthy,
            "candidates": results,
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if healthy else 2


def _shadow_run(args: argparse.Namespace) -> int:
    manifest = load_operator_manifest(args.manifest)
    validation_specs = load_context_specs(args.validation_contexts)
    holdout_specs = load_context_specs(args.holdout_contexts)
    validation_ids = tuple(spec.case_id for spec in validation_specs)
    holdout_ids = tuple(spec.case_id for spec in holdout_specs)

    producer = DeferredFileCausalEvidenceProducer(
        validation_path=args.validation_evidence,
        holdout_path=args.holdout_evidence,
        validation_case_ids=validation_ids,
        holdout_case_ids=holdout_ids,
        name=manifest.evidence_producer_name,
        version=manifest.evidence_producer_version,
    )

    plan = manifest.llm_plan
    planned = {candidate.name: candidate for candidate in plan.candidates}
    entries = []
    for spec in manifest.candidates:
        built = build_shadow_candidate(spec)
        if built.candidate != planned[spec.name]:
            raise RuntimeError(
                f"runtime candidate identity differs from preregistered manifest "
                f"for {spec.name!r}"
            )
        entries.append(built.entry)

    run = run_locked_shadow_benchmark(
        plan=manifest.shadow_plan,
        entries=entries,
        producer=producer,
        validation_specs=validation_specs,
        holdout_specs=holdout_specs,
        commit_sha=args.commit_sha,
    )
    if producer.loaded_splits != ("validation", "holdout"):
        raise RuntimeError(
            "locked shadow run did not consume validation then holdout evidence"
        )

    payload = {
        "schema_version": _OUTPUT_SCHEMA,
        "operator_manifest_fingerprint": manifest.fingerprint,
        "llm_plan_fingerprint": plan.fingerprint,
        "shadow_plan_fingerprint": run.shadow_plan_fingerprint,
        "commit_sha": args.commit_sha,
        "selected_candidate": to_primitive(run.selected_candidate),
        "artifact": to_primitive(run.artifact),
        "holdout": to_primitive(run.holdout),
        "evidence_manifest_fingerprint": run.evidence_manifest_fingerprint,
        "validation_evidence_fingerprint": run.validation_evidence_fingerprint,
        "holdout_evidence_fingerprint": run.holdout_evidence_fingerprint,
        "validation_decisions": [
            to_primitive(decision) for decision in run.validation_decisions
        ],
        "holdout_decisions": [
            to_primitive(decision) for decision in run.holdout_decisions
        ],
    }
    output = Path(args.output)
    _write_json(output, payload)
    print(
        json.dumps(
            {
                "output": str(output),
                "selected_candidate": run.selected_candidate.name,
                "promotion_eligible": run.artifact.promotion_eligible,
                "operator_manifest_fingerprint": manifest.fingerprint,
                "evidence_manifest_fingerprint": run.evidence_manifest_fingerprint,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="growthevo-operator",
        description=(
            "Validate, preflight and execute locked GrowthEvo LLM shadow benchmarks "
            "without putting credentials or causal holdout labels in the manifest."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate",
        help="validate and fingerprint a non-secret operator manifest",
    )
    validate.add_argument("--manifest", required=True)
    validate.set_defaults(func=_validate)

    contexts = sub.add_parser(
        "context-fingerprints",
        help="derive exact causal context fingerprints without reading labels",
    )
    contexts.add_argument("--contexts", required=True)
    contexts.add_argument("--output")
    contexts.set_defaults(func=_context_fingerprints)

    doctor = sub.add_parser(
        "doctor",
        help="check provider SDK readiness without making model requests",
    )
    doctor.add_argument("--manifest", required=True)
    doctor.add_argument(
        "--instantiate",
        action="store_true",
        help=(
            "also instantiate provider clients using their normal environment or "
            "workload identity; no model request is sent, but SDK initialization "
            "may perform provider-specific credential or metadata discovery"
        ),
    )
    doctor.set_defaults(func=_doctor)

    shadow = sub.add_parser(
        "shadow-run",
        help="run validation selection and one-shot holdout with deferred labels",
    )
    shadow.add_argument("--manifest", required=True)
    shadow.add_argument("--validation-contexts", required=True)
    shadow.add_argument("--validation-evidence", required=True)
    shadow.add_argument("--holdout-contexts", required=True)
    shadow.add_argument("--holdout-evidence", required=True)
    shadow.add_argument("--commit-sha", required=True)
    shadow.add_argument("--output", required=True)
    shadow.set_defaults(func=_shadow_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"growthevo-operator: {exc}", file=sys.stderr)
        return 2
