"""The stats report as a self-contained HTML page, and its loopback server.

`html` renders the `stats.build_tables` aggregation as one page: stat
tiles, a context distribution chart, and the report's tables, with no
external scripts, styles, or fonts, so the saved file works from
`file://`. The page skeleton, stylesheet, and chart script are the assets
under `tokencrate/pages/`; the chart is drawn by uPlot, inlined from the
hash-pinned files under `tokencrate/pages/vendor/`. The skeleton is a
`string.Template` whose slots receive only finished, pre-escaped HTML -
every transcript-supplied string is escaped at the call site that formats
it, and the JSON data island carries only trusted agent labels and
numbers, with `</` escaped. `serve` re-reads the transcripts per request
on a loopback-only server that answers only its own `Host` names, and adds
a live panel to the served page: the page polls the server's `/live`
endpoint, which polls the model server's loopback API for the loaded
preset's request gauges and token counters, at most every LIVE_INTERVAL
seconds and only while a page asks, into a bounded ring of samples that
holds nothing but numbers and the preset's name.
"""

from __future__ import annotations

import contextlib
import functools
import html as html_text
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from string import Template

from . import TokenCrateError
from .localhttp import http_get
from .presets import PRESET_NAME_RE, rendered_slots
from .session import AGENTS
from .stats import (
    DEFINITIONS,
    Filter,
    Request,
    Session,
    build_tables,
    fit_verdict,
    meta_text,
    percentile,
    read_sessions,
    share,
)

# `stats --serve` without `--port`, clear of the API (4207) and UI
# (4224, 4250) defaults.
SERVE_PORT = 4210
# How often the served page asks the browser to reload it.
REFRESH_SECONDS = 60
# The live panel: the shortest time between two scrapes of the model
# server, the ring's length (ten minutes at that pace), and the timeout of
# each loopback request.
LIVE_INTERVAL = 2.0
LIVE_SAMPLES = 300
LIVE_TIMEOUT = 2
# What a scrape keeps of `GET /metrics?model=`: the two token counters the
# rates come from and the two request gauges. Every other line is dropped.
LIVE_COUNTERS = ("llamacpp:prompt_tokens_total", "llamacpp:tokens_predicted_total")
LIVE_GAUGES = ("llamacpp:requests_processing", "llamacpp:requests_deferred")
# The speculative-decoding counters of an MTP preset, cumulative since its
# load; absent on a preset without a draft model.
SPEC_COUNTERS = ("llamacpp:spec_decode_num_accepted_tokens_total", "llamacpp:spec_decode_num_draft_tokens_total")
# The GPU query the sampler runs beside each scrape when the host has the
# tool and LLM_GPU is true: memory in use and installed (MiB) and power
# draw (W), as numbers only, one line per GPU (the first is kept).
NVIDIA_SMI_QUERY = ("--query-gpu=memory.used,memory.total,power.draw", "--format=csv,noheader,nounits")


@functools.cache
def asset(name: str) -> str:
    """One file under `tokencrate/pages/`, read once per process."""
    try:
        return files("tokencrate").joinpath("pages").joinpath(name).read_text(encoding="utf-8")
    except OSError as error:
        # A partial copy of the checkout is the one way this happens.
        raise TokenCrateError(f"the stats page asset tokencrate/pages/{name} is missing: {error}") from None


def prose(text: str) -> str:
    """Fixed report prose as HTML: escaped, with backtick pairs as code."""
    return re.sub(r"`([^`]*)`", r"<code>\1</code>", html_text.escape(text))


# Columns the page styles by their header: a share gets a meter under its
# percentage, a model name is set in monospace. The Markdown is untouched.
SHARE_COLUMNS = ("Cache-read share", "over 16K", "over 32K", "over 48K")
MONO_COLUMNS = ("Model",)


def tags(name: str, values: tuple[str, ...] | list[str], numeric: tuple[bool, ...], header=()) -> list[str]:
    """One header or data cell per column; numeric columns align right, a
    whole number gets its thousands separators (the Markdown keeps the
    plain digits), a share carries its meter, and a header is a button
    that sorts the table."""
    cells = []
    for index, (value, is_numeric) in enumerate(zip(values, numeric, strict=True)):
        classes = ["n"] if is_numeric else []
        text = html_text.escape(value)
        style = ""
        if name == "th":
            text = f'<button type="button">{text}</button>'
        elif is_numeric and value.isdigit():
            text = f"{int(value):,}"
        elif header and header[index] in SHARE_COLUMNS and value.endswith("%") and value[:-1].isdigit():
            classes.append("share")
            style = f' style="--share: {value}"'
        elif header and header[index] in MONO_COLUMNS:
            classes.append("mono")
        scope = ' scope="col"' if name == "th" else ""
        attributes = f' class="{" ".join(classes)}"' if classes else ""
        cells.append(f"<{name}{attributes}{scope}{style}>{text}</{name}>")
    return cells


def slug(title: str) -> str:
    """A section id from its title: `Preset fit` -> `preset-fit`."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def ecdf_points(requests: list[Request]) -> list[list[float]]:
    """The distribution as (context, share of requests at or below it),
    one point per distinct context, decimated to keep the page small."""
    contexts = sorted(request.context for request in requests)
    points: list[list[float]] = []
    for index, value in enumerate(contexts):
        cumulative = round((index + 1) / len(contexts), 4)
        if points and points[-1][0] == value:
            points[-1][1] = cumulative
        else:
            points.append([value, cumulative])
    if len(points) > 300:
        step = len(points) / 299
        points = [points[min(len(points) - 1, round(index * step))] for index in range(299)] + [points[-1]]
    return points


def slot_mark(sessions: list[Session], slots: dict[str, int], loaded: str | None) -> tuple[str, int] | None:
    """The one preset whose slot the chart marks: the loaded one on the
    served page when it is rendered, otherwise the rendered preset that
    served the most requests (a local request's model is its preset)."""
    if loaded in slots:
        return f"{loaded} slot (loaded)", slots[loaded]
    served = Counter(
        request.model for session in sessions for request in session.requests if request.model in slots
    ).most_common(1)
    if served:
        return f"{served[0][0]} slot (most used)", slots[served[0][0]]
    return None


def ecdf_chart(sessions: list[Session], slot: tuple[str, int] | None = None) -> str:
    """The context-per-request distribution as one figure: an ECDF step
    line per agent, drawn by the inlined uPlot from the data island. The
    island carries aligned arrays - one shared x axis of every plotted
    context size, and per series the share of requests at or below each
    of them, forward-filled (an ECDF is right-continuous, so the carried
    value is exact) with leading zeros and the flat tail to `xmax` - and
    the reference marks: the compaction p50 and `slot`. The axis extends
    to a slot up to twice the largest context; a roomier slot is marked at
    the right edge instead, so the distribution keeps its width."""
    series = []
    for slot_index, agent in enumerate(AGENTS, start=1):
        requests = [request for session in sessions if session.agent == agent for request in session.requests]
        if requests:
            series.append({"label": agent, "slot": slot_index, "points": ecdf_points(requests)})
    largest = max(point[0] for entry in series for point in entry["points"])
    marks = []
    compactions = [tokens for session in sessions for tokens in session.compaction_tokens]
    if compactions:
        marks.append({"label": "compaction p50", "value": percentile(compactions, 0.5)})
    if slot is not None:
        marks.append({"label": slot[0], "value": slot[1], "beyond": slot[1] > 2 * largest})
    span = max(largest, slot[1]) if slot is not None and slot[1] <= 2 * largest else largest
    tick = 8192
    while span > 8 * tick:
        tick *= 2
    xmax = max(tick, math.ceil(span / tick) * tick)
    columns = sorted({0, xmax, *(value for entry in series for value, _ in entry["points"])})
    for entry in series:
        points, filled, index, value = entry.pop("points"), [], 0, 0.0
        for column in columns:
            while index < len(points) and points[index][0] <= column:
                value = points[index][1]
                index += 1
            filled.append(value)
        entry["values"] = filled

    # The island holds only the AGENTS labels, preset names from the
    # maintainer's rendered configuration, and numbers; the "</" escape
    # keeps a future transcript-supplied string from closing the tag.
    data = {"xmax": xmax, "tick": tick, "x": columns, "series": series, "marks": marks}
    island = json.dumps(data).replace("</", "<\\/")
    legend = "".join(
        f'<span><span class="key" style="border-top-color: var(--series-{entry["slot"]})"></span>'
        f"{html_text.escape(entry['label'])}</span>"
        for entry in series
    )
    caption = "How many requests would fit in a context of a given size"
    if len(series) == 1:
        caption += f" ({html_text.escape(series[0]['label'])})"
        legend = ""
    return (
        '<figure id="context">\n'
        f"<figcaption>{caption}</figcaption>\n"
        + (f'<div class="legend">{legend}</div>\n' if legend else "")
        + '<div id="ecdf" role="img" tabindex="0" '
        'aria-label="Share of requests that fit at each context size; the arrow keys move the readout, '
        'and the Requests table carries the numbers"></div>\n'
        '<div id="tooltip"></div>\n'
        f'<script type="application/json" id="ecdf-data">{island}</script>\n'
        "</figure>"
    )


def verdict(sessions: list[Session], slots: dict[str, int], loaded: str | None, down: bool = False) -> str:
    """The served page's lead: whether the loaded preset's slot fits the
    report's requests, in words, with a status glyph and colour beside them;
    `down` says the model server did not answer the last poll."""
    if loaded not in slots:
        if down:
            text = "Model server not reachable; "
        elif loaded:
            text = f"<b>{html_text.escape(loaded)}</b> is loaded but not in build/models.ini; "
        else:
            text = "No preset loaded; "
        return (
            '<section class="verdict" data-status="none"><span class="dot" aria-hidden="true"></span>'
            f"{text}the Preset fit table judges every rendered preset.</section>"
        )
    over, _, fits = fit_verdict(sessions, slots[loaded])
    total = sum(len(session.requests) for session in sessions)
    if fits:
        status, glyph, text = "good", "\u2713", "every request fit"
    else:
        status, glyph, text = (
            "critical",
            "\u2715",
            f"{over:,} of {total:,} requests ({share(over, total)}) would not fit",
        )
    return (
        f'<section class="verdict" data-status="{status}"><span class="dot" aria-hidden="true">{glyph}</span>'
        f"<b>{html_text.escape(loaded)}</b> (slot {slots[loaded]:,} tokens, loaded): {text}</section>"
    )


def live_panel(api: str, gpu: bool) -> str:
    """The served page's live panel: one script that builds the panel and
    polls `/live`; `api` (host:port of the model server, as `stats_server`
    derives it) names what is polled when it cannot be reached, and `gpu`
    says whether the server runs a GPU query at all (without one the panel
    shows no GPU tiles)."""
    return (
        '<script id="live-script" '
        f'data-api="{html_text.escape(api)}" data-interval="{int(LIVE_INTERVAL * 1000)}" '
        f'data-gpu="{int(gpu)}">\n'
        f"{asset('live.js')}</script>"
    )


def html(
    sessions: list[Session],
    refresh: int | None = None,
    live: str | None = None,
    selection: Filter | None = None,
    slots: dict[str, int] | None = None,
    loaded: str | None = None,
    gpu: bool = False,
    down: bool = False,
) -> str:
    """The stats report as one self-contained HTML page; `live` (the model
    server's host:port) adds the served page's live panel and its verdict
    on `loaded`, the preset the server saw loaded; `selection` names the
    filters the meta line reports; `slots` are the rendered presets'
    contexts per slot."""
    slots = slots or {}
    requests = [request for session in sessions for request in session.requests]
    contexts = [request.context for request in requests]
    prompt = sum(request.input + request.cache_read for request in requests)
    tiles = (
        ("Sessions", f"{len(sessions):,}"),
        ("Requests", f"{len(requests):,}"),
        ("Cache-read share", share(sum(request.cache_read for request in requests), prompt)),
        ("Requests over 32K", share(sum(context > 32768 for context in contexts), len(contexts))),
    )
    sections = []
    links = [("Context", "context"), ("Preset fit", "preset-fit")]
    for table in build_tables(sessions, slots):
        anchor = slug(table.title)
        if table.title != "Preset fit":
            links.append((table.title.split(" ")[0], anchor))
        sections.append(f'<h2 id="{anchor}">{html_text.escape(table.title)}</h2>')
        if not table.rows:
            sections.append(f"<p>{prose(table.empty_note)}</p>")
            continue
        body, foot = (table.rows[:-1], table.rows[-1:]) if table.total else (table.rows, [])
        sections.append(f'<div class="scroll" role="region" tabindex="0" aria-label="{html_text.escape(table.title)}">')
        sections.append("<table>")
        sections.append("<thead><tr>" + "".join(tags("th", table.header, table.numeric)) + "</tr></thead>")
        sections.append("<tbody>")
        sections += ["<tr>" + "".join(tags("td", row, table.numeric, table.header)) + "</tr>" for row in body]
        sections.append("</tbody>")
        if foot:
            sections.append("<tfoot><tr>" + "".join(tags("td", foot[0], table.numeric, table.header)) + "</tr></tfoot>")
        sections.append("</table>")
        sections.append("</div>")
    links.append(("Definitions", "definitions"))
    nav = "<nav>" + "".join(f'<a href="#{anchor}">{label}</a>' for label, anchor in links) + "</nav>"
    rendered = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    footer = f"Rendered {rendered}" + (f"; the page refreshes every {refresh} s." if refresh else ".")
    return Template(asset("stats.html")).substitute(
        refresh=f'<meta http-equiv="refresh" content="{refresh}">\n' if refresh else "",
        vendorstyle=asset("vendor/uPlot.min.css"),
        vendorscript=asset("vendor/uPlot.iife.js"),
        style=asset("stats.css"),
        nav=nav,
        meta=html_text.escape(meta_text(sessions, selection)),
        footer=footer,
        hero=verdict(sessions, slots, loaded, down) if live else "",
        tiles='<div class="tiles">\n'
        + "\n".join(
            f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div></div>'
            for label, value in tiles
        )
        + "\n</div>",
        chart=ecdf_chart(sessions, slot_mark(sessions, slots, loaded if live else None)),
        tables="\n".join(sections),
        definitions='<h2 id="definitions">Definitions</h2>\n<ul class="definitions">\n'
        + "\n".join(f"<li><b>{html_text.escape(term)}</b>: {prose(text)}</li>" for term, text in DEFINITIONS)
        + "\n</ul>",
        script=asset("stats.js"),
        live=live_panel(live, gpu) if live else "",
    )


# --- Live samples of the model server ----------------------------------------


@dataclass
class Sample:
    """One look at the model server: wall time in seconds, whether the API
    answered, the loaded preset, whether its counters were scraped, its
    request gauges, the token rates since the previous scrape (None until
    the preset has been scraped twice, and after a counter went backwards,
    which is a restart), the share of drafted tokens the MTP preset accepted
    since its load, and the GPU's memory and power when the host reports
    them."""

    t: float
    up: bool
    model: str | None
    scraped: bool
    processing: int | None
    deferred: int | None
    prompt_rate: float | None
    generation_rate: float | None
    acceptance: float | None = None
    gpu_memory_mib: int | None = None
    gpu_memory_total_mib: int | None = None
    gpu_power_w: float | None = None


def prometheus_values(body: str, names: tuple[str, ...]) -> dict[str, float]:
    """The unlabelled samples of `names` from Prometheus text; a name whose
    value is not a finite number is absent."""
    values = {}
    for line in body.splitlines():
        name, _, rest = line.partition(" ")
        if name in names:
            try:
                value = float(rest.strip())
            except ValueError:
                continue
            if math.isfinite(value):
                values[name] = value
    return values


def nvidia_smi_command(gpu: bool) -> list[str] | None:
    """The GPU query when the stack uses the GPU and the host has the tool,
    resolved once to its absolute path; None otherwise."""
    found = shutil.which("nvidia-smi") if gpu else None
    return [found, *NVIDIA_SMI_QUERY] if found else None


def gpu_reading(command: list[str]) -> tuple[int | None, int | None, float | None]:
    """The first GPU's memory in use, its memory in all, and its power draw
    from the query's CSV line; a field that is not a number (`[N/A]`) is
    None, as is everything when the command fails or takes longer than
    the scrape timeout."""
    try:
        run = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=LIVE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    if run.returncode:
        return None, None, None
    fields = [number(field) for field in (run.stdout.splitlines() or [""])[0].split(",")[:3]] + [None] * 3
    memory, total, power = fields[0], fields[1], fields[2]
    return (
        int(memory) if memory is not None else None,
        int(total) if total is not None else None,
        round(power, 1) if power is not None else None,
    )


def number(text: str) -> float | None:
    """A finite number from one CSV field; None for `[N/A]` and the like."""
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class LiveSampler:
    """The ring of samples behind `/live`. A snapshot scrapes the model
    server first when the previous scrape is at least `interval` old, so
    however many pages poll, the API sees one request pair per interval
    and none while no page is open. Only a preset that `GET /models`
    reported loaded on this and the previous snapshot is asked for its
    counters: a scrape routes to the preset, and asking for one that just
    unloaded would load it again. The lock covers the ring and the timing
    only, never a request, so a slow router or GPU query delays one poll,
    not every page; one scrape runs at a time, so samples stay in order
    and the previous counters belong to the scrape before."""

    def __init__(
        self,
        service_url: str,
        interval: float = LIVE_INTERVAL,
        clock=time.monotonic,
        gpu_command: list[str] | None = None,
    ) -> None:
        self.service_url = service_url.rstrip("/")
        self.interval = interval
        self.clock = clock
        self.gpu_command = gpu_command
        self.samples: deque[Sample] = deque(maxlen=LIVE_SAMPLES)
        self.lock = threading.Lock()
        self.scraped_at: float | None = None
        self.scraping = False
        self.loaded: str | None = None
        self.previous: tuple[str, dict[str, float], float] | None = None
        # The presets asked for their counters, for the tests' audit.
        self.asked: deque[str] = deque(maxlen=LIVE_SAMPLES)

    def snapshot(self) -> list[Sample]:
        with self.lock:
            now = self.clock()
            due = not self.scraping and (self.scraped_at is None or now - self.scraped_at >= self.interval)
            if due:
                self.scraped_at = now
                self.scraping = True
        if due:
            try:
                sample = self.scrape()
                if self.gpu_command:
                    sample.gpu_memory_mib, sample.gpu_memory_total_mib, sample.gpu_power_w = gpu_reading(
                        self.gpu_command
                    )
            finally:
                with self.lock:
                    self.scraping = False
            with self.lock:
                self.samples.append(sample)
        with self.lock:
            return list(self.samples)

    def loaded_preset(self) -> tuple[bool, str | None]:
        """Whether the API answers, and the loaded preset's validated name."""
        body = http_get(f"{self.service_url}/models", timeout=LIVE_TIMEOUT)
        if body is None:
            return False, None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return True, None
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return True, None
        loaded = sorted(
            str(model["id"])
            for model in models
            if isinstance(model, dict)
            and isinstance(model.get("id"), str)
            and PRESET_NAME_RE.fullmatch(model["id"])
            and isinstance(model.get("status"), dict)
            and model["status"].get("value") == "loaded"
        )
        return True, loaded[0] if loaded else None

    def scrape(self) -> Sample:
        up, model = self.loaded_preset()
        sample = Sample(time.time(), up, model, False, None, None, None, None)
        settled = up and model is not None and model == self.loaded
        self.loaded = model
        if not settled:
            self.previous = None
            return sample
        self.asked.append(model)
        body = http_get(f"{self.service_url}/metrics?model={model}", timeout=LIVE_TIMEOUT)
        if body is None:
            self.previous = None
            return sample
        sample.scraped = True
        gauges = prometheus_values(body, LIVE_GAUGES)
        counters = prometheus_values(body, LIVE_COUNTERS)
        spec = prometheus_values(body, SPEC_COUNTERS)
        at = self.clock()
        sample.processing = int(gauges[LIVE_GAUGES[0]]) if LIVE_GAUGES[0] in gauges else None
        sample.deferred = int(gauges[LIVE_GAUGES[1]]) if LIVE_GAUGES[1] in gauges else None
        if all(name in spec for name in SPEC_COUNTERS) and spec[SPEC_COUNTERS[1]] > 0:
            sample.acceptance = round(min(1.0, spec[SPEC_COUNTERS[0]] / spec[SPEC_COUNTERS[1]]), 3)
        # A rate needs both counters in this scrape and the previous one of
        # the same preset; a counter that went backwards is a restart.
        complete = all(name in counters for name in LIVE_COUNTERS)
        if complete and self.previous and self.previous[0] == model and at > self.previous[2]:
            deltas = [counters[name] - self.previous[1][name] for name in LIVE_COUNTERS]
            if min(deltas) >= 0:
                elapsed = at - self.previous[2]
                sample.prompt_rate = round(deltas[0] / elapsed, 1)
                sample.generation_rate = round(deltas[1] / elapsed, 1)
        self.previous = (model, counters, at) if complete else None
        return sample


# --- The loopback server (`stats --serve`) ---------------------------------


def stats_server(
    agents_dir: Path,
    port: int,
    service_url: str,
    selection: Filter | None = None,
    *,
    gpu_command: list[str] | None = None,
    build_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """The page on 127.0.0.1:`port`, re-reading the transcripts (through
    `selection`) and the rendered presets under `build_dir` on every
    request, and `/live`, the samples of the model server at `service_url`. Only the server's own loopback `Host` names
    are answered, so a page on another site cannot use the browser's name
    resolution to reach it; without CORS headers the response body stays
    unreadable cross-origin either way."""
    sampler = LiveSampler(service_url, gpu_command=gpu_command)
    api = service_url.partition("://")[2].rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_arguments) -> None:
            return

        def answer(self, status: int, body: bytes, content_type: str) -> None:
            # A reader that went away mid-response is not worth a traceback.
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                # `--detach` reads this to know the server it started is
                # the one answering the port.
                self.send_header(PID_HEADER, str(os.getpid()))
                self.end_headers()
                self.wfile.write(body)

        def refuse(self, status: int, message: str) -> None:
            self.answer(status, f"{message}\n".encode(), "text/plain; charset=utf-8")

        def do_GET(self) -> None:
            bound = self.server.server_address[1]
            if self.headers.get("Host", "") not in (f"127.0.0.1:{bound}", f"localhost:{bound}"):
                return self.refuse(403, "stats answers only its own loopback host names")
            path = self.path.partition("?")[0]
            if path == "/live":
                body = {"api": api, "samples": [asdict(s) for s in sampler.snapshot()]}
                return self.answer(200, json.dumps(body).encode("utf-8"), "application/json")
            if path != "/":
                return self.refuse(404, "the stats page is at /")
            try:
                # The page's verdict is about the preset the last sample saw
                # loaded; the snapshot scrapes only when one is due anyway.
                samples = sampler.snapshot()
                page = html(
                    read_sessions(agents_dir, selection),
                    refresh=REFRESH_SECONDS,
                    live=api,
                    selection=selection,
                    slots=rendered_slots(build_dir) if build_dir else {},
                    loaded=samples[-1].model if samples else None,
                    gpu=gpu_command is not None,
                    down=bool(samples) and not samples[-1].up,
                )
            except TokenCrateError as error:
                return self.refuse(503, str(error))
            self.answer(200, page.encode("utf-8"), "text/html; charset=utf-8")

    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise TokenCrateError(f"cannot serve the stats page on 127.0.0.1:{port}: {error}") from None


def serve(
    agents_dir: Path,
    port: int,
    service_url: str,
    selection: Filter | None = None,
    *,
    gpu: bool = False,
    root: Path | None = None,
) -> int:
    """Serve until interrupted; Ctrl-C, SIGHUP, or SIGTERM stop it. A
    server that `--detach` started finds its own PID in the file under
    `root` and removes the file when it ends."""
    with stats_server(
        agents_dir,
        port,
        service_url,
        selection,
        gpu_command=nvidia_smi_command(gpu),
        build_dir=root / "build" if root else None,
    ) as server:
        print(f"Serving the stats page at http://127.0.0.1:{server.server_address[1]}/ (Ctrl-C stops it)")
        try:
            server.serve_forever()
        finally:
            if root is not None:
                forget(root, os.getpid())
    return 0


# --- A detached server (`stats --serve --detach`, `stats --stop`) ----------

# Where the wrapper notes the server it started in the background, beside
# the engine locks; `status` reads it, `stats --stop` and `down` end it.
PID_FILE = "build/stats-serve.pid"
LOG_FILE = "build/stats-serve.log"
PID_HEADER = "X-TokenCrate-Stats-Pid"
DETACH_TIMEOUT = 10
# The child's command line, as `detach` spells it; nothing else is ever
# signalled.
CHILD_ARGUMENTS = ("-m", "tokencrate", "stats", "--serve")


def pid_file(root: Path) -> Path:
    return root / PID_FILE


def read_pid_file(root: Path) -> dict | None:
    """The record of a detached server ({pid, port, started}), or None."""
    try:
        record = json.loads(pid_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(record, dict) and isinstance(record.get("pid"), int) and isinstance(record.get("port"), int):
        return record
    return None


def process_start(pid: int) -> int | None:
    """The process's start time in clock ticks since boot (/proc), which a
    reused PID never repeats; None where /proc has no answer."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        return int(stat.rpartition(")")[2].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def is_stats_process(pid: int, started: int | None = None) -> bool:
    """Whether `pid` is alive and is the server `detach` started: its
    command line runs `-m tokencrate stats --serve` and, when the record
    carries one, its start time matches, so a PID the kernel handed to
    another program after the server ended is never signalled. Without
    /proc, liveness alone decides."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", errors="replace").split("\0")
    except OSError:
        return True
    expected = list(CHILD_ARGUMENTS)
    runs_server = any(arguments[i : i + len(expected)] == expected for i in range(len(arguments)))
    same_start = started is None or process_start(pid) == started
    return runs_server and same_start


def running_server(root: Path) -> dict | None:
    """The detached server's record when its process still runs; a stale
    file (the process is gone, or another program has its PID) is removed."""
    record = read_pid_file(root)
    if record is None:
        return None
    if is_stats_process(record["pid"], record.get("started")):
        return record
    pid_file(root).unlink(missing_ok=True)
    return None


def forget(root: Path, pid: int) -> None:
    """Remove the record when it is `pid`'s own, never a newer server's."""
    record = read_pid_file(root)
    if record is not None and record["pid"] == pid:
        pid_file(root).unlink(missing_ok=True)


def port_answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def served_by(port: int) -> int | None:
    """The PID the server on `port` names in its answer, or None when
    nothing answers or the answer is not a stats page."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/live", timeout=2) as response:
            value = response.headers.get(PID_HEADER, "")
    except urllib.error.HTTPError as error:
        value = error.headers.get(PID_HEADER, "") if error.headers else ""
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return int(value) if value.isdigit() else None


def detach(root: Path, port: int, arguments: list[str]) -> int:
    """Start `stats --serve` with `arguments` as a background process of
    its own session, logging to build/stats-serve.log, and return once
    the port answers with that process's PID. The record is created
    exclusively before the start, so two `--detach` at once cannot both
    succeed, and removed again if the child fails."""
    if running := running_server(root):
        raise TokenCrateError(
            f"a stats server is already serving on 127.0.0.1:{running['port']} (pid {running['pid']}); "
            "run: bash bin/tokencrate stats --stop"
        )
    if port_answers(port):
        raise TokenCrateError(f"host port {port} is already in use; choose another with --port")
    pid_file(root).parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = pid_file(root).open("x", encoding="utf-8")
    except FileExistsError:
        raise TokenCrateError("another stats --serve --detach is starting; run: bash bin/tokencrate status") from None
    with handle, (root / LOG_FILE).open("wb") as log:
        child = subprocess.Popen(
            [sys.executable, "-u", *CHILD_ARGUMENTS, *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        handle.write(json.dumps({"pid": child.pid, "port": port, "started": process_start(child.pid)}) + "\n")
    deadline = time.monotonic() + DETACH_TIMEOUT
    while time.monotonic() < deadline:
        if child.poll() is not None:
            forget(root, child.pid)
            raise TokenCrateError(
                f"the stats server ended with status {child.returncode} before it answered; see {LOG_FILE}"
            )
        if served_by(port) == child.pid:
            print(
                f"Serving the stats page at http://127.0.0.1:{port}/ in the background "
                f"(pid {child.pid}; stats --stop ends it)"
            )
            return 0
        time.sleep(0.1)
    child.terminate()
    forget(root, child.pid)
    raise TokenCrateError(
        f"the stats server did not answer on 127.0.0.1:{port} within {DETACH_TIMEOUT}s; see {LOG_FILE}"
    )


def stop(root: Path) -> bool:
    """End the detached server, if one runs; True when one was stopped."""
    running = running_server(root)
    if running is None:
        return False
    pid, started = running["pid"], running.get("started")
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + DETACH_TIMEOUT
    while time.monotonic() < deadline and is_stats_process(pid, started):
        time.sleep(0.1)
    if is_stats_process(pid, started):
        raise TokenCrateError(f"the stats server (pid {pid}) did not end on SIGTERM")
    forget(root, pid)
    return True


def status_line(root: Path) -> str | None:
    """One line for `status`, or None without a detached server."""
    running = running_server(root)
    if running is None:
        return None
    answering = "serving" if port_answers(running["port"]) else "not answering"
    return (
        f"Stats page: {answering} at http://127.0.0.1:{running['port']}/ (pid {running['pid']}; stats --stop ends it)"
    )
