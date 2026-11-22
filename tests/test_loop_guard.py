"""The `guard` set's loop guard, driven under node with a fake `pi`: when it
appends a reminder to a tool result, steers, blocks a call, and ends the run."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTENSION = PROJECT_ROOT / "config" / "agent-sets" / "guard" / "loop" / "index.js"

# Replays pi's hook sequence for each turn (message_end, then tool_call and
# tool_result per call, then turn_end) and records what the guard returned.
DRIVER = r"""
import { pathToFileURL } from "node:url";
const factory = (await import(pathToFileURL(process.argv[1]).href)).default;

function session() {
  const handlers = {};
  const steers = [];
  const notices = [];
  let aborts = 0;
  let pending = false;
  factory({
    on(name, handler) { handlers[name] = handler; },
    sendMessage(message, options) { steers.push({ message, options }); },
  });
  const ctx = {
    ui: { notify(text) { notices.push(text); } },
    abort() { aborts += 1; },
    hasPendingMessages: () => pending,
  };
  let ids = 0;
  // One assistant turn. `calls` are [name, args, result] with result
  // { text, isError?, structuredContent?, invalid? }; an invalid call skips
  // tool_call and tool_result, as pi does for unknown tools and bad arguments.
  const turn = (calls) => {
    const parts = calls.map(([name, args]) => ({ type: "toolCall", id: `c${++ids}`, name, arguments: args }));
    const message = { role: "assistant", content: parts };
    const before = { steers: steers.length, notices: notices.length, aborts };
    const outcome = { block: false, terminate: false, notes: [], reasons: [], terminated: [] };
    handlers.message_end({ message }, ctx);
    const toolResults = [];
    calls.forEach(([name, args, result], index) => {
      const id = parts[index].id;
      const content = [{ type: "text", text: result.text }];
      if (result.invalid) {
        toolResults.push({ toolCallId: id, content, isError: true });
        return;
      }
      const decision = handlers.tool_call({ toolName: name, toolCallId: id, input: args }, ctx);
      if (decision?.block) {
        outcome.block = true;
        outcome.terminate ||= Boolean(decision.terminate);
        outcome.terminated.push(Boolean(decision.terminate));
        outcome.reasons.push(decision.reason);
        toolResults.push({ toolCallId: id, content: [{ type: "text", text: decision.reason }], isError: true });
        return;
      }
      outcome.terminated.push(false);
      const event = { toolName: name, toolCallId: id, input: args, content, isError: Boolean(result.isError) };
      if (result.structuredContent) event.structuredContent = result.structuredContent;
      const patch = handlers.tool_result(event, ctx);
      if (patch) {
        outcome.notes.push(patch.content.at(-1).text);
        outcome.kept = patch.content.length === 2 && patch.content[0].text === result.text;
        outcome.structured = patch.structuredContent ?? null;
      }
      toolResults.push({ toolCallId: id, content: patch?.content ?? content, isError: Boolean(result.isError) });
    });
    handlers.turn_end({ message, toolResults }, ctx);
    outcome.steers = steers.slice(before.steers);
    outcome.notices = notices.slice(before.notices);
    outcome.aborts = aborts - before.aborts;
    return outcome;
  };
  const input = (source) => handlers.input({ text: "next", source });
  const child = (name, args, result) => {
    const id = `parent/${++ids}`;
    const call = { toolName: name, toolCallId: id, parentToolCallId: "parent", input: args };
    const decision = handlers.tool_call(call, ctx);
    const content = [{ type: "text", text: result.text }];
    const patch = handlers.tool_result({ ...call, content, isError: Boolean(result.isError) }, ctx);
    return decision ?? patch ?? null;
  };
  return { turn, input, child, queue: (value) => { pending = value; } };
}

const ok = (text) => ({ text });
const error = (text) => ({ text, isError: true });
const range = (count, step) => Array.from({ length: count }, (_, index) => step(index + 1));
const out = {};

// A rerun that prints a new PID, address, timestamp, and duration repeats.
{
  const s = session();
  const status = (n) => ok(`pid ${40000 + n} at 0x7f${n}a0 2026-11-18T10:0${n}:00Z took ${n}.2s`);
  const exit = { structuredContent: { exit_code: 0 } };
  out.repeat = range(9, (n) => s.turn([["bash", { command: "./status.sh" }, { ...status(n), ...exit }]]));
}

// A todo call between two attempts neither counts nor breaks the run.
{
  const s = session();
  const read = () => s.turn([["read", { path: "a.txt" }, ok("same")]]);
  out.todo = range(10, (n) => (n % 2 ? read() : s.turn([["todo", { action: "list", n }, ok(`list ${n}`)]])));
}

// The turn that ends the run ends it for a bookkeeping call beside it too,
// and a queued message cannot start another turn.
{
  const s = session();
  const read = ["read", { path: "a.txt" }, ok("same")];
  range(7, () => s.turn([read]));
  s.queue(true);
  out.stopWithTodo = s.turn([read, ["todo", { action: "list" }, ok("list")]]);
}

// Waiting for a build prints the same until it finishes.
{
  const s = session();
  out.poll = range(10, () => s.turn([["bash", { command: "sleep 60 && tail -3 build.log" }, ok("compiling...")]]));
}

// Two turns that come back in the same order with the same results.
{
  const s = session();
  out.cycle = range(10, (n) =>
    n % 2 ? s.turn([["read", { path: "a.txt" }, ok("A")]]) : s.turn([["read", { path: "b.txt" }, ok("B")]]),
  );
  const t = session();
  out.cycle3 = range(15, (n) => t.turn([["read", { path: `${n % 3}.txt` }, ok(`file ${n % 3}`)]]));
}

// Edit, build, edit, build, with the build failing differently each time.
{
  const s = session();
  const edit = ["edit", { path: "a.c", edits: [{ oldText: "x", newText: "y" }] }, ok("Successfully replaced 1 block")];
  const build = (n) => error(`a.c:${n}: error: expected ';' before '}' token\nCommand exited with code 2`);
  out.progress = range(24, (n) => s.turn([n % 2 ? edit : ["bash", { command: "make" }, build(n)]]));
}

// Fix and test: each edit succeeds, the test still fails behind pytest's banner.
{
  const s = session();
  const pytest = (n) =>
    error(
      [
        "F.                                                                       [100%]",
        "=================================== FAILURES ===================================",
        "_________________________________ test_add _________________________________",
        ">       assert add(2, 2) == 4",
        `E       assert ${n} == 4`,
        "tests/test_calc.py:4: AssertionError",
        `FAILED tests/test_calc.py::test_add - assert ${n} == 4`,
        "",
        "Command exited with code 1",
      ].join("\n"),
    );
  out.fixTest = range(10, (n) => [
    s.turn([["edit", { path: "src/calc.py", edits: [{ oldText: `v${n}`, newText: `v${n + 1}` }] }, ok("Replaced")]]),
    s.turn([["bash", { command: "cd /workspace && python3 -m pytest -q" }, pytest(n)]]),
  ]).flat();
}

// Searches that find nothing exit nonzero without output.
{
  const s = session();
  const nothing = error("(no output)\n\nCommand exited with code 1");
  out.search = range(12, (n) => s.turn([["bash", { command: `rg -n symbol${n} src` }, nothing]]));
}

// Edits of one file with different content that keep failing the same way.
const failingEdit = (n) => [
  "edit",
  { path: "src/a.ts", edits: [{ oldText: `attempt ${n}`, newText: "fixed" }] },
  error("Could not find the exact text in src/a.ts. The old text must match exactly including all whitespace."),
];
const editOf = (oldText, result) => ["edit", { path: "src/a.ts", edits: [{ oldText, newText: "b" }] }, result];
{
  const s = session();
  out.failures = range(9, (n) => s.turn([failingEdit(n)]));
  out.failureOther = s.turn([["read", { path: "src/b.ts" }, ok("fine")]]);
  const r = session();
  out.failureReset = [
    ...range(4, (n) => r.turn([failingEdit(n)])),
    r.turn([editOf("a", ok("Successfully replaced 1 block"))]),
    ...range(3, (n) => r.turn([failingEdit(10 + n)])),
  ];
  const d = session();
  out.failureNewError = [
    ...range(2, (n) => d.turn([failingEdit(n)])),
    d.turn([editOf("z", error("Error: EACCES: permission denied, open 'src/a.ts'"))]),
    d.turn([failingEdit(3)]),
  ];
  // A command is the same without its cd and variable set-up; another
  // command of the same program is not.
  const b = session();
  const command = (n) => (n === 2 ? "cd app && CI=1 npm   test" : "npm test");
  const npm = error("npm ERR! code ELIFECYCLE\nCommand exited with code 1");
  out.failingCommand = range(3, (n) => b.turn([["bash", { command: command(n) }, npm]]));
  out.otherCommand = b.turn([["bash", { command: "npm run lint" }, npm]]);
}

// Calls pi refuses before any hook (invalid arguments) are judged at turn end.
{
  const s = session();
  const invalid = { text: "Validation failed for tool \"edit\":\n  - edits: missing", invalid: true };
  out.invalid = range(8, () => s.turn([["edit", { path: "a.ts" }, invalid]]));
  out.afterInvalid = s.turn([["read", { path: "b.ts" }, ok("fine")]]);
}

// pi's edit with the coding set's pi-lens, as pi 1.5.2 reports it: pi-lens
// refuses an edit whose text is missing before tool_call and tool_result.
{
  const absent = (path, n) => [
    "edit",
    { path, edits: [{ oldText: `absent text ${n}`, newText: "x" }] },
    {
      text:
        `🔄 RETRYABLE — Edit target not found\n\nedits[0].oldText ("absent text ${n}") was not found ` +
        "in the current file content. This text does not appear anywhere in the file",
      invalid: true,
    },
  ];
  const s = session();
  out.lensOneFile = range(9, (n) => s.turn([absent("f0.txt", n)]));
  const m = session();
  out.lensManyFiles = range(12, (n) => m.turn([absent(`f${n}.txt`, n)]));
  // Another tool's parameter names.
  const a = session();
  out.aliases = range(9, (n) => {
    const args = { path: "f0.txt", old_str: `line ${n}`, new_str: "x" };
    const received = JSON.stringify(args, null, 2);
    const text = `Validation failed for tool "edit":\n  - edits: missing\n\nReceived arguments:\n${received}`;
    return a.turn([["edit", args, { text, invalid: true }]]);
  });
}

// The tool call budget of one prompt.
{
  const s = session();
  out.budget = range(1000, (n) => s.turn([["bash", { command: `echo ${n}` }, ok(`${n}`)]]));
  // Past the soft cap, a call that keeps returning the same result.
  const r = session();
  range(100, (n) => r.turn([["bash", { command: `echo ${n}` }, ok(`${n}`)]]));
  out.budgetRepeat = range(6, (n) => [
    r.turn([["bash", { command: "./check.sh" }, ok("2 failing")]]),
    r.turn([["bash", { command: `ls ${n}` }, ok(`${n}`)]]),
  ]).flat();
  // Past the soft cap, a call whose result changes each time.
  const c = session();
  range(100, (n) => c.turn([["bash", { command: `echo ${n}` }, ok(`${n}`)]]));
  out.budgetProgress = range(8, (n) => [
    c.turn([["edit", { path: "src/a.ts", edits: [{ oldText: `x${n}`, newText: `x${n + 1}` }] }, ok("ok")]]),
    c.turn([["bash", { command: "npm test" }, ok(`Tests: ${n} failed, ${20 - n} passed`)]]),
  ]).flat();
}

// The user's next prompt starts over; a message an extension sends does not.
{
  const s = session();
  const same = () => s.turn([["read", { path: "a.txt" }, ok("same")]]);
  range(4, same);
  s.input("interactive");
  out.afterInput = range(4, same);
  s.input("extension");
  out.afterExtensionInput = same();
  range(3, same);
  s.input("extension");
  out.haltedAfterExtensionInput = s.turn([["read", { path: "c.txt" }, ok("other")]]);
  s.input("interactive");
  out.afterHaltInput = s.turn([["read", { path: "c.txt" }, ok("other")]]);
}

// Calls a tool issues itself (codemode) are not counted and not judged.
{
  const s = session();
  const missing = error("Could not find the exact text in src/a.ts.");
  out.children = range(1200, (n) => s.child(...editOf(`${n}`, missing)));
  out.afterChildren = s.turn([failingEdit(1)]);
}

console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is required to drive the extension")
class LoopGuardTests(unittest.TestCase):
    out: dict

    @classmethod
    def setUpClass(cls) -> None:
        run = subprocess.run(
            ["node", "--input-type=module", "-e", DRIVER, "--", str(EXTENSION)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        cls.out = json.loads(run.stdout)

    def blocked(self, turns: list[dict]) -> list[int]:
        return [n for n, turn in enumerate(turns, 1) if turn["block"]]

    def terminated(self, turns: list[dict]) -> list[int]:
        return [n for n, turn in enumerate(turns, 1) if turn["terminate"]]

    def noted(self, turns: list[dict]) -> list[int]:
        return [n for n, turn in enumerate(turns, 1) if turn["notes"]]

    def steered(self, turns: list[dict]) -> list[int]:
        return [n for n, turn in enumerate(turns, 1) if turn["steers"]]

    def test_identical_results_after_masking_remind_block_and_end_the_run(self) -> None:
        turns = self.out["repeat"]
        self.assertEqual(self.noted(turns), [3, 4])
        self.assertIn("returned the same result 3 times in a row", turns[2]["notes"][0])
        # The reminder is appended: the output stays, and so does its structured copy.
        self.assertTrue(turns[2]["kept"])
        self.assertEqual(turns[2]["structured"], {"exit_code": 0})
        self.assertEqual(self.blocked(turns), [5, 6, 7, 8, 9])
        self.assertEqual(self.terminated(turns), [8, 9])
        self.assertIn("same `bash` call 5 times in a row", turns[4]["reasons"][0])
        self.assertIn("Do not repeat it.", turns[4]["reasons"][0])
        self.assertIn("stopped the run", turns[7]["reasons"][0])
        self.assertEqual(turns[7]["notices"], ["loop guard: the same bash call came 8 times in a row; the run stops"])
        self.assertEqual(self.steered(turns), [])
        self.assertEqual(sum(turn["aborts"] for turn in turns), 0)

    def test_a_todo_call_between_repeats_is_transparent(self) -> None:
        turns = self.out["todo"]
        reads = turns[0::2]
        self.assertEqual(self.noted(reads), [3, 4])
        self.assertEqual(self.blocked(reads), [5])
        self.assertEqual(self.blocked(turns[1::2]), [])

    def test_a_stop_ends_every_call_of_the_turn_and_a_queued_message(self) -> None:
        turn = self.out["stopWithTodo"]
        self.assertEqual(turn["terminated"], [True, True])
        self.assertEqual(turn["aborts"], 1)

    def test_polling_is_reminded_but_not_blocked(self) -> None:
        turns = self.out["poll"]
        self.assertEqual(self.noted(turns), [3, 4])
        self.assertEqual(self.blocked(turns), [])

    def test_a_cycle_of_two_turns_is_blocked_at_the_fourth_and_ended_at_the_fifth(self) -> None:
        turns = self.out["cycle"]
        self.assertEqual(self.noted(turns), [6])
        self.assertIn("same cycle of 2 turns 3 times", turns[5]["notes"][0])
        self.assertEqual(self.blocked(turns), [8, 9, 10])
        self.assertEqual(self.terminated(turns), [10])
        self.assertIn("cycle of 2 turns (read → read)", turns[7]["reasons"][0])

    def test_a_cycle_of_three_turns(self) -> None:
        turns = self.out["cycle3"]
        self.assertEqual(self.noted(turns), [9])
        self.assertEqual(self.blocked(turns), [12, 13, 14, 15])
        self.assertEqual(self.terminated(turns), [15])

    def test_a_changing_error_is_progress(self) -> None:
        for case in ("progress", "fixTest"):
            turns = self.out[case]
            self.assertEqual(self.noted(turns), [], case)
            self.assertEqual(self.blocked(turns), [], case)
            self.assertEqual(self.steered(turns), [], case)

    def test_a_search_that_finds_nothing_is_not_a_failure(self) -> None:
        turns = self.out["search"]
        self.assertEqual(self.noted(turns), [])
        self.assertEqual(self.blocked(turns), [])
        self.assertEqual(self.steered(turns), [])

    def test_failures_on_one_target_remind_steer_and_end_the_run(self) -> None:
        turns = self.out["failures"]
        self.assertEqual(self.noted(turns), [3, 4, 5, 6, 7, 8])
        self.assertIn("`edit` on src/a.ts failed the same way 3 times in a row", turns[2]["notes"][0])
        self.assertEqual(self.steered(turns), [5])
        steer = turns[4]["steers"][0]
        self.assertEqual(steer["options"], {"deliverAs": "steer"})
        self.assertEqual(steer["message"]["customType"], "loop-guard")
        self.assertTrue(steer["message"]["display"])
        self.assertIn("Could not find the exact text in src/a.ts", steer["message"]["content"])
        self.assertEqual(self.blocked(turns), [9])
        self.assertEqual(self.terminated(turns), [9])
        self.assertEqual(turns[8]["notices"], ["loop guard: edit on src/a.ts failed 8 times in a row; the run stops"])
        # Once the guard ends the run, every call is refused until the user's next prompt.
        self.assertTrue(self.out["failureOther"]["terminate"])

    def test_a_success_or_a_different_error_starts_the_target_over(self) -> None:
        self.assertEqual(self.noted(self.out["failureReset"]), [3, 4, 8])
        self.assertEqual(self.noted(self.out["failureNewError"]), [])

    def test_a_shell_target_is_the_command_without_its_set_up(self) -> None:
        turns = self.out["failingCommand"]
        self.assertEqual(self.noted(turns), [3])
        self.assertIn("`npm test` failed the same way 3 times", turns[2]["notes"][0])
        self.assertEqual(self.out["otherCommand"]["notes"], [])

    def test_calls_pi_refuses_before_the_hooks_are_judged_at_turn_end(self) -> None:
        turns = self.out["invalid"]
        self.assertEqual(self.blocked(turns), [])
        self.assertEqual(self.steered(turns), [3, 4, 5, 6, 7])
        self.assertIn("returned the same result 3 times", turns[2]["steers"][0]["message"]["content"])
        self.assertIn("Do not send it again.", turns[4]["steers"][0]["message"]["content"])
        self.assertEqual([turn["aborts"] for turn in turns], [0] * 7 + [1])
        self.assertEqual(turns[7]["notices"], ["loop guard: the same edit call came 8 times in a row; the run stops"])
        self.assertTrue(self.out["afterInvalid"]["terminate"])

    def test_edits_refused_before_they_run_are_followed_per_file(self) -> None:
        for case in ("lensOneFile", "aliases"):
            turns = self.out[case]
            self.assertEqual(self.steered(turns), [3, 4, 5, 6, 7, 8], case)
            self.assertIn("`edit` on f0.txt failed the same way 3 times", turns[2]["steers"][0]["message"]["content"])
            # A refused call reaches no tool_call, so the run ends by an abort.
            self.assertEqual([turn["aborts"] for turn in turns], [0] * 8 + [1], case)
        other_files = self.out["lensManyFiles"]
        self.assertEqual(self.steered(other_files), [])
        self.assertEqual(self.blocked(other_files), [])

    def test_the_tool_call_budget(self) -> None:
        turns = self.out["budget"]
        self.assertEqual(self.noted(turns), [100])
        self.assertIn("tool call 100 since the user's last message", turns[99]["notes"][0])
        self.assertEqual(turns[99]["notices"], ["loop guard: 100 tool calls since your prompt"])
        self.assertEqual(self.blocked(turns), [1000])
        self.assertEqual(self.terminated(turns), [1000])

    def test_past_the_soft_cap_a_call_that_keeps_returning_the_same_result_ends_the_run(self) -> None:
        repeat = self.out["budgetRepeat"]
        self.assertEqual(self.noted(repeat), [7])
        self.assertIn("returned the same result 4 times since tool call 100", repeat[6]["notes"][0])
        self.assertEqual(self.blocked(repeat), [11, 12])
        self.assertEqual(self.terminated(repeat), [11, 12])
        self.assertIn("returned the same result 5 times since tool call 100", repeat[10]["reasons"][0])
        progress = self.out["budgetProgress"]
        self.assertEqual(self.noted(progress), [])
        self.assertEqual(self.blocked(progress), [])

    def test_the_users_next_prompt_starts_over(self) -> None:
        self.assertEqual(self.blocked(self.out["afterInput"]), [])
        self.assertEqual(self.noted(self.out["afterInput"]), [3, 4])
        self.assertTrue(self.out["afterExtensionInput"]["block"])
        # A stopped run stays stopped for a run an extension starts.
        self.assertTrue(self.out["haltedAfterExtensionInput"]["terminate"])
        self.assertFalse(self.out["afterHaltInput"]["block"])

    def test_calls_a_tool_issues_are_ignored(self) -> None:
        self.assertEqual(self.out["children"], [None] * 1200)
        after = self.out["afterChildren"]
        self.assertFalse(after["block"])
        self.assertEqual(after["notes"], [])


if __name__ == "__main__":
    unittest.main()
