# Coding agents and skills

TokenCrate runs coding agents in containers that reach the local model
without a route to the internet by default. The agent sees exactly one
project directory, mounted read-write at its host path, plus a temporary
home with selected state from `LLM_AGENTS_DIR`. The root filesystem is
read-only and Linux capabilities are dropped.

| Agent | Command | What it is |
| --- | --- | --- |
| pi | `bash bin/tokencrate agent pi` | A small coding agent with a fixed tool set, configured entirely from files, plus the [agent sets](agent-sets.md) you select |
| oh-my-pi | `bash bin/tokencrate agent omp` | A fork of pi with more context per turn and faster-moving releases; its added features (language servers, subagents, MCP) are outside what TokenCrate's runs cover |

Both agents read the same skills, the same `AGENTS.md` in your project,
and the same model list, one entry per loadable preset. The preset in
`LLM_DEFAULT_PRESET` is the model they start with.

Reasoning effort is the agent's thinking level; see [reasoning
effort](models.md#reasoning-effort) for the levels, what each does, and
how they map onto each preset.

The first request costs about 8,000 tokens for pi with the `coding` set,
8,900 to 9,700 with the toolchain selections, and 19,028 for oh-my-pi,
measured with the 27B on an RTX 5090. The default preset has one 64K
slot; pi compacts the conversation when the slot fills, and a session
whose turns read 20 KB files filled it in about ten turns and refilled
it within two. Use `qwen3.8-27b-q4-mtp-long` (one 128K slot) when a
session runs out of context.

## What the container can and cannot do

- It can read and change every file below the project directory, including
  files ignored by Git. Do not use a directory that contains secrets or
  unrelated data as a project, and not the engine's own state
  (`~/.local/share/containers`, `~/.config/containers`, `~/.docker`),
  which decides what your next container runs. [`agent`](cli.md#agent)
  lists the directories the wrapper refuses.
- It can run any command installed in the image: Git, curl, ripgrep, and
  jq, plus Node.js and fd in the pi image, Bun in the oh-my-pi image, and
  whatever the selected [agent sets](agent-sets.md) add. It cannot install
  system packages; a set is how a package gets into the image.
- It cannot reach the internet, resolve internet names, or reach a running
  browser UI; `bash bin/tokencrate smoke --agent pi` proves that those
  routes are absent. Its other host inputs are read-only: agent settings,
  its generated model-list file, and the skills described below.
- It reads the skills and any `AGENTS.md` inside the project, so a cloned
  repository can instruct the agent. Project-local code runs inside the
  container as soon as the agent loads it. The shipped
  `defaultProjectTrust: ask` is expected to gate pi's `.pi/` resources
  (subagent definitions, extensions, prompts, skills) behind a prompt;
  nothing gates oh-my-pi's Bun configuration (a `bunfig.toml` `preload`).
- Files it writes can run on the host later: `.git/hooks`, `core.hooksPath`
  or `credential.helper` in `.git/config`, Makefiles, package scripts, and
  `.envrc`. Git does not show changes below `.git/` in a diff, so inspect
  `.git/config` and `.git/hooks` after a session before running Git on the
  host.
- Its home is writable tmpfs, reset when the container stops; [Storage
  layout](configuration.md#storage-layout) lists the transcript and UI
  directories that persist, and [Agent
  configuration](#agent-configuration) says what one conversation can
  change for a later one.
- Commits made inside the container use `GIT_AUTHOR_NAME` and
  `GIT_AUTHOR_EMAIL` from `.env`; without them, `git commit` asks for an
  identity. The project is marked as a safe Git directory inside the
  container because its owner can differ from the container user on Docker.

When a task needs the network, for example to install packages, start the
session with `--egress`; no setting grants it. The wrapper prints a
warning, and the session is then on the default network with a route
out; [Egress](privacy.md#egress) says what else it reaches there.

Agent sets apply to the pi image only; oh-my-pi keeps its built-in tools.
[Agent sets](agent-sets.md) lists every shipped set and how to write one.

## Cloud providers

`agent pi --cloud` and `ui <set> --cloud` offer cloud models beside the
local preset, with the same project and skills. The keys live in one
file of your own, named by `LLM_CLOUD_KEYS_FILE` (default
`local/cloud-keys.env`). The file holds one `NAME=value` line per key,
using the variable names pi reads, for example `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, or `OPENROUTER_API_KEY`; pi's
documentation lists every provider's. Its grammar is the container
entrypoint's own: an upper-case name, matching quotes around a value
removed, nothing expanded, blank lines and lines starting with `#`
skipped, LF line endings. The wrapper mounts the file read-only into
that one session or UI and never opens it. Start from the template:

```bash
cp cloud-keys.env.example local/cloud-keys.env && chmod 600 local/cloud-keys.env
bash bin/tokencrate agent pi --cloud --dir ~/src/my-project
```

The entrypoint refuses a line that sets a name the agent image owns:
`PATH`, `HOME`, `USER`, `LOGNAME`, `IFS`, `BASH_ENV`, `ENV`,
`TOKENCRATE_*`, `LD_*`, `GIT_CONFIG_GLOBAL`, `PI_CONFIG_FILES`,
`PI_BASH_NO_LOGIN`, `PI_TELEMETRY`, `PI_SKIP_VERSION_CHECK`,
`PI_OFFLINE`, `PI_LENS_*`, `PILENS_*`, `DOTNET_CLI_*`, `NODE_OPTIONS`,
and `BUN_INSTALL`. The file therefore cannot switch the [privacy
settings](privacy.md#telemetry-switches) off; any other variable pi
reads is passed on.

Pick the cloud model with `/model`. pi ships each provider's endpoint
and a model list bundled with the pinned package, so a provider is
offered as soon as its key variable is set. One key can enable more than
one provider: pi also offers the regional and plan variants that read
the same variable (`moonshotai-cn`, `opencode-go`), and `HF_TOKEN` in
the file enables its Hugging Face provider. Providers that need a login
or a second variable, such as pi's ChatGPT subscription (`openai-codex`),
are not set up by the wrapper.

Use `--cloud` only in a project you trust:

- The whole conversation leaves the machine, the turns the local model
  answered included, with their file contents and tool output ([What
  leaves the machine](privacy.md#what-leaves-the-machine)).
- Every process in the session can read the keys and has a route out
  for the session's lifetime. A project whose `AGENTS.md` or scripts ask
  for the keys can therefore send them anywhere. A key printed into a
  transcript stays in the project's agent home; later sessions and
  browser UIs of that project mount that home.
- A browser UI started with `--cloud` holds the keys while it runs
  ([`ui`](cli.md#ui) says what ends that). Whoever reaches its port can
  use them and the route out: every local process and every other browser
  UI ([network limits](privacy.md#networks)).
  Run one such UI at a time and stop it when the work is done.
- Cloud models are offered through pi only. oh-my-pi fills unset
  provider settings, base URLs included, from `.env` files in its home,
  its configuration root, and the project (`.env`, `.env.local`,
  `.env.development`, `.env.development.local`), so a project could send
  a key and every prompt to a server of its choosing; the wrapper
  refuses `agent omp --cloud`. An oh-my-pi session with `--egress` in a
  project whose `.env` holds a provider key offers and reaches that
  provider, and `smoke --agent` cannot see that key.

`--cloud` is the only way a container receives a key. [`agent`](cli.md#agent)
lists what `--cloud` refuses.

## Skills

Skills follow the Agent Skills standard: a directory with a `SKILL.md` whose
frontmatter carries `name` and `description`. Agents read the description at
start and load the body only when a task matches. TokenCrate links two
sources into `~/.agents/skills` inside every agent container:

| Source | Location | Pinning |
| --- | --- | --- |
| Skill sets | `LLM_SKILLS_DIR/<set>/<skill>`, fetched by `skills fetch` | Repository, full commit, path, and tree digest in `config/skill-sets/<set>.toml` |
| Private skills | `LLM_LOCAL_SKILLS_DIR/<skill>` (default `local/skills`) | Yours; not committed |

`LLM_SKILL_SETS` names the fetched sets to load (default
`pocock-core,skill-crate`); `agent` refuses to start while a named set is
unknown, not fetched, or incomplete. Private skills are always loaded;
a skill of your own, such as notes on working with the local model, goes
below `LLM_LOCAL_SKILLS_DIR`. The entire fetched-skills directory is
mounted read-only, so unselected sets remain readable by agent tools.
Skill names must be unique across the loaded sources; the container
refuses to start otherwise. The `coding` agent set adds four pi-lens
skills from the image.

Included:

- `pocock-core`: seventeen engineering and productivity skills from
  `mattpocock/skills` (MIT), one `[[skill]]` table each in
  `config/skill-sets/pocock-core.toml`. A skill that another one calls by
  name is pinned with it; the manifest header lists the callers.
  `code-review`, `to-spec`, `triage`, and `wayfinder` send you to
  `setup-matt-pocock-skills` when no issue tracker is configured.
- `skill-crate`: one skill, `documentation-guidelines`, from
  [SkillCrate](https://github.com/angelo-lesniak/skill-crate) (MIT): the
  documentation policy and workflow that TokenCrate's own pages follow,
  usable in any project.

`skills status <set>` recomputes the digests of fetched skills; a
mismatch means the files on disk changed. `skills fetch` refuses a commit
whose digest differs from the manifest, so review an upstream change and
re-pin it. Read a skill before you pin it.

## Browser UIs

`bash bin/tokencrate ui <set>` starts a browser UI for pi; see
[`ui`](cli.md#ui) for commands and options. Each UI runs inside a pi
container and shares the project's pi transcripts with terminal sessions.
[Storage layout](configuration.md#storage-layout) lists the retained files.

| Set | What it is | Choose it when |
| --- | --- | --- |
| `pi-web` | [PI WEB](https://github.com/jmfederico/pi-web): a file browser, editor, diffs, terminal, and layout for small screens, with one project at a time | You want a terminal session in a browser tab |
| `paseo` | [Paseo](https://github.com/getpaseo/paseo): several agent sessions side by side, worktrees, and session import | You want several sessions at once or Paseo's workspace workflow |

Compared with `agent pi`:

- The UI has no password, and its terminal and file editor have the
  agent's access to the project.
  [Browser UIs](privacy.md#browser-uis) states who can reach it and
  [Forwarder](privacy.md#forwarder) what the forwarder protects.
- Extension dialogs (`confirm`, `select`, `input`) appear in the browser.
  Paseo runs pi in RPC mode, which is expected to show no project trust
  prompt, so project-local `.pi/` resources are expected not to load in
  Paseo sessions.
- Each keeps its own state under the agent home (`~/.pi-web`, `~/.paseo`
  in the container), which persists with the project's sessions.
- `ui <set> --egress` and `ui <set> --cloud` give the UI container what
  the flags give a terminal session, and `status` marks such a UI
  `egress` or `cloud`. [Cloud providers](#cloud-providers) says who can
  use the route and the keys while it runs.

**PI WEB** runs a session daemon and web server on the image's pi. The
launcher switches off PI WEB's session-spawning tools and environment
note (the `coding` set provides a subagent tool) and keeps its bundled
relay out of pi's package list.

**Paseo** runs pi as a subprocess in RPC mode. At first start the
launcher registers the project as a local workspace without a worktree.
When the project has no daemon configuration yet, it seeds one: `Pi` as
the only provider, the selected preset as the default model at thinking
level `xhigh`, and a saved agent profile named after the preset for
one-click starts. That configuration persists in the project's `.paseo`
directory and a later `--preset` does not replace it; the browser
remembers the last choice in its create-agent form. Paseo's web client
treats a new identity at a known address as an unreachable host. The
daemon identity (`daemon-keypair.json` and `server-id`) therefore lives
in each project's `.paseo` directory and is shared through the per-set
store ([Storage layout](configuration.md#storage-layout)): the launcher
copies the first daemon's identity into the store, and before a later
project's daemon starts it copies the store's identity into that
project's `.paseo`. [Troubleshooting](troubleshooting.md#paseo-asks-to-pair-again-or-shows-the-previous-project)
says how to get a fresh identity.

## Use four clients with one model

A terminal pi, a terminal oh-my-pi, PI WEB, and Paseo can work on one
project at once. Start each with the same `--preset` and `--dir`, and give
each client its own conversation: shared pi transcripts do not make
concurrent writes to one conversation safe. All four use the one
loaded preset; on a preset with one slot, their requests queue (the
[independent-client check](validation.md#status) is the run behind
this).

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
home last until the container stops. Stop the UI between tasks that must
not trust each other, and inspect the project and the retained UI
directories before trusting a later session.

Neither bash tool reads shell startup files from the home: pi's bash
tool passes `--noprofile --norc`, and `PI_BASH_NO_LOGIN=1` keeps
oh-my-pi's bash tool from starting a login shell.

The entrypoint writes the agent configuration into the fresh home at
every start, which fixes what a session can change. oh-my-pi rewrites
its `config.yml` in the home, so a model chosen with `/model` lasts
until the container stops. `PI_CONFIG_FILES` names the repository's
`config/agents/omp/config.yml` as an overlay above that home copy and
the project, so changing one of its keys in the session has no effect.
The `coding` set's subagents run on the session's own model and thinking
level. The repository's `config/agents/omp/AGENTS.md` is oh-my-pi's
global context, mounted read-only at `~/.omp/agent/AGENTS.md`. pi's
`packages` are exactly the image's local directories, and `PI_OFFLINE=1`
keeps pi from adding to them.
