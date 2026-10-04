from __future__ import annotations

from pathlib import Path


_README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_uses_balanced_github_math_fences_when_present() -> None:
    text = _README.read_text(encoding="utf-8")

    # Avoid the display-dollar rendering bug that previously affected the README.
    # The product-first landing page does not require mathematical sections, but if
    # fenced GitHub math is introduced again it must remain balanced and non-empty.
    assert "$$" not in text

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "```math":
            index += 1
            continue
        index += 1
        body_lines = 0
        while index < len(lines) and lines[index].strip() != "```":
            body_lines += 1
            index += 1
        assert index < len(lines), "README contains an unclosed fenced math block"
        assert body_lines > 0, "README contains an empty fenced math block"
        index += 1
