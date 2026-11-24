// The tool calls since the user's prompt. Past a soft cap, a call that
// returns the same result again and again ends the run; a hard cap ends it
// regardless.
//
// Source: Qwen Code, a fork of Gemini CLI: getTurnToolCallCapHalt and the
// consecutive identical-result count in
// packages/core/src/services/loopDetectionService.ts, Apache License 2.0,
// Copyright 2025 Google LLC; CAP_REPEAT_REMINDER_AT in
// packages/core/src/services/loop-protection.ts, Apache License 2.0,
// Copyright 2026 Qwen Team.
// Changes: reimplemented in JavaScript for pi, with other thresholds.
import { digest } from "./output.js";
import { callKey } from "./targets.js";

// At the soft cap the user is told and the model reads a note. Past it, a
// call that returned the same result this many times in a row (other calls
// between them allowed) gets a reminder, and the call that would repeat it
// once more than the stop count ends the run. The turn that would reach the
// hard cap ends the run.
const SOFT = 100;
const REMIND = 4;
const STOP = 6;
const HARD = 1000;

export class Budget {
  #calls = 0; // model calls since the user's prompt
  #repeats = new Map(); // call key -> { result, count }, past the soft cap

  reset() {
    this.#calls = 0;
    this.#repeats.clear();
  }

  // Numbers the turn's calls; returns what the user is told at the soft cap.
  count(turn) {
    const before = this.#calls;
    turn.calls.forEach((call, index) => turn.numbers.set(call.id, before + index + 1));
    this.#calls += turn.calls.length;
    if (before >= SOFT || this.#calls < SOFT) return undefined;
    turn.softCap = turn.calls[SOFT - before - 1].id;
    return `${SOFT} tool calls since your prompt`;
  }

  // Why the turn ends the run before it runs.
  exhausted() {
    if (this.#calls < HARD) return undefined;
    return {
      notice: `${this.#calls} tool calls since your prompt`,
      reason: `this turn would reach tool call ${this.#calls} since the user's last message.`,
    };
  }

  // Why this call ends the run before it runs.
  refusal(turn, call) {
    const repeats = this.#repeats.get(callKey(call));
    if (!(turn.numbers.get(call.id) > SOFT && repeats?.count >= STOP - 1)) return undefined;
    return {
      notice: `the same ${call.name} call returned the same result ${repeats.count} times after ${SOFT} tool calls`,
      reason:
        `this same \`${call.name}\` call returned the same result ${repeats.count} times since tool call ${SOFT} ` +
        "after the user's last message.",
    };
  }

  // The reminders for one result.
  observe(turn, call, result) {
    const notes = [];
    if (turn.numbers.get(call.id) > SOFT) {
      const key = callKey(call);
      const returned = digest(result.content);
      const previous = this.#repeats.get(key);
      const count = previous?.result === returned ? previous.count + 1 : 1;
      this.#repeats.set(key, { result: returned, count });
      if (count === REMIND) {
        notes.push(
          `Loop guard: this same call returned the same result ${count} times since tool call ${SOFT}. ` +
            `Use the result you have; at ${STOP} the loop guard ends the run.`,
        );
      }
    }
    if (call.id === turn.softCap) {
      turn.softCap = undefined;
      notes.push(
        `Loop guard: this is tool call ${SOFT} since the user's last message. Make sure each call makes ` +
          "progress; from here on, a call that keeps returning the same result ends the run.",
      );
    }
    return notes;
  }
}
