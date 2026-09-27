"""The stats report over synthetic transcripts: what it counts, what it
never prints, and the command around it."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import Scratch
from tokencrate import TokenCrateError, stats

CWD_DIRECTORY = "--srv-PROJECTSECRET--"


def entry(**fields) -> str:
    return json.dumps(fields)


def assistant(provider: str, model: str, stop: str, usage: dict | None, **extra) -> str:
    message: dict = {"role": "assistant", "provider": provider, "model": model, "stopReason": stop, **extra}
    message["content"] = [{"type": "text", "text": "TOPSECRET-ANSWER"}]
    if usage is not None:
        message["usage"] = {"cost": {"total": 0}, **usage}
    return entry(type="message", id="e1", timestamp="2026-09-21T16:00:00.000Z", message=message)


def tokens(input: int, output: int, cache_read: int, cache_write: int = 0) -> dict:
    return {
        "input": input,
        "output": output,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "reasoning": 0,
        "totalTokens": input + output + cache_read + cache_write,
    }


PI_SESSION = "\n".join(
    [
        entry(type="session", version=3, id="a", timestamp="2026-09-21T16:00:00.000Z", cwd="/srv/PROJECTSECRET"),
        entry(type="session_info", id="i", name="TOPSECRET-NAME"),
        entry(type="message", id="u", message={"role": "user", "content": "TOPSECRET-PROMPT"}),
        assistant("tokencrate", "qwen-fixture", "toolUse", tokens(500, 100, 1000)),
        entry(type="message", id="t", message={"role": "toolResult", "toolName": "read", "isError": False}),
        "{not json",
        assistant("tokencrate", "qwen-fixture", "stop", tokens(400, 100, 16000)),
        entry(type="compaction", id="c", tokensBefore=16500, summary="TOPSECRET-SUMMARY"),
        assistant("tokencrate", "qwen-fixture", "stop", tokens(3000, 200, 0, 800)),
    ]
)
CLOUD_SESSION = assistant("openrouter", "acme/model|x", "stop", tokens(2000, 50, 0))
OMP_SESSION = "\n".join(
    [
        entry(type="session", version=3, id="b", timestamp="2026-09-21T17:00:00.000Z", cwd="/srv/PROJECTSECRET"),
        assistant(
            "tokencrate",
            "qwen-fixture",
            "stop",
            tokens(19000, 40, 0),
            ttft=1200.5,
            duration=3400.5,
            contextSnapshot={"promptTokens": 19000, "nonMessageTokens": 16000, "compactionEpoch": 0},
        ),
        entry(type="message", id="t", message={"role": "toolResult", "toolName": "bash", "isError": True}),
        assistant("tokencrate", "qwen-fixture", "error", None, errorMessage="boom"),
        assistant("tokencrate", "qwen-fixture", "toolUse", tokens(100, 60, 19000), ttft=800.0, duration=1500.0),
    ]
)


def write_transcripts(agents_dir: Path) -> None:
    pi_sessions = agents_dir / "pi" / "PROJECTSECRET-1a2b3c" / ".pi" / "agent" / "sessions" / CWD_DIRECTORY
    omp_sessions = agents_dir / "omp" / "PROJECTSECRET-9z8y7x" / ".omp" / "agent" / "sessions" / CWD_DIRECTORY
    pi_sessions.mkdir(parents=True)
    omp_sessions.mkdir(parents=True)
    (pi_sessions / "2026-09-21T16-00-00-000Z_a.jsonl").write_text(PI_SESSION, encoding="utf-8")
    (pi_sessions / "2026-09-21T18-00-00-000Z_c.jsonl").write_text(CLOUD_SESSION, encoding="utf-8")
    (pi_sessions / "abandoned.jsonl").write_text(entry(type="session", version=3, id="x"), encoding="utf-8")
    (omp_sessions / "2026-09-21T17-00-00-000Z_b.jsonl").write_text(OMP_SESSION, encoding="utf-8")
    # Not transcripts: a UI extension's registry below the same home, and
    # oh-my-pi's terminal buffers; a loose glob would count both.
    registry = agents_dir / "pi" / "PROJECTSECRET-1a2b3c" / ".config" / "ui-ext" / "sessions"
    registry.mkdir(parents=True)
    (registry / "x.registry.jsonl").write_text(assistant("tokencrate", "decoy", "stop", tokens(999999, 1, 0)))
    terminals = agents_dir / "omp" / "PROJECTSECRET-9z8y7x" / ".omp" / "agent" / "terminal-sessions"
    terminals.mkdir(parents=True)
    (terminals / "t.jsonl").write_text(assistant("tokencrate", "decoy", "stop", tokens(888888, 1, 0)))


class StatsReportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory(prefix="tokencrate-stats-")
        self.addCleanup(tmp.cleanup)
        self.agents_dir = Path(tmp.name)
        write_transcripts(self.agents_dir)

    def test_the_report_aggregates_sessions_requests_models_and_timings(self) -> None:
        text = stats.report(self.agents_dir)
        self.assertTrue(text.startswith("# TokenCrate stats report\n\n- Date: "), text)
        self.assertIn("- Transcripts: 3 session(s), 6 request(s) below LLM_AGENTS_DIR\n", text)
        # Sessions: count, requests, first-request p50, peak context
        # p50/p90/max, compactions with the p50 context before them.
        self.assertIn("| pi | 2 | 4 | 1500 | 2050 | 16500 | 16500 | 1 (p50 before: 16500) |", text)
        self.assertIn("| omp | 1 | 2 | 19000 | 19160 | 19160 | 19160 | 0 |", text)
        # Requests: input and output are summed once per request; the context
        # columns are nearest-rank percentiles and the >16K/32K/48K shares.
        self.assertIn("| pi | 4 | 5900 | 450 | 74% | 2050 | 16500 | 16500 | 25% | 0% | 0% |", text)
        self.assertIn("| omp | 2 | 19100 | 100 | 50% | 19040 | 19160 | 19160 | 100% | 0% | 0% |", text)
        self.assertIn("| all | 6 | 25000 | 550 | 59% | 4000 | 19160 | 19160 | 50% | 0% | 0% |", text)
        # Providers and models: local and cloud rows stay apart, and a pipe
        # in a transcript-supplied name cannot break the table.
        self.assertIn("| tokencrate | qwen-fixture | 5 |", text)
        self.assertIn("| openrouter | acme/model/x | 1 | 2000 | 50 |", text)
        self.assertIn("| pi | 1 | 0 | stop 3, toolUse 1 |", text)
        self.assertIn("| omp | 1 | 1 | stop 1, toolUse 1 |", text)
        # Timings exist only where a transcript carries ttft and duration.
        self.assertIn("| tokencrate | qwen-fixture | 2 | 800 | 1200 | 1500 | 3400 |", text)

    def test_the_report_carries_no_content_names_or_paths(self) -> None:
        text = stats.report(self.agents_dir)
        for secret in ("TOPSECRET", "PROJECTSECRET", "/srv/", "boom", "999999", "888888", "decoy"):
            self.assertNotIn(secret, text)

    def test_an_errored_turn_and_an_abandoned_session_are_not_counted(self) -> None:
        sessions = stats.read_sessions(self.agents_dir)
        self.assertEqual([session.agent for session in sessions], ["pi", "pi", "omp"])
        self.assertEqual(sum(len(session.requests) for session in sessions), 6)

    def test_without_transcripts_the_report_says_where_they_would_be(self) -> None:
        with TemporaryDirectory(prefix="tokencrate-stats-") as empty:
            with self.assertRaises(TokenCrateError) as caught:
                stats.report(Path(empty))
        self.assertIn("no agent transcripts below", str(caught.exception))

    def test_a_planted_symlink_cannot_route_the_reader_outside(self) -> None:
        sessions = self.agents_dir / "pi" / "PROJECTSECRET-1a2b3c" / ".pi" / "agent" / "sessions" / CWD_DIRECTORY
        with TemporaryDirectory(prefix="tokencrate-outside-") as outside:
            foreign = Path(outside) / "foreign.jsonl"
            foreign.write_text(assistant("tokencrate", "FOREIGNMODEL", "stop", tokens(1, 1, 0)), encoding="utf-8")
            (sessions / "link.jsonl").symlink_to(foreign)
            linked = Path(outside) / "linked-sessions"
            linked.mkdir()
            (linked / "x.jsonl").write_text(assistant("tokencrate", "FOREIGNMODEL", "stop", tokens(1, 1, 0)))
            (sessions / "linked").symlink_to(linked)
            text = stats.report(self.agents_dir)
        self.assertNotIn("FOREIGNMODEL", text)

    def test_a_line_beyond_the_limit_is_skipped(self) -> None:
        sessions = self.agents_dir / "pi" / "PROJECTSECRET-1a2b3c" / ".pi" / "agent" / "sessions" / CWD_DIRECTORY
        short = assistant("tokencrate", "big-model", "stop", tokens(7, 7, 0))
        (sessions / "big.jsonl").write_text(short + "\n" + "x" * 4096 + "\n", encoding="utf-8")
        with unittest.mock.patch.object(stats, "LINE_LIMIT", 1024):
            read = stats.read_sessions(self.agents_dir)
        models = {request.model for session in read for request in session.requests}
        self.assertIn("big-model", models)

    def test_numbers_are_read_defensively(self) -> None:
        self.assertEqual(stats.integer(500.0), 500)
        self.assertEqual(stats.integer(500.5), 0)
        self.assertEqual(stats.integer(True), 0)
        self.assertEqual(stats.integer("500"), 0)
        self.assertEqual(stats.duration(5), 5.0)
        self.assertIsNone(stats.duration(float("nan")))
        self.assertIsNone(stats.duration(float("inf")))
        self.assertIsNone(stats.duration(True))

    def test_percentiles_are_nearest_rank_observations(self) -> None:
        self.assertEqual(stats.percentile([5], 0.9), 5)
        self.assertEqual(stats.percentile([1, 2, 3, 4], 0.5), 2)
        self.assertEqual(stats.percentile([1, 2, 3, 4], 0.9), 4)
        self.assertEqual(stats.percentile(list(range(1, 101)), 0.99), 99)

    def test_the_transcript_directories_are_the_retained_ones(self) -> None:
        self.assertEqual(stats.sessions_directory("pi"), ".pi/agent/sessions")
        self.assertEqual(stats.sessions_directory("omp"), ".omp/agent/sessions")


class StatsCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def test_stats_needs_no_engine_and_saves_the_report(self) -> None:
        write_transcripts(self.scratch.storage / "agents")
        result = self.scratch.run("stats", PATH="/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# TokenCrate stats report", result.stdout)
        self.assertIn("Saved stats report to", result.stdout)
        saved = list((self.scratch.root / "reports").glob("stats-*.md"))
        self.assertEqual(len(saved), 1, saved)
        self.assertIn("| pi | 2 | 4 |", saved[0].read_text(encoding="utf-8"))

    def test_stats_refuses_options_arguments_and_an_empty_agents_directory(self) -> None:
        result = self.scratch.run("stats", PATH="/usr/bin:/bin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no agent transcripts below", result.stderr)
        result = self.scratch.run("stats", "--preset", "x")
        self.assertIn("--preset is only valid with doctor, smoke, bench, agent, or ui", result.stderr)
        result = self.scratch.run("stats", "extra")
        self.assertIn("unexpected argument for stats: extra", result.stderr)


if __name__ == "__main__":
    unittest.main()
