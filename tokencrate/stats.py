"""Usage statistics from the retained agent transcripts.

`stats` walks the retained sessions directories below LLM_AGENTS_DIR (the
same paths `session.PERSISTENT_DIRECTORIES` binds into the containers) and
reads usage numbers and metadata from every transcript entry: token
counts, provider and model names, stop reasons, tool names and error
flags, and the per-message timings oh-my-pi writes and pi writes with the
`metrics` agent set. Message content, session names, and
working-directory paths stay out of the report. Transcripts are agent
output, so the reader stays defensive: only regular files that resolve
below the agents directory are read (an agent writes its retained
directories and could plant a symbolic link), one line at a time and up to
LINE_LIMIT characters, and an unreadable file or undecodable line is
skipped, as a running agent may end a transcript mid-line.

One pass over the transcripts (`read_sessions`) feeds every output, so the
numbers cannot drift apart: the `Table` model from `build_tables` carries
the aggregated cells, `report` renders it as the Markdown the CLI prints
and saves, and `statspage` renders the same tables as the HTML page and
serves it.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import TokenCrateError
from .session import AGENTS, PERSISTENT_DIRECTORIES

# The per-request context sizes the capacity columns count: would a slot
# of this size have fit the request?
CONTEXT_STEPS = ((16384, "16K"), (32768, "32K"), (49152, "48K"))
# The longest transcript line that is parsed; real entries stay far below
# (a compaction of a full 64K context serializes to about 256 KB).
LINE_LIMIT = 8 * 1024 * 1024
# The largest token count a transcript can claim: the biggest integer a
# browser's JSON holds exactly, so the page's numbers stay faithful.
TOKEN_LIMIT = 2**53
# An entry's ISO timestamp is at most this long before it is parsed, so a
# hostile string never reaches the parser (whose error names the input).
TIMESTAMP_LIMIT = 40
# A thinking level as pi and oh-my-pi spell them (off, low, xhigh ...).
LEVEL_RE = re.compile(r"[a-z]{1,16}")
# `--since`: a duration back from now, or an ISO date or date-time.
DURATION_RE = re.compile(r"([1-9][0-9]{0,5})([mhdw])")
DURATION_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
FOOTNOTE = (
    "Context is one request as the server saw it: `usage.totalTokens` = input + cacheRead + cacheWrite "
    "+ output; the `>` columns count the requests one slot of that size would not have fit. First request "
    "= input + cacheRead + cacheWrite of a session's first assistant message. Cache-read share = cacheRead "
    "/ (input + cacheRead). Token sums count input and output once per request; summing context would "
    "re-count the conversation every turn. A request whose provider reported no usage counts with zeros. "
    "Percentiles are nearest-rank observations. Turns count a session's user messages; a session's duration is "
    "the time between its first and last message. A request's thinking level is the last level change before it. "
    "Timings: oh-my-pi records `ttft` and `duration` itself; pi records "
    "them through the `metrics` agent set, from the moment the request is sent (provider retries included) to the "
    "first streamed content and to the final message, for completed answers only. The two agents measure "
    "differently, so their rows stay apart."
)
NO_TIMINGS = (
    "No timed requests: oh-my-pi transcripts carry `ttft` and `duration`; pi transcripts carry them when the "
    "`metrics` agent set is loaded."
)
NO_LEVELS = "No thinking levels: no transcript carries a `thinking_level_change` entry before its requests."


@dataclass
class Request:
    provider: str
    model: str
    input: int
    output: int
    cache_read: int
    cache_write: int
    context: int
    stop_reason: str
    ttft_ms: float | None
    duration_ms: float | None
    # The thinking level current when the request was made ("?" before
    # any level entry).
    level: str = "?"


@dataclass
class Session:
    agent: str
    requests: list[Request] = field(default_factory=list)
    tool_calls: int = 0
    tool_errors: int = 0
    compaction_tokens: list[int] = field(default_factory=list)
    # User messages, and the first and last message timestamps.
    turns: int = 0
    first_at: float | None = None
    last_at: float | None = None
    level: str = "?"

    @property
    def duration_s(self) -> float | None:
        if self.first_at is None or self.last_at is None:
            return None
        return max(0.0, self.last_at - self.first_at)

    @property
    def peak_context(self) -> int:
        return max(request.context for request in self.requests)

    @property
    def first_request(self) -> int:
        first = self.requests[0]
        return first.input + first.cache_read + first.cache_write


def sessions_directory(agent: str) -> str:
    """The one retained home path that holds transcripts (`.../sessions`)."""
    return next(path for path in PERSISTENT_DIRECTORIES[agent] if path.endswith("/sessions"))


def transcript_files(agents_dir: Path, agent: str) -> list[Path]:
    """Every transcript below the retained sessions directories of `agent`,
    one directory per project home below `agents_dir/<agent>`: regular
    files whose resolved path stays below the agents directory, so a
    symbolic link an agent planted cannot route the reader elsewhere."""
    root = Path(os.path.realpath(agents_dir))
    return sorted(
        path
        for path in (agents_dir / agent).glob(f"*/{sessions_directory(agent)}/**/*.jsonl")
        if path.is_file() and Path(os.path.realpath(path)).is_relative_to(root)
    )


def integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, float):
        value = int(value) if value.is_integer() else 0
    if not isinstance(value, int):
        return 0
    # Clamped so a hostile count cannot push the page's embedded numbers
    # past what a browser holds exactly, or a path left of the plot.
    return min(max(value, 0), TOKEN_LIMIT)


def duration(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def timestamp(value: object) -> float | None:
    """An entry's ISO timestamp as epoch seconds; None for anything else."""
    if not isinstance(value, str) or len(value) > TIMESTAMP_LIMIT:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def since_cutoff(value: str, now: datetime | None = None) -> datetime:
    """The `--since` value as an absolute point in time: `<n>m|h|d|w` back
    from now, or an ISO date or date-time (naive means local time)."""
    now = now or datetime.now().astimezone()
    try:
        if match := DURATION_RE.fullmatch(value):
            return now - timedelta(**{DURATION_UNITS[match.group(2)]: int(match.group(1))})
        if len(value) <= TIMESTAMP_LIMIT:
            parsed = datetime.fromisoformat(value)
            # A value at the edge of the calendar fails here, not above.
            return parsed if parsed.tzinfo else parsed.astimezone()
    except (ValueError, OverflowError):
        pass
    raise TokenCrateError(
        f"--since requires a duration such as 30m, 12h, 7d, or 2w, or an ISO date or date-time: {value!r}"
    )


def read_request(message: dict) -> Request | None:
    """One assistant message as a request record; None without a usage
    object (an errored turn has none)."""
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    tokens = {key: integer(usage.get(key)) for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")}
    context = tokens["totalTokens"] or sum(value for key, value in tokens.items() if key != "totalTokens")
    context = min(context, TOKEN_LIMIT)
    return Request(
        provider=str(message.get("provider") or "?"),
        model=str(message.get("model") or "?"),
        input=tokens["input"],
        output=tokens["output"],
        cache_read=tokens["cacheRead"],
        cache_write=tokens["cacheWrite"],
        context=context,
        stop_reason=str(message.get("stopReason") or "?"),
        ttft_ms=duration(message.get("ttft")),
        duration_ms=duration(message.get("duration")),
    )


def level_name(value: object) -> str:
    return value if isinstance(value, str) and LEVEL_RE.fullmatch(value) else "?"


def read_session(path: Path, agent: str) -> Session | None:
    """The usage records of one transcript; None for a file without an
    assistant message (opened and abandoned, or not a transcript at all)."""
    result = Session(agent)
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in iter(lambda: handle.readline(LINE_LIMIT), ""):
                read_line(line, result)
    except OSError:
        return None
    return result if result.requests else None


def read_line(line: str, result: Session) -> None:
    """One transcript entry into the session's counts; anything that is not
    a well-formed entry of a known kind is ignored."""
    try:
        entry = json.loads(line)
    except ValueError:  # malformed JSON, or an integer past Python's digit limit
        return
    if not isinstance(entry, dict):
        return
    if entry.get("type") == "compaction":
        result.compaction_tokens.append(integer(entry.get("tokensBefore")))
        return
    if entry.get("type") == "thinking_level_change":
        result.level = level_name(entry.get("thinkingLevel"))
        return
    message = entry.get("message") if entry.get("type") == "message" else None
    if not isinstance(message, dict):
        return
    at = timestamp(entry.get("timestamp"))
    if at is not None:
        result.first_at = at if result.first_at is None else min(result.first_at, at)
        result.last_at = at if result.last_at is None else max(result.last_at, at)
    if message.get("role") == "assistant":
        request = read_request(message)
        if request:
            request.level = result.level
            result.requests.append(request)
    elif message.get("role") == "toolResult":
        result.tool_calls += 1
        result.tool_errors += bool(message.get("isError"))
    elif message.get("role") == "user":
        result.turns += 1


@dataclass(frozen=True)
class Filter:
    """What `--since` and `--agent` keep: sessions of one agent, and sessions
    whose last message is at or after the cutoff (a session counts whole)."""

    since: datetime | None = None
    agent: str = ""

    def keeps(self, session: Session) -> bool:
        if self.agent and session.agent != self.agent:
            return False
        if self.since is not None:
            return session.last_at is not None and session.last_at >= self.since.timestamp()
        return True

    def describe(self) -> str:
        parts = []
        if self.agent:
            parts.append(f"agent {self.agent}")
        if self.since is not None:
            parts.append(f"since {self.since.isoformat(timespec='seconds')}")
        return ", ".join(parts)


def read_sessions(agents_dir: Path, selection: Filter | None = None) -> list[Session]:
    selection = selection or Filter()
    found = False
    sessions = []
    for agent in AGENTS:
        for path in transcript_files(agents_dir, agent):
            if session := read_session(path, agent):
                found = True
                if selection.keeps(session):
                    sessions.append(session)
    if not sessions:
        if found:
            raise TokenCrateError(f"no agent transcripts match {selection.describe()} below {agents_dir}")
        raise TokenCrateError(
            f"no agent transcripts below {agents_dir}; they are retained once an agent session answered"
        )
    return sessions


def percentile(values: list, fraction: float):
    """Nearest-rank percentile: an observed value, defined for any n >= 1."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def cell(value: object) -> str:
    """A transcript-supplied string as one Markdown table cell."""
    return " ".join(str(value).split())[:80].replace("|", "/") or "?"


def share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def duration_text(seconds: float) -> str:
    """Seconds as `38s`, `4m 30s`, or `1h 12m`."""
    whole = round(seconds)
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m {whole % 60:02d}s"
    return f"{whole // 3600}h {whole % 3600 // 60:02d}m"


# --- The tables, computed once for both renderers -------------------------


@dataclass
class Table:
    title: str
    header: tuple[str, ...]
    numeric: tuple[bool, ...]
    rows: list[list[str]]
    empty_note: str = ""


def session_cells(label: str, sessions: list[Session]) -> list[str]:
    peaks = [session.peak_context for session in sessions]
    firsts = [session.first_request for session in sessions]
    durations = [seconds for session in sessions if (seconds := session.duration_s) is not None]
    compactions = [tokens for session in sessions for tokens in session.compaction_tokens]
    compacted = f"{len(compactions)} (p50 before: {percentile(compactions, 0.5)})" if compactions else "0"
    return [
        label,
        str(len(sessions)),
        str(sum(len(session.requests) for session in sessions)),
        str(percentile([session.turns for session in sessions], 0.5)),
        duration_text(percentile(durations, 0.5)) if durations else "-",
        duration_text(percentile(durations, 0.9)) if durations else "-",
        str(percentile(firsts, 0.5)),
        str(percentile(peaks, 0.5)),
        str(percentile(peaks, 0.9)),
        str(max(peaks)),
        compacted,
    ]


def request_cells(labels: list[str], requests: list[Request]) -> list[str]:
    contexts = [request.context for request in requests]
    prompt = sum(request.input + request.cache_read for request in requests)
    return [
        *labels,
        str(len(requests)),
        str(sum(request.input for request in requests)),
        str(sum(request.output for request in requests)),
        share(sum(request.cache_read for request in requests), prompt),
        str(percentile(contexts, 0.5)),
        str(percentile(contexts, 0.9)),
        str(max(contexts)),
        *(share(sum(context > step for context in contexts), len(contexts)) for step, _ in CONTEXT_STEPS),
    ]


def by_provider_and_model(requests: list[Request]) -> list[tuple[tuple[str, str], list[Request]]]:
    grouped: dict[tuple[str, str], list[Request]] = {}
    for request in requests:
        grouped.setdefault((request.provider, request.model), []).append(request)
    return sorted(grouped.items(), key=lambda item: -len(item[1]))


def build_tables(sessions: list[Session]) -> list[Table]:
    by_agent = {agent: [session for session in sessions if session.agent == agent] for agent in AGENTS}
    present = {agent: grouped for agent, grouped in by_agent.items() if grouped}
    requests = [request for session in sessions for request in session.requests]
    step_headers = tuple(f">{label}" for _, label in CONTEXT_STEPS)
    request_headers = ("Requests", "Input", "Output", "Cache-read share", "Context p50", "p90", "max", *step_headers)

    tables = [
        Table(
            "Sessions",
            (
                "Agent",
                "Sessions",
                "Requests",
                "Turns p50",
                "Duration p50",
                "p90",
                "First request p50",
                "Peak context p50",
                "p90",
                "max",
                "Compactions",
            ),
            (False, True, True, True, True, True, True, True, True, True, False),
            [session_cells(agent, grouped) for agent, grouped in present.items()],
        )
    ]

    request_rows = [
        request_cells([agent], [request for session in grouped for request in session.requests])
        for agent, grouped in present.items()
    ]
    if len(present) > 1:
        request_rows.append(request_cells(["all"], requests))
    tables.append(
        Table("Requests", ("Agent", *request_headers), (False, *(True,) * len(request_headers)), request_rows)
    )

    tables.append(
        Table(
            "Providers and models",
            ("Provider", "Model", *request_headers),
            (False, False, *(True,) * len(request_headers)),
            [
                request_cells([cell(provider), cell(model)], grouped)
                for (provider, model), grouped in by_provider_and_model(requests)
            ],
        )
    )

    tool_rows = []
    for agent, grouped in present.items():
        reasons = Counter(request.stop_reason for session in grouped for request in session.requests)
        tool_rows.append(
            [
                agent,
                str(sum(session.tool_calls for session in grouped)),
                str(sum(session.tool_errors for session in grouped)),
                ", ".join(f"{cell(reason)} {count}" for reason, count in reasons.most_common()),
            ]
        )
    tables.append(
        Table(
            "Tools and stop reasons",
            ("Agent", "Tool calls", "Tool errors", "Stop reasons"),
            (False, True, True, False),
            tool_rows,
        )
    )

    level_rows = []
    for agent, grouped in present.items():
        by_level: dict[str, list[Request]] = {}
        for session in grouped:
            for request in session.requests:
                by_level.setdefault(request.level, []).append(request)
        for level, level_requests in sorted(by_level.items(), key=lambda item: -len(item[1])):
            outputs = [request.output for request in level_requests]
            level_rows.append(
                [agent, level, str(len(level_requests)), str(percentile(outputs, 0.5)), str(percentile(outputs, 0.9))]
            )
    tables.append(
        Table(
            "Thinking levels",
            ("Agent", "Level", "Requests", "Output p50", "p90"),
            (False, False, True, True, True),
            level_rows if any(row[1] != "?" for row in level_rows) else [],
            empty_note=NO_LEVELS,
        )
    )

    # Keyed by agent as well: both agents name the same provider and model,
    # and each measures its timings by its own definition.
    timing_rows = []
    for agent, grouped in present.items():
        timed = [
            request
            for session in grouped
            for request in session.requests
            if request.ttft_ms is not None and request.duration_ms is not None
        ]
        for (provider, model), timed_group in by_provider_and_model(timed):
            timing_rows.append(
                [
                    agent,
                    cell(provider),
                    cell(model),
                    str(len(timed_group)),
                    f"{percentile([request.ttft_ms for request in timed_group], 0.5):.0f}",
                    f"{percentile([request.ttft_ms for request in timed_group], 0.9):.0f}",
                    f"{percentile([request.duration_ms for request in timed_group], 0.5):.0f}",
                    f"{percentile([request.duration_ms for request in timed_group], 0.9):.0f}",
                ]
            )
    tables.append(
        Table(
            "Timings",
            ("Agent", "Provider", "Model", "Requests", "TTFT p50 ms", "p90", "Duration p50 ms", "p90"),
            (False, False, False, True, True, True, True, True),
            timing_rows,
            empty_note=NO_TIMINGS,
        )
    )
    return tables


def summary_line(sessions: list[Session], selection: Filter | None = None) -> str:
    requests = sum(len(session.requests) for session in sessions)
    line = f"Transcripts: {len(sessions)} session(s), {requests} request(s) below LLM_AGENTS_DIR"
    described = selection.describe() if selection else ""
    return f"{line} ({described})" if described else line


def report(sessions: list[Session], selection: Filter | None = None) -> str:
    """The Markdown stats report."""
    lines = ["# TokenCrate stats report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- {summary_line(sessions, selection)}")
    for table in build_tables(sessions):
        lines += ["", f"## {table.title}", ""]
        if not table.rows:
            lines.append(table.empty_note)
            continue
        lines.append("| " + " | ".join(table.header) + " |")
        lines.append("| " + " | ".join("---:" if numeric else "---" for numeric in table.numeric) + " |")
        lines += ["| " + " | ".join(row) + " |" for row in table.rows]
    lines += ["", FOOTNOTE]
    return "\n".join(lines) + "\n"
