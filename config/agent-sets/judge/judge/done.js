// The done check: a run that completes with a final message claiming the
// work is finished, and no passing test, build, or lint run after the last
// change, gets one continuation asking the agent to run one. It is asked
// before the run settles, so an aborted or failed run gets none.
import { describe, text, toolCalls, yesNo } from "./calls.js";

const FOLLOW_UP = "Before you call this done, run the project's tests or build and report the result.";
const QUESTIONS = {
  done: yesNo("Does `final` tell the user the requested work is finished?", "Claims the work is finished", "Progress, a question, or a blocker"),
  verified: yesNo(
    "Did a call in `calls` that tests, builds, or lints the change succeed after the last edit?",
    "A passing check ran after the last edit",
    "No passing check after the last edit",
  ),
};

// The messages after the last user message.
const sinceLastUser = (messages) => messages.slice(messages.findLastIndex((message) => message.role === "user") + 1);
const callsOf = (run) => {
  const inputs = new Map(run.flatMap(toolCalls).map((call) => [call.id, call.arguments]));
  return run
    .filter((message) => message.role === "toolResult")
    .map((message) => ({
      tool: message.toolName,
      call: describe(inputs.get(message.toolCallId)),
      failed: message.isError === true,
      output: text(message.content).slice(-300),
    }));
};

export class DoneCheck {
  #judge;
  #report;
  #asked = false;

  constructor(judge, report) {
    this.#judge = judge;
    this.#report = report;
  }

  newPrompt() {
    this.#asked = false;
  }

  // The result of agent_before_settle.
  async beforeSettle(request, event, signal) {
    if (this.#asked || event.outcome !== "completed") return undefined;
    const run = sinceLastUser(event.context?.contextMessages ?? []);
    const final = text(run.filter((message) => message.role === "assistant").at(-1)?.content).slice(-2000);
    if (!final) return undefined;
    const answers = await this.#judge.ask({ request, final, calls: callsOf(run).slice(-20) }, QUESTIONS, { signal });
    if (!answers) return undefined;
    const advise = answers.done?.noul >= 0.8 && answers.verified?.noul < 0.5;
    this.#report.answered("done", answers, advise);
    if (!advise) return undefined;
    this.#asked = true;
    return {
      entries: [...event.entries, { type: "custom_message", customType: "judge", content: FOLLOW_UP, display: true }],
      continue: true,
    };
  }
}
