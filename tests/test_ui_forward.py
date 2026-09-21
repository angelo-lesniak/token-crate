"""The UI forwarder (services/agents/ui-forward.js): it passes requests and
WebSocket upgrades to the target and refuses requests for another host or
from another origin."""

from __future__ import annotations

import http.client
import http.server
import shutil
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests.support import SOURCE_ROOT, free_port

FORWARDER = SOURCE_ROOT / "services" / "agents" / "ui-forward.js"


class Target(http.server.BaseHTTPRequestHandler):
    """A stand-in for the UI: echoes the path, and answers an upgrade with 101."""

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        self.server.received_headers = list(self.headers.items())
        if self.path == "/truncated":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"hello")
            self.close_connection = True
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(300):
                    self.wfile.write(b"data: heartbeat\n\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except OSError:
                self.server.stream_closed.set()
            return
        if self.headers.get("Upgrade") == "websocket":
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.end_headers()
            self.wfile.write(b"upgraded:" + self.rfile.readline())
            return
        body = f"path={self.path} host={self.headers.get('Host')}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def wait_for_port(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"nothing listens on {port}")


@unittest.skipUnless(shutil.which("node"), "node is required to run the forwarder")
class ForwarderTests(unittest.TestCase):
    published_port: int | None = None

    def setUp(self) -> None:
        self.target_port = free_port()
        self.listen_port = free_port()
        self.published_port = self.published_port or self.listen_port
        self.target = http.server.ThreadingHTTPServer(("127.0.0.1", self.target_port), Target)
        self.target.stream_closed = threading.Event()
        threading.Thread(target=self.target.serve_forever, daemon=True).start()
        self.addCleanup(self.target.server_close)
        self.addCleanup(self.target.shutdown)
        self.forwarder = subprocess.Popen(
            [
                "node",
                str(FORWARDER),
                "127.0.0.1",
                str(self.target_port),
                str(self.listen_port),
                str(self.published_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.stop_forwarder)
        wait_for_port(self.listen_port)

    def stop_forwarder(self) -> None:
        self.forwarder.kill()
        self.forwarder.wait()

    def test_truncated_backend_response_closes_the_browser_connection(self) -> None:
        with self.assertRaises(http.client.IncompleteRead):
            self.get("/truncated")
        self.assertEqual(self.get("/")[0], 200)

    def test_browser_cancellation_closes_the_backend_stream(self) -> None:
        with socket.create_connection(("127.0.0.1", self.listen_port), timeout=2) as client:
            client.sendall(f"GET /stream HTTP/1.1\r\nHost: 127.0.0.1:{self.published_port}\r\n\r\n".encode())
            self.assertIn(b"200", client.recv(4096))
        self.assertTrue(self.target.stream_closed.wait(2), "the canceled stream remained open upstream")

    def get(self, path: str, **headers: str) -> tuple[int, str]:
        headers.setdefault("Host", f"127.0.0.1:{self.published_port}")
        request = urllib.request.Request(f"http://127.0.0.1:{self.listen_port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read().decode()

    def test_requests_for_the_published_address_reach_the_target(self) -> None:
        status, body = self.get("/api/x?y=1")
        self.assertEqual(status, 200)
        self.assertEqual(body, f"path=/api/x?y=1 host=127.0.0.1:{self.published_port}")
        status, _ = self.get("/", Origin=f"http://127.0.0.1:{self.published_port}")
        self.assertEqual(status, 200)
        status, _ = self.get("/", Host=f"localhost:{self.published_port}")
        self.assertEqual(status, 200)

    def test_another_host_or_origin_is_refused(self) -> None:
        status, body = self.get("/", Host=f"ui.example.com:{self.published_port}")
        self.assertEqual(status, 403)
        self.assertIn("refused a request for host ui.example.com", body)
        status, _ = self.get("/", Origin="http://evil.example.com")
        self.assertEqual(status, 403)
        status, _ = self.get("/", Origin="null")
        self.assertEqual(status, 403)

    def test_a_browser_request_from_another_site_is_refused(self) -> None:
        # Browsers say where a request comes from; a page of the UI itself or
        # a typed address passes, another site does not, and a client without
        # the header (curl, the wrapper's readiness poll) passes.
        for site in ("same-origin", "none"):
            status, _ = self.get("/", **{"Sec-Fetch-Site": site})
            self.assertEqual(status, 200, site)
        for site in ("cross-site", "same-site"):
            status, body = self.get("/", **{"Sec-Fetch-Site": site})
            self.assertEqual(status, 403, site)
            self.assertIn(f"(Sec-Fetch-Site: {site})", body)
        # Paseo's web client connects to localhost from a page opened as
        # 127.0.0.1, which the browser calls cross-site; the Origin header
        # still names the UI and settles it, and a foreign Origin never passes.
        ui = f"http://127.0.0.1:{self.published_port}"
        cross = {"Sec-Fetch-Site": "cross-site"}
        status, _ = self.get("/", Host=f"localhost:{self.published_port}", Origin=ui, **cross)
        self.assertEqual(status, 200)
        status, _ = self.get("/", Origin="http://evil.example.com", **cross)
        self.assertEqual(status, 403)

    def upgrade(self, **headers: str) -> bytes:
        headers.setdefault("Host", f"127.0.0.1:{self.published_port}")
        raw = "GET /ws HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items())
        raw += "Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
        with socket.create_connection(("127.0.0.1", self.listen_port), timeout=5) as sock:
            sock.sendall(raw.encode() + b"frame\n")
            received = b""
            while b"upgraded:frame" not in received and b"403" not in received:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                received += chunk
            return received

    def test_websocket_upgrades_pass_through_with_the_same_check(self) -> None:
        good = self.upgrade(Origin=f"http://127.0.0.1:{self.published_port}")
        self.assertIn(b" 101 ", good)
        self.assertIn(b"upgraded:frame", good)

    def test_upgrade_forwards_only_the_validated_host(self) -> None:
        with socket.create_connection(("127.0.0.1", self.listen_port), timeout=2) as client:
            client.sendall(
                f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.published_port}\r\n"
                "Host: other.example.invalid\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\nframe\n".encode()
            )
            self.assertIn(b"101", client.recv(4096))
        hosts = [value for name, value in self.target.received_headers if name.lower() == "host"]
        self.assertEqual(hosts, [f"127.0.0.1:{self.published_port}"])

    def test_http_and_websocket_authorization(self) -> None:
        authorities = [f"{host}:{self.published_port}" for host in ("127.0.0.1", "localhost", "[::1]")]
        implicit = ["127.0.0.1", "localhost", "[::1]"]
        if self.published_port == 80:
            authorities += implicit
        cases = []
        for host in authorities:
            cases.append((True, {"Host": host}))
            for site in ("none", "same-origin", "same-site", "cross-site"):
                cases.append((site in ("none", "same-origin"), {"Host": host, "Sec-Fetch-Site": site}))
            for origin in authorities:
                cases.append((True, {"Host": host, "Origin": f"http://{origin}", "Sec-Fetch-Site": "cross-site"}))
        foreign = [
            f"evil.example.com:{self.published_port}",
            f"localhost.evil.example:{self.published_port}",
            f"127.0.0.2:{self.published_port}",
            "127.0.0.1:81",
        ]
        if self.published_port != 80:
            foreign += implicit
        for host in foreign:
            cases.append((False, {"Host": host, "Origin": f"http://{authorities[0]}"}))
        for origin in [
            *[f"http://{host}" for host in foreign],
            f"https://{authorities[0]}",
            f"ws://{authorities[0]}",
            authorities[0],
            f"http://{authorities[0]}/",
            f"http://user@{authorities[0]}",
            "null",
            "",
        ]:
            for site in ("same-origin", "cross-site"):
                cases.append((False, {"Origin": origin, "Sec-Fetch-Site": site}))
        for allowed, headers in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.get("/", **headers)[0], 200 if allowed else 403)
                self.assertIn(b" 101 " if allowed else b" 403 ", self.upgrade(**headers))


class Port80ForwarderTests(ForwarderTests):
    # Published authority and actual listener are independent; no privileged bind.
    published_port = 80


if __name__ == "__main__":
    unittest.main()
