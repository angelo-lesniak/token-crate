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
const factory = (await import(pathToFileURL(process.argv[1]).href)).default;
const handlers = {};
factory({ on(name, handler) { (handlers[name] ||= []).push(handler); } });
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
const results = { registered: Object.keys(handlers).sort() };

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


if __name__ == "__main__":
    unittest.main()
