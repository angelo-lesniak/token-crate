"""Reading the retained agent transcripts into usage records.

`read_sessions` walks the retained sessions directories below
LLM_AGENTS_DIR (the same paths `agenthome.PERSISTENT_DIRECTORIES` binds
into the containers) and reads usage numbers and metadata from every
transcript entry: token counts, provider and model names, stop reasons,
tool names and error flags, and the per-message timings oh-my-pi writes
and pi writes with the `metrics` agent set. Message content, session
names, and working-directory paths stay out of the records. Transcripts
are agent output, so the reader stays defensive: a file is checked
through the descriptor it is then read from, and only a regular file
below the agents directory is read (an agent writes its retained
directories and could put a link or a pipe in place of a transcript), one
line at a time and up to LINE_LIMIT characters, and an unreadable file or
undecodable line is skipped, as a running agent may end a transcript
mid-line.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .. import TokenCrateError
from ..agenthome import AGENTS, PERSISTENT_DIRECTORIES

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
    """Every transcript path below the retained sessions directories of
    `agent`, one directory per project home below `agents_dir/<agent>`;
    `open_transcript` decides what each one is when it is read."""
    return sorted((agents_dir / agent).glob(f"*/{sessions_directory(agent)}/**/*.jsonl"))


def open_transcript(path: Path, root: Path):
    """`path` opened for reading, checked as the object that is then read:
    the leaf is opened without following a link, and the descriptor must be
    a regular file whose real path (/proc/self/fd) stays below `root`, the
    resolved agents directory. A link or a FIFO an agent put in place
    between the listing and the read raises OSError instead of being
    followed or waited on."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
        if not regular or not Path(os.readlink(f"/proc/self/fd/{fd}")).is_relative_to(root):
            raise OSError(f"not a regular file below {root}: {path}")
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, encoding="utf-8", errors="replace")


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


def read_session(path: Path, agent: str, root: Path) -> Session | None:
    """The usage records of one transcript; None for a file without an
    assistant message (opened and abandoned, or not a transcript at all)
    and for anything `open_transcript` refuses."""
    result = Session(agent)
    try:
        with open_transcript(path, root) as handle:
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
    except (ValueError, RecursionError):  # malformed JSON, an integer past the digit limit, or nesting past the stack
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
    root = Path(os.path.realpath(agents_dir))
    for agent in AGENTS:
        for path in transcript_files(agents_dir, agent):
            if session := read_session(path, agent, root):
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
