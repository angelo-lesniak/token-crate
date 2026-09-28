"""The dashboard profile's llama exporter (services/dashboard/llama-exporter.js),
driven under node against a fake router and a fake store: it scrapes a
preset only after two polls reported it loaded, keeps numeric llamacpp
lines alone, serves them at /metrics, and its query gate forwards the
Prometheus read paths to the store and nothing else."""

from __future__ import annotations

import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
import unittest
import urllib.request

from tests.support import SOURCE_ROOT, free_port

EXPORTER = SOURCE_ROOT / "services" / "dashboard" / "llama-exporter.js"


class Router(http.server.BaseHTTPRequestHandler):
    loaded = "ci-small"
    metrics_fail = False
    asked: list[str] = []

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/models":
            body = json.dumps(
                {
                    "data": [
                        {"id": Router.loaded, "status": {"value": "loaded"}},
                        {"id": "ci-tiny", "status": {"value": "unloaded"}},
                        {"id": "<script>alert(1)</script>", "status": {"value": "loaded"}},
                    ]
                }
            ).encode()
        elif self.path.startswith("/metrics"):
            Router.asked.append(self.path)
            if Router.metrics_fail:
                self.send_response(503)
                self.end_headers()
                return
            body = (
                b"# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed\n"
                b"llamacpp:prompt_tokens_total 1200\n"
                b"llamacpp:tokens_predicted_total 34.5\n"
                b"llamacpp:requests_processing 1\n"
                b"llamacpp:n_busy_slots_per_decode nan\n"
                b'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="0"} 5\n'
                b'llamacpp:prompt{text="TOPSECRET-PROMPT"} 1\n'
                b"other_metric 7\n"
                b"llamacpp:evil 1; rm -rf /\n"
            )
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Store(http.server.BaseHTTPRequestHandler):
    """A stand-in for VictoriaMetrics: echoes method, path, and body."""

    seen: list[str] = []

    def log_message(self, *_args) -> None:
        pass

    def answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        Store.seen.append(f"{self.command} {self.path} {body}")
        payload = b'{"status":"success"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = answer
    do_POST = answer
    do_DELETE = answer


def fetch(port: int, path: str = "/metrics", method: str = "GET", body: bytes | None = None) -> tuple[int, str]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


@unittest.skipUnless(shutil.which("node"), "node is required to run the exporter")
class ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        Router.asked = []
        Router.loaded = "ci-small"
        Store.seen = []
        self.router = http.server.HTTPServer(("127.0.0.1", 0), Router)
        threading.Thread(target=self.router.serve_forever, daemon=True).start()
        self.addCleanup(self.router.server_close)
        self.addCleanup(self.router.shutdown)
        self.store = http.server.HTTPServer(("127.0.0.1", 0), Store)
        threading.Thread(target=self.store.serve_forever, daemon=True).start()
        self.addCleanup(self.store.server_close)
        self.addCleanup(self.store.shutdown)
        self.port = free_port()
        self.query_port = free_port()
        self.process = subprocess.Popen(
            ["node", str(EXPORTER)],
            env={
                "PATH": "/usr/bin:/bin",
                "LLAMA_URL": f"http://127.0.0.1:{self.router.server_address[1]}",
                "STORE_URL": f"http://127.0.0.1:{self.store.server_address[1]}",
                "POLL_MS": "1000",
                "PORT": str(self.port),
                "QUERY_PORT": str(self.query_port),
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.addCleanup(self.stop)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("the exporter did not listen")

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)

    def test_the_settled_preset_is_scraped_and_only_numbers_pass(self) -> None:
        _, first = fetch(self.port)
        # One poll so far: the router is up, no preset is settled, nothing asked.
        self.assertIn("tokencrate_router_up 1\n", first)
        self.assertIn("tokencrate_preset_loaded 0\n", first)
        self.assertNotIn("llamacpp:", first)
        time.sleep(2.2)
        _, body = fetch(self.port)
        self.assertIn('tokencrate_preset_loaded{preset="ci-small"} 1\n', body)
        self.assertIn('llamacpp:prompt_tokens_total{preset="ci-small"} 1200\n', body)
        self.assertIn('llamacpp:tokens_predicted_total{preset="ci-small"} 34.5\n', body)
        self.assertIn(
            'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{preset="ci-small",position="0"} 5\n', body
        )
        self.assertRegex(body, r"tokencrate_scrape_age_seconds \d+\.\d\n")
        for dropped in ("nan", "TOPSECRET", "other_metric", "rm -rf", "# HELP", "script"):
            self.assertNotIn(dropped, body)
        # Only the settled preset was ever asked for, by its validated name.
        self.assertTrue(Router.asked, "the router was never scraped")
        self.assertEqual(set(Router.asked), {"/metrics?model=ci-small"})
        # A swap: the new preset is named a poll later and scraped after that.
        Router.loaded = "ci-tiny"
        time.sleep(1.2)
        self.assertIn("tokencrate_preset_loaded 0\n", fetch(self.port)[1])
        time.sleep(1.2)
        self.assertIn('tokencrate_preset_loaded{preset="ci-tiny"} 1\n', fetch(self.port)[1])
        self.assertEqual(set(Router.asked), {"/metrics?model=ci-small", "/metrics?model=ci-tiny"})
        # Anything but GET /metrics is refused.
        self.assertEqual(fetch(self.port, "/")[0], 404)

    def test_the_query_gate_forwards_read_paths_only(self) -> None:
        status, body = fetch(self.query_port, "/api/v1/query?query=up")
        self.assertEqual((status, body), (200, '{"status":"success"}'))
        status, _ = fetch(self.query_port, "/api/v1/query_range", "POST", b"query=up&start=1&end=2&step=15")
        self.assertEqual(status, 200)
        self.assertEqual(fetch(self.query_port, "/api/v1/label/__name__/values")[0], 200)
        for refused in (
            ("/api/v1/import", "POST", b"x 1"),
            ("/api/v1/admin/tsdb/delete_series?match[]=up", "POST", None),
            ("/api/v1/admin/tsdb/delete_series?match[]=up", "GET", None),
            ("/snapshot/create", "GET", None),
            ("/api/v1/query", "DELETE", None),
            ("/api/v1/../v1/import", "POST", b"x 1"),
            ("/", "GET", None),
        ):
            status, body = fetch(self.query_port, *refused)
            self.assertEqual(status, 403, refused)
            self.assertIn("read paths only", body)
        self.assertEqual(
            Store.seen,
            [
                "GET /api/v1/query?query=up ",
                "POST /api/v1/query_range query=up&start=1&end=2&step=15",
                "GET /api/v1/label/__name__/values ",
            ],
        )

    def test_a_router_that_is_down_reports_so(self) -> None:
        self.router.shutdown()
        self.router.server_close()
        time.sleep(1.5)
        _, body = fetch(self.port)
        self.assertIn("tokencrate_router_up 0\n", body)
        self.assertIn("tokencrate_preset_loaded 0\n", body)
        self.assertNotIn("tokencrate_scrape_age_seconds", body)

    def test_a_failed_counter_read_keeps_the_preset_and_the_last_lines(self) -> None:
        time.sleep(2.2)
        self.assertIn('llamacpp:prompt_tokens_total{preset="ci-small"} 1200\n', fetch(self.port)[1])
        # The router still names the preset loaded, but its counters do not
        # answer: the preset stays reported and the last lines age.
        Router.metrics_fail = True
        self.addCleanup(setattr, Router, "metrics_fail", False)
        time.sleep(1.2)
        _, body = fetch(self.port)
        self.assertIn('tokencrate_preset_loaded{preset="ci-small"} 1\n', body)
        self.assertIn('llamacpp:prompt_tokens_total{preset="ci-small"} 1200\n', body)
        self.assertRegex(body, r"tokencrate_scrape_age_seconds [1-9]")


if __name__ == "__main__":
    unittest.main()
