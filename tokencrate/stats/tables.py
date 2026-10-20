"""The aggregation of the usage records into tables, computed once for
both renderers.

One pass over the transcripts (`transcripts.read_sessions`) feeds every
output, so the numbers cannot drift apart: the `Table` model from
`build_tables` carries the aggregated cells, `report` renders it as the
Markdown the CLI prints and saves, and `page` renders the same tables as
the HTML page.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ..agenthome import AGENTS
from .transcripts import Request, Session

# The per-request context sizes the capacity columns count: would a slot
# of this size have fit the request?
CONTEXT_STEPS = ((16384, "16K"), (32768, "32K"), (49152, "48K"))
# The measures, defined once: the Markdown report's "Definitions" list and
# the HTML page's, in this order.
DEFINITIONS = (
    (
        "Context",
        "one request as the server saw it: `usage.totalTokens` = input + cacheRead + cacheWrite + output. "
        "Every observed context was already bounded by the slot it ran in and by the agent's compaction.",
    ),
    (
        "over 16K, 32K, 48K",
        "the share of requests that one slot of that size would not have fit.",
    ),
    (
        "Slot",
        "the context one request may use on a rendered preset: `ctx-size` / `parallel` "
        "(the preset's `ctx_size` and `parallel`), read back from the rendered model list. "
        '"Would not fit" counts every request in the report against that slot, whichever preset or provider served '
        "it; a preset fits when none of them exceeds its slot.",
    ),
    ("First request", "input + cacheRead + cacheWrite of a session's first assistant message."),
    ("Cache-read share", "cacheRead / (input + cacheRead)."),
    (
        "Input total, Output total",
        "input and output counted once per request; summing context would re-count the conversation every turn. "
        "A request whose provider reported no usage counts with zeros.",
    ),
    ("Percentiles", "nearest-rank observations."),
    ("Turns", "a session's user messages."),
    ("Length", "the time between a session's first and last message."),
    ("Compactions", 'the compaction entries of the sessions; "Before compaction" is the context each one replaced.'),
    ("Thinking level", "the last level change before a request."),
    (
        "TTFT, Duration",
        "oh-my-pi records `ttft` and `duration` itself; pi records them through the `metrics` agent set, from the "
        "moment the request is sent (provider retries included) to the first streamed content and to the final "
        "message, for completed answers only. The two agents measure differently, so their rows stay apart.",
    ),
)
NO_PRESETS = "No rendered presets: `up` renders them and writes the model list the wrapper reads back."
NO_TIMINGS = (
    "No timed requests: oh-my-pi transcripts carry `ttft` and `duration`; pi transcripts carry them when the "
    "`metrics` agent set is loaded."
)
NO_LEVELS = "No thinking levels: no transcript carries a `thinking_level_change` entry before its requests."
# The per-request columns, shared by the Requests and the Providers tables.
REQUEST_HEADERS = (
    "Requests",
    "Input total",
    "Output total",
    "Cache-read share",
    "Context p50",
    "Context p90",
    "Context max",
    *(f"over {label}" for _, label in CONTEXT_STEPS),
)


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


@dataclass
class Table:
    title: str
    header: tuple[str, ...]
    numeric: tuple[bool, ...]
    rows: list[list[str]]
    empty_note: str = ""
    # The last row sums the others (the page renders it as a footer).
    total: bool = False


def session_cells(label: str, sessions: list[Session]) -> list[str]:
    peaks = [session.peak_context for session in sessions]
    firsts = [session.first_request for session in sessions]
    durations = [seconds for session in sessions if (seconds := session.duration_s) is not None]
    compactions = [tokens for session in sessions for tokens in session.compaction_tokens]
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
        str(len(compactions)),
        str(percentile(compactions, 0.5)) if compactions else "-",
    ]


def fit_verdict(sessions: list[Session], slot: int) -> tuple[int, int, bool]:
    """How the report's requests measure against one slot: the requests and
    the sessions (by peak context) that exceed it, and whether it fits (none
    does). A request the server refused for its size is not in a transcript,
    so the counts are what a preset of this slot would have refused."""
    requests = [request for session in sessions for request in session.requests]
    over = sum(request.context > slot for request in requests)
    return over, sum(session.peak_context > slot for session in sessions), over == 0


def fit_rows(sessions: list[Session], slots: dict[str, int]) -> list[list[str]]:
    rows = []
    for preset, slot in sorted(slots.items()):
        over, sessions_over, fits = fit_verdict(sessions, slot)
        rows.append([preset, str(slot), str(over), str(sessions_over), "fits" if fits else "too small"])
    return rows


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


def preset_fit_table(sessions: list[Session], slots: dict[str, int]) -> Table:
    return Table(
        "Preset fit",
        ("Preset", "Slot", "Requests over slot", "Sessions over slot", "Fit"),
        (False, True, True, True, False),
        fit_rows(sessions, slots),
        empty_note=NO_PRESETS,
    )


def sessions_table(present: dict[str, list[Session]]) -> Table:
    return Table(
        "Sessions",
        (
            "Agent",
            "Sessions",
            "Requests",
            "Turns p50",
            "Length p50",
            "Length p90",
            "First request p50",
            "Peak context p50",
            "Peak context p90",
            "Peak context max",
            "Compactions",
            "Before compaction p50",
        ),
        (False, *(True,) * 11),
        [session_cells(agent, grouped) for agent, grouped in present.items()],
    )


def requests_table(present: dict[str, list[Session]], requests: list[Request]) -> Table:
    """One row per agent and, when more than one agent is present, an
    `all` row over `requests`, every request of the report."""
    rows = [
        request_cells([agent], [request for session in grouped for request in session.requests])
        for agent, grouped in present.items()
    ]
    total = len(present) > 1
    if total:
        rows.append(request_cells(["all"], requests))
    return Table(
        "Requests",
        ("Agent", *REQUEST_HEADERS),
        (False, *(True,) * len(REQUEST_HEADERS)),
        rows,
        total=total,
    )


def providers_table(requests: list[Request]) -> Table:
    return Table(
        "Providers and models",
        ("Provider", "Model", *REQUEST_HEADERS),
        (False, False, *(True,) * len(REQUEST_HEADERS)),
        [
            request_cells([cell(provider), cell(model)], grouped)
            for (provider, model), grouped in by_provider_and_model(requests)
        ],
    )


def tools_table(present: dict[str, list[Session]]) -> Table:
    rows = []
    for agent, grouped in present.items():
        reasons = Counter(request.stop_reason for session in grouped for request in session.requests)
        rows.append(
            [
                agent,
                str(sum(session.tool_calls for session in grouped)),
                str(sum(session.tool_errors for session in grouped)),
                ", ".join(f"{cell(reason)} {count}" for reason, count in reasons.most_common()),
            ]
        )
    return Table(
        "Tools and stop reasons",
        ("Agent", "Tool calls", "Tool errors", "Stop reasons"),
        (False, True, True, False),
        rows,
    )


def levels_table(present: dict[str, list[Session]]) -> Table:
    """The requests per thinking level and agent; empty (with its note)
    when no transcript carried a level."""
    rows = []
    for agent, grouped in present.items():
        by_level: dict[str, list[Request]] = {}
        for session in grouped:
            for request in session.requests:
                by_level.setdefault(request.level, []).append(request)
        for level, level_requests in sorted(by_level.items(), key=lambda item: -len(item[1])):
            outputs = [request.output for request in level_requests]
            rows.append(
                [agent, level, str(len(level_requests)), str(percentile(outputs, 0.5)), str(percentile(outputs, 0.9))]
            )
    return Table(
        "Thinking levels",
        ("Agent", "Level", "Requests", "Output p50", "Output p90"),
        (False, False, True, True, True),
        rows if any(row[1] != "?" for row in rows) else [],
        empty_note=NO_LEVELS,
    )


def timings_table(present: dict[str, list[Session]]) -> Table:
    # Keyed by agent as well: both agents name the same provider and model,
    # and each measures its timings by its own definition.
    rows = []
    for agent, grouped in present.items():
        timed = [
            request
            for session in grouped
            for request in session.requests
            if request.ttft_ms is not None and request.duration_ms is not None
        ]
        for (provider, model), timed_group in by_provider_and_model(timed):
            rows.append(
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
    return Table(
        "Timings",
        (
            "Agent",
            "Provider",
            "Model",
            "Requests",
            "TTFT p50 ms",
            "TTFT p90 ms",
            "Duration p50 ms",
            "Duration p90 ms",
        ),
        (False, False, False, True, True, True, True, True),
        rows,
        empty_note=NO_TIMINGS,
    )


def build_tables(sessions: list[Session], slots: dict[str, int] | None = None) -> list[Table]:
    """Every table of the report, in the order both renderers show them;
    `slots` (preset -> context per slot, from the rendered preset file)
    fills the Preset fit table."""
    by_agent = {agent: [session for session in sessions if session.agent == agent] for agent in AGENTS}
    present = {agent: grouped for agent, grouped in by_agent.items() if grouped}
    requests = [request for session in sessions for request in session.requests]
    return [
        preset_fit_table(sessions, slots or {}),
        sessions_table(present),
        requests_table(present, requests),
        providers_table(requests),
        tools_table(present),
        levels_table(present),
        timings_table(present),
    ]
