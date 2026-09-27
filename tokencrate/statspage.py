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
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from string import Template

from . import TokenCrateError
from .localhttp import http_get
from .presets import PRESET_NAME_RE
from .session import AGENTS
from .stats import FOOTNOTE, Request, Session, build_tables, read_sessions, share, summary_line

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


def tags(name: str, values: tuple[str, ...] | list[str], numeric: tuple[bool, ...]) -> list[str]:
    """One header or data cell per column; numeric columns align right."""
    return [
        f'<{name} class="n">{html_text.escape(value)}</{name}>'
        if is_numeric
        else f"<{name}>{html_text.escape(value)}</{name}>"
        for value, is_numeric in zip(values, numeric, strict=True)
    ]


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


def ecdf_chart(sessions: list[Session]) -> str:
    """The context-per-request distribution as one figure: an ECDF step
    line per agent, drawn by the inlined uPlot from the data island. The
    island carries aligned arrays - one shared x axis of every plotted
    context size, and per series the share of requests at or below each
    of them, forward-filled (an ECDF is right-continuous, so the carried
    value is exact) with leading zeros and the flat tail to `xmax`."""
    series = []
    for slot, agent in enumerate(AGENTS, start=1):
        requests = [request for session in sessions if session.agent == agent for request in session.requests]
        if requests:
            series.append({"label": agent, "slot": slot, "points": ecdf_points(requests)})
    largest = max(point[0] for entry in series for point in entry["points"])
    tick = 8192
    while largest > 8 * tick:
        tick *= 2
    xmax = max(tick, math.ceil(largest / tick) * tick)
    columns = sorted({0, xmax, *(value for entry in series for value, _ in entry["points"])})
    for entry in series:
        points, filled, index, value = entry.pop("points"), [], 0, 0.0
        for column in columns:
            while index < len(points) and points[index][0] <= column:
                value = points[index][1]
                index += 1
            filled.append(value)
        entry["values"] = filled

    # The island holds only the AGENTS labels and numbers today; the "</"
    # escape keeps a future transcript-supplied string from closing the tag.
    data = {"xmax": xmax, "tick": tick, "x": columns, "series": series}
    island = json.dumps(data).replace("</", "<\\/")
    legend = "".join(
        f'<span><span class="key" style="border-top-color: var(--series-{entry["slot"]})"></span>'
        f"{html_text.escape(entry['label'])}</span>"
        for entry in series
    )
    caption = "Share of requests at or below a context size"
    if len(series) == 1:
        caption += f" ({html_text.escape(series[0]['label'])})"
        legend = ""
    return (
        "<figure>\n"
        f"<figcaption>Context per request &mdash; {caption}</figcaption>\n"
        + (f'<div class="legend">{legend}</div>\n' if legend else "")
        + '<div id="ecdf" role="img" tabindex="0" '
        'aria-label="Share of requests at or below each context size; the table below carries the numbers"></div>\n'
        '<div id="tooltip"></div>\n'
        f'<script type="application/json" id="ecdf-data">{island}</script>\n'
        "</figure>"
    )


def live_panel(api: str) -> str:
    """The served page's live panel: one script that builds the panel and
    polls `/live`; `api` (host:port of the model server, as `stats_server`
    derives it) names what is polled when it cannot be reached."""
    return (
        '<script id="live-script" '
        f'data-api="{html_text.escape(api)}" data-interval="{int(LIVE_INTERVAL * 1000)}">\n'
        f"{asset('live.js')}</script>"
    )


def html(sessions: list[Session], refresh: int | None = None, live: str | None = None) -> str:
    """The stats report as one self-contained HTML page; `live` (the model
    server's host:port) adds the served page's live panel."""
    requests = [request for session in sessions for request in session.requests]
    contexts = [request.context for request in requests]
    prompt = sum(request.input + request.cache_read for request in requests)
    tiles = (
        ("Sessions", f"{len(sessions):,}"),
        ("Requests", f"{len(requests):,}"),
        ("Cache-read share", share(sum(request.cache_read for request in requests), prompt)),
        ("Requests above 32K", share(sum(context > 32768 for context in contexts), len(contexts))),
    )
    sections = []
    for table in build_tables(sessions):
        sections.append(f"<h2>{html_text.escape(table.title)}</h2>")
        if not table.rows:
            sections.append(f"<p>{prose(table.empty_note)}</p>")
            continue
        sections.append("<table>")
        sections.append("<thead><tr>" + "".join(tags("th", table.header, table.numeric)) + "</tr></thead>")
        sections.append("<tbody>")
        sections += ["<tr>" + "".join(tags("td", row, table.numeric)) + "</tr>" for row in table.rows]
        sections.append("</tbody>")
        sections.append("</table>")
    return Template(asset("stats.html")).substitute(
        refresh=f'<meta http-equiv="refresh" content="{refresh}">\n' if refresh else "",
        vendorstyle=asset("vendor/uPlot.min.css"),
        vendorscript=asset("vendor/uPlot.iife.js"),
        style=asset("stats.css"),
        meta=f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')} &middot; {html_text.escape(summary_line(sessions))}",
        tiles='<div class="tiles">\n'
        + "\n".join(
            f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div></div>'
            for label, value in tiles
        )
        + "\n</div>",
        chart=ecdf_chart(sessions),
        tables="\n".join(sections),
        footnote=prose(FOOTNOTE),
        script=asset("stats.js"),
        live=live_panel(live) if live else "",
    )


# --- Live samples of the model server ----------------------------------------


@dataclass
class Sample:
    """One look at the model server: wall time in seconds, whether the API
    answered, the loaded preset, whether its counters were scraped, its
    request gauges, and the token rates since the previous scrape (None
    until the preset has been scraped twice, and after a counter went
    backwards, which is a restart)."""

    t: float
    up: bool
    model: str | None
    scraped: bool
    processing: int | None
    deferred: int | None
    prompt_rate: float | None
    generation_rate: float | None


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


class LiveSampler:
    """The ring of samples behind `/live`. A snapshot scrapes the model
    server first when the previous scrape is at least `interval` old, so
    however many pages poll, the API sees one request pair per interval
    and none while no page is open. Only a preset that `GET /models`
    reported loaded on this and the previous snapshot is asked for its
    counters: a scrape routes to the preset, and asking for one that just
    unloaded would load it again."""

    def __init__(self, service_url: str, interval: float = LIVE_INTERVAL, clock=time.monotonic) -> None:
        self.service_url = service_url.rstrip("/")
        self.interval = interval
        self.clock = clock
        self.samples: deque[Sample] = deque(maxlen=LIVE_SAMPLES)
        self.lock = threading.Lock()
        self.scraped_at: float | None = None
        self.loaded: str | None = None
        self.previous: tuple[str, dict[str, float], float] | None = None
        self.asked: list[str] = []

    def snapshot(self) -> list[Sample]:
        with self.lock:
            now = self.clock()
            if self.scraped_at is None or now - self.scraped_at >= self.interval:
                self.scraped_at = now
                self.samples.append(self.scrape())
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
        at = self.clock()
        sample.processing = int(gauges[LIVE_GAUGES[0]]) if LIVE_GAUGES[0] in gauges else None
        sample.deferred = int(gauges[LIVE_GAUGES[1]]) if LIVE_GAUGES[1] in gauges else None
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


def stats_server(agents_dir: Path, port: int, service_url: str) -> ThreadingHTTPServer:
    """The page on 127.0.0.1:`port`, re-reading the transcripts on every
    request, and `/live`, the samples of the model server at `service_url`.
    Only the server's own loopback `Host` names are answered, so a page on
    another site cannot use the browser's name resolution to reach it;
    without CORS headers the response body stays unreadable cross-origin
    either way."""
    sampler = LiveSampler(service_url)
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
                page = html(read_sessions(agents_dir), refresh=REFRESH_SECONDS, live=api)
            except TokenCrateError as error:
                return self.refuse(503, str(error))
            self.answer(200, page.encode("utf-8"), "text/html; charset=utf-8")

    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise TokenCrateError(f"cannot serve the stats page on 127.0.0.1:{port}: {error}") from None


def serve(agents_dir: Path, port: int, service_url: str) -> int:
    """Serve until interrupted; Ctrl-C, SIGHUP, or SIGTERM stop it."""
    with stats_server(agents_dir, port, service_url) as server:
        print(f"Serving the stats page at http://127.0.0.1:{server.server_address[1]}/ (Ctrl-C stops it)")
        server.serve_forever()
    return 0
