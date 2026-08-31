from __future__ import annotations

"""Run the preregistered full Open Bandit Dataset OPE benchmark end-to-end.

The default transport uses the ZOZO NEXT Hugging Face mirror pinned to the OBD
1.0 data revision.  Only the three files required by the pre-registered ``all``
experiment are materialised locally: random-policy evidence, BTS factual
reference, and the random campaign item context.  This preserves local
chronological parsing semantics while avoiding the 11.7 GB all-campaign archive
and a second extracted copy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PLAN = _REPO_ROOT / "benchmarks" / "ope" / "obd-full-all-random-to-bts.v1.json"
_CANONICAL_RELEASE = "https://research.zozo.com/data_release/open_bandit_dataset.zip"
_HF_DATASET = "zozonext/open-bandit"
_HF_DATA_REVISION = "57a688e"
_HF_BASE = f"https://huggingface.co/datasets/{_HF_DATASET}/resolve/{_HF_DATA_REVISION}"
_MIN_FREE_BYTES_AFTER_DOWNLOAD = 2 * 1024**3
_EXPECTED_SOURCE_BYTES = {
    "behavior": 695_501_426,
    "target_reference": 6_321_017_454,
    "item_context": 10_041,
}
_EXPECTED_SOURCE_SHA256 = {
    "behavior": "f24fdf91e38de41dcd15f2482279358766556be04155b35882e327b465d104b7",
    "target_reference": "05ba8416e6626be0dc16ee09a434d736eca1c4c274e10eabe3931521c4aeede2",
    "item_context": "88345bc52dea9965cf148f02c661d03ce566f278b2b870ec0c70c5d3da1c2d1c",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_pinned_source_file(path: Path, *, identity: str) -> tuple[int, str]:
    expected_bytes = _EXPECTED_SOURCE_BYTES[identity]
    expected_sha256 = _EXPECTED_SOURCE_SHA256[identity]
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise RuntimeError(
            f"full OBD {identity} size mismatch for {path}: "
            f"got {actual_bytes}, expected {expected_bytes}"
        )
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"full OBD {identity} SHA256 mismatch for {path}: "
            f"got {actual_sha256}, expected {expected_sha256}"
        )
    return actual_bytes, actual_sha256


def _campaign_file(root: Path, policy: str, campaign: str) -> Path:
    return root / policy / campaign / f"{campaign}.csv"


def _item_context_file(root: Path, policy: str, campaign: str) -> Path:
    return root / policy / campaign / "item_context.csv"


def _looks_like_behavior_root(path: Path, campaign: str = "all") -> bool:
    return (
        _campaign_file(path, "random", campaign).is_file()
        and _item_context_file(path, "random", campaign).is_file()
    )


def _looks_like_full_root(path: Path, campaign: str = "all") -> bool:
    return _looks_like_behavior_root(path, campaign) and _campaign_file(
        path, "bts", campaign
    ).is_file()


def _find_obd_root(
    root: Path,
    *,
    campaign: str = "all",
    require_target: bool = True,
) -> Path:
    predicate = _looks_like_full_root if require_target else _looks_like_behavior_root
    if predicate(root, campaign):
        return root
    matches = sorted(
        path
        for path in root.rglob("*")
        if path.is_dir() and predicate(path, campaign)
    )
    if len(matches) != 1:
        kind = "full" if require_target else "random-policy"
        raise ValueError(
            f"expected exactly one {kind} OBD root under {root}, found {len(matches)}"
        )
    return matches[0]


def _mirror_url(policy: str, campaign: str, filename: str) -> str:
    return f"{_HF_BASE}/{policy}/{campaign}/{filename}?download=true"


def _request(url: str, *, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": "GrowthEvo-Harness/full-obd-benchmark"},
    )


def _remote_size(url: str) -> int | None:
    """Return final response Content-Length after redirects when advertised."""

    try:
        with urllib.request.urlopen(_request(url, method="HEAD")) as response:
            raw = response.headers.get("Content-Length")
    except OSError:
        return None
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _assert_download_budget(
    cache_dir: Path,
    downloads: list[tuple[str, Path]],
    *,
    reserve_bytes: int = _MIN_FREE_BYTES_AFTER_DOWNLOAD,
) -> dict[str, int | None]:
    """Fail before large transfers when advertised sizes exceed local free disk."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(cache_dir).free
    sizes: dict[str, int | None] = {}
    required_bytes = 0
    unknown = False
    for url, destination in downloads:
        if destination.is_file() and destination.stat().st_size > 0:
            sizes[url] = destination.stat().st_size
            continue
        size = _remote_size(url)
        sizes[url] = size
        if size is None:
            unknown = True
        else:
            required_bytes += size
    if not unknown and free_bytes - required_bytes < reserve_bytes:
        raise RuntimeError(
            "insufficient disk for pinned OBD campaign files: "
            f"free={free_bytes}, required={required_bytes}, reserve={reserve_bytes}"
        )
    return sizes


def _download(url: str, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    with urllib.request.urlopen(_request(url)) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
    if temporary.stat().st_size <= 0:
        raise RuntimeError(f"downloaded empty OBD file from {url}")
    temporary.replace(destination)


def _download_campaign_pair(
    cache_dir: Path,
    *,
    campaign: str,
) -> tuple[Path, dict[str, object]]:
    """Materialise only the pinned campaign files needed by this experiment."""

    root = cache_dir / f"obd-v1-{_HF_DATA_REVISION}"
    behavior_csv = _campaign_file(root, "random", campaign)
    target_csv = _campaign_file(root, "bts", campaign)
    item_context = _item_context_file(root, "random", campaign)
    behavior_url = _mirror_url("random", campaign, f"{campaign}.csv")
    target_url = _mirror_url("bts", campaign, f"{campaign}.csv")
    item_context_url = _mirror_url("random", campaign, "item_context.csv")
    downloads = [
        (behavior_url, behavior_csv),
        (target_url, target_csv),
        (item_context_url, item_context),
    ]
    advertised = _assert_download_budget(cache_dir, downloads)
    for url, destination in downloads:
        _download(url, destination)
    if not _looks_like_full_root(root, campaign):
        raise RuntimeError("downloaded OBD mirror does not satisfy OBP campaign layout")

    behavior_bytes, behavior_sha256 = _verify_pinned_source_file(
        behavior_csv, identity="behavior"
    )
    target_bytes, target_sha256 = _verify_pinned_source_file(
        target_csv, identity="target_reference"
    )
    item_context_bytes, item_context_sha256 = _verify_pinned_source_file(
        item_context, identity="item_context"
    )
    provenance: dict[str, object] = {
        "canonical_release_url": _CANONICAL_RELEASE,
        "transport": "huggingface-zozonext-pinned-campaign-files",
        "mirror_dataset": _HF_DATASET,
        "mirror_data_revision": _HF_DATA_REVISION,
        "disk_reserve_bytes": _MIN_FREE_BYTES_AFTER_DOWNLOAD,
        "behavior_url": behavior_url,
        "behavior_advertised_bytes": advertised[behavior_url],
        "behavior_sha256": behavior_sha256,
        "behavior_bytes": behavior_bytes,
        "target_reference_url": target_url,
        "target_reference_advertised_bytes": advertised[target_url],
        "target_reference_sha256": target_sha256,
        "target_reference_bytes": target_bytes,
        "target_reference_storage": "local-pinned-campaign-file",
        "item_context_url": item_context_url,
        "item_context_advertised_bytes": advertised[item_context_url],
        "item_context_sha256": item_context_sha256,
        "item_context_bytes": item_context_bytes,
    }
    return root, provenance


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
    prediction_batch_size: int = 50_000,
) -> Path:
    plan = load_ope_experiment_plan(plan_path)
    if plan.dataset != "obd-full-all-random-to-bts":
        raise ValueError("full OBD runner requires the full all/random-to-bts plan")
    if prediction_batch_size <= 0:
        raise ValueError("prediction_batch_size must be positive")

    source_provenance: dict[str, object]
    if data_root is None:
        resolved_data_root, source_provenance = _download_campaign_pair(
            cache_dir,
            campaign=plan.campaign,
        )
    else:
        resolved_data_root = _find_obd_root(
            data_root.resolve(),
            campaign=plan.campaign,
            require_target=True,
        )
        behavior_csv = _campaign_file(resolved_data_root, "random", plan.campaign)
        target_csv = _campaign_file(resolved_data_root, "bts", plan.campaign)
        item_context = _item_context_file(
            resolved_data_root, "random", plan.campaign
        )
        behavior_bytes, behavior_sha256 = _verify_pinned_source_file(
            behavior_csv, identity="behavior"
        )
        target_bytes, target_sha256 = _verify_pinned_source_file(
            target_csv, identity="target_reference"
        )
        item_context_bytes, item_context_sha256 = _verify_pinned_source_file(
            item_context, identity="item_context"
        )
        source_provenance = {
            "canonical_release_url": _CANONICAL_RELEASE,
            "transport": "preexisting-full-data-root",
            "behavior_sha256": behavior_sha256,
            "behavior_bytes": behavior_bytes,
            "target_reference_sha256": target_sha256,
            "target_reference_bytes": target_bytes,
            "item_context_sha256": item_context_sha256,
            "item_context_bytes": item_context_bytes,
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
            "--prediction-batch-size",
            str(prediction_batch_size),
        ],
        cwd=_REPO_ROOT,
        check=True,
    )

    manifest_path = export_dir / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan.validate_export_manifest(manifest)
    if manifest.get("schema_version") != "growthevo.obd-export.v3":
        raise RuntimeError("full OBD export requires the memory-bounded v3 manifest")
    if manifest.get("action_distribution_storage") != "shared_context_free":
        raise RuntimeError("full OBD export did not use memory-bounded action probabilities")
    if manifest.get("q_prediction_storage") != "compact_factual_and_target":
        raise RuntimeError("full OBD export did not use compact Q predictions")

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
                "growth_evo_commit_sha": _git_sha(),
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
        description="Run the preregistered full Open Bandit OPE benchmark."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help=(
            "Existing full OBD root with random/<campaign>/<campaign>.csv and "
            "bts/<campaign>/<campaign>.csv. Omit to fetch only the pinned files "
            "needed by the checked-in campaign plan."
        ),
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
    parser.add_argument("--prediction-batch-size", type=int, default=50_000)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_full_obd(
        data_root=args.data_root,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        plan_path=args.plan,
        prediction_batch_size=args.prediction_batch_size,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
