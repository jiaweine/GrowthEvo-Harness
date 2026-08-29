from __future__ import annotations

from pathlib import Path


_README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_uses_balanced_github_math_fences() -> None:
    text = _README.read_text(encoding="utf-8")

    # GitHub supports fenced `math` blocks and they proved more robust for this
    # README than display-dollar delimiters. Keep the original rendering bug from
    # reappearing during future documentation rewrites.
    assert "$$" not in text

    lines = text.splitlines()
    math_blocks = 0
    index = 0
    while index < len(lines):
        if lines[index].strip() != "```math":
            index += 1
            continue
        math_blocks += 1
        index += 1
        body_lines = 0
        while index < len(lines) and lines[index].strip() != "```":
            body_lines += 1
            index += 1
        assert index < len(lines), "README contains an unclosed fenced math block"
        assert body_lines > 0, "README contains an empty fenced math block"
        index += 1

    assert math_blocks >= 10, "README unexpectedly lost the documented math sections"
