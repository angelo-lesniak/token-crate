import { counts } from "./targets.js";

// What the detectors share about the turn under way.
export class Turn {
  constructor(calls = []) {
    this.calls = calls; // every call of the assistant message
    this.counted = calls.filter(counts); // the calls repeats and cycles count
    this.numbers = new Map(); // call id -> its number since the user's prompt
    this.results = new Map(); // call id -> normalized result, from tool_result
    this.blocked = new Set(); // call ids this guard blocked
    this.observed = new Set(); // call ids tool_result saw
    this.planned = undefined; // the repeat or cycle the turn continues
    this.noted = false; // the repeat or cycle reminder reached a tool result
    this.softCap = undefined; // the id of the call that reaches the soft cap
    this.steers = []; // what the model should read before its next turn
  }
}
