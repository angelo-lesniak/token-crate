// One file (the path of a file tool) or one bash command failing again and
// again with the same error line. A successful edit or write starts every
// streak over, and a command that only exits nonzero without output (a
// search that finds nothing) does not count.
//
// Sources, reimplemented in JavaScript for pi:
// - OpenHands software-agent-sdk, the action-error streak of StuckDetector in
//   openhands-sdk/openhands/sdk/conversation/stuck_detector.py, MIT License:
//   Copyright (c) 2026 OpenHands contributors.
// - Qwen Code, packages/cli/src/acp-integration/session/
//   repeated-tool-failure-guard.ts, Apache License 2.0, Copyright 2025 Qwen.
//   Changes: reimplemented in JavaScript for pi, with other thresholds.
import { errorLine, failed, quiet } from "./output.js";
import { changesFiles, subjectOf } from "./targets.js";

// Failures in a row of one target with the same error: reminders from the
// third, a steering message at the fifth, and from the eighth the next call
// on that target ends the run.
const REMIND = 3;
const STEER = 5;
const STOP = 8;

export class Failures {
  #streaks = new Map(); // failure subject -> { line, count }

  reset() {
    this.#streaks.clear();
  }

  // Why this call ends the run before it runs.
  refusal(call) {
    const subject = subjectOf(call.name, call.arguments);
    const streak = this.#streaks.get(subject.key);
    if (!(streak?.count >= STOP)) return undefined;
    return {
      notice: `${subject.label.replaceAll("`", "")} failed ${streak.count} times in a row`,
      reason: `${subject.label} failed the same way ${streak.count} times in a row: ${streak.line}.`,
    };
  }

  // The reminders for one result.
  observe(turn, call, result) {
    const subject = subjectOf(call.name, call.arguments);
    if (!failed(result)) {
      if (changesFiles(call)) this.reset();
      else this.#streaks.delete(subject.key);
      return [];
    }
    if (quiet(result.content)) return [];
    const line = errorLine(result.content);
    const streak = this.#streaks.get(subject.key);
    const count = streak?.line === line ? streak.count + 1 : 1;
    this.#streaks.set(subject.key, { line, count });
    if (count === STEER) {
      turn.steers.push(
        `${subject.label} failed the same way ${count} times in a row: ${line}. Stop retrying it. Find the cause ` +
          "first (read the file or the whole error), try a different method, or tell the user what blocks you. " +
          `At ${STOP} such failures the loop guard ends the run.`,
      );
    }
    if (count < REMIND) return [];
    return [
      `Loop guard: ${subject.label} failed the same way ${count} times in a row. Do not retry it unchanged: ` +
        "read the error and the current state of what it works on, then change the approach.",
    ];
  }
}
