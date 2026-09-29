"""The HTML stats page over synthetic transcripts: what it renders, what
it never carries, and the loopback server around it."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class FakeRouter:
    """A loopback stand-in for the model server's API: `/models` with one
    loaded preset, an unloaded one, and a hostile name; `/metrics` whose
    counters advance per scrape, with a labelled line, a non-numeric
    value, and a text label that must never reach a sample."""

    def __init__(self) -> None:
        self.scrapes = 0
        self.reset_at: int | None = None
        self.loaded = "ci-small"
        self.asked: list[str] = []
        router = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments) -> None:
                return

            def do_GET(self) -> None:
                if self.path == "/models":
                    body = json.dumps(
                        {
                            "data": [
                                {"id": router.loaded, "status": {"value": "loaded"}},
                                {"id": "ci-tiny", "status": {"value": "unloaded"}},
                                {"id": "<script>alert(1)</script>", "status": {"value": "loaded"}},
                                {"id": "SLEEPY", "status": {"value": "sleeping"}},
                            ]
                        }
                    ).encode()
                elif self.path.startswith("/metrics"):
                    router.asked.append(self.path)
                    if self.path != f"/metrics?model={router.loaded}":
                        self.send_response(400)
                        self.end_headers()
                        return
                    router.scrapes += 1
                    tick = router.scrapes - (router.reset_at or 0) if router.reset_at else router.scrapes
                    body = (
                        f"# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed\n"
                        f"llamacpp:prompt_tokens_total {100 * tick}\n"
                        f"llamacpp:tokens_predicted_total {10 * tick}\n"
                        f"llamacpp:requests_processing 1\n"
                        f"llamacpp:requests_deferred 2\n"
                        f"llamacpp:n_busy_slots_per_decode nan\n"
                        f'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{{position="0"}} 5\n'
                        f"llamacpp:spec_decode_num_accepted_tokens_total {5 * tick}\n"
                        f"llamacpp:spec_decode_num_draft_tokens_total {8 * tick}\n"
                        f'llamacpp:prompt{{text="TOPSECRET-PROMPT"}} 1\n'
                    ).encode()
                else:
                    self.send_response(400)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LiveSamplerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = FakeRouter()
        self.addCleanup(self.router.close)

    def test_samples_carry_gauges_and_rates_of_the_settled_preset_only(self) -> None:
        clock = [1000.0]
        sampler = statspage.LiveSampler(self.router.url, interval=2, clock=lambda: clock[0])
        first = sampler.snapshot()[-1]
        # Seen loaded once: named, not yet scraped (a swap in between would
        # otherwise ask the router to load a preset that just unloaded).
        self.assertEqual((first.up, first.model, first.scraped, first.processing), (True, "ci-small", False, None))
        self.assertEqual(self.router.scrapes, 0)
        clock[0] += 2
        second = sampler.snapshot()[-1]
        self.assertEqual((second.scraped, second.processing, second.deferred, second.prompt_rate), (True, 1, 2, None))
        self.assertEqual(second.acceptance, 0.625)
        clock[0] += 2
        third = sampler.snapshot()[-1]
        # The fake advances its counters by 100 and 10 per scrape.
        self.assertEqual((third.prompt_rate, third.generation_rate), (50.0, 5.0))
        self.assertGreater(third.t, 1_700_000_000)
        # A counter that went backwards is a restart: no rate for that tick.
        self.router.reset_at = self.router.scrapes + 1
        clock[0] += 2
        self.assertIsNone(sampler.snapshot()[-1].prompt_rate)
        clock[0] += 2
        self.assertEqual(sampler.snapshot()[-1].prompt_rate, 50.0)
        # A swap: the new preset is named, and scraped from the next tick on.
        self.router.loaded = "ci-tiny"
        clock[0] += 2
        swapped = sampler.snapshot()[-1]
        self.assertEqual((swapped.model, swapped.scraped, swapped.processing), ("ci-tiny", False, None))
        clock[0] += 2
        self.assertEqual(sampler.snapshot()[-1].processing, 1)
        # Only settled presets were ever asked for their counters.
        self.assertEqual(sorted(set(sampler.asked)), ["ci-small", "ci-tiny"])
        self.assertEqual(self.router.asked, [f"/metrics?model={name}" for name in sampler.asked])
        for sample in sampler.samples:
            for value in vars(sample).values():
                self.assertIsInstance(value, (bool, int, float, str, type(None)))
            self.assertNotIn("script", str(sample.model))
            self.assertNotIn("TOPSECRET", json.dumps(vars(sample)))

    def test_one_scrape_runs_at_a_time(self) -> None:
        # A poll that lands while a scrape is in flight (a slow router) returns
        # the ring as it is instead of starting a second, overlapping scrape.
        import threading

        sampler = statspage.LiveSampler(self.router.url, interval=0)
        started = threading.Event()
        release = threading.Event()
        original = sampler.scrape

        def slow_scrape():
            started.set()
            release.wait(5)
            return original()

        sampler.scrape = slow_scrape
        thread = threading.Thread(target=sampler.snapshot)
        thread.start()
        started.wait(5)
        self.assertEqual(sampler.snapshot(), [])
        release.set()
        thread.join(5)
        self.assertEqual(len(sampler.snapshot()), 2)

    def test_a_snapshot_within_the_interval_scrapes_nothing_and_the_ring_is_bounded(self) -> None:
        sampler = statspage.LiveSampler(self.router.url, interval=60)
        for _ in range(3):
            sampler.snapshot()
        self.assertEqual(len(sampler.samples), 1)
        with unittest.mock.patch.object(statspage, "LIVE_SAMPLES", 3):
            sampler = statspage.LiveSampler(self.router.url, interval=0)
            for _ in range(8):
                sampler.snapshot()
        self.assertEqual(len(sampler.samples), 3)

    def test_the_gpu_reading_keeps_numbers_only(self) -> None:
        # A fake nvidia-smi: memory and power as the query prints them, a
        # `[N/A]` field, a second GPU that is ignored, and a failing one.
        with TemporaryDirectory(prefix="tokencrate-smi-") as tmp:
            fake = Path(tmp) / "nvidia-smi"
            fake.write_text(
                '#!/bin/sh\ncase "$FAKE_SMI" in\n'
                "  na) echo '21244, 32607, [N/A]' ;;\n"
                "  fail) exit 9 ;;\n"
                "  *) echo '21244, 32607, 312.55'; echo '100, 200, 50' ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            command = [str(fake), *statspage.NVIDIA_SMI_QUERY]
            with unittest.mock.patch.dict("os.environ", {"FAKE_SMI": "ok"}):
                self.assertEqual(statspage.gpu_reading(command), (21244, 32607, 312.6))
                sampler = statspage.LiveSampler(self.router.url, interval=0, gpu_command=command)
                sample = sampler.snapshot()[-1]
                self.assertEqual((sample.gpu_memory_mib, sample.gpu_memory_total_mib), (21244, 32607))
                self.assertEqual(sample.gpu_power_w, 312.6)
            with unittest.mock.patch.dict("os.environ", {"FAKE_SMI": "na"}):
                self.assertEqual(statspage.gpu_reading(command), (21244, 32607, None))
            with unittest.mock.patch.dict("os.environ", {"FAKE_SMI": "fail"}):
                self.assertEqual(statspage.gpu_reading(command), (None, None, None))
            self.assertEqual(statspage.gpu_reading([str(fake) + "-missing"]), (None, None, None))
        self.assertIsNone(statspage.nvidia_smi_command(False))
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            self.assertEqual(statspage.nvidia_smi_command(True), ["/usr/bin/nvidia-smi", *statspage.NVIDIA_SMI_QUERY])

    def test_a_stack_that_is_down_gives_unreachable_samples(self) -> None:
        self.router.close()
        sampler = statspage.LiveSampler(self.router.url, interval=0)
        sample = sampler.snapshot()[-1]
        self.assertEqual((sample.up, sample.model, sample.scraped, sample.prompt_rate), (False, None, False, None))


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
        # The tables carry the same cells as the Markdown report, in scroll
        # regions with column headers, and whole numbers get separators.
        self.assertIn("<tr><td>pi</td>", page)
        self.assertIn('<td class="n">2</td><td class="n">4</td><td class="n">0</td><td class="n">0s</td>', page)
        self.assertIn('<div class="scroll" role="region" tabindex="0" aria-label="Sessions">', page)
        self.assertIn('<th class="n" scope="col"><button type="button">Sessions</button></th>', page)
        self.assertIn('<td class="n">16,500</td>', page)
        self.assertNotIn("title=", page)
        self.assertIn('<ul class="definitions">\n<li><b>Context</b>: one request as the server saw it', page)
        # The saved page has no verdict; the fit table follows the slots.
        self.assertNotIn('class="verdict"', page)
        self.assertIn("No rendered presets", page)
        fitted = statspage.html(stats.read_sessions(self.agents_dir), slots={"ci-small": 16384})
        self.assertIn('<tr><td>ci-small</td><td class="n">16,384</td><td class="n">3</td>', fitted)
        # The meta line names the scope and the filters the page was made
        # with; the render time is in the footer; nothing names the directory.
        self.assertIn('<p class="meta">3 sessions, 6 requests, all agents, all time; none in the last 24 h</p>', page)
        self.assertNotIn("LLM_AGENTS_DIR", page)
        self.assertRegex(page, r"<footer>Rendered 20\d\d-\d\d-\d\d \d\d:\d\d:\d\d [A-Z]+\.</footer>")
        filtered = statspage.html(
            stats.read_sessions(self.agents_dir, stats.Filter(agent="pi")), selection=stats.Filter(agent="pi")
        )
        self.assertIn("2 sessions, 4 requests, agent pi, all time; none in the last 24 h</p>", filtered)
        # Section navigation, sortable headers, the total row as a footer,
        # the share meters, and monospace model cells.
        self.assertIn('<nav><a href="#context">Context</a><a href="#preset-fit">Preset fit</a>', page)
        self.assertIn('<a href="#definitions">Definitions</a></nav>', page)
        self.assertIn('<h2 id="definitions">Definitions</h2>', page)
        self.assertIn('<h2 id="providers-and-models">', page)
        self.assertIn('<th scope="col"><button type="button">Agent</button></th>', page)
        self.assertIn("<tfoot><tr><td>all</td>", page)
        self.assertIn('<td class="n share" style="--share: 74%">74%</td>', page)
        self.assertIn('<td class="mono">acme/model/x</td>', page)
        self.assertNotIn('<td class="mono"><script>', statspage.html([make_session("<script>alert(1)</script>")]))
        self.assertIn('<td>openrouter</td><td class="mono">acme/model/x</td>', page)
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

    def test_the_chart_marks_the_compaction_and_one_slot(self) -> None:
        sessions = stats.read_sessions(self.agents_dir)
        # No rendered presets: the compaction p50 is the only mark.
        self.assertEqual(island(statspage.html(sessions))["marks"], [{"label": "compaction p50", "value": 16500}])
        # The most-used rendered preset's slot (the fixture's local model
        # is not a rendered preset, so none is marked) ...
        self.assertEqual(len(island(statspage.html(sessions, slots={"ci-small": 32768}))["marks"]), 1)
        # ... unless a request names it: the axis extends to a slot within
        # twice the largest context, and a roomier slot is marked beyond.
        slots = {"qwen-fixture": 32768, "other": 1024}
        data = island(statspage.html(sessions, slots=slots))
        self.assertEqual(data["marks"][1], {"label": "qwen-fixture slot (most used)", "value": 32768, "beyond": False})
        self.assertEqual(data["xmax"], 32768)
        data = island(statspage.html(sessions, slots={"qwen-fixture": 131072}))
        self.assertEqual(data["marks"][1]["beyond"], True)
        self.assertEqual(data["xmax"], 24576)
        # The served page marks the loaded preset and leads with its verdict.
        served = statspage.html(
            sessions, live="127.0.0.1:1", slots={"ci-small": 16384, "ci-big": 32768}, loaded="ci-small"
        )
        self.assertEqual(island(served)["marks"][1]["label"], "ci-small slot (loaded)")
        self.assertIn(
            '<section class="verdict" data-status="critical"><span class="dot" aria-hidden="true">\u2715</span>'
            "<b>ci-small</b> (slot 16,384 tokens, loaded): 3 of 6 requests (50%) would not fit</section>",
            served,
        )
        served = statspage.html(sessions, live="127.0.0.1:1", slots={"ci-big": 32768}, loaded="ci-big")
        self.assertIn('data-status="good"><span class="dot" aria-hidden="true">\u2713</span><b>ci-big</b>', served)
        self.assertIn("(slot 32,768 tokens, loaded): every request fit</section>", served)
        served = statspage.html(sessions, live="127.0.0.1:1", slots={"ci-big": 32768}, loaded=None)
        self.assertIn('data-status="none"', served)
        self.assertIn("No preset loaded; the Preset fit table judges every rendered preset.", served)
        served = statspage.html(sessions, live="127.0.0.1:1", slots={"ci-big": 32768}, loaded=None, down=True)
        self.assertIn("Model server not reachable; the Preset fit table judges", served)
        served = statspage.html(sessions, live="127.0.0.1:1", slots={}, loaded="ci-big")
        self.assertIn("<b>ci-big</b> is loaded but not in build/models.ini; the Preset fit table", served)
        # The GPU tiles exist only when the server runs a GPU query.
        self.assertIn('data-gpu="0"', served)
        self.assertIn('data-gpu="1"', statspage.html(sessions, live="127.0.0.1:1", gpu=True))

    def test_a_single_agent_page_names_it_without_a_legend(self) -> None:
        page = statspage.html([make_session("qwen-solo")])
        self.assertNotIn('<div class="legend">', page)
        self.assertIn("(pi)</figcaption>", page)
        self.assertNotIn("<tfoot>", page)  # one agent: no total row
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
        slots = ["chart", "definitions", "footer", "hero", "live", "meta", "nav", "refresh", "script", "style"]
        slots += ["tables", "tiles"]
        self.assertEqual(sorted(identifiers), slots + ["vendorscript", "vendorstyle"])


class StatsServeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory(prefix="tokencrate-stats-")
        self.addCleanup(tmp.cleanup)
        self.agents_dir = Path(tmp.name)
        write_transcripts(self.agents_dir)
        self.router = FakeRouter()
        self.addCleanup(self.router.close)
        self.build_dir = self.agents_dir / "build"
        self.build_dir.mkdir()
        (self.build_dir / "models.ini").write_text("[ci-small]\nctx-size = 16384\nparallel = 1\n", encoding="utf-8")
        self.server = statspage.stats_server(self.agents_dir, 0, self.router.url, build_dir=self.build_dir)
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
        # The served page reloads itself and carries the live panel's
        # script; the saved one has neither.
        self.assertIn('<meta http-equiv="refresh" content="60">', body)
        self.assertIn('<script id="live-script" data-api="127.0.0.1:', body)
        self.assertIn('fetch("/live"', body)
        # The served page's verdict is about the preset the sampler saw
        # loaded, against the rendered slots; the fake router loads
        # ci-small, whose 16K slot would refuse three fixture requests.
        self.assertIn("<b>ci-small</b> (slot 16,384 tokens, loaded): 3 of 6 requests (50%) would not fit", body)
        self.assertIn("<tr><td>ci-small</td>", body)
        saved = statspage.html(stats.read_sessions(self.agents_dir))
        self.assertNotIn("live-script", saved)
        self.assertNotIn("/live", saved)
        self.assertNotIn("http-equiv", saved)
        status, _ = self.fetch("/", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)
        for foreign in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", "127.0.0.1:1"):
            status, body = self.fetch("/", host=foreign)
            self.assertEqual(status, 403, foreign)
            self.assertIn("loopback host names", body)
        status, _ = self.fetch("/elsewhere")
        self.assertEqual(status, 404)

    def test_live_answers_json_of_numbers_on_the_same_names_only(self) -> None:
        status, body = self.fetch("/live")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(sorted(data), ["api", "samples"])
        self.assertEqual(data["api"], self.router.url.partition("://")[2])
        self.assertEqual(len(data["samples"]), 1)
        sample = data["samples"][0]
        self.assertEqual(
            sorted(sample),
            [
                "acceptance",
                "deferred",
                "generation_rate",
                "gpu_memory_mib",
                "gpu_memory_total_mib",
                "gpu_power_w",
                "model",
                "processing",
                "prompt_rate",
                "scraped",
                "t",
                "up",
            ],
        )
        # Without a GPU command the tiles stay empty.
        self.assertEqual((sample["acceptance"], sample["gpu_memory_mib"], sample["gpu_power_w"]), (None, None, None))
        self.assertEqual((sample["up"], sample["model"]), (True, "ci-small"))
        for foreign in ("evil.example", f"evil.example:{self.port}"):
            status, _ = self.fetch("/live", host=foreign)
            self.assertEqual(status, 403, foreign)
        status, _ = self.fetch("/live/x")
        self.assertEqual(status, 404)

    def test_without_transcripts_the_server_answers_503(self) -> None:
        with TemporaryDirectory(prefix="tokencrate-stats-") as empty:
            server = statspage.stats_server(Path(empty), 0, self.router.url)
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
            statspage.stats_server(self.agents_dir, self.port, self.router.url)
        self.assertIn(f"cannot serve the stats page on 127.0.0.1:{self.port}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
