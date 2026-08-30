from __future__ import annotations

import sys
from collections.abc import Callable

from . import __version__


def _dispatch(program: str, main: Callable[[], int]) -> int:
    if sys.argv[1:] == ["--version"]:
        print(f"{program} {__version__}")
        return 0
    return main()


def locked_ope_main() -> int:
    if sys.argv[1:] == ["--version"]:
        print(f"growthevo-locked-ope {__version__}")
        return 0
    from .bench.locked_ope_cli import main

    return main()


def locked_targeting_main() -> int:
    if sys.argv[1:] == ["--version"]:
        print(f"growthevo-locked-targeting {__version__}")
        return 0
    from .bench.locked_targeting_cli import main

    return main()
