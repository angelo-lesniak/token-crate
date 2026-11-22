// The stall check: when three of the last six calls failed and three of
// those failures share a target (a path, or bash's first command word), the
// model is asked whether the failures repeat one strategy with only
// superficial variation and whether the later calls show progress; a repeat
// without progress is steered to the agent once per prompt. It is asked
// again only after three more tool results. Identical repeats are the loop
// guard's (guard set); this check is for near-duplicates.
//
// The questions and the output normalisation follow pi-warden 2.12.1 (the
// npm package's dist/stuck.js, stuckQuestions and normaliseOutput), MIT
// License: Copyright (c) 2026 Ryan Gapac; the list of what is not a repeat
// follows the loop detection prompt of Gemini CLI
// (packages/core/src/services/loopDetectionService.ts), Apache License 2.0:
// Copyright 2025 Google LLC.
import { target, text, toolCalls, yesNo } from "./calls.js";

// The gate: failures in the window, failures on one target, and the tool
// results to wait after a question.
const WINDOW = 6;
const MIN_FAILURES = 3;
const COOLDOWN = 3;
const ERROR_LINE = /error|fail|not found|denied|refused|exception|traceback/i;
const ADVICE =
  "The last attempts repeat one failing strategy. Re-read the error, state a new hypothesis, and change the " +
  "approach (gather the missing information or try another method) before trying again; if two methods have " +
  "failed, report the blocker to the user.";
const QUESTIONS = {
  sameStrategy: yesNo(
    "Do the failed entries in `calls` repeat the same strategy with only superficial variation?",
    "Yes: the same command or edit is retried, or only flags, paths, names, or wording change while the idea stays the same",
    "No: incremental edits to one file, a build or test re-run after a change, sequential reads of different files, or a retry with a real variation",
  ),
  progress: yesNo(
    "Do the later entries in `calls` show a different error, a partial success, or new information compared with the earlier ones?",
    "A different error, a partial success, or new information",
    "The same failure with nothing new",
  ),
};

// Durations, hex, long numbers, and timestamps differ between identical
// runs; counts and line numbers stay.
const normalise = (output) =>
  output
    .replace(/\b\d+(?:\.\d+)?\s*(?:ms|s|m|h|µs|us|ns)\b/g, "#t")
    .replace(/0x[0-9a-fA-F]+/g, "0x#")
    .replace(/\d{5,}/g, "#")
    .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?/g, "#date");

export class StallCheck {
  #judge;
  #steered = false;
  // The last tool results since the last prompt, and the count since the
  // last question.
  #attempts = [];
  #sinceAsked = Infinity;
  #observed = new Set(); // the calls of this turn that tool_result saw

  constructor(judge) {
    this.#judge = judge;
  }

  newRun() {
    this.#attempts = [];
    this.#sinceAsked = Infinity;
  }

  newPrompt() {
    this.#steered = false;
  }

  observe(event) {
    this.#observed.add(event.toolCallId);
    this.#attempted(event.toolName, event.input, event);
  }

  // The advice for the agent, if the judge finds it stalled.
  async endTurn(request, event, signal) {
    // pi runs no tool_result for a call refused before it ran: invalid
    // arguments, or one another extension blocked, as pi-lens does an edit
    // whose text is not in the file.
    const asked = new Map(toolCalls(event.message).map((call) => [call.id, call]));
    for (const result of event.toolResults) {
      const call = asked.get(result.toolCallId);
      if (call && !this.#observed.has(call.id)) this.#attempted(call.name, call.arguments, result);
    }
    this.#observed = new Set();
    if (this.#steered || this.#sinceAsked < COOLDOWN || event.toolResults.length === 0) return undefined;
    if (!this.#stalled()) return undefined;
    this.#sinceAsked = 0;
    const calls = this.#attempts.map(({ target, ...attempt }) => attempt);
    const answers = await this.#judge.ask({ request, calls }, QUESTIONS, { signal });
    if (!(answers?.sameStrategy?.noul >= 0.9 && answers?.progress?.noul < 0.5)) return undefined;
    this.#steered = true;
    return ADVICE;
  }

  #attempted(tool, input, result) {
    const output = text(result.content);
    const failed = result.isError === true;
    this.#attempts.push({
      tool,
      target: target(tool, input),
      call: JSON.stringify(input ?? {}).slice(0, 300),
      failed,
      // The line that names the error; undefined drops out of the request.
      error: failed ? output.split("\n").find((line) => ERROR_LINE.test(line))?.slice(0, 300) : undefined,
      output: normalise(output).slice(-300),
    });
    this.#attempts = this.#attempts.slice(-WINDOW);
    this.#sinceAsked++;
  }

  #stalled() {
    const perTarget = new Map();
    for (const attempt of this.#attempts) {
      if (attempt.failed) perTarget.set(attempt.target, (perTarget.get(attempt.target) ?? 0) + 1);
    }
    return Math.max(0, ...perTarget.values()) >= MIN_FAILURES;
  }
}
