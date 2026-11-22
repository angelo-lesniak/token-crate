// Repeats and cycles:
// - A repeat is a turn whose tool calls (name and key-sorted arguments) and
//   results equal the previous turn's, with durations, hex addresses, long
//   numbers, and timestamps masked, so a rerun that only prints a new PID or
//   time still repeats.
// - A cycle is two or three turns that come back in the same order with the
//   same results (read, edit, read, edit). A result that changes, such as a
//   build failing with a different error, breaks it.
// The unit is a turn, as in oh-my-pi: identical calls the model sends in
// parallel are one decision. A turn made only of polling commands (sleep,
// watch, tail -f, git status...) gets reminders but is never blocked for
// repeating: waiting prints the same until something outside the agent
// changes; the budget still bounds it.
//
// Sources, reimplemented in JavaScript for pi:
// - oh-my-pi 18.18.0, ToolCallLoopGuard in @oh-my-pi/pi-ai
//   src/utils/tool-call-loop-guard.ts and its redirect prompt, MIT License:
//   Copyright (c) 2025 Mario Zechner, Copyright (c) 2025-2026 Can Bölük,
//   Copyright (c) 2026 Stencil Labs, Inc.
// - OpenHands software-agent-sdk, the alternating action-observation check
//   of StuckDetector in
//   openhands-sdk/openhands/sdk/conversation/stuck_detector.py, MIT License:
//   Copyright (c) 2026 OpenHands contributors.
// - @wkqco33/pi-loop-guard 0.2.0, cycles of two and more calls in
//   src/detector.ts, MIT License: Copyright (c) 2026 wkqco33.
import { canonical, digest, sha1, summary } from "./output.js";
import { callKey, counts, polls } from "./targets.js";

// Counted in full cycles; a repeat is a cycle of one turn.
const CYCLES = [
  // The third identical turn in a row gets a reminder, the fifth is blocked,
  // the eighth ends the run.
  { length: 1, remind: 3, block: 5, stop: 8 },
  // A cycle of two or three turns: a reminder when the third full cycle
  // ends, a block for the turn that would end the fourth, the end of the run
  // at the fifth.
  { length: 2, remind: 3, block: 4, stop: 5 },
  { length: 3, remind: 3, block: 4, stop: 5 },
];
// Turns kept, more than the longest run any threshold needs.
const HISTORY = 64;
const LEVELS = ["none", "remind", "block", "stop"];
const CHANGE = "Change the approach: use different arguments or another tool, or, if the task is done or blocked, say so and stop.";

// A turn as these checks see it: its calls, and its calls with their
// normalized results, both hashed.
const turnOf = (calls, resultOf) => ({
  calls: sha1(JSON.stringify(calls.map(callKey).sort())),
  key: sha1(JSON.stringify(calls.map((call) => [callKey(call), resultOf(call.id)]).sort())),
  names: [...new Set(calls.map((call) => call.name))].join("+"),
  poll: calls.every(polls),
});

// How many turns the cycle of `length` turns ending with the last one spans,
// or 0 when the last turn does not continue one. A cycle of two or three
// identical turns is a repeat, which the cycle of one turn counts.
const span = (turns, length) => {
  const last = turns.slice(-length);
  if (last.length < length || (length > 1 && last.every((turn) => turn.key === last[0].key))) return 0;
  let matches = 0;
  for (let i = turns.length - 1; i - length >= 0 && turns[i].key === turns[i - length].key; i--) matches++;
  return matches > 0 ? matches + length : 0;
};

const atLeast = (found, name) => LEVELS.indexOf(found?.level ?? "none") >= LEVELS.indexOf(name);
const levelOf = (cycle, count) =>
  count >= cycle.stop * cycle.length
    ? "stop"
    : count >= cycle.block * cycle.length
      ? "block"
      : count >= cycle.remind * cycle.length && count % cycle.length === 0
        ? "remind"
        : "none";
const found = (cycle, turns, count) => ({
  cycle,
  count,
  level: levelOf(cycle, count),
  // Polling may repeat itself; the budget bounds it.
  exempt: turns.slice(-cycle.length).every((turn) => turn.poll),
});
// The most severe repeat or cycle among the candidates.
const worst = (candidates) => candidates.reduce((best, next) => (atLeast(best, next.level) ? best : next), undefined);
// The repeat or cycle the last of these turns ends.
const ending = (turns) => worst(CYCLES.map((cycle) => found(cycle, turns, span(turns, cycle.length))));

const reminder = ({ cycle, count }) =>
  cycle.length === 1
    ? `Loop guard: this exact call returned the same result ${count} times in a row. Do not repeat it; ` +
      "change the approach, or, if the task is done or blocked, say so and stop."
    : `Loop guard: your last ${count} turns went round the same cycle of ${cycle.length} turns ` +
      `${count / cycle.length} times with the same results. Break the cycle; change the approach.`;

export class Cycles {
  #turns = []; // the turns that ran since the last reset, oldest first

  reset() {
    this.#turns = [];
  }

  // Why the turn ends the run before it runs. A turn that sends the calls of
  // the turn `length` turns back is taken to return its result too: a block
  // has to come before the calls run.
  plan(turn) {
    if (turn.counted.length === 0) return undefined;
    const next = turnOf(turn.counted, () => "");
    const planned = worst(
      CYCLES.filter((cycle) => this.#turns.at(-cycle.length)?.calls === next.calls).map((cycle) => {
        const before = this.#turns.at(-cycle.length);
        const ran = [...this.#turns, { ...before, poll: next.poll }];
        return { ...found(cycle, ran, span(ran, cycle.length)), turn: before };
      }),
    );
    if (planned?.exempt) return undefined;
    turn.planned = planned;
    if (planned?.level !== "stop") return undefined;
    const { cycle, count } = planned;
    const notice =
      cycle.length === 1
        ? `the same ${turn.counted[0].name} call came ${count} times in a row`
        : `a cycle of ${cycle.length} turns came back ${Math.floor((count - 1) / cycle.length)} times`;
    return { notice, reason: this.#repeated(planned, turn.counted[0]) };
  }

  // Why this call is not run.
  block(turn, call) {
    if (!counts(call) || !atLeast(turn.planned, "block")) return undefined;
    return `Not run: ${this.#repeated(turn.planned, call)} Do not repeat it. ${CHANGE}`;
  }

  // The reminder, on the result that completes the turn.
  observe(turn, call, result) {
    if (!turn.counted.some((counted) => counted.id === call.id)) return [];
    turn.results.set(call.id, digest(result.content));
    if (!turn.counted.every((counted) => turn.results.has(counted.id))) return [];
    const run = ending([...this.#turns, turnOf(turn.counted, (id) => turn.results.get(id))]);
    if (run?.level !== "remind") return [];
    turn.noted = true;
    return [reminder(run)];
  }

  // Keeps the turn that ran; returns why the run ends after it, or the
  // message the model reads before its next turn.
  end(turn, calls, results, halted) {
    // A reply without tool calls ends any repeat or cycle.
    if (calls.length === 0) this.reset();
    const counted = calls.filter(counts);
    if (counted.length === 0) return {};
    // A turn this guard blocked continued its run; its results are the block reasons.
    const blocked = atLeast(turn.planned, "block") && counted.some((call) => turn.blocked.has(call.id));
    this.#turns.push(
      blocked ? turn.planned.turn : turnOf(counted, (id) => turn.results.get(id) ?? digest(results.get(id)?.content)),
    );
    if (this.#turns.length > HISTORY) this.#turns.splice(0, this.#turns.length - HISTORY);
    if (blocked || halted) return {};
    const run = ending(this.#turns);
    if (!run) return {};
    if (!run.exempt && run.level === "stop") {
      const notice = `the same ${counted[0].name} call came ${run.count} times in a row`;
      return { stop: { notice, reason: this.#repeated(run, counted[0]) } };
    }
    if (!run.exempt && run.level === "block") {
      return { steer: `Loop guard: ${this.#repeated(run, counted[0])} Do not send it again. ${CHANGE}` };
    }
    return run.level === "remind" && !turn.noted ? { steer: reminder(run) } : {};
  }

  // What the model reads about a repeat or cycle.
  #repeated({ cycle, count }, call) {
    return cycle.length === 1
      ? `you sent this same \`${call.name}\` call ${count} times in a row, and each time it returned the same result: ` +
          `${summary(JSON.stringify(canonical(call.arguments)), 400)}.`
      : `this \`${call.name}\` call continues a cycle of ${cycle.length} turns ` +
          `(${this.#turns.slice(-cycle.length).map((turn) => turn.names).join(" → ")}) ` +
          `that already went round ${Math.floor((count - 1) / cycle.length)} times with the same results.`;
  }
}
