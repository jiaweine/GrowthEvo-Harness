from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_full_data_dispatches_are_serialized_per_benchmark_without_cancellation() -> None:
    cases = (
        ("full-criteo-pr-validation.yml", "full-criteo-research-validation"),
        ("full-obd-pr-validation.yml", "full-obd-research-validation"),
    )

    for filename, group in cases:
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "workflow_dispatch:" in workflow
        assert f"concurrency:\n  group: {group}\n  queue: max\n  cancel-in-progress: false" in workflow
        assert "group: full-criteo-${{ github.ref }}" not in workflow
        assert "group: full-obd-${{ github.ref }}" not in workflow


def test_distinct_full_data_benchmarks_do_not_share_a_concurrency_group() -> None:
    criteo = (WORKFLOWS / "full-criteo-pr-validation.yml").read_text(encoding="utf-8")
    obd = (WORKFLOWS / "full-obd-pr-validation.yml").read_text(encoding="utf-8")

    assert "group: full-criteo-research-validation" in criteo
    assert "group: full-obd-research-validation" in obd
    assert "group: full-obd-research-validation" not in criteo
    assert "group: full-criteo-research-validation" not in obd
