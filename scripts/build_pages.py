from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_api_base(value: str | None) -> str:
    """Return a safe Pages API base or fail the build on a malformed value.

    GitHub Pages is HTTPS. A remote ``http://`` API would be blocked as mixed
    content and could expose requests in transit, so cleartext is only accepted
    for loopback development addresses.
    """
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    if any(char.isspace() for char in raw):
        raise ValueError("GROWTHEVO_API_BASE cannot contain whitespace")
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("GROWTHEVO_API_BASE is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("GROWTHEVO_API_BASE must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("GROWTHEVO_API_BASE must not embed credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("GROWTHEVO_API_BASE must not contain a query string or fragment")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("remote GROWTHEVO_API_BASE must use https to avoid mixed-content/insecure transport")
    return raw


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
        "product-pages.css",
        "responsive.css",
        "fidelity.css",
        "data.js",
        "runtime-ui.js",
        "product-data.js",
        "product-advanced-data.js",
        "views.js",
        "dashboard-page.js",
        "pages.js",
        "app.js",
        "icon.svg",
    ):
        shutil.copy2(source / name, output / "assets" / name)

    api_base = normalize_api_base(os.getenv("GROWTHEVO_API_BASE"))
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
