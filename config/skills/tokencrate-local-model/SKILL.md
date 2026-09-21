---
name: tokencrate-local-model
description: Work efficiently with a local 27B-class model served by TokenCrate. Use at the start of any session on a TokenCrate endpoint, when tool calls fail or loop, or when the context window is small.
license: MIT
metadata:
  source: token-crate
---

# Working with a local model on TokenCrate

You are talking to a locally hosted open-weight model with a fixed context
window (32K to 128K tokens depending on the preset). Nothing leaves the
machine, but every token you read or write costs time on one GPU.

## Keep the context small

- Read files in slices. Prefer `grep` or a targeted `read` with a line range
  over dumping whole files.
- Do not paste large command outputs back into the conversation. Filter with
  `head`, `tail`, `grep`, or `jq` first.
- Summarize what you learned before moving on; the earliest turns can be
  compacted away.
- Keep `AGENTS.md` short and project-specific. The skill catalog and tool
  schemas already use part of the window.

## Tool calls

- Put every tool argument in the JSON arguments object; never write arguments
  as prose after the call.
- If a tool call is rejected, repeat it with corrected JSON instead of
  describing what you would have done.

## Reasoning effort

- Sessions start at the highest thinking level the preset accepts. Ask the
  user to lower it (`/thinking low` in pi or oh-my-pi, or `reasoning_effort`
  in the request from another client) for quick edits, and to keep the
  default for design questions, instead of reasoning at length in the answer.
- Do not restate your reasoning in the final message; give the conclusion and
  the concrete change.

## Verify before you finish

- Run the project's tests or linters through the shell tool and quote only
  the failing lines.
- State what you changed, what you ran, and what you did not verify.
