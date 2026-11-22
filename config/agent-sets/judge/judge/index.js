// Advice from Kev-4B, a decision model on the judge service; it never
// blocks a call. client.js talks to the service, and each check has its
// module: done.js, stall.js, and on-task.js.
//
// TOKENCRATE_JUDGE_URL is http://judge:8080 in an offline session, the
// judge's address on the default network in one with a route out (the
// wrapper reads it), and empty without the service; the extension
// registers nothing when it is empty or names any host other than `judge`
// or an IPv4 address, so a session never asks a name its resolver could
// send off the machine.
import { Judge } from "./client.js";
import { DoneCheck } from "./done.js";
import { OnTaskCheck } from "./on-task.js";
import { StallCheck } from "./stall.js";

const BASE_URL = process.env.TOKENCRATE_JUDGE_URL ?? "";

function judgeOrigin(base) {
  try {
    const url = new URL(base);
    const ipv4 = /^\d{1,3}(\.\d{1,3}){3}$/.test(url.hostname);
    return url.protocol === "http:" && (url.hostname === "judge" || ipv4) ? url.origin : "";
  } catch {
    return "";
  }
}

export default function (pi) {
  const origin = judgeOrigin(BASE_URL);
  if (!origin) return;
  const judge = new Judge(origin, (type, data) => pi.appendEntry(type, data));
  const done = new DoneCheck(judge);
  const stall = new StallCheck(judge);
  const onTask = new OnTaskCheck(judge);
  // The last request the user gave, as the run received it (templates and
  // skills expanded), not a follow-up an extension sent.
  let request = "";
  let typed = false;

  pi.on("input", (event) => {
    // A message to a running agent (a steer or a queued follow-up) starts no run.
    if (event.streamingBehavior) return;
    stall.newRun();
    typed = event.source !== "extension";
    if (!typed) return;
    request = String(event.text ?? "").slice(0, 4000);
    done.newPrompt();
    stall.newPrompt();
  });

  pi.on("before_agent_start", (event) => {
    if (typed && event.messageType === "user") request = String(event.prompt ?? "").slice(0, 4000);
    typed = false;
  });

  pi.on("tool_result", (event, ctx) => {
    // A call another tool issued (codemode) is not the model's attempt.
    if (!event.parentToolCallId) stall.observe(event);
    onTask.observe(request, event, ctx);
  });

  pi.on("turn_end", async (event, ctx) => {
    const advice = await stall.endTurn(request, event, ctx.signal);
    if (advice) pi.sendMessage({ customType: "judge", content: advice, display: true }, { deliverAs: "steer" });
  });

  // The last point at which pi takes one more continuation; it is not
  // reached after an abort, and the outcome says how the run ended.
  pi.on("agent_before_settle", (event, ctx) => done.beforeSettle(request, event, ctx.signal));
}
