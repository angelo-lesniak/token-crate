"""TokenCrate: pinned local-LLM and coding-agent containers for Docker and Podman.

The package is the whole command-line tool; ``bin/tokencrate`` is a shim that
runs ``python3 -m tokencrate``. Every module raises :class:`TokenCrateError`
for a user-facing failure; the dispatcher prints it as ``TokenCrate: <message>``
and exits 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The repository root: the package lives directly below it.
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TokenCrateError(Exception):
    """A safe, user-facing error message. An OSError is reported by the
    dispatcher the same way; no function converts it."""


def warn(message: str) -> None:
    """Print a one-line notice on stderr in the wrapper's voice."""
    print(f"TokenCrate: {message}", file=sys.stderr, flush=True)
