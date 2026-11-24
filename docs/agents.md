# Coding agents and skills

TokenCrate runs coding agents in containers that reach the local model
without a route to the internet by default. The agent sees exactly one
project directory, mounted read-write at its host path, plus a temporary
home with selected state from `LLM_AGENTS_DIR`. The root filesystem is
read-only and Linux capabilities are dropped.

| Agent | Command | What it is |
| --- | --- | --- |
| pi | `bash bin/tokencrate agent pi` | A coding agent with the [agent sets](agent-sets.md) you select |
| oh-my-pi | `bash bin/tokencrate agent omp` | A fork of pi with built-in tools |

Both agents read the same skills, the same `AGENTS.md` in your project,
and the same model list. The list has one entry per preset that could
load when `up` last ran: its model files were downloaded and it passed
the [build gate](models.md#build-gate). After you download a model set
or open the gate for a preset, run `up` again to add it to the list.
The preset in `LLM_DEFAULT_PRESET` is the model they start with.

pi compacts a conversation when less than `compaction.reserveTokens`
of the slot is left, and keeps the last `keepRecentTokens` of it
verbatim. [The settings](../config/agents/pi/settings.json) size both
for a 128K slot: the reserve holds a 16K reply plus the margin pi keeps,
and pi shortens a longer reply near the end of the slot to what fits.
The entrypoint caps each at a quarter of a smaller slot, unless
`compaction.modelOverrides` names the preset (`tokencrate/<preset>`).
pi also sends a reasoning budget with every request (pi's
`thinkingBudgets`, 16,384 tokens at `xhigh`), which llama-server ends
the reasoning at; pi lowers it to leave at least 1,024 tokens for the
answer, so a reply or a compaction summary near the end of the slot
keeps room for its answer.

When compaction becomes frequent, run [`stats`](cli.md#stats): its
Preset fit table compares the context of each request in your sessions,
tool schemas and global context included, with the slot of every
loadable preset.

## What the container can and cannot do

- It can read and change every file below the project directory, including
  files ignored by Git. Do not use a directory that contains secrets or
  unrelated data as a project, and not the engine's own state
  (`~/.local/share/containers`, `~/.config/containers`, `~/.docker`),
  which decides what your next container runs. [`agent`](cli.md#agent)
  lists the directories the wrapper refuses.
- It can run any command installed in the image, Git and curl included,
  and in the pi image the tools of the selected [agent
  sets](agent-sets.md). It cannot install system packages; a set is how
  a package gets into the image.
- It has no route out, resolves no internet names, and reaches no browser
  UI by default ([Networks](privacy.md#networks) says which containers
  share a network). Its other host inputs are read-only: agent settings,
  its model list, and the skills.
- It reads the skills and any `AGENTS.md` inside the project, so a cloned
  repository can instruct the agent. Project-local code runs inside the
  container as soon as the agent loads it. With the shipped
  `defaultProjectTrust: ask`, pi's `.pi/` resources (subagent
  definitions, extensions, prompts, skills, MCP servers) are expected
  not to load until you accept a prompt; nothing gates oh-my-pi's Bun
  configuration (a `bunfig.toml` `preload`).
- Files it writes can run on the host later: `.git/hooks`, `core.hooksPath`
  or `credential.helper` in `.git/config`, Makefiles, package scripts, and
  `.envrc`. Git does not show changes below `.git/` in a diff, so inspect
  `.git/config` and `.git/hooks` after a session before running Git on the
  host.
- Its home is writable tmpfs, reset when the container stops, except
  the transcript, UI, and memory directories that [Storage
  layout](configuration.md#storage-layout) lists.
- Commits made inside the container use `GIT_AUTHOR_NAME` and
  `GIT_AUTHOR_EMAIL` from `.env`; without them, `git commit` fails with
  `Author identity unknown`.

When a task needs the network, for example to install packages, start
the session with `--egress`; [Egress](privacy.md#egress) says what else
the session then reaches.

## Cloud providers

`agent pi --cloud` and `ui <set> --cloud` offer cloud models beside the
local preset. The keys live in the file that `LLM_CLOUD_KEYS_FILE`
names; the wrapper mounts it read-only into that one session or UI and
never opens it. Start from the template, which lists the variables the
pinned pi reads for single-key providers:

```bash
cp cloud-keys.env.example local/cloud-keys.env && chmod 600 local/cloud-keys.env
bash bin/tokencrate agent pi --cloud --dir ~/src/my-project
```

Each line is `NAME=value` with an upper-case name; blank lines and
lines starting with `#` are skipped, and matching quotes around a value
are removed. The container's entrypoint exports each key without
expanding anything. It refuses a line with a carriage return and a name
the agent image owns, such as `PATH`, `LD_*`, `TOKENCRATE_*`, a
telemetry switch, or the memory sets' `PI_MEMORY_*` and `HINDSIGHT_*`;
the refusal names the line and the variable, and the `case` list in
[`entrypoint.sh`](../services/agents/entrypoint.sh) is the full set.

A session starts on the local preset; pick a cloud model with `/model`,
or start on one with `-- --model <provider>/<model>`. The `roles` set's
planner and reviewer run on the session's model, its scout and worker
on the local preset. A provider is offered as soon as its key variable
is set, with the regional and plan variants that read the same
variable; `HF_TOKEN` in the file enables pi's Hugging Face provider.
The wrapper does not set up a provider that needs a login or a second
variable, such as pi's ChatGPT subscription (`openai-codex`).

Use `--cloud` only in a project you trust:

- The whole conversation leaves the machine, the turns the local model
  answered included ([What leaves the
  machine](privacy.md#what-leaves-the-machine)).
- Every process in the session can read the keys and use the route
  out, so a project whose `AGENTS.md` or scripts ask for the keys can
  send them anywhere. A key printed into a transcript stays in the
  project's agent home, which later sessions and browser UIs of that
  project mount.
- A browser UI started with `--cloud` holds the keys until it stops
  ([`ui`](cli.md#ui) says what stops it), and whatever reaches its port
  can use them, every local process and every other browser UI
  included. Run one such UI at a time and stop it when the work is
  done.
- The wrapper refuses `agent omp --cloud`: oh-my-pi fills unset
  provider settings, base URLs included, from `.env` files in its home,
  its configuration root, and the project (`.env`, `.env.local`,
  `.env.development`, `.env.development.local`), so a project could
  send a key and every prompt to a server of its choosing. For the same
  reason, an oh-my-pi session with `--egress` in a project whose `.env`
  holds a provider key reaches that provider.

## Skills

Skills follow the Agent Skills standard: a directory with a `SKILL.md`
whose frontmatter carries `name` and `description`. Agents read the
description at start and load the body only when a task matches.
TokenCrate links two sources into `~/.agents/skills` in every agent
container:

- the skill sets that `LLM_SKILL_SETS` names, fetched by [`skills
  fetch`](cli.md#skills) into `LLM_SKILLS_DIR/<set>/<skill>` and pinned
  by the manifests in `config/skill-sets/`; `skills list` prints the
  shipped sets;
- your private skills in `LLM_LOCAL_SKILLS_DIR/<skill>`, always loaded
  and not committed.

The whole fetched-skills directory is mounted read-only, so unselected
sets remain readable by agent tools. A skill's name must be unique
across both sources and match its frontmatter `name`; the container
refuses to start otherwise.

## Memory between sessions

`agent pi --memory project` keeps the store of the `memory` and
`hindsight` sets for the project, `--memory global` one store for all
projects. Without `--memory`, and in a browser UI, the `memory` store
lasts until the container stops and `hindsight` is inert.

- **`memory`** keeps Markdown files in its store ([Storage
  layout](configuration.md#storage-layout) says where); delete a file
  to remove that memory.
- **`hindsight`** uses the memory server ([`agent`](cli.md#agent) says
  which sessions reach it). To delete every bank, run `down` and empty
  `LLM_AGENTS_DIR/hindsight`.

An instruction planted in a memory reaches later sessions, and with
`global` other projects. [Networks](privacy.md#networks) says which
sessions can read and change a bank.

## MCP servers

The `mcp` set turns on pi's MCP client. Add a server to the project's
`.pi/mcp.json`, which pi reads after you accept the trust prompt;
`~/.pi/agent/mcp.json` is lost when the container stops. Use `deferred`
exposure: it declares one `tool_search` tool, where pi's default
`codemode` exposure lists the server's tools in every request:

```json
{ "mcpServers": { "<name>": { "command": "<command>", "args": [], "exposure": "deferred" } } }
```

A stdio server's command runs in the container, so an [agent
set](agent-sets.md#write-a-set) must install it in the image; `npx` and
remote servers need `--egress`.

## Browser UIs

`bash bin/tokencrate ui <set>` starts a browser UI for pi
([`ui`](cli.md#ui) lists its options). The shipped UI set is `pi-web`:
[agegr's pi-web](https://github.com/agegr/pi-web), with a session tree,
a file browser, Git diffs, and a terminal. The UI runs inside a pi
container, opens the project `ui` names, and shares its pi transcripts
with terminal sessions; its own state persists per project beside them.

The UI has no password, and its terminal and file editor have the
agent's access to the project; [Browser UIs](privacy.md#browser-uis)
says who can reach it. Extension dialogs appear in the browser.

## Use three clients with one model

A terminal pi, a terminal oh-my-pi, and pi-web can work on one project
at once. Start each with the same `--preset` and `--dir`, and give
each client its own conversation: concurrent writes to one conversation
are not safe. On a preset with one slot, their requests queue.

## Agent configuration

The defining files are
[`config/agents/pi/settings.json`](../config/agents/pi/settings.json),
[`config/agents/omp/config.yml`](../config/agents/omp/config.yml),
`config/agents/omp/AGENTS.md` (oh-my-pi's global context),
[`services/agents/entrypoint.sh`](../services/agents/entrypoint.sh), and
the agent volumes in `compose.yaml`. Edit them to change the next
container's defaults; TokenCrate has no separate input for private agent
settings, themes, or keybindings.

The entrypoint writes the agent configuration into the fresh home at
every start. A model chosen with `/model` in oh-my-pi lasts until the
container stops, but a key that `config/agents/omp/config.yml` sets
cannot be changed in the session: that file overlays the home and the
project. Neither bash tool reads shell startup files from the home.

A running UI container serves one project and one home, shared by its
conversations. An agent in one conversation can change what later
conversations and sessions execute or read: project hooks and scripts,
`AGENTS.md`, `.pi/`, retained transcripts, and UI configuration.
Changes elsewhere in the agent home last until the container stops.
Stop the UI between tasks that must not trust each other, and inspect
the project and the retained UI directories before trusting a later
session.
