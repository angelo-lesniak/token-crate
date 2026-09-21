# Coding agents and skills

TokenCrate runs coding agents in containers that reach the local model
without a route to the internet by default. Terminal sessions share their
internal network with each other and the model. The agent sees exactly one
project directory, mounted read-write at its host path, plus a temporary
home with selected state from `LLM_AGENTS_DIR`. The root filesystem is
read-only and Linux capabilities are dropped.

| Agent | Command | What it is |
| --- | --- | --- |
| pi | `bash bin/tokencrate agent pi` | A small coding agent with a fixed tool set, configured entirely from files, plus the [agent sets](agent-sets.md) you select |
| oh-my-pi | `bash bin/tokencrate agent omp` | A fork of pi with language-server integration, subagents, and MCP support; more capable, more context per turn, and faster-moving releases |

Both agents read the same skills, the same `AGENTS.md` in your project,
and the same model list, one entry per loadable preset. The preset in
`LLM_DEFAULT_PRESET` is the model they start with.

Reasoning effort is the agent's thinking level; see [reasoning
effort](models.md#reasoning-effort) for the levels, what each does, and
how they map onto each preset.

The first request costs about 8,000 tokens for pi with the `coding` set,
8,900 to 9,700 with the toolchain selections, and 19,028 for oh-my-pi.
These measurements used the 27B on an RTX 5090; see the
[pi](validation.md#pi-and-the-agent-sets) and
[oh-my-pi](validation.md#oh-my-pi) records. The
[request-size record](validation.md#request-size-of-the-coding-set)
measures the tools and schema characters each set adds to every request.
The default preset has one 64K slot. Use `qwen3.8-27b-q4-long` (one 128K
slot) when a session runs out of context.

## What the container can and cannot do

- It can read and change every file below the project directory, including
  files ignored by Git. Do not use a directory that contains secrets or
  unrelated data as a project. The wrapper refuses the TokenCrate checkout
  and the storage directories named in `.env`, including projects inside
  or containing those directories. The next start trusts their contents.
- It can run any command installed in the image: Git, ripgrep, jq, and
  Node.js with fd in the pi image, Bun in the oh-my-pi image, and whatever the
  selected [agent sets](agent-sets.md) add. It cannot install system
  packages; a set is how a package gets into the image.
- It cannot reach the internet, resolve names, or reach a running browser
  UI. Its other host inputs are read-only: agent settings, its generated
  model-list file, and the skills described below.
  `bash bin/tokencrate smoke --agent pi`
  proves that those routes are absent, and on Docker that the bridge has
  no host address ([Privacy and
  containment](privacy.md#defaults-and-their-limits) has the engine
  details).
- It reads the skills and any `AGENTS.md` inside the project, so a cloned
  repository can instruct the agent; pi loads those context files whether
  or not the project is trusted. pi's project trust prompt
  (`defaultProjectTrust: ask`) gates the project's own `.pi/` resources,
  which run as code: subagent definitions (`.pi/agents/*.md`), extensions,
  prompts, and skills. oh-my-pi has no such gate for Bun: a `bunfig.toml`
  with a `preload` entry in the project runs its script inside the
  container as soon as `agent omp` starts, before any prompt.
- Files it writes can run on the host later: `.git/hooks`, `core.hooksPath`
  or `credential.helper` in `.git/config`, Makefiles, package scripts, and
  `.envrc`. Git does not show changes below `.git/` in a diff, so inspect
  `.git/config` and `.git/hooks` after a session before running Git on the
  host.
- Its home is writable tmpfs, reset when the container stops. Only the
  transcript and UI directories listed in [Storage
  layout](configuration.md#storage-layout) persist. Terminal and UI
  containers share pi transcripts but have separate live settings. A
  running UI's conversations share its home; [Agent
  configuration](#agent-configuration) says what one conversation can
  change for a later one.
- Commits made inside the container use `GIT_AUTHOR_NAME` and
  `GIT_AUTHOR_EMAIL` from `.env`; without them, `git commit` asks for an
  identity. The project is marked as a safe Git directory inside the
  container because its owner can differ from the container user on Docker.

When a task needs the network, for example to install packages, start the
session with `--egress`; no setting grants it. The wrapper prints a
warning; the container then has the same network access as any other
container on the default network.

The sets apply to the pi image only; oh-my-pi keeps its built-in tools.
[Agent sets](agent-sets.md) lists every shipped set, what it adds, how to
write one, and how the image is rendered.

## Skills

Skills follow the Agent Skills standard: a directory with a `SKILL.md` whose
frontmatter carries `name` and `description`. Agents read the description at
start and load the body only when a task matches. TokenCrate links three
sources into `~/.agents/skills` inside every agent container:

| Source | Location | Pinning |
| --- | --- | --- |
| Skill sets | `LLM_SKILLS_DIR/<set>/<skill>`, fetched by `skills fetch` | Repository, full commit, path, and tree digest in `config/skill-sets/<set>.toml` |
| Repository skills | `config/skills/<skill>` | Versioned with TokenCrate |
| Private skills | `LLM_LOCAL_SKILLS_DIR/<skill>` (default `local/skills`) | Yours; not committed |

`LLM_SKILL_SETS` names the fetched sets to load (default
`pocock-core,skill-crate`); `agent` refuses to start while a named set is
unknown, not fetched, or incomplete. Repository and private skills are
always loaded. The entire fetched-skills directory is mounted read-only,
so unselected sets remain readable by agent tools. An empty selection
links no fetched sets into the skills view. Skill names must be unique
across the loaded sources; the container refuses to start otherwise.
The `coding` agent set adds four pi-lens skills from the image.

Included:

- `pocock-core`: ten skills from `mattpocock/skills` (MIT) for engineering
  and productivity tasks (`tdd`, `code-review`, `diagnosing-bugs`,
  `implement`, `research`, `triage`, `to-spec`, `writing-for-agents`,
  `grill-me`, `handoff`).
- `skill-crate`: one skill, `documentation-guidelines`, from
  [SkillCrate](https://github.com/angelo-lesniak/skill-crate) (MIT): the
  documentation policy and workflow that TokenCrate's own pages follow,
  usable in any project.
- `tokencrate-local-model`, the repository skill: how to work efficiently
  with a local 27B model: small context, well-formed tool calls, thinking
  levels.

`skills status <set>` recomputes the digests of fetched skills. A digest
mismatch means the files on disk changed; `skills fetch` refuses to install a
commit whose digest differs from the manifest, so an upstream change must be
reviewed and re-pinned deliberately. Commit pinning is not a code review:
read a skill before you pin it.

## Browser UIs

`bash bin/tokencrate ui <set>` starts a browser UI for pi; see
[`ui`](cli.md#ui) for commands and options. Each UI runs inside a pi
container and shares the project's pi transcripts with terminal sessions.
[Storage layout](configuration.md#storage-layout) lists the retained files.

| Set | What it is | Choose it when |
| --- | --- | --- |
| `pi-web` | [PI WEB](https://github.com/jmfederico/pi-web): a file browser, editor, diffs, terminal, and layout for small screens, with one project at a time | You want a terminal session in a browser tab |
| `paseo` | [Paseo](https://github.com/getpaseo/paseo): several agent sessions side by side, worktrees, and session import; adds about 0.5 GB to the image | You want several sessions at once or Paseo's workspace workflow |

Compared with `agent pi`:

- The UI has no password, and its terminal and file editor have the
  agent's access to the project.
  [Privacy and containment](privacy.md#defaults-and-their-limits) states
  who can reach it and what that protects.
- Extension dialogs (`confirm`, `select`, `input`) appear in the browser.
  PI WEB handles project trust through its own prompt. Paseo runs pi in
  RPC mode, which shows no trust prompt and falls back to
  `defaultProjectTrust` (`ask`). Project-local `.pi/` resources therefore
  do not load in Paseo sessions.
- Each keeps its own state under the agent home (`~/.pi-web`, `~/.paseo`
  in the container), which persists with the project's sessions.

**PI WEB** runs a session daemon and web server using the image's pi.
It adds an `ask_user` tool and asks the model for a session title after
the first message. The launcher disables its session-spawning tools and
environment note in the system prompt; the `coding` set already provides
a subagent tool. It also keeps PI WEB's bundled relay out of pi's package
list. Uploads go to `.pi-web/uploads` inside the project by default.

**Paseo** runs pi as a subprocess in RPC mode. At first start, the launcher
registers the project as a local workspace without a worktree. It seeds
the daemon configuration with `Pi` as the only provider, the selected
preset as the default model, and thinking level `xhigh`. A saved agent
profile named after the preset uses it for one-click starts.

Select the provider and model in the browser's create-agent form on first
use; the browser remembers the last choice. The daemon configuration
persists in the agent home. A later launch with `--preset` does not
replace that configuration or the browser's selection.

Paseo's web client treats a new identity at a known address as an
unreachable host. The wrapper therefore keeps one daemon identity
(a keypair and server ID) per UI set under
`LLM_AGENTS_DIR/pi/<set>-identity/` and copies it into every project's
home. The browser sees one host whose project changes.

## Use four clients with one model

Start the model once, then both UIs from the checkout; these commands
return when ready. Run each terminal-agent command in its own terminal
and keep those two open. The project directory must already exist and
lie outside the TokenCrate checkout.

```bash
bash bin/tokencrate up
bash bin/tokencrate ui pi-web --preset qwen3.8-27b-q4-mtp --dir ~/src/my-project
bash bin/tokencrate ui paseo --preset qwen3.8-27b-q4-mtp --dir ~/src/my-project
bash bin/tokencrate agent pi --preset qwen3.8-27b-q4-mtp --dir ~/src/my-project
bash bin/tokencrate agent omp --preset qwen3.8-27b-q4-mtp --dir ~/src/my-project
```

Open the addresses printed by the UI commands. Create a separate
conversation in each client and confirm `tokencrate/qwen3.8-27b-q4-mtp`
is selected. Paseo retains provider and model settings: select the same
model in its create-agent form or saved profile even after changing
`--preset`. Existing conversations in either UI can also remember their
model. Do not erase retained state to change the selection.

Send prompts one after another, allowing PI WEB's automatic title request
to finish before the next prompt. All four clients use `http://llama:8080`
and the same loaded preset; opening a client creates no model server.
The MTP preset still has one inference slot. Keeping clients open does
not require simultaneous generation or a different preset. Use distinct
conversations: shared pi transcripts do not make concurrent writes to
one conversation safe. oh-my-pi keeps separate transcripts.

The [`ui` reference](cli.md#ui) covers independent start, logs, stop, and
port selection. Evidence and remaining checks are in
[Validation](validation.md#status).

## Agent configuration

The defining files are `config/agents/pi/settings.json`,
`config/agents/omp/config.yml`, `services/agents/entrypoint.sh`, and the
agent volumes in `compose.yaml`.

At each start, both agents use the repository's thinking level `xhigh`.
pi also uses project trust `ask` and the compaction limits in
`settings.json`. Edit the repository files to change the next container's
defaults. TokenCrate has no separate input for private agent settings,
themes, or keybindings.

A running UI container serves one project and one home, shared by its
conversations. An agent in one conversation can change what later
conversations and sessions execute or read: project hooks and scripts,
`AGENTS.md`, `.pi/`, retained transcripts, and UI configuration, including
Paseo's provider command and environment. Changes elsewhere in the agent
home last until the container stops.
Stop the UI between tasks that must not trust each other, and inspect the
project and the retained UI directories before trusting a later session.

Neither bash tool reads shell startup files from the home: pi's bash
tool passes `--noprofile --norc`, and `PI_BASH_NO_LOGIN=1` keeps
oh-my-pi's bash tool from starting a login shell.

The entrypoint writes these files into the fresh home at every start:

- the skills link at `~/.agents/skills` and the model list rendered
  from the presets;
- pi's `settings.json`: the repository file with `tokencrate` as the
  default provider, the selected preset as the default model, and
  `packages` set to exactly the image's list of local directories;
  `PI_OFFLINE=1` keeps pi from installing anything, so the image's list
  is what loads;
- the image seeds: the tools note at `~/.pi/agent/AGENTS.md`, which pi
  loads as global context (one line per set naming the installed tools
  and what needs `--egress`),
  the `coding` set's subagent definitions, and the `dotnet` set's NuGet
  configuration. The definitions are seeded without the `model:` line
  their upstream examples carry, so a subagent runs on the session's own
  model and thinking level;
- oh-my-pi's `config.yml`: the repository file
  `config/agents/omp/config.yml` with `modelRoles.default` set to the
  selected preset, written to `~/.omp/agent/config.yml`. oh-my-pi reads
  and rewrites that file, so a model chosen in the session applies and
  the tmpfs drops it when the container stops. `PI_CONFIG_FILES` names
  the repository file as an overlay as well, which keeps the keys it sets
  above the home copy and the project: automatic skill learning stays
  off, the bash tool keeps `/bin/bash`, no other provider is enabled, and
  the onboarding wizard stays closed (it asks an interactive session to
  sign in to a provider it cannot reach, and records its completion in
  the home, which the next container drops). Changing one of those keys
  in the session has no effect.

The repository's `config/agents/omp/AGENTS.md` is mounted read-only at
`~/.omp/agent/AGENTS.md` as oh-my-pi's global context.

## Bring your own client

Any OpenAI-compatible client on the host can use the running stack at
`http://127.0.0.1:4207/v1` with any model name listed by
`http://127.0.0.1:4207/v1/models` (the rendered preset ids). Every request
must name the preset in its `model` field: the router loads that preset on
first use and unloads the one loaded before. Clients that run on the host
are outside the containment described above.
