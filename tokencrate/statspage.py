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
on a loopback-only server that answers only its own `Host` names.
"""

from __future__ import annotations

import contextlib
import functools
import html as html_text
import json
import math
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from string import Template

from . import TokenCrateError
from .session import AGENTS
from .stats import FOOTNOTE, Request, Session, build_tables, read_sessions, share, summary_line

# `stats --serve` without `--port`, clear of the API (4207) and UI
# (4224, 4250) defaults.
SERVE_PORT = 4260
# How often the served page asks the browser to reload it.
REFRESH_SECONDS = 60


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


def html(sessions: list[Session], refresh: int | None = None) -> str:
    """The stats report as one self-contained HTML page."""
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
    )


# --- The loopback server (`stats --serve`) ---------------------------------


def stats_server(agents_dir: Path, port: int) -> ThreadingHTTPServer:
    """The page on 127.0.0.1:`port`, re-reading the transcripts on every
    request. Only the server's own loopback `Host` names are answered, so
    a page on another site cannot use the browser's name resolution to
    reach it; without CORS headers the response body stays unreadable
    cross-origin either way."""

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
            if self.path.partition("?")[0] != "/":
                return self.refuse(404, "the stats page is at /")
            try:
                page = html(read_sessions(agents_dir), refresh=REFRESH_SECONDS)
            except TokenCrateError as error:
                return self.refuse(503, str(error))
            self.answer(200, page.encode("utf-8"), "text/html; charset=utf-8")

    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise TokenCrateError(f"cannot serve the stats page on 127.0.0.1:{port}: {error}") from None


def serve(agents_dir: Path, port: int) -> int:
    """Serve until interrupted; Ctrl-C, SIGHUP, or SIGTERM stop it."""
    with stats_server(agents_dir, port) as server:
        print(f"Serving the stats page at http://127.0.0.1:{server.server_address[1]}/ (Ctrl-C stops it)")
        server.serve_forever()
    return 0
