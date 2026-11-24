"""The judge set's pi extension, driven under node with a fake `pi` against a
stub of the judge service on 127.0.0.1 (/v1/models and /v1/systemone):
which URLs it accepts, when each check asks, what it sends, when it
advises, how it treats a slow, absent, or foreign server, and that it
sends one request at a time."""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTENSION = PROJECT_ROOT / "config" / "agent-sets" / "judge" / "judge" / "index.js"

# Replays the steps against the extension factory, awaiting each handler as
# pi does (a `wait` step sleeps), and prints what the extension did: its
# handlers, steers, notices, failure entries and the entries of answered
# questions (checks), every status it set, the results of
# agent_before_settle, and how many fetches it made. A `start` step runs
# session_start with the entries of a resumed session.
DRIVER = r"""
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
const steps = JSON.parse(process.argv[2]);
const handlers = {};
const out = { steers: [], notices: [], entries: [], checks: [], statuses: [], settles: [], fetches: 0 };
const realFetch = globalThis.fetch;
globalThis.fetch = (...args) => { out.fetches++; return realFetch(...args); };
module.default({
  on(name, handler) { (handlers[name] ||= []).push(handler); },
  appendEntry(type, data) { (data?.check ? out.checks : out.entries).push({ type, data }); },
  sendMessage(message, options) { out.steers.push({ content: message.content, deliverAs: options?.deliverAs }); },
  sendUserMessage(text) { out.steers.push({ content: text, deliverAs: "user" }); },
});
out.registered = Object.keys(handlers).sort();
const ui = {
  notify(text) { out.notices.push(text); },
  setStatus(key, text) { out.statuses.push([key, text]); },
};
const ctx = { ui };
for (const step of steps) {
  if (step.on === "wait") { await new Promise((resolve) => setTimeout(resolve, step.ms)); continue; }
  if (step.on === "start") {
    const branch = step.entries.map((data) => ({ type: "custom", customType: "judge", data }));
    const resumed = { ...ctx, sessionManager: { getBranch: () => branch } };
    for (const handler of handlers.session_start || []) await handler({ reason: "resume" }, resumed);
    continue;
  }
  for (const handler of handlers[step.on] || []) {
    const value = await handler(step.event, ctx);
    if (step.on === "agent_before_settle") out.settles.push(value ?? null);
  }
}
await new Promise((resolve) => setTimeout(resolve, 100));
console.log(JSON.stringify(out));
"""


class StubJudge(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), StubHandler)
        self.requests: list[dict] = []
        self.answers: dict[str, float] = {}
        self.models: tuple[int, dict] = (200, {"object": "list", "data": [{"id": "kev-4b", "aliases": ["kev-4b"]}]})
        # Per POST in order: seconds to wait before answering, or None to
        # close the connection without an answer; later POSTs answer at once.
        self.delays: list[float | None] = []
        self.active = self.most_active = 0
        self.lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def handle_error(self, request, client_address) -> None:
        pass  # an answer the extension stopped waiting for has nowhere to go

    def posts(self) -> list[dict]:
        return [request for request in self.requests if request["method"] == "POST"]

    def gets(self) -> list[dict]:
        return [request for request in self.requests if request["method"] == "GET"]


class StubHandler(http.server.BaseHTTPRequestHandler):
    server: StubJudge

    def answer(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.server.requests.append({"method": "GET", "path": self.path})
        self.answer(*self.server.models)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        with self.server.lock:
            delay = self.server.delays.pop(0) if self.server.delays else 0
            self.server.requests.append({"method": "POST", "path": self.path, **body})
            self.server.active += 1
            self.server.most_active = max(self.server.most_active, self.server.active)
        try:
            if delay is None:
                return  # the connection closes without an answer
            time.sleep(delay)
            self.answer(
                200, {"answers": {key: {"noul": self.server.answers.get(key, 0.5)} for key in body["questions"]}}
            )
        finally:
            with self.server.lock:
                self.server.active -= 1

    def log_message(self, *_args) -> None:
        pass


def user(text: str = "make the tests pass", expanded: str | None = None) -> list[dict]:
    """A prompt the user typed, and the run it starts with the expanded text."""
    return [
        {"on": "input", "event": {"text": text, "source": "interactive"}},
        {"on": "before_agent_start", "event": {"messageType": "user", "prompt": expanded or text}},
    ]


def result(tool: str, input: dict, output: str, *, failed: bool = True) -> dict:
    return {
        "on": "tool_result",
        "event": {
            "toolName": tool,
            "toolCallId": "ran",
            "input": input,
            "isError": failed,
            "content": [{"type": "text", "text": output}],
        },
    }


def turn() -> dict:
    return {"on": "turn_end", "event": {"toolResults": [{"toolCallId": "ran"}]}}


def failing_test(duration: int) -> list[dict]:
    """One turn whose `npm test` fails the same way in a different time."""
    output = f"> npm test\nFAIL src/app.test.ts\nError: expected 2, got 3\nTests: 1 failed, took {duration}ms"
    return [result("bash", {"command": f"npm test -- --seed {duration}"}, output), turn()]


def stalled() -> list[dict]:
    return [*failing_test(1), *failing_test(2), *failing_test(3)]


def settle(outcome: str = "completed", final: str = "Done: the parser is refactored.") -> dict:
    edit = {"path": "src/parser.ts", "edits": [{"oldText": "a", "newText": "b"}]}
    check = {"command": "npx tsc --noEmit"}
    asked = [
        {"type": "toolCall", "id": "1", "name": "edit", "arguments": edit},
        {"type": "toolCall", "id": "2", "name": "bash", "arguments": check},
    ]
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "refactor the parser"}]},
        {"role": "assistant", "content": asked},
        {
            "role": "toolResult",
            "toolCallId": "1",
            "toolName": "edit",
            "isError": False,
            "content": [{"type": "text", "text": "ok"}],
        },
        {
            "role": "toolResult",
            "toolCallId": "2",
            "toolName": "bash",
            "isError": False,
            "content": [{"type": "text", "text": "(no output)"}],
        },
        {"role": "assistant", "content": [{"type": "text", "text": final}]},
    ]
    other = {"type": "custom", "customType": "other-extension"}
    return {
        "on": "agent_before_settle",
        "event": {"outcome": outcome, "entries": [other], "continue": False, "context": {"contextMessages": messages}},
    }


def refused_edit(path: str, number: int) -> dict:
    """A turn whose edit pi-lens refused before it ran, so without tool_result."""
    call = {
        "type": "toolCall",
        "id": f"edit{number}",
        "name": "edit",
        "arguments": {"path": path, "edits": [{"oldText": f"absent text {number}", "newText": "x"}]},
    }
    text = f'🔄 RETRYABLE — Edit target not found\n\nedits[0].oldText ("absent text {number}") was not found'
    refused = {
        "toolCallId": call["id"],
        "toolName": "edit",
        "isError": True,
        "content": [{"type": "text", "text": text}],
    }
    return {
        "on": "turn_end",
        "event": {"message": {"role": "assistant", "content": [call]}, "toolResults": [refused]},
    }


def wait(ms: int) -> dict:
    return {"on": "wait", "ms": ms}


STALL = {"sameStrategy": 0.95, "progress": 0.1}
UNVERIFIED_DONE = {"done": 0.9, "verified": 0.1}


@unittest.skipUnless(shutil.which("node"), "node is required to drive the extension")
class JudgeExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.judge = StubJudge()
        threading.Thread(target=self.judge.serve_forever, daemon=True).start()
        self.addCleanup(self.judge.server_close)
        self.addCleanup(self.judge.shutdown)

    def drive(self, steps: list[dict], url: str | None = None) -> dict:
        run = subprocess.run(
            ["node", "--input-type=module", "-e", DRIVER, "--", str(EXTENSION), json.dumps(steps)],
            env={"PATH": os.environ["PATH"], "TOKENCRATE_JUDGE_URL": self.judge.url if url is None else url},
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return json.loads(run.stdout)

    def test_without_a_url_or_with_a_host_name_nothing_registers(self) -> None:
        for url in ("", "http://example.com:8080", "http://judge.lan:8080", "https://10.89.0.4:8080", "not a url"):
            with self.subTest(url=url):
                self.assertEqual(self.drive([*user(), *stalled()], url)["registered"], [])
        # The service's name on the internal networks, or an address.
        handlers = ["agent_before_settle", "before_agent_start", "input", "session_start", "tool_result", "turn_end"]
        for url in ("http://judge:8080", "http://10.89.0.4:8080"):
            with self.subTest(url=url):
                self.assertEqual(self.drive([], url)["registered"], handlers)
        self.assertEqual(self.judge.requests, [])

    def test_the_stall_gate_needs_three_failures_on_one_target(self) -> None:
        self.judge.answers = STALL
        # Three failures on three files, then two on one file in a window of six.
        spread = user() + [
            step
            for path in ("a.ts", "b.ts", "c.ts")
            for step in (result("edit", {"path": path}, "Error: no match"), turn())
        ]
        two = user() + [result("edit", {"path": "a.ts"}, "Error: no match"), turn()] * 2
        old = [*user(), *failing_test(1), *failing_test(2)]
        old += [result("read", {"path": "x"}, "ok", failed=False), turn()] * 4 + failing_test(3)
        for steps in (spread, two, old):
            with self.subTest(steps=len(steps)):
                self.assertEqual(self.drive(steps)["steers"], [])
        self.assertEqual(self.judge.posts(), [])

    def test_a_met_gate_asks_both_questions_once_with_normalised_outputs(self) -> None:
        self.judge.answers = STALL
        out = self.drive([*user(), *failing_test(1200), *failing_test(1350), *failing_test(1480)])
        (request,) = self.judge.posts()
        self.assertEqual(request["path"], "/v1/systemone")
        self.assertEqual(set(request["questions"]), {"sameStrategy", "progress"})
        self.assertIn("incremental edits to one file", request["questions"]["sameStrategy"]["criteria"]["false"])
        self.assertEqual(request["state"]["request"], "make the tests pass")
        calls = request["state"]["calls"]
        self.assertEqual(len(calls), 3)
        self.assertEqual({call["output"] for call in calls}, {calls[0]["output"]}, "durations are masked")
        self.assertIn("took #t", calls[0]["output"])
        self.assertEqual(calls[0]["error"], "FAIL src/app.test.ts", "the first line that names a failure")
        self.assertNotIn("target", calls[0])
        self.assertEqual(len(out["steers"]), 1)
        self.assertEqual(out["steers"][0]["deliverAs"], "steer")
        self.assertIn("repeat one failing strategy", out["steers"][0]["content"])

    def test_a_steer_needs_the_same_strategy_and_no_progress(self) -> None:
        for answers, steered in (
            (STALL, True),
            ({"sameStrategy": 0.95, "progress": 0.6}, False),
            ({"sameStrategy": 0.85, "progress": 0.1}, False),
        ):
            with self.subTest(answers=answers):
                self.judge.answers = answers
                self.assertEqual(len(self.drive([*user(), *stalled()])["steers"]), 1 if steered else 0)

    def test_after_a_question_three_more_results_pass_before_the_next(self) -> None:
        self.judge.answers = {"sameStrategy": 0.95, "progress": 0.9}
        steps = [*user(), *stalled()]
        self.drive(steps + failing_test(4) + failing_test(5))
        self.assertEqual(len(self.judge.posts()), 1, "two results after the question")
        self.judge.requests.clear()
        self.drive(steps + failing_test(4) + failing_test(5) + failing_test(6))
        self.assertEqual(len(self.judge.posts()), 2, "the third result after the question")

    def test_one_steer_per_prompt(self) -> None:
        self.judge.answers = STALL
        prompt = [*user(), *stalled()]
        out = self.drive(prompt + [step for n in range(4, 10) for step in failing_test(n)])
        self.assertEqual((len(out["steers"]), len(self.judge.posts())), (1, 1))
        self.judge.requests.clear()
        self.assertEqual(len(self.drive(prompt + prompt)["steers"]), 2, "the next prompt starts over")

    def test_the_request_is_the_expanded_prompt_and_not_a_steer_or_an_extensions_message(self) -> None:
        self.judge.answers = STALL
        steer = {
            "on": "input",
            "event": {"text": "also fix lint", "source": "interactive", "streamingBehavior": "steer"},
        }
        extension = [
            {"on": "input", "event": {"text": "from another extension", "source": "extension"}},
            {"on": "before_agent_start", "event": {"messageType": "user", "prompt": "from another extension"}},
        ]
        self.drive([*user("/fix-tests", "Fix the failing tests in src/app.ts"), steer, *stalled()])
        self.drive([*user(), *extension, *stalled()])
        first, second = self.judge.posts()
        self.assertEqual(first["state"]["request"], "Fix the failing tests in src/app.ts")
        self.assertEqual(second["state"]["request"], "make the tests pass")

    def test_the_status_and_one_entry_per_answered_question_show_what_the_judge_did(self) -> None:
        self.judge.answers = UNVERIFIED_DONE
        resumed = [{"check": "stall", "verdicts": {"sameStrategy": 0.2, "progress": 0.9}, "advised": False}]
        out = self.drive([{"on": "start", "entries": [*resumed, {"url": "x", "failure": "y"}]}, *user(), settle()])
        self.assertEqual(out["statuses"][0], ["judge", "judge: 1 asked, 0 advised"])
        self.assertEqual(out["statuses"][-1], ["judge", "judge: 2 asked, 1 advised"])
        self.assertEqual(
            out["checks"],
            [{"type": "judge", "data": {"check": "done", "verdicts": {"done": 0.9, "verified": 0.1}, "advised": True}}],
        )
        # A question without an answer is no entry.
        self.judge.delays = [None]
        out = self.drive([*user(), settle()])
        self.assertEqual((out["checks"], out["statuses"][-1]), ([], ["judge", "judge: 0 asked, 0 advised"]))

    def test_a_completed_run_that_claims_done_unverified_gets_one_continuation(self) -> None:
        self.judge.answers = UNVERIFIED_DONE
        out = self.drive([*user("refactor the parser"), settle(), settle()])
        (request,) = self.judge.posts()
        self.assertEqual(set(request["questions"]), {"done", "verified"})
        self.assertEqual(request["state"]["final"], "Done: the parser is refactored.")
        self.assertEqual(
            request["state"]["calls"],
            [
                {"tool": "edit", "call": "src/parser.ts", "failed": False, "output": "ok"},
                # A check that prints nothing is known by its command alone.
                {"tool": "bash", "call": "npx tsc --noEmit", "failed": False, "output": "(no output)"},
            ],
        )
        first, second = out["settles"]
        self.assertTrue(first["continue"])
        other, follow_up = first["entries"]
        self.assertEqual(other["customType"], "other-extension", "the entries of earlier handlers are kept")
        self.assertEqual((follow_up["type"], follow_up["customType"]), ("custom_message", "judge"))
        self.assertIn("run the project's tests or build", follow_up["content"])
        self.assertIsNone(second, "once per prompt")

    def test_a_long_command_keeps_its_start_and_its_end(self) -> None:
        step = settle()
        message = step["event"]["context"]["contextMessages"][1]
        message["content"][1]["arguments"] = {"command": "cat > a.py <<EOF\n" + "x" * 900 + "\nEOF\npython -m pytest"}
        self.drive([*user(), step])
        (request,) = self.judge.posts()
        command = request["state"]["calls"][1]["call"]
        self.assertTrue(command.startswith("cat > a.py"))
        self.assertTrue(command.endswith("python -m pytest"))
        self.assertLessEqual(len(command), 201)

    def test_an_on_task_question_names_the_file(self) -> None:
        # The path counts even where it follows more text than the judge is sent.
        edit = {"edits": [{"oldText": "a", "newText": "b" * 4000}], "path": "src/parser.ts"}
        self.drive([*user(), result("edit", edit, "ok", failed=False)])
        (request,) = self.judge.posts()
        self.assertEqual(request["state"]["edit"]["path"], "src/parser.ts")

    def test_edits_refused_before_they_run_reach_the_stall_gate(self) -> None:
        self.judge.answers = STALL
        one_file = self.drive([*user(), *(refused_edit("src/app.ts", n) for n in range(3))])
        (request,) = self.judge.posts()
        self.assertEqual(set(request["questions"]), {"sameStrategy", "progress"})
        self.assertIn("src/app.ts", request["state"]["calls"][0]["call"])
        self.assertIn("Edit target not found", request["state"]["calls"][0]["error"])
        self.assertEqual(len(one_file["steers"]), 1)
        self.judge.requests.clear()
        self.drive([*user(), *(refused_edit(f"src/{n}.ts", n) for n in range(3))])
        self.assertEqual(self.judge.posts(), [], "three files are three targets")

    def test_an_aborted_failed_or_verified_run_gets_no_continuation(self) -> None:
        self.judge.answers = UNVERIFIED_DONE
        out = self.drive([*user(), settle("aborted"), settle("error")])
        self.assertEqual((out["settles"], self.judge.posts()), ([None, None], []))
        self.judge.answers = {"done": 0.9, "verified": 0.9}
        self.assertEqual(self.drive([*user(), settle()])["settles"], [None])

    def test_one_request_at_a_time_and_an_on_task_question_yields(self) -> None:
        # Four parallel edits on a judge that takes a second each: one
        # on-task question, the others skipped while it is pending.
        self.judge.delays = [1, 1, 1]
        self.judge.answers = UNVERIFIED_DONE
        edits = [result("edit", {"path": f"f{n}.ts"}, "ok", failed=False) for n in range(4)]
        out = self.drive([*user("refactor the parser"), *edits, settle()])
        questions = [set(request["questions"]) for request in self.judge.posts()]
        self.assertEqual(questions, [{"onTask"}, {"done", "verified"}], "the done check waits for the pending one")
        self.assertEqual(self.judge.most_active, 1)
        self.assertTrue(out["settles"][0]["continue"])
        self.assertEqual(out["entries"], [])

    def test_a_timeout_or_a_dropped_answer_skips_that_check_only(self) -> None:
        self.judge.answers = UNVERIFIED_DONE
        self.judge.delays = [None]
        out = self.drive([*user(), settle(), *user(), settle()])
        self.assertEqual(len(self.judge.posts()), 2)
        self.assertEqual(out["settles"][0], None)
        self.assertTrue(out["settles"][1]["continue"], "the judge is asked again")
        self.judge.requests.clear()
        self.judge.delays = [6]
        out = self.drive([*user(), settle(), wait(1500), *user(), settle()])
        self.assertEqual(len(self.judge.posts()), 2)
        self.assertTrue(out["settles"][1]["continue"])
        (entry,) = out["entries"]
        self.assertTrue(entry["data"]["failure"].startswith("TimeoutError"), entry)

    def test_three_failures_in_a_row_count_as_no_judge(self) -> None:
        # Two timeouts, an answer that resets the count, then three more:
        # the seventh check is not asked.
        self.judge.answers = UNVERIFIED_DONE
        self.judge.delays = [6, 6, 0, 6, 6, 6]
        out = self.drive([step for _ in range(7) for step in (*user(), settle())])
        self.assertEqual(len(self.judge.posts()), 6)
        self.assertTrue(out["settles"][2]["continue"])
        first, given_up = out["entries"]
        self.assertTrue(first["data"]["failure"].startswith("TimeoutError"), first)
        self.assertEqual(given_up["data"]["failure"], "3 failed requests in a row; not asked again")
        self.assertEqual(out["statuses"][-1], ["judge", "judge: off, 3 failed requests in a row"])

    def test_a_refused_connection_is_tried_again_until_three_in_a_row(self) -> None:
        # A judge that restarts refuses connections for a moment; nothing
        # listening there at all costs three checks.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{probe.getsockname()[1]}"
        out = self.drive([step for _ in range(4) for step in (*user(), settle())], closed)
        self.assertEqual(out["fetches"], 3)
        first, given_up = out["entries"]
        self.assertEqual(first["data"], {"url": closed, "failure": "TypeError: ECONNREFUSED"})
        self.assertEqual(given_up["data"]["failure"], "3 failed requests in a row; not asked again")

    def test_a_name_that_does_not_resolve_is_never_tried_again(self) -> None:
        out = self.drive([*user(), settle(), *user(), settle()], "http://judge:8080")
        self.assertEqual(out["fetches"], 1)
        (entry,) = out["entries"]
        self.assertIn(entry["data"]["failure"], ("TypeError: ENOTFOUND", "TypeError: EAI_AGAIN"))
        self.assertEqual(out["statuses"][-1], ["judge", "judge: off, no judge service"])

    def test_only_a_server_that_names_the_judge_model_is_asked(self) -> None:
        self.judge.answers = UNVERIFIED_DONE
        # Checked before every question: an address can change hands
        # between two of them.
        self.drive([*user(), settle(), *user(), settle()])
        self.assertEqual([request["method"] for request in self.judge.requests], ["GET", "POST", "GET", "POST"])
        self.assertEqual(self.judge.gets()[0]["path"], "/v1/models")
        # Another container on the judge's old address: never asked again.
        self.judge.requests.clear()
        self.judge.models = (200, {"object": "list", "data": [{"id": "dev-server"}]})
        out = self.drive([*user(), settle(), *user(), settle()])
        self.assertEqual((out["fetches"], self.judge.posts()), (1, []))
        self.assertIn("does not name kev-4b", out["entries"][0]["data"]["failure"])
        self.assertEqual(out["statuses"][-1], ["judge", "judge: off, the server does not serve kev-4b"])
        # A server without the endpoint counts as a failed request.
        self.judge.requests.clear()
        self.judge.models = (404, {"error": "not found"})
        out = self.drive([step for _ in range(4) for step in (*user(), settle())])
        self.assertEqual((len(self.judge.gets()), self.judge.posts()), (3, []))
        # The judge while it loads Kev-4B is asked at every check.
        self.judge.requests.clear()
        self.judge.models = (503, {"error": {"message": "Loading model"}})
        out = self.drive([step for _ in range(4) for step in (*user(), settle())])
        self.assertEqual((len(self.judge.gets()), self.judge.posts()), (4, []))
        (entry,) = out["entries"]
        self.assertEqual(entry["data"]["failure"], "HTTP 503 from /v1/models")


if __name__ == "__main__":
    unittest.main()
