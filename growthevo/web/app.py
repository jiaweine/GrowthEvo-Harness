from __future__ import annotations

from pathlib import Path
from typing import Any

from .data import build_dashboard_payload

STATIC_DIR = Path(__file__).with_name("static")


def create_app() -> Any:
    """Create the optional GrowthEvo web application."""

    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise RuntimeError(
            "GrowthEvo web dependencies are not installed. "
            "Install them with: pip install -e '.[web]'"
        ) from exc

    app = FastAPI(
        title="GrowthEvo Web",
        version="1",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "growthevo-web"}

    @app.get("/api/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        return build_dashboard_payload()

    @app.get("/api/capabilities", tags=["dashboard"])
    def capabilities() -> list[dict[str, str]]:
        payload = build_dashboard_payload()
        return payload["capabilities"]

    @app.get("/api/evidence", tags=["dashboard"])
    def evidence() -> list[dict[str, Any]]:
        payload = build_dashboard_payload()
        return payload["evidence"]

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
