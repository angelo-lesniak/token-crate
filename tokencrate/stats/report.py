"""The Markdown stats report the CLI prints and saves, and the scope line
both renderers lead with."""

from __future__ import annotations

import time

from .tables import DEFINITIONS, build_tables
from .transcripts import Filter, Session

RECENT_HOURS = 24


def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def recent_clause(sessions: list[Session], selection: Filter | None = None, now: float | None = None) -> str:
    """How much of the report is from the last 24 hours (sessions by their
    last message, as `--since` counts them); empty when `--since` already
    cuts inside that window, so the clause never repeats the filter."""
    now = time.time() if now is None else now
    cutoff = now - RECENT_HOURS * 3600
    # A `--since 24h` resolved moments before the render is inside the day.
    if selection and selection.since is not None and selection.since.timestamp() > cutoff - 60:
        return ""
    recent = [session for session in sessions if session.last_at is not None and session.last_at >= cutoff]
    if not recent:
        return f"none in the last {RECENT_HOURS} h"
    requests = sum(len(session.requests) for session in recent)
    return f"{plural(len(recent), 'session')} and {plural(requests, 'request')} in the last {RECENT_HOURS} h"


def meta_text(sessions: list[Session], selection: Filter | None = None, now: float | None = None) -> str:
    """The report's one-line scope: counts, the filters or their absence,
    and the last day's share."""
    requests = sum(len(session.requests) for session in sessions)
    agent = f"agent {selection.agent}" if selection and selection.agent else "all agents"
    since = f"since {selection.since.isoformat(timespec='seconds')}" if selection and selection.since else "all time"
    recent = recent_clause(sessions, selection, now)
    return f"{plural(len(sessions), 'session')}, {plural(requests, 'request')}, {agent}, {since}" + (
        f"; {recent}" if recent else ""
    )


def report(sessions: list[Session], selection: Filter | None = None, slots: dict[str, int] | None = None) -> str:
    """The Markdown stats report."""
    lines = ["# TokenCrate stats report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- Scope: {meta_text(sessions, selection)}")
    for table in build_tables(sessions, slots):
        lines += ["", f"## {table.title}", ""]
        if not table.rows:
            lines.append(table.empty_note)
            continue
        lines.append("| " + " | ".join(table.header) + " |")
        lines.append("| " + " | ".join("---:" if numeric else "---" for numeric in table.numeric) + " |")
        lines += ["| " + " | ".join(row) + " |" for row in table.rows]
    lines += ["", "## Definitions", ""]
    lines += [f"- **{term}**: {text}" for term, text in DEFINITIONS]
    return "\n".join(lines) + "\n"
