"""The stats report as a self-contained HTML page.

`html` renders the `tables.build_tables` aggregation as one page: stat
tiles, a context distribution chart, and the report's tables, with no
external scripts, styles, or fonts, so the saved file works from
`file://`. The page skeleton, stylesheet, and chart script are the assets
under `pages/` beside this module; the chart is drawn by uPlot, inlined
from the hash-pinned files under `pages/vendor/`. The skeleton is a
`string.Template` whose slots receive only finished, pre-escaped HTML -
every transcript-supplied string is escaped at the call site that formats
it, and the JSON data island carries only trusted agent labels and
numbers, with `</` escaped. The served page adds a verdict on the loaded
preset and the live panel, whose script polls the server's `/live`
endpoint.
"""

from __future__ import annotations

import functools
import html as html_text
import json
import math
import re
import time
from collections import Counter
from importlib.resources import files
from string import Template

from .. import TokenCrateError
from ..agenthome import AGENTS
from .live import LIVE_INTERVAL, LIVE_SAMPLES
from .report import meta_text
from .tables import DEFINITIONS, build_tables, fit_verdict, percentile, share
from .transcripts import Filter, Request, Session

# How often the served page asks the browser to reload it.
REFRESH_SECONDS = 60


@functools.cache
def asset(name: str) -> str:
    """One file under `pages/` beside this module, read once per process."""
    try:
        return files(__package__).joinpath("pages").joinpath(name).read_text(encoding="utf-8")
    except OSError as error:
        # A partial copy of the checkout is the one way this happens.
        raise TokenCrateError(f"the stats page asset tokencrate/stats/pages/{name} is missing: {error}") from None


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
    the right edge instead, so the distribution keeps its width. Without
    a request the figure is an empty axis of one tick."""
    series = []
    for slot_index, agent in enumerate(AGENTS, start=1):
        requests = [request for session in sessions if session.agent == agent for request in session.requests]
        if requests:
            series.append({"label": agent, "slot": slot_index, "points": ecdf_points(requests)})
    largest = max((point[0] for entry in series for point in entry["points"]), default=0)
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
            text = f"<b>{html_text.escape(loaded)}</b> is loaded but not in the rendered model list; "
        else:
            text = "No preset loaded; "
        return (
            '<section class="verdict" data-status="none"><span class="dot" aria-hidden="true"></span>'
            f"{text}the Preset fit table judges every rendered preset.</section>"
        )
    over, _, fits = fit_verdict(sessions, slots[loaded])
    total = sum(len(session.requests) for session in sessions)
    if fits:
        status, glyph, text = "good", "✓", "every request fit"
    else:
        status, glyph, text = (
            "critical",
            "✕",
            f"{over:,} of {total:,} requests ({share(over, total)}) would not fit",
        )
    return (
        f'<section class="verdict" data-status="{status}"><span class="dot" aria-hidden="true">{glyph}</span>'
        f"<b>{html_text.escape(loaded)}</b> (slot {slots[loaded]:,} tokens, loaded): {text}</section>"
    )


def live_panel(api: str, gpu: bool) -> str:
    """The served page's live panel: one script that builds the panel and
    polls `/live` at the sampler's pace and charts the window its ring
    holds; `api` (host:port of the model server, as `server.stats_server`
    derives it) names what is polled when it cannot be reached, and `gpu`
    says whether the server runs a GPU query at all (without one the panel
    shows no GPU tiles)."""
    return (
        '<script id="live-script" '
        f'data-api="{html_text.escape(api)}" data-interval="{int(LIVE_INTERVAL * 1000)}" '
        f'data-window="{LIVE_SAMPLES * LIVE_INTERVAL:.0f}" data-gpu="{int(gpu)}">\n'
        f"{asset('live.js')}</script>"
    )


def html(
    sessions: list[Session],
    live: str | None = None,
    selection: Filter | None = None,
    slots: dict[str, int] | None = None,
    loaded: str | None = None,
    gpu: bool = False,
    down: bool = False,
) -> str:
    """The stats report as one self-contained HTML page; `live` (the model
    server's host:port) makes it the served page: it reloads itself every
    REFRESH_SECONDS and carries the live panel and the verdict on `loaded`,
    the preset the server saw loaded; `selection` names the filters the
    meta line reports; `slots` are the rendered presets' contexts per
    slot."""
    slots = slots or {}
    tables = build_tables(sessions, slots)
    requests = next(table for table in tables if table.title == "Requests")
    # Its last row is the `all` row, or the one present agent's.
    totals = dict(zip(requests.header, requests.rows[-1], strict=True))
    tiles = (
        ("Sessions", f"{len(sessions):,}"),
        ("Requests", f"{int(totals['Requests']):,}"),
        ("Cache-read share", totals["Cache-read share"]),
        ("Requests over 32K", totals["over 32K"]),
    )
    sections = []
    links = [("Context", "context"), ("Preset fit", "preset-fit")]
    for table in tables:
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
    footer = f"Rendered {rendered}" + (f"; the page refreshes every {REFRESH_SECONDS} s." if live else ".")
    return Template(asset("stats.html")).substitute(
        refresh=f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">\n' if live else "",
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
