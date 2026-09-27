"""The HTML stats page over synthetic transcripts: what it renders, what
it never carries, and the loopback server around it."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import unittest
from pathlib import Path
from string import Template
from tempfile import TemporaryDirectory

from tests.test_stats import write_transcripts
from tokencrate import TokenCrateError, stats, statspage

# The vendored chart library, byte-for-byte the files of the published
# npm artifact https://registry.npmjs.org/uplot/-/uplot-1.6.32.tgz (MIT).
# A version bump must change these hashes, so it can never hide inside a
# collapsed vendor diff; git already guards the bytes themselves.
VENDOR_HASHES = {
    "vendor/uPlot.iife.js": "1b71fc5e6b5b572922ed9941ed21d067207c8e5ecac0d35de66fd65d9686e791",
    "vendor/uPlot.min.css": "df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04",
}


def island(page: str) -> dict:
    """The chart's JSON data island, as the page script reads it."""
    matched = re.search(r'<script type="application/json" id="ecdf-data">(.*?)</script>', page, re.DOTALL)
    assert matched
    return json.loads(matched.group(1).replace("<\\/", "</"))


def make_session(model: str) -> stats.Session:
    request = stats.Request(
        provider="tokencrate",
        model=model,
        input=100,
        output=10,
        cache_read=0,
        cache_write=0,
        context=110,
        stop_reason="stop",
        ttft_ms=None,
        duration_ms=None,
    )
    return stats.Session("pi", requests=[request])


class StatsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory(prefix="tokencrate-stats-")
        self.addCleanup(tmp.cleanup)
        self.agents_dir = Path(tmp.name)
        write_transcripts(self.agents_dir)

    def test_the_page_charts_the_distribution_and_mirrors_the_tables(self) -> None:
        page = statspage.html(stats.read_sessions(self.agents_dir))
        self.assertIn("<title>TokenCrate stats</title>", page)
        self.assertNotIn("http-equiv", page)  # the saved page never self-reloads
        # The chart: the inlined library, its mount, a legend, and one
        # aligned series per agent in the data island.
        self.assertIn("uPlot.js", page)
        self.assertIn('<div id="ecdf" role="img" tabindex="0"', page)
        self.assertIn('<div class="legend">', page)
        data = island(page)
        self.assertEqual([series["label"] for series in data["series"]], ["pi", "omp"])
        self.assertEqual([series["slot"] for series in data["series"]], [1, 2])
        # The tables carry the same cells as the Markdown report.
        self.assertIn("<tr><td>pi</td>", page)
        self.assertIn('<td class="n">2</td><td class="n">4</td><td class="n">1500</td>', page)
        self.assertIn("<td>openrouter</td><td>acme/model/x</td>", page)
        # Escaping: a transcript string cannot smuggle markup into the page.
        self.assertNotIn("<script>alert", statspage.html([make_session("<script>alert(1)</script>")]))
        for secret in ("TOPSECRET", "PROJECTSECRET", "/srv/"):
            self.assertNotIn(secret, page)

    def test_the_data_island_is_aligned_bounded_and_right_continuous(self) -> None:
        data = island(statspage.html(stats.read_sessions(self.agents_dir)))
        # The fixture's largest context is 19,160 tokens: an 8,192-token
        # tick and one x axis from 0 to the next tick multiple.
        self.assertEqual(data["tick"], 8192)
        self.assertEqual(data["xmax"], 24576)
        self.assertEqual(data["x"][0], 0)
        self.assertEqual(data["x"][-1], 24576)
        self.assertEqual(data["x"], sorted(data["x"]))
        for series in data["series"]:
            values = series["values"]
            self.assertEqual(len(values), len(data["x"]))
            # Leading zeros up to the first observed context, monotone to
            # the full share, and the flat tail out to xmax.
            self.assertEqual(values[0], 0)
            self.assertEqual(values, sorted(values))
            self.assertEqual(values[-1], 1.0)

    def test_a_single_agent_page_names_it_without_a_legend(self) -> None:
        page = statspage.html([make_session("qwen-solo")])
        self.assertNotIn('<div class="legend">', page)
        self.assertIn("(pi)</figcaption>", page)
        # A one-point distribution still spans the axis: zero at the
        # origin, the full share at the observed context and the far edge.
        data = island(page)
        self.assertEqual(data["series"][0]["values"][0], 0)
        self.assertEqual(data["series"][0]["values"][-1], 1.0)

    def test_the_vendored_chart_library_is_the_pinned_artifact(self) -> None:
        for name, expected in VENDOR_HASHES.items():
            blob = statspage.asset(name)
            self.assertEqual(hashlib.sha256(blob.encode("utf-8")).hexdigest(), expected, name)
            # Inlined verbatim into <script>/<style>, so these substrings
            # would end the element early; their absence is hash-frozen.
            for stop in ("</script", "</style", "<!--"):
                self.assertNotIn(stop, blob, name)
        page = statspage.html([make_session("qwen-solo")])
        self.assertIn("Copyright (c) 2025, Leon Sorokin", page)  # the license header ships with every page

    def test_the_skeleton_slots_are_exactly_what_the_renderer_fills(self) -> None:
        # `substitute` would raise on a slot the renderer misses; this pins
        # the other direction, a skeleton edit that drops or renames one.
        identifiers = Template(statspage.asset("stats.html")).get_identifiers()
        slots = ["chart", "footnote", "meta", "refresh", "script", "style", "tables", "tiles"]
        self.assertEqual(sorted(identifiers), slots + ["vendorscript", "vendorstyle"])


class StatsServeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory(prefix="tokencrate-stats-")
        self.addCleanup(tmp.cleanup)
        self.agents_dir = Path(tmp.name)
        write_transcripts(self.agents_dir)
        self.server = statspage.stats_server(self.agents_dir, 0)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def fetch(self, path: str, host: str | None = None) -> tuple[int, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        headers = {"Host": host} if host else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")

    def test_the_page_is_served_on_its_own_loopback_names_only(self) -> None:
        status, body = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("<title>TokenCrate stats</title>", body)
        # The served page reloads itself; the saved one does not.
        self.assertIn('<meta http-equiv="refresh" content="60">', body)
        status, _ = self.fetch("/", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)
        for foreign in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", "127.0.0.1:1"):
            status, body = self.fetch("/", host=foreign)
            self.assertEqual(status, 403, foreign)
            self.assertIn("loopback host names", body)
        status, _ = self.fetch("/elsewhere")
        self.assertEqual(status, 404)

    def test_without_transcripts_the_server_answers_503(self) -> None:
        with TemporaryDirectory(prefix="tokencrate-stats-") as empty:
            server = statspage.stats_server(Path(empty), 0)
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            self.addCleanup(connection.close)
            connection.request("GET", "/")
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertIn("no agent transcripts below", response.read().decode("utf-8"))

    def test_an_occupied_port_is_a_one_sentence_refusal(self) -> None:
        with self.assertRaises(TokenCrateError) as caught:
            statspage.stats_server(self.agents_dir, self.port)
        self.assertIn(f"cannot serve the stats page on 127.0.0.1:{self.port}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
