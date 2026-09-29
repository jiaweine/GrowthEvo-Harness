from __future__ import annotations

import argparse
from collections.abc import Sequence
import os


def _default_port() -> int:
    configured = os.getenv("PORT") or os.getenv("GROWTHEVO_PORT")
    if configured is None:
        return 8765
    try:
        port = int(configured)
    except ValueError as exc:
        raise ValueError("PORT/GROWTHEVO_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT/GROWTHEVO_PORT must be between 1 and 65535")
    return port


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GrowthEvo web dashboard.")
    parser.add_argument("--host", default=os.getenv("GROWTHEVO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, choices=range(1, 65536), default=_default_port())
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise SystemExit(
            "GrowthEvo web dependencies are not installed. "
            "Install them with: pip install -e '.[web]'"
        ) from exc

    uvicorn.run(
        "growthevo.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
