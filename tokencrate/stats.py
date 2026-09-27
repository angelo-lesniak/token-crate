"""Usage statistics from the retained agent transcripts.

`stats` walks the retained sessions directories below LLM_AGENTS_DIR (the
same paths `session.PERSISTENT_DIRECTORIES` binds into the containers) and
reads usage numbers and metadata from every transcript entry: token
counts, provider and model names, stop reasons, tool names and error
flags, and oh-my-pi's per-message timings. Message content, session names,
and working-directory paths stay out of the report. Transcripts are agent
output, so the reader stays defensive: only regular files that resolve
below the agents directory are read (an agent writes its retained
directories and could plant a symbolic link), one line at a time and up to
LINE_LIMIT characters, and an unreadable file or undecodable line is
skipped, as a running agent may end a transcript mid-line. The report
function returns Markdown; the CLI prints it and saves it under reports/.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import TokenCrateError
from .session import AGENTS, PERSISTENT_DIRECTORIES

# The per-request context sizes the capacity columns count: would a slot
# of this size have fit the request?
CONTEXT_STEPS = ((16384, "16K"), (32768, "32K"), (49152, "48K"))
# The longest transcript line that is parsed; real entries stay far below
# (a compaction of a full 64K context serializes to about 256 KB).
LINE_LIMIT = 8 * 1024 * 1024


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


@dataclass
class Session:
    agent: str
    requests: list[Request] = field(default_factory=list)
    tool_calls: int = 0
    tool_errors: int = 0
    compaction_tokens: list[int] = field(default_factory=list)

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
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, float) and value.is_integer() else 0


def duration(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def read_request(message: dict) -> Request | None:
    """One assistant message as a request record; None without a usage
    object (an errored turn has none)."""
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    tokens = {key: integer(usage.get(key)) for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")}
    context = tokens["totalTokens"] or sum(value for key, value in tokens.items() if key != "totalTokens")
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
    except json.JSONDecodeError:
        return
    if not isinstance(entry, dict):
        return
    if entry.get("type") == "compaction":
        result.compaction_tokens.append(integer(entry.get("tokensBefore")))
        return
    message = entry.get("message") if entry.get("type") == "message" else None
    if not isinstance(message, dict):
        return
    if message.get("role") == "assistant":
        request = read_request(message)
        if request:
            result.requests.append(request)
    elif message.get("role") == "toolResult":
        result.tool_calls += 1
        result.tool_errors += bool(message.get("isError"))


def read_sessions(agents_dir: Path) -> list[Session]:
    sessions = [
        session
        for agent in AGENTS
        for path in transcript_files(agents_dir, agent)
        if (session := read_session(path, agent))
    ]
    if not sessions:
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


def session_row(label: str, sessions: list[Session]) -> str:
    peaks = [session.peak_context for session in sessions]
    firsts = [session.first_request for session in sessions]
    compactions = [tokens for session in sessions for tokens in session.compaction_tokens]
    compacted = f"{len(compactions)} (p50 before: {percentile(compactions, 0.5)})" if compactions else "0"
    return (
        f"| {label} | {len(sessions)} | {sum(len(session.requests) for session in sessions)} "
        f"| {percentile(firsts, 0.5)} | {percentile(peaks, 0.5)} | {percentile(peaks, 0.9)} | {max(peaks)} "
        f"| {compacted} |"
    )


def request_row(label: str, requests: list[Request]) -> str:
    contexts = [request.context for request in requests]
    prompt = sum(request.input + request.cache_read for request in requests)
    steps = " | ".join(share(sum(context > step for context in contexts), len(contexts)) for step, _ in CONTEXT_STEPS)
    return (
        f"| {label} | {len(requests)} | {sum(request.input for request in requests)} "
        f"| {sum(request.output for request in requests)} "
        f"| {share(sum(request.cache_read for request in requests), prompt)} "
        f"| {percentile(contexts, 0.5)} | {percentile(contexts, 0.9)} | {max(contexts)} | {steps} |"
    )


def report(agents_dir: Path) -> str:
    """The Markdown stats report over every retained transcript."""
    sessions = read_sessions(agents_dir)
    by_agent = {agent: [session for session in sessions if session.agent == agent] for agent in AGENTS}
    requests = [request for session in sessions for request in session.requests]

    lines = ["# TokenCrate stats report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- Transcripts: {len(sessions)} session(s), {len(requests)} request(s) below LLM_AGENTS_DIR")
    lines += [
        "",
        "## Sessions",
        "",
        "| Agent | Sessions | Requests | First request p50 | Peak context p50 | p90 | max | Compactions |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for agent, grouped in by_agent.items():
        if grouped:
            lines.append(session_row(agent, grouped))
    lines += [
        "",
        "## Requests",
        "",
        "| Agent | Requests | Input | Output | Cache-read share | Context p50 | p90 | max "
        f"| >{' | >'.join(label for _, label in CONTEXT_STEPS)} |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for agent, grouped in by_agent.items():
        if grouped:
            lines.append(request_row(agent, [request for session in grouped for request in session.requests]))
    if len([None for grouped in by_agent.values() if grouped]) > 1:
        lines.append(request_row("all", requests))

    lines += [
        "",
        "## Providers and models",
        "",
        "| Provider | Model | Requests | Input | Output | Cache-read share | Context p50 | p90 | max "
        f"| >{' | >'.join(label for _, label in CONTEXT_STEPS)} |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    by_model: dict[tuple[str, str], list[Request]] = {}
    for request in requests:
        by_model.setdefault((request.provider, request.model), []).append(request)
    for (provider, model), grouped in sorted(by_model.items(), key=lambda item: -len(item[1])):
        lines.append(request_row(f"{cell(provider)} | {cell(model)}", grouped))

    lines += [
        "",
        "## Tools and stop reasons",
        "",
        "| Agent | Tool calls | Tool errors | Stop reasons |",
        "| --- | ---: | ---: | --- |",
    ]
    for agent, grouped in by_agent.items():
        if not grouped:
            continue
        reasons = Counter(request.stop_reason for session in grouped for request in session.requests)
        listed = ", ".join(f"{cell(reason)} {count}" for reason, count in reasons.most_common())
        lines.append(
            f"| {agent} | {sum(session.tool_calls for session in grouped)} "
            f"| {sum(session.tool_errors for session in grouped)} | {listed} |"
        )

    timed = [request for request in requests if request.ttft_ms is not None and request.duration_ms is not None]
    lines += ["", "## Timings", ""]
    if timed:
        lines += [
            "| Provider | Model | Requests | TTFT p50 ms | p90 | Duration p50 ms | p90 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        by_timed: dict[tuple[str, str], list[Request]] = {}
        for request in timed:
            by_timed.setdefault((request.provider, request.model), []).append(request)
        for (provider, model), grouped in sorted(by_timed.items(), key=lambda item: -len(item[1])):
            ttfts = [request.ttft_ms for request in grouped]
            durations = [request.duration_ms for request in grouped]
            lines.append(
                f"| {cell(provider)} | {cell(model)} | {len(grouped)} "
                f"| {percentile(ttfts, 0.5):.0f} | {percentile(ttfts, 0.9):.0f} "
                f"| {percentile(durations, 0.5):.0f} | {percentile(durations, 0.9):.0f} |"
            )
    else:
        lines.append("No timed requests; only oh-my-pi transcripts carry `ttft` and `duration`.")

    lines += [
        "",
        "Context is one request as the server saw it: `usage.totalTokens` = input + cacheRead + cacheWrite "
        "+ output; the `>` columns count the requests one slot of that size would not have fit. First request "
        "= input + cacheRead + cacheWrite of a session's first assistant message. Cache-read share = cacheRead "
        "/ (input + cacheRead). Token sums count input and output once per request; summing context would "
        "re-count the conversation every turn. A request whose provider reported no usage counts with zeros. "
        "Percentiles are nearest-rank observations.",
    ]
    return "\n".join(lines) + "\n"
