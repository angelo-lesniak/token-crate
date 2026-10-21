"""Usage statistics from the retained agent transcripts.

`transcripts` reads the retained sessions into usage records, `tables`
aggregates them for both renderers, and `report` renders the
Markdown the CLI prints and saves; this namespace re-exports that reading
and reporting API. The HTML page (`page`), the live sampler of the model
server (`live`), and the loopback server of `stats --serve` (`server`)
are imported by name, so a reader of the records pulls in none of the
container stack.
"""

from __future__ import annotations

from .report import report
from .tables import DEFINITIONS, Table, build_tables
from .transcripts import Filter, Request, Session, read_sessions, since_cutoff

__all__ = [
    "DEFINITIONS",
    "Filter",
    "Request",
    "Session",
    "Table",
    "build_tables",
    "read_sessions",
    "report",
    "since_cutoff",
]
