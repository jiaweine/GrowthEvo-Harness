from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GrowthEvo web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
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
