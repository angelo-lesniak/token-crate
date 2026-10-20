"""The agent home as every module sees it: the agents, where the home is
mounted in the container, and which of its paths the host retains.

A leaf: `runtime` creates the host homes at `init`, `stats` reads the
transcripts from them, and `session` binds them, so none of them can
import the others for these names.
"""

from __future__ import annotations

AGENTS = ("pi", "omp")
HOME_IN_CONTAINER = "/home/agent"
# The home is a per-container tmpfs; these are the only home paths bound
# from the host, read-write. OMP externalizes transcript images to blobs;
# its other two directories retain --continue selection and references to
# custom transcript files for storage GC. Paths are relative to the home.
PERSISTENT_DIRECTORIES = {
    "pi": (".pi/agent/sessions",),
    "omp": tuple(f".omp/agent/{name}" for name in ("sessions", "blobs", "terminal-sessions", "custom-session-files")),
}


def persistent_directories(agent: str, state: str | None = None) -> tuple[str, ...]:
    """The home paths bound from the host: the transcript directories and,
    for a browser UI, the state directory its set declares."""
    return PERSISTENT_DIRECTORIES[agent] + ((state,) if state else ())
