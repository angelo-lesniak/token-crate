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
  definitions, extensions, prompts, skills) are expected not to load
  until you accept a prompt; nothing gates oh-my-pi's Bun configuration
  (a `bunfig.toml` `preload`).
- Files it writes can run on the host later: `.git/hooks`, `core.hooksPath`
  or `credential.helper` in `.git/config`, Makefiles, package scripts, and
  `.envrc`. Git does not show changes below `.git/` in a diff, so inspect
  `.git/config` and `.git/hooks` after a session before running Git on the
  host.
- Its home is writable tmpfs, reset when the container stops, except
  the transcript and UI directories that [Storage
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
the agent image owns, such as `PATH`, `LD_*`, `TOKENCRATE_*`, or a
telemetry switch; the refusal names the line and the variable, and the
`case` list in
[`entrypoint.sh`](../services/agents/entrypoint.sh) is the full set.

Pick the cloud model with `/model`. A provider is offered as soon as
its key variable is set, with the regional and plan variants that read
the same variable; `HF_TOKEN` in the file enables pi's Hugging Face
provider. The wrapper does not set up a provider that needs a login or
a second variable, such as pi's ChatGPT subscription (`openai-codex`).

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

## Browser UIs

`bash bin/tokencrate ui <set>` starts a browser UI for pi
([`ui`](cli.md#ui) lists its options). Each UI runs inside a pi
container and shares the project's pi transcripts with terminal
sessions; its own state persists per project beside them.

| Set | What it is | Choose it when |
| --- | --- | --- |
| `pi-web` | [PI WEB](https://github.com/jmfederico/pi-web): a file browser, editor, diffs, terminal, and layout for small screens, with one project at a time | You want a terminal session in a browser tab |
| `paseo` | [Paseo](https://github.com/getpaseo/paseo): several agent sessions side by side, worktrees, and session import | You want several sessions at once or Paseo's workspace workflow |

The UI has no password, and its terminal and file editor have the
agent's access to the project; [Browser UIs](privacy.md#browser-uis)
says who can reach it. Extension dialogs appear in the browser.

PI WEB switches off its own session-spawning and session-messaging
tools; the `coding` set's subagent tool takes their place.

Paseo runs pi in RPC mode, which shows no project trust prompt, so
project-local `.pi/` resources are expected not to load there. At first
start the launcher registers the project as a workspace and seeds a
daemon configuration with pi as the only provider and the selected
preset as the default model. That configuration persists in the
project's `.paseo` directory, so a later `--preset` does not replace it.
Paseo's web client treats a new daemon identity at a known address as
an unreachable host, so the launcher shares one identity between
projects through the per-set store
([Troubleshooting](troubleshooting.md#paseo-asks-to-pair-again-or-shows-the-previous-project)
says how to get a fresh one).

## Use four clients with one model

A terminal pi, a terminal oh-my-pi, PI WEB, and Paseo can work on one
project at once. Start each with the same `--preset` and `--dir`, and
give each client its own conversation: concurrent writes to one
conversation are not safe. On a preset with one slot, their requests
queue.

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
`AGENTS.md`, `.pi/`, retained transcripts, and UI configuration, including
Paseo's provider command and environment. Changes elsewhere in the agent
home last until the container stops. Stop the UI between tasks that must
not trust each other, and inspect the project and the retained UI
directories before trusting a later session.
