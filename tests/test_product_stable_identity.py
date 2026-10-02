from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCANNED = [
    ROOT / "growthevo" / "web",
    ROOT / "apps" / "mobile" / "src",
    ROOT / "apps" / "mobile" / "App.tsx",
    ROOT / "apps" / "mobile" / "README.md",
    ROOT / "docs" / "product_surface.md",
    ROOT / "docs" / "deployment_architecture.md",
    ROOT / "docs" / "performance_testing.md",
    ROOT / "scripts" / "stress_product.py",
    ROOT / "scripts" / "stress_decision_semantics.py",
    ROOT / ".github" / "workflows" / "product-surface.yml",
]

FORBIDDEN = {
    "versioned public API path": re.compile(r"/api/v\d+\b", re.IGNORECASE),
    "numbered product identity field": re.compile(r"\b(?:policy|agent|harness)_version\b", re.IGNORECASE),
    "numbered action identity": re.compile(r"\b(?:free_shipping|coupon_10|push_reminder|email_guide|member_reminder|reactivation_card)_v\d+\b", re.IGNORECASE),
    "numbered policy shorthand": re.compile(r"\bpv_\d+\b", re.IGNORECASE),
    "numbered agent/harness generation": re.compile(r"\b(?:growth-agent|agent-growth|agent-creative|agent-operator|harness)-\d+(?:\.\d+)*(?:-[a-z0-9]+)?\b", re.IGNORECASE),
}


def _files() -> list[Path]:
    files: list[Path] = []
    for target in SCANNED:
        if target.is_dir():
            files.extend(path for path in target.rglob("*") if path.is_file() and path.suffix in {".py", ".js", ".html", ".md", ".json"})
        elif target.exists():
            files.append(target)
    return sorted(set(files))


def test_product_surface_keeps_one_stable_public_identity() -> None:
    failures: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {label}: {match.group(0)!r}")
    assert not failures, "\n" + "\n".join(failures)
