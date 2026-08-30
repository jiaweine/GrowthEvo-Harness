from __future__ import annotations

import sys

from . import __version__


def _print_version_if_requested(program: str) -> bool:
    if sys.argv[1:] != ["--version"]:
        return False
    print(f"{program} {__version__}")
    return True


def locked_ope_main() -> int:
    if _print_version_if_requested("growthevo-locked-ope"):
        return 0
    from .bench.locked_ope_cli import main

    return main()


def locked_targeting_main() -> int:
    if _print_version_if_requested("growthevo-locked-targeting"):
        return 0
    from .bench.locked_targeting_cli import main

    return main()
