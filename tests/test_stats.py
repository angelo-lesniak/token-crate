"""The stats report over synthetic transcripts: what it counts, what it
never prints, and the command around it."""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import Scratch, free_port
from tokencrate import TokenCrateError, stats

CWD_DIRECTORY = "--srv-PROJECTSECRET--"


def entry(**fields) -> str:
    return json.dumps(fields)


def assistant(provider: str, model: str, stop: str, usage: dict | None, at: str = "16:00:00", **extra) -> str:
    message: dict = {"role": "assistant", "provider": provider, "model": model, "stopReason": stop, **extra}
    message["content"] = [{"type": "text", "text": "TOPSECRET-ANSWER"}]
    if usage is not None:
        message["usage"] = {"cost": {"total": 0}, **usage}
    return entry(type="message", id="e1", timestamp=f"2026-09-21T{at}.000Z", message=message)


def user(at: str) -> str:
    return entry(
        type="message",
        id="u",
        timestamp=f"2026-09-21T{at}.000Z",
        message={"role": "user", "content": "TOPSECRET-PROMPT"},
    )


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
        # pi writes the level before the first message; the level entry
        # and the session header carry timestamps the duration ignores.
        entry(type="thinking_level_change", id="l", timestamp="2026-09-21T15:00:00.000Z", thinkingLevel="xhigh"),
        user("16:00:00"),
        assistant("tokencrate", "qwen-fixture", "toolUse", tokens(500, 100, 1000), "16:00:10"),
        entry(
            type="message",
            id="t",
            timestamp="2026-09-21T16:00:11.000Z",
            message={"role": "toolResult", "toolName": "read", "isError": False},
        ),
        "{not json",
        # Timed by the metrics set's extension, in oh-my-pi's fields.
        assistant("tokencrate", "qwen-fixture", "stop", tokens(400, 100, 16000), "16:01:00", ttft=300, duration=900),
        entry(type="compaction", id="c", tokensBefore=16500, summary="TOPSECRET-SUMMARY"),
        # Another extension's entry, and timing fields that are not numbers.
        entry(type="custom", id="x", customType="TOPSECRET-EXT", data={"note": "TOPSECRET-DATA", "ttft": 5}),
        # A level change mid-session, a malformed level, and a malformed
        # timestamp on the last request.
        entry(type="thinking_level_change", id="l2", thinkingLevel="low"),
        entry(type="thinking_level_change", id="l3", thinkingLevel="<b>TOPSECRET</b>"),
        user("16:04:00"),
        entry(type="thinking_level_change", id="l4", thinkingLevel="low"),
        assistant(
            "tokencrate",
            "qwen-fixture",
            "stop",
            tokens(3000, 200, 0, 800),
            "not-a-time",
            ttft="TOPSECRET-TTFT",
            duration=[1],
        ),
    ]
)
CLOUD_SESSION = assistant("openrouter", "acme/model|x", "stop", tokens(2000, 50, 0), "18:00:00")
OMP_SESSION = "\n".join(
    [
        entry(type="session", version=3, id="b", timestamp="2026-09-21T17:00:00.000Z", cwd="/srv/PROJECTSECRET"),
        entry(type="thinking_level_change", id="l", timestamp="2026-09-21T17:00:00.000Z", thinkingLevel="high"),
        user("17:00:00"),
        assistant(
            "tokencrate",
            "qwen-fixture",
            "stop",
            tokens(19000, 40, 0),
            "17:00:04",
            ttft=1200.5,
            duration=3400.5,
            contextSnapshot={"promptTokens": 19000, "nonMessageTokens": 16000, "compactionEpoch": 0},
        ),
        entry(type="message", id="t", message={"role": "toolResult", "toolName": "bash", "isError": True}),
        assistant("tokencrate", "qwen-fixture", "error", None, "17:30:00", errorMessage="boom"),
        assistant(
            "tokencrate", "qwen-fixture", "toolUse", tokens(100, 60, 19000), "18:12:30", ttft=800.0, duration=1500.0
        ),
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
        text = stats.report(stats.read_sessions(self.agents_dir))
        self.assertTrue(text.startswith("# TokenCrate stats report\n\n- Date: "), text)
        self.assertIn("- Transcripts: 3 session(s), 6 request(s) below LLM_AGENTS_DIR\n", text)
        # Sessions: count, requests, turns p50, duration p50/p90 (first to
        # last message; the cloud session has one message, so the pi p90 is
        # the timed session's four minutes), first-request p50, peak context
        # p50/p90/max, compactions with the p50 context before them.
        self.assertIn("| pi | 2 | 4 | 0 | 0s | 4m 00s | 1500 | 2050 | 16500 | 16500 | 1 (p50 before: 16500) |", text)
        self.assertIn("| omp | 1 | 2 | 1 | 1h 12m | 1h 12m | 19000 | 19160 | 19160 | 19160 | 0 |", text)
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
        # Thinking levels: the last change before each request; a malformed
        # level is "?", the cloud session has no level entry.
        self.assertIn("| pi | xhigh | 2 | 100 | 100 |", text)
        self.assertIn("| pi | low | 1 | 200 | 200 |", text)
        self.assertIn("| pi | ? | 1 | 50 | 50 |", text)
        self.assertIn("| omp | high | 2 | 40 | 60 |", text)
        # Timings exist only where a transcript carries numeric ttft and
        # duration, one row per agent: the two agents measure differently.
        self.assertIn("| pi | tokencrate | qwen-fixture | 1 | 300 | 300 | 900 | 900 |", text)
        self.assertIn("| omp | tokencrate | qwen-fixture | 2 | 800 | 1200 | 1500 | 3400 |", text)
        self.assertNotIn("No timed requests", text)

    def test_the_report_carries_no_content_names_or_paths(self) -> None:
        text = stats.report(stats.read_sessions(self.agents_dir))
        for secret in ("TOPSECRET", "PROJECTSECRET", "/srv/", "boom", "999999", "888888", "decoy"):
            self.assertNotIn(secret, text)

    def test_an_errored_turn_and_an_abandoned_session_are_not_counted(self) -> None:
        sessions = stats.read_sessions(self.agents_dir)
        self.assertEqual([session.agent for session in sessions], ["pi", "pi", "omp"])
        self.assertEqual(sum(len(session.requests) for session in sessions), 6)

    def test_since_and_agent_keep_whole_sessions(self) -> None:
        # A session counts whole when its last message is at or after the
        # cutoff; the summary names the filters; nothing matching is its own
        # sentence, distinct from an empty directory.
        cutoff = stats.since_cutoff("2026-09-21T17:30:00+00:00")
        kept = stats.read_sessions(self.agents_dir, stats.Filter(since=cutoff))
        self.assertEqual([session.agent for session in kept], ["pi", "omp"])
        self.assertEqual(sum(len(session.requests) for session in kept), 3)
        text = stats.report(kept, stats.Filter(since=cutoff))
        self.assertIn("2 session(s), 3 request(s) below LLM_AGENTS_DIR (since 2026-09-21T17:30:00+00:00)", text)
        only_pi = stats.read_sessions(self.agents_dir, stats.Filter(agent="pi"))
        self.assertEqual({session.agent for session in only_pi}, {"pi"})
        self.assertEqual(len(stats.read_sessions(self.agents_dir, stats.Filter(since=cutoff, agent="pi"))), 1)
        with self.assertRaises(TokenCrateError) as caught:
            stats.read_sessions(self.agents_dir, stats.Filter(since=stats.since_cutoff("2027-01-01")))
        self.assertIn("no agent transcripts match since 2027-01-01T00:00:00", str(caught.exception))

    def test_since_takes_a_duration_or_an_iso_time(self) -> None:
        from datetime import UTC, datetime, timedelta

        now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
        self.assertEqual(stats.since_cutoff("30m", now), now - timedelta(minutes=30))
        self.assertEqual(stats.since_cutoff("12h", now), now - timedelta(hours=12))
        self.assertEqual(stats.since_cutoff("7d", now), now - timedelta(days=7))
        self.assertEqual(stats.since_cutoff("2w", now), now - timedelta(weeks=2))
        self.assertEqual(stats.since_cutoff("2026-09-20T10:00:00Z", now), datetime(2026, 9, 20, 10, tzinfo=UTC))
        self.assertIsNotNone(stats.since_cutoff("2026-09-20").tzinfo)  # local midnight
        for bad in ("0d", "yesterday", "7", "2026-13-01", "x" * 60, "999999d", "0001-01-01", "9999-12-31T23:59:59"):
            with self.assertRaises(TokenCrateError, msg=bad):
                stats.since_cutoff(bad, now)

    def test_timestamps_and_levels_are_read_defensively(self) -> None:
        self.assertEqual(stats.timestamp("2026-09-21T16:00:00.000Z"), 1790006400.0)
        self.assertIsNone(stats.timestamp("2026-09-21T16:00:00.000Z" + "0" * 40))
        self.assertIsNone(stats.timestamp("0001-01-01T00:00:00"))
        self.assertIsNone(stats.timestamp(1789999200))
        self.assertIsNone(stats.timestamp("TOPSECRET"))
        self.assertEqual(stats.level_name("xhigh"), "xhigh")
        self.assertEqual(stats.level_name("X"), "?")
        self.assertEqual(stats.level_name(None), "?")
        self.assertEqual(stats.duration_text(38), "38s")
        self.assertEqual(stats.duration_text(270), "4m 30s")
        self.assertEqual(stats.duration_text(4320), "1h 12m")

    def test_without_transcripts_the_report_says_where_they_would_be(self) -> None:
        with TemporaryDirectory(prefix="tokencrate-stats-") as empty:
            with self.assertRaises(TokenCrateError) as caught:
                stats.read_sessions(Path(empty))
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
            text = stats.report(stats.read_sessions(self.agents_dir))
        self.assertNotIn("FOREIGNMODEL", text)

    def test_an_integer_past_the_digit_limit_is_skipped(self) -> None:
        # json.loads raises a plain ValueError for it, not a JSONDecodeError.
        session = stats.Session("pi")
        stats.read_line(
            '{"type": "message", "message": {"role": "assistant", "usage": {"input": ' + "9" * 5000 + "}}}", session
        )
        self.assertEqual(session.requests, [])

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
        self.assertEqual(stats.integer(-5), 0)
        self.assertEqual(stats.integer(2**60), 2**53)
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
        self.assertIn("Saved stats page to", result.stdout)
        page = saved[0].with_suffix(".html")
        self.assertIn('id="ecdf-data"', page.read_text(encoding="utf-8"))

    def test_stats_refuses_options_arguments_and_an_empty_agents_directory(self) -> None:
        result = self.scratch.run("stats", PATH="/usr/bin:/bin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no agent transcripts below", result.stderr)
        result = self.scratch.run("stats", "--preset", "x")
        self.assertIn("--preset is only valid with doctor, smoke, bench, agent, or ui", result.stderr)
        result = self.scratch.run("stats", "extra")
        self.assertIn("unexpected argument for stats: extra", result.stderr)
        result = self.scratch.run("stats", "--port", "4210")
        self.assertIn("--port applies to stats --serve", result.stderr)
        result = self.scratch.run("stats", "--serve", "--port", "0")
        self.assertIn("--port requires a port from 1 to 65535", result.stderr)
        result = self.scratch.run("bench", "--serve")
        self.assertIn("--serve is only valid with stats", result.stderr)
        result = self.scratch.run("stats", "--since", "yesterday")
        self.assertIn("--since requires a duration such as 30m, 12h, 7d, or 2w", result.stderr)
        result = self.scratch.run("bench", "--since", "7d")
        self.assertIn("--since is only valid with stats", result.stderr)
        result = self.scratch.run("stats", "--agent", "claude")
        self.assertIn("--agent requires pi or omp", result.stderr)

    def test_stats_serves_in_the_background_until_stopped_or_down(self) -> None:
        import os
        import signal
        import urllib.request

        write_transcripts(self.scratch.storage / "agents")
        port = str(free_port())
        started = self.scratch.run(
            "stats", "--serve", "--detach", "--port", port, "--since", "2026-09-01", PATH="/usr/bin:/bin"
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self.assertIn(f"Serving the stats page at http://127.0.0.1:{port}/ in the background", started.stdout)
        record = json.loads((self.scratch.root / "build" / "stats-serve.pid").read_text())
        self.addCleanup(lambda: os.path.exists(f"/proc/{record['pid']}") and os.kill(record["pid"], signal.SIGKILL))
        self.assertEqual(record["port"], int(port))
        self.assertIsInstance(record["started"], int)
        self.assertIn("Serving the stats page", (self.scratch.root / "build" / "stats-serve.log").read_text())
        # The page answers with the child's own filter, and status names it.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
            self.assertIn("(since ", response.read().decode())
        status = self.scratch.run("status")
        self.assertIn(f"Stats page: serving at http://127.0.0.1:{port}/ (pid {record['pid']}", status.stdout)
        # A second one is refused while the first runs.
        refused = self.scratch.run("stats", "--serve", "--detach", "--port", port)
        self.assertIn("a stats server is already serving", refused.stderr)
        self.assertIn("Stopped the stats page.", self.scratch.run("stats", "--stop").stdout)
        self.assertFalse((self.scratch.root / "build" / "stats-serve.pid").exists())
        self.assertFalse(os.path.exists(f"/proc/{record['pid']}"))
        self.assertIn("No stats page is served in the background.", self.scratch.run("stats", "--stop").stdout)
        # down ends a detached server with the rest; a stale file is ignored.
        started = self.scratch.run("stats", "--serve", "--detach", "--port", port, PATH="/usr/bin:/bin")
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        record = json.loads((self.scratch.root / "build" / "stats-serve.pid").read_text())
        self.assertIn("Stopped the stats page.", self.scratch.run("down").stdout)
        self.assertFalse(os.path.exists(f"/proc/{record['pid']}"))
        (self.scratch.root / "build" / "stats-serve.pid").write_text(json.dumps({"pid": 2**22 - 1, "port": 4210}))
        self.assertNotIn("Stats page:", self.scratch.run("status").stdout)
        self.assertFalse((self.scratch.root / "build" / "stats-serve.pid").exists())
        self.assertIn("--stop takes no other stats option", self.scratch.run("stats", "--stop", "--port", port).stderr)
        self.assertIn("--detach applies to stats --serve", self.scratch.run("stats", "--detach").stderr)
        self.assertIn("--detach is only valid with stats --serve", self.scratch.run("bench", "--detach").stderr)
        # A bad cutoff is refused by the parent, and a port another program
        # holds is refused before anything starts.
        bad = self.scratch.run("stats", "--serve", "--detach", "--port", port, "--since", "yesterday")
        self.assertIn("--since requires a duration", bad.stderr)
        self.assertFalse((self.scratch.root / "build" / "stats-serve.pid").exists())
        import socket

        with socket.socket() as holder:
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            holder.bind(("127.0.0.1", int(port)))
            holder.listen(1)
            busy = self.scratch.run("stats", "--serve", "--detach", "--port", port)
        self.assertIn(f"host port {port} is already in use", busy.stderr)
        self.assertFalse((self.scratch.root / "build" / "stats-serve.pid").exists())

    def test_stats_filters_by_time_and_agent(self) -> None:
        write_transcripts(self.scratch.storage / "agents")
        result = self.scratch.run("stats", "--since", "2026-09-21T17:30:00Z", "--agent", "omp", PATH="/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "1 session(s), 2 request(s) below LLM_AGENTS_DIR (agent omp, since 2026-09-21T17:30:00+00:00)",
            result.stdout,
        )
        self.assertNotIn("| pi |", result.stdout)


if __name__ == "__main__":
    unittest.main()
