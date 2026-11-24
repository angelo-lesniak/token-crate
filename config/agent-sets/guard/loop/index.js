// A loop guard the model sees. Three detectors find the ways a model goes
// round in circles instead of making progress: repeats and cycles of turns
// (cycles.js), one target failing again and again (failures.js), and the
// budget of tool calls per prompt (budget.js). The guard answers with a
// reminder appended to the tool result the model reads, then a block whose
// reason is the tool result, then the end of the run. Each module names the
// projects it follows and their licenses.
//
// Calls a tool issues itself (codemode) are not counted, the bookkeeping
// tools (targets.js) neither count nor break a run, and the user's next
// prompt starts everything over.
//
// pi runs neither tool_call nor tool_result for an unknown tool, invalid
// arguments, or a call another extension blocked first, so turn_end checks
// every call again: for those the reminder or block comes as a steering
// message, and the end of the run as an abort. Once the guard ends a run,
// it refuses every call until the user's next prompt, also in a follow-up
// run an extension starts. report.js shows the user each intervention.
import { Budget } from "./budget.js";
import { Cycles } from "./cycles.js";
import { Failures } from "./failures.js";
import { Report } from "./report.js";
import { toolCalls } from "./targets.js";
import { Turn } from "./turn.js";

export default function (pi) {
  const cycles = new Cycles();
  const failures = new Failures();
  const budget = new Budget();
  const report = new Report(pi);
  let halted; // the reason every call is refused, once the guard ends the run
  let turn = new Turn();

  const stop = (ctx, { notice, reason }) => {
    halted = `Not run: ${reason} The loop guard stopped the run here.`;
    report.intervened("stop", reason);
    ctx?.ui?.notify?.(`loop guard: ${notice}; the run stops`, "warning");
  };
  const refusal = () => {
    for (const call of turn.calls) {
      const refused = budget.refusal(turn, call) ?? failures.refusal(call);
      if (refused) return refused;
    }
    return undefined;
  };
  const observe = (call, result) => [...failures.observe(turn, call, result), ...budget.observe(turn, call, result)];

  pi.on("session_start", (_event, ctx) => report.use(ctx, { count: true }));

  pi.on("input", (event, ctx) => {
    report.use(ctx);
    if (event.source === "extension") return;
    cycles.reset();
    failures.reset();
    budget.reset();
    halted = undefined;
  });

  // Every decision a turn's calls can be refused for is taken here, before
  // the first of them runs, so that all calls of a stopped turn terminate.
  pi.on("message_end", (event, ctx) => {
    if (event.message.role !== "assistant") return;
    report.use(ctx);
    turn = new Turn(toolCalls(event.message));
    const notice = budget.count(turn);
    if (notice) ctx?.ui?.notify?.(`loop guard: ${notice}`, "warning");
    if (halted || turn.calls.length === 0) return;
    const refused = budget.exhausted() ?? refusal() ?? cycles.plan(turn);
    if (refused) stop(ctx, refused);
  });

  pi.on("tool_call", (event) => {
    // A call a tool issued (codemode) is not a model turn.
    if (event.parentToolCallId) return undefined;
    const reason = halted ?? cycles.block(turn, { name: event.toolName, arguments: event.input });
    if (!reason) return undefined;
    turn.blocked.add(event.toolCallId);
    // The calls refused after the end of a run count with that end.
    if (!halted) report.intervened("block", reason);
    return halted ? { block: true, terminate: true, reason } : { block: true, reason };
  });

  pi.on("tool_result", (event) => {
    if (event.parentToolCallId) return undefined;
    const call = { id: event.toolCallId, name: event.toolName, arguments: event.input };
    turn.observed.add(call.id);
    const notes = [...cycles.observe(turn, call, event), ...observe(call, event)];
    // One note per result, the first: a repeat or cycle, a failure, the budget.
    if (notes.length === 0) return undefined;
    report.intervened("reminder", notes[0]);
    return {
      content: [...event.content, { type: "text", text: notes[0] }],
      ...(event.structuredContent === undefined ? {} : { structuredContent: event.structuredContent }),
    };
  });

  pi.on("turn_end", (event, ctx) => {
    const calls = toolCalls(event.message);
    const results = new Map(event.toolResults.map((result) => [result.toolCallId, result]));
    // Calls tool_result did not see: an unknown tool, invalid arguments, or a
    // call another extension blocked.
    for (const call of calls) {
      const result = results.get(call.id);
      if (!result || turn.observed.has(call.id) || turn.blocked.has(call.id)) continue;
      const notes = observe(call, result); // may add a steer, which comes first
      turn.steers.push(...notes);
    }
    const ended = cycles.end(turn, calls, results, halted);
    if (ended.stop) stop(ctx, ended.stop);
    else if (ended.steer) turn.steers.unshift(ended.steer);
    if (!halted && turn.steers.length > 0) {
      report.intervened("steer", turn.steers[0]);
      pi.sendMessage({ customType: "loop-guard", content: turn.steers[0], display: true }, { deliverAs: "steer" });
    }
    // pi ends the run after a batch only when every call in it was refused
    // with terminate, and a queued message starts another turn regardless.
    if (halted && (calls.some((call) => !turn.blocked.has(call.id)) || ctx?.hasPendingMessages?.())) ctx?.abort?.();
    turn = new Turn();
    return undefined;
  });
}
