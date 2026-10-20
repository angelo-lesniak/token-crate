"""The loopback server of `stats --serve`.

`serve` re-reads the transcripts per request on a loopback-only server
that answers only its own `Host` names, serves the page with its live
panel, and answers `/live` from the `live.LiveSampler` ring.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import TokenCrateError
from ..env import Settings
from ..presets import rendered_slots
from .live import LiveSampler, nvidia_smi_command
from .page import html
from .transcripts import Filter, read_sessions

# `stats --serve` without `--port`, clear of the API (4207) and UI
# (4224, 4250) defaults.
SERVE_PORT = 4210
# How often the served page asks the browser to reload it.
REFRESH_SECONDS = 60


def stats_server(
    settings: Settings,
    port: int,
    selection: Filter | None = None,
    *,
    gpu_command: list[str] | None = None,
) -> ThreadingHTTPServer:
    """The page on 127.0.0.1:`port`, re-reading the transcripts (through
    `selection`) and the rendered presets on every request, and `/live`,
    the samples of the model server. Only the server's own loopback `Host`
    names are answered, so a page on another site cannot use the browser's
    name resolution to reach it; without CORS headers the response body
    stays unreadable cross-origin either way."""
    sampler = LiveSampler(settings, gpu_command=gpu_command)
    api = settings.service_url.partition("://")[2]

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
                # The page's verdict is about the preset the last sample saw
                # loaded; the snapshot scrapes only when one is due anyway.
                samples = sampler.snapshot()
                page = html(
                    read_sessions(settings.agents_dir, selection),
                    refresh=REFRESH_SECONDS,
                    live=api,
                    selection=selection,
                    slots=rendered_slots(settings.build_dir),
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


def serve(settings: Settings, port: int, selection: Filter | None = None) -> int:
    """Serve until interrupted; Ctrl-C, SIGHUP, or SIGTERM stop it."""
    with stats_server(settings, port, selection, gpu_command=nvidia_smi_command(settings.gpu)) as server:
        print(f"Serving the stats page at http://127.0.0.1:{server.server_address[1]}/ (Ctrl-C stops it)")
        server.serve_forever()
    return 0
