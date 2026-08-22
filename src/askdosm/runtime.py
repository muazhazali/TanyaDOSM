"""Runtime compatibility checks."""

from __future__ import annotations

import sys


def require_supported_python() -> None:
    """Fail early with an actionable message on unsupported interpreters."""
    if sys.version_info[:2] != (3, 14):
        version = ".".join(map(str, sys.version_info[:3]))
        raise RuntimeError(
            f"TanyaDOSM requires Python 3.14.x; current interpreter is {version}. "
            "Run `uv sync` and launch commands through `uv run`."
        )
