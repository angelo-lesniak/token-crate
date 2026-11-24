// How the detectors compare what tools return.
//
// normalize follows normaliseOutput in pi-warden 2.12.1's dist/stuck.js, MIT
// License: Copyright (c) 2026 Ryan Gapac.
import { createHash } from "node:crypto";

// The error line a failure is told apart by, cut to this many characters.
const ERROR_LINE = 200;
// A line that names the error, preferred over the first line of the output.
const ERROR_WORDS = /error|fail|not found|no such|denied|refused|exception|traceback|cannot|could not|invalid/i;
// Lines that name no error: a banner (pytest's `=== FAILURES ===`), a
// traceback header, and pi's notes on an empty output and the exit code.
const NOT_ERROR = /^(?:[=_-]{3,}.*[=_-]{3,}|traceback\b.*)$/i;
const QUIET = /^(?:\(no output\)|Command exited with code \d+)$/;

export const sha1 = (value) => createHash("sha1").update(value).digest("hex");
export const canonical = (value) =>
  Array.isArray(value)
    ? value.map(canonical)
    : value && typeof value === "object"
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]))
      : value;
export const summary = (value, limit) => {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
};
const text = (content) => (content ?? []).flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n");
const lines = (content) => text(content).split("\n").map((line) => line.trim()).filter(Boolean);
// Durations, addresses, PIDs, and timestamps change between identical runs;
// counts and line numbers stay.
const normalize = (value) =>
  value
    .replace(/\b\d+(?:\.\d+)?\s*(?:ms|s|m|h|µs|us|ns)\b/g, "#t")
    .replace(/0x[0-9a-fA-F]+/g, "0x#")
    .replace(/\d{5,}/g, "#")
    .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?/g, "#date");
export const digest = (content) => sha1(normalize(text(content)));

// pi's bash marks a nonzero exit as an error; other tools may only report
// the exit code.
export const failed = (result) =>
  result.isError === true ||
  [result.details?.exitCode, result.structuredContent?.exit_code].some((code) => typeof code === "number" && code !== 0);
export const quiet = (content) => lines(content).every((line) => QUIET.test(line));
export const errorLine = (content) => {
  const candidates = lines(content).filter((line) => !NOT_ERROR.test(line) && !QUIET.test(line));
  return normalize(candidates.find((line) => ERROR_WORDS.test(line)) ?? candidates[0] ?? "")
    .slice(0, ERROR_LINE)
    .replace(/[.:]+$/, "");
};
