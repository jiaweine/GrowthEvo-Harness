from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def build(output: Path, source: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    (output / "assets").mkdir(parents=True)

    shutil.copy2(source / "index.html", output / "index.html")
    shutil.copy2(source / "manifest.webmanifest", output / "manifest.webmanifest")
    shutil.copy2(source / "service-worker.js", output / "service-worker.js")
    for name in (
        "styles.css",
        "layout.css",
        "dashboard.css",
        "agent.css",
        "responsive.css",
        "fidelity.css",
        "data.js",
        "views.js",
        "dashboard-page.js",
        "pages.js",
        "app.js",
        "icon.svg",
    ):
        shutil.copy2(source / name, output / "assets" / name)

    api_base = os.getenv("GROWTHEVO_API_BASE", "").strip().rstrip("/")
    mode = "api" if api_base else "demo"
    cfg = f"window.GROWTHEVO_CONFIG = {json.dumps({'MODE': mode, 'API_BASE': api_base}, ensure_ascii=False)};\n"
    (output / "assets" / "config.js").write_text(cfg, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the static GrowthEvo GitHub Pages artifact.")
    parser.add_argument("--source", type=Path, default=Path("growthevo/web/static"))
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()
    build(args.output, args.source)
