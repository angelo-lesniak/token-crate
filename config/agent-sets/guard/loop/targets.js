// What a call works on, and the kinds of calls the detectors tell apart.
//
// POLL_COMMAND follows pi-warden 2.12.1's dist/stuck.js, MIT License:
// Copyright (c) 2026 Ryan Gapac.
import { canonical, sha1, summary } from "./output.js";

// Tools that only keep the session's own checklist (`todo` from the todo set,
// `scratchpad` from the memory set): ticking an item between two attempts is
// not progress, so these neither count for nor break a repeat or a cycle.
const BOOKKEEPING = new Set(["todo", "scratchpad"]);
// pi's tools that change files: a success means the model changed
// something, so every failure streak starts over.
const EDIT_TOOLS = new Set(["edit", "write"]);
// Commands that wait for or watch something outside the agent (pi-warden).
const POLL_COMMAND =
  /\b(?:sleep|watch|wait)\b|\bgh\s+(?:run|pr)\s+(?:watch|checks|view|list)\b|\bgit\s+status\b|\btail\s+-[fF]\b|\b(?:ps|pgrep)\b/;
// Set-up in front of a command: `cd app && `, `export X=1; `, `CI=1 `.
const SETUP = /^(?:(?:cd|pushd|export|set|source|\.)\s[^;&|\n]*(?:&&|;|\n)\s*|\w+=\S*\s+)/;

export const toolCalls = (message) =>
  message?.role === "assistant" ? message.content.filter((part) => part.type === "toolCall") : [];
export const callKey = (call) => sha1(JSON.stringify([call.name, canonical(call.arguments)]));
export const counts = (call) => !BOOKKEEPING.has(call.name);
export const changesFiles = (call) => EDIT_TOOLS.has(call.name);
const isCommand = (input) => typeof input?.command === "string";
export const polls = (call) => isCommand(call.arguments) && POLL_COMMAND.test(call.arguments.command);

// The command a shell call runs without its set-up, whitespace collapsed.
const commandOf = (input) => {
  let command = input.command.trim();
  for (let next; (next = command.replace(SETUP, "")) !== command; ) command = next;
  return command.replace(/\s+/g, " ");
};
// What a failure streak is about: the file a call works on, else the command.
export const subjectOf = (name, input) => {
  const path = input?.path ?? input?.file_path ?? input?.filePath;
  if (typeof path === "string") return { key: `${name}\0${path}`, label: `\`${name}\` on ${path}` };
  if (isCommand(input)) {
    const command = commandOf(input);
    return { key: `${name}\0${command}`, label: `\`${summary(command, 120)}\`` };
  }
  return { key: name, label: `\`${name}\`` };
};
