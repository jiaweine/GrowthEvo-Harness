from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
import runpy


def test_operator_console_script_is_packaged() -> None:
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}
    assert scripts["growthevo-operator"] == "growthevo.cli:operator_main"


def test_production_operator_offline_demo_smoke(capsys) -> None:
    root = Path(__file__).resolve().parents[1]
    runpy.run_path(
        str(root / "examples" / "production_operator_demo.py"),
        run_name="__main__",
    )
    output = capsys.readouterr().out
    assert '"selected_candidate": "causal-winner"' in output
    assert '"promotion_eligible": true' in output
    assert '"runtime_remained_baseline": true' in output
    assert '"real_provider_claim": false' in output
