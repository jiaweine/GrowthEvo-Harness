from __future__ import annotations

import importlib.metadata
import sys
import tomllib
from pathlib import Path

import growthevo
from growthevo import cli
from growthevo._version import __version__ as source_version


ROOT = Path(__file__).resolve().parents[1]


def _configuration() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _project() -> dict[str, object]:
    return _configuration()["project"]


def test_project_uses_single_source_dynamic_version() -> None:
    configuration = _configuration()
    project = configuration["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    assert configuration["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "growthevo._version.__version__"
    }


def test_source_public_and_installed_distribution_versions_match() -> None:
    assert growthevo.__version__ == source_version
    assert importlib.metadata.version("growthevo-harness") == source_version


def test_installed_cli_entrypoints_use_version_aware_wrappers() -> None:
    scripts = _project()["scripts"]
    assert scripts["growthevo-locked-ope"] == "growthevo.cli:locked_ope_main"
    assert scripts["growthevo-locked-targeting"] == "growthevo.cli:locked_targeting_main"


def test_locked_ope_cli_reports_version_without_loading_benchmark_args(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(sys, "argv", ["growthevo-locked-ope", "--version"])
    assert cli.locked_ope_main() == 0
    assert capsys.readouterr().out == f"growthevo-locked-ope {source_version}\n"


def test_locked_targeting_cli_reports_version_without_loading_benchmark_args(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(sys, "argv", ["growthevo-locked-targeting", "--version"])
    assert cli.locked_targeting_main() == 0
    assert capsys.readouterr().out == f"growthevo-locked-targeting {source_version}\n"
