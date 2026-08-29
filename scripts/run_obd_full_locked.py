from __future__ import annotations

"""Run the preregistered full Open Bandit Dataset OPE benchmark end-to-end."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PLAN = _REPO_ROOT / "benchmarks" / "ope" / "obd-full-all-random-to-bts.v1.json"
_OFFICIAL_ARCHIVE = "https://research.zozo.com/data_release/open_bandit_dataset.zip"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_obd_root(path: Path) -> bool:
    return (
        (path / "random" / "all.csv").is_file()
        and (path / "bts" / "all.csv").is_file()
        and (path / "item_context.csv").is_file()
    )


def _find_obd_root(root: Path) -> Path:
    if _looks_like_obd_root(root):
        return root
    matches = sorted(
        path
        for path in root.rglob("*")
        if path.is_dir() and _looks_like_obd_root(path)
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one extracted OBD root under {root}, found {len(matches)}"
        )
    return matches[0]


def _download_and_extract(cache_dir: Path) -> tuple[Path, dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / "open_bandit_dataset.zip"
    extracted = cache_dir / "extracted"
    if not archive.exists():
        with urllib.request.urlopen(_OFFICIAL_ARCHIVE) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
    archive_digest = _sha256(archive)
    if not extracted.exists():
        extracted.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
    return _find_obd_root(extracted), {
        "archive_url": _OFFICIAL_ARCHIVE,
        "archive_sha256": archive_digest,
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown-local-commit"


def run_full_obd(
    *,
    data_root: Path | None,
    cache_dir: Path,
    output_dir: Path,
    plan_path: Path,
) -> Path:
    plan = load_ope_experiment_plan(plan_path)
    if plan.dataset != "obd-full-all-random-to-bts":
        raise ValueError("full OBD runner requires the full all/random-to-bts plan")

    source_provenance: dict[str, str]
    if data_root is None:
        resolved_data_root, source_provenance = _download_and_extract(cache_dir)
    else:
        resolved_data_root = _find_obd_root(data_root.resolve())
        source_provenance = {
            "archive_url": _OFFICIAL_ARCHIVE,
            "archive_sha256": "not-computed-for-preexisting-data-root",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    export_dir = output_dir / "export"
    exporter = _REPO_ROOT / "scripts" / "export_obd_locked_ope.py"
    subprocess.run(
        [
            sys.executable,
            str(exporter),
            "--campaign",
            plan.campaign,
            "--data-path",
            str(resolved_data_root),
            "--dataset-source",
            plan.dataset_source,
            "--output-dir",
            str(export_dir),
            "--validation-fraction",
            str(plan.validation_fraction),
            "--n-sim",
            str(plan.n_sim),
            "--q-model",
            plan.q_model,
            "--q-folds",
            str(plan.q_folds),
            "--random-state",
            str(plan.random_state),
        ],
        cwd=_REPO_ROOT,
        check=True,
    )

    manifest_path = export_dir / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan.validate_export_manifest(manifest)

    result_path = output_dir / "locked-result.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "growthevo.bench.locked_ope_cli",
            "--tuning-jsonl",
            str(export_dir / "validation.jsonl"),
            "--test-jsonl",
            str(export_dir / "holdout.jsonl"),
            "--candidates-json",
            str(export_dir / "ope_candidates.json"),
            "--tuning-reference",
            str(manifest["validation_reference"]),
            "--test-reference",
            str(manifest["holdout_reference"]),
            "--benchmark",
            plan.benchmark,
            "--dataset",
            plan.dataset,
            "--commit-sha",
            _git_sha(),
            "--support-propensity-floor",
            str(plan.support_propensity_floor),
            "--min-support-coverage",
            str(plan.evidence_gate.min_support_coverage),
            "--min-effective-sample-ratio",
            str(plan.evidence_gate.min_effective_sample_ratio),
            "--experiment-plan-json",
            str(plan_path),
            "--export-manifest-json",
            str(manifest_path),
            "--output",
            str(result_path),
        ],
        cwd=_REPO_ROOT,
        check=True,
    )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    prereg = result.get("experiment_plan")
    if prereg is None or prereg.get("fingerprint") != plan.fingerprint:
        raise RuntimeError("locked result is not bound to the requested full OBD plan")

    shutil.copy2(plan_path, output_dir / plan_path.name)
    (output_dir / "source-provenance.json").write_text(
        json.dumps(
            {
                **source_provenance,
                "resolved_data_root": str(resolved_data_root),
                "dataset_source": plan.dataset_source,
                "experiment_plan_fingerprint": plan.fingerprint,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the preregistered full 26M-row Open Bandit OPE benchmark."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Existing extracted OBD root; omit to download the official archive.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_REPO_ROOT / ".benchmark-data" / "open-bandit-full",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "benchmark-results" / "obd-full-all-random-to-bts",
    )
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_full_obd(
        data_root=args.data_root,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        plan_path=args.plan,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
