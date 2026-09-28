"""The `metrics` set's pi extension, driven under node with a fake `pi`:
what it adds to a completed assistant message and what it leaves alone."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTENSION = PROJECT_ROOT / "config" / "agent-sets" / "metrics" / "timings" / "index.js"

# The hook sequence pi runs per request, replayed against the extension
# factory: the handlers' return values are what pi would act on.
DRIVER = r"""
import { pathToFileURL } from "node:url";
const module = await import(pathToFileURL(process.argv[1]).href);
const factory = module.default;
const handlers = {};
const commands = {};
factory({
  on(name, handler) { (handlers[name] ||= []).push(handler); },
  registerCommand(name, options) { commands[name] = options; },
});
const emit = (name, event) => {
  let result;
  for (const handler of handlers[name] || []) {
    const value = handler(event, {});
    if (value !== undefined) { result = value; }
  }
  return result;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const answer = (stopReason) => ({
  role: "assistant",
  stopReason,
  usage: { input: 5, output: 2, totalTokens: 7 },
  content: [{ type: "text", text: "hi" }],
});
const results = { registered: Object.keys(handlers).sort(), commands: Object.keys(commands) };

results.payload = emit("before_provider_request", { type: "before_provider_request", payload: { messages: [] } });
await sleep(40);
emit("message_update", { message: answer("pending"), assistantMessageEvent: { type: "text_delta" } });
await sleep(40);
results.completed = emit("message_end", { message: answer("stop") });

emit("before_provider_request", { type: "before_provider_request", payload: {} });
emit("message_update", { message: answer("pending"), assistantMessageEvent: { type: "text_delta" } });
results.errored = emit("message_end", { message: answer("error") });

emit("before_provider_request", { type: "before_provider_request", payload: {} });
results.silent = emit("message_end", { message: answer("stop") });

results.orphan = emit("message_end", { message: answer("stop") });
results.user = emit("message_end", { message: { role: "user", content: "x" } });
results.tool = emit("message_end", { message: { role: "toolResult", toolName: "bash" } });

emit("before_provider_request", { type: "before_provider_request", payload: {} });
emit("message_update", { message: answer("pending"), assistantMessageEvent: { type: "toolcall_start" } });
results.again = emit("message_end", { message: answer("toolUse") });

// /usage over a transcript as pi's session manager returns it: content,
// names, and a hostile level that must not reach the line.
const timed = (ttft, duration, usage) => ({ type: "message", message: { ...answer("stop"), usage, ttft, duration } });
const entries = [
  { type: "session", id: "s", cwd: "/srv/TOPSECRET" },
  { type: "thinking_level_change", thinkingLevel: "xhigh" },
  { type: "message", message: { role: "user", content: "TOPSECRET-PROMPT" } },
  timed(300, 900, { input: 500, output: 100, cacheRead: 1000, cacheWrite: 0, totalTokens: 1600 }),
  { type: "message", message: { role: "toolResult", toolName: "read", isError: false, content: "TOPSECRET" } },
  { type: "message", message: { ...answer("error"), usage: undefined } },
  timed(500, 12400, { input: 400, output: 200, cacheRead: 16000, cacheWrite: 0, totalTokens: 16600 }),
  { type: "message", message: { role: "toolResult", toolName: "bash", isError: true } },
  { type: "message", message: { ...answer("stop"), usage: { input: "9", output: 2.5, cacheRead: -1 } } },
  { type: "custom", customType: "TOPSECRET-EXT", data: { note: "TOPSECRET" } },
];
const notified = [];
const ui = { notify: (text, type) => notified.push([text, type]) };
const ctx = { ui, sessionManager: { getEntries: () => entries } };
await commands.usage.handler("", ctx);
await commands.usage.handler("", { ...ctx, sessionManager: { getEntries: () => [] } });
results.usage = notified;
console.log(JSON.stringify(results));
"""


@unittest.skipUnless(shutil.which("node"), "node is required to drive the extension")
class MetricsExtensionTests(unittest.TestCase):
    def test_a_completed_answer_is_timed_and_nothing_else_is_touched(self) -> None:
        run = subprocess.run(
            ["node", "--input-type=module", "-e", DRIVER, "--", str(EXTENSION)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        results = json.loads(run.stdout)
        self.assertEqual(results["registered"], ["before_provider_request", "message_end", "message_update"])
        self.assertEqual(results["commands"], ["usage"])
        # The request hook returns nothing: a value would replace the payload.
        self.assertNotIn("payload", results)
        completed = results["completed"]["message"]
        self.assertGreaterEqual(completed["ttft"], 40)
        self.assertGreaterEqual(completed["duration"], completed["ttft"] + 40)
        self.assertEqual(completed["stopReason"], "stop")
        self.assertEqual(completed["usage"]["totalTokens"], 7)
        self.assertEqual(completed["content"], [{"type": "text", "text": "hi"}])
        # An errored answer, one that streamed nothing, a message without a
        # request before it, and other roles are left as they are.
        for case in ("errored", "silent", "orphan", "user", "tool"):
            self.assertNotIn(case, results, case)
        again = results["again"]["message"]
        self.assertEqual(again["stopReason"], "toolUse")
        self.assertIn("ttft", again)
        self.assertIn("duration", again)
        # /usage: the stats definitions over the transcript (three requests,
        # the errored one with no usage skipped, non-integers as zeros, the
        # last request's context and the peak, timings over the timed two,
        # two tool calls with one error), one status line, no content.
        self.assertEqual(
            results["usage"],
            [
                [
                    "usage: 3 requests, 900 in / 300 out, cache-read 95%, context 0 (peak 16,600), "
                    "ttft p50 300 ms, duration p50 0.9 s, 2 tools, 1 error",
                    "info",
                ],
                ["usage: no requests in this transcript yet", "info"],
            ],
        )
        self.assertNotIn("TOPSECRET", run.stdout)


if __name__ == "__main__":
    unittest.main()
