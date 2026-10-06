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


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _default_workers() -> int:
    # Do not inherit hosting-platform WEB_CONCURRENCY implicitly. Every worker
    # owns independent DB/provider pools and circuit state, so process
    # multiplication must be an explicit GrowthEvo capacity decision.
    return _bounded_int_env("GROWTHEVO_WEB_WORKERS", 1, minimum=1, maximum=16)


def _default_limit_concurrency() -> int:
    return _bounded_int_env(
        "GROWTHEVO_HTTP_LIMIT_CONCURRENCY", 512, minimum=16, maximum=65535
    )


def _default_graceful_shutdown_seconds() -> int:
    return _bounded_int_env(
        "GROWTHEVO_HTTP_GRACEFUL_SHUTDOWN_SECONDS", 55, minimum=1, maximum=300
    )


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
        workers=1 if args.reload else _default_workers(),
        limit_concurrency=_default_limit_concurrency(),
        timeout_graceful_shutdown=_default_graceful_shutdown_seconds(),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
