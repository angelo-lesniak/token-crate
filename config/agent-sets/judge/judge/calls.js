// What the judge reads about the agent's tool calls, and how it is asked.

export const text = (content) =>
  typeof content === "string" ? content : (content ?? []).flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n");
export const toolCalls = (message) =>
  message?.role === "assistant" ? message.content.filter((part) => part.type === "toolCall") : [];

// What a call works on: its path, else the first word of its command,
// else the tool.
export const target = (tool, input) =>
  typeof input?.path === "string" ? input.path : typeof input?.command === "string" ? input.command.trim().split(/\s+/)[0] : tool;

// What a call did, for the done check: a check that prints nothing is
// known by its command alone, and one often ends a long command.
export const describe = (input) => {
  if (typeof input?.command !== "string") return typeof input?.path === "string" ? input.path : undefined;
  const command = input.command.trim();
  return command.length > 200 ? `${command.slice(0, 100)}…${command.slice(-100)}` : command;
};

// llama.cpp's wire name for a yes/no question is `noul`; the answer is the
// probability of true.
export const yesNo = (instructions, yes, no) => ({ type: "noul", instructions, criteria: { true: yes, false: no } });
