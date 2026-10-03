from __future__ import annotations

import argparse
from collections.abc import Sequence
import os


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _default_port() -> int:
    configured = os.getenv("PORT") or os.getenv("GROWTHEVO_PORT")
    if configured is None:
        return 8765
    try:
        return _port(configured)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"invalid PORT/GROWTHEVO_PORT: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GrowthEvo web dashboard.")
    parser.add_argument("--host", default=os.getenv("GROWTHEVO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=_port, default=_default_port())
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
