from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.ci_changed_paths import PROFILES, changed_paths, matches_profile


def test_each_profile_tracks_its_workflow_and_shared_matcher() -> None:
    for profile, patterns in PROFILES.items():
        assert "tools/ci_changed_paths.py" in patterns, profile
        assert "tests/test_ci_changed_paths.py" in patterns, profile

    assert matches_profile("product-auth", ["growthevo/web/auth.py"])
    assert matches_profile("product-persistence", ["growthevo/web/persistence.py"])
    assert matches_profile("product-stress", ["tests/test_product_api.py"])
    assert matches_profile("product-surface", ["apps/mobile/App.tsx"])
    assert matches_profile("codeql", ["scripts/stress_product.py"])


def test_irrelevant_document_does_not_activate_product_or_codeql_gates() -> None:
    paths = ["docs/repository_governance_audit.md"]
    for profile in PROFILES:
        assert matches_profile(profile, paths) is False, profile


def test_all_zero_base_sha_fails_closed() -> None:
    with pytest.raises(ValueError, match="all-zero"):
        changed_paths(base="0" * 40, head="1" * 40)


def test_changed_paths_reads_exact_git_diff(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "ci@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=tmp_path, check=True)

    tracked = tmp_path / "README.md"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    tracked.write_text("two\n", encoding="utf-8")
    added = tmp_path / "growthevo" / "web" / "auth.py"
    added.parent.mkdir(parents=True)
    added.write_text("# auth\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "head"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    paths = changed_paths(base=base, head=head, root=tmp_path)
    assert paths == ("README.md", "growthevo/web/auth.py")
    assert matches_profile("product-auth", paths) is True
