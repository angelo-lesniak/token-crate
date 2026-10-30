# Configuration

`.env` holds the settings of one machine; this page says when a change
takes effect and where TokenCrate keeps models, sessions, generated
files, and pins.

`.env` is not committed to Git. [`.env.example`](../.env.example) is the
reference for settings and defaults. `init` writes a `.env` that holds
only a comment; copy a line from `.env.example` into it to change a
setting. The file must be owned by your user and readable by your user
only (mode `0600`). The wrapper refuses it otherwise and names the
`chmod` to run.

Precedence is the shell environment, then `.env`, then `.env.example`;
a key omitted from `.env` takes the example's default. A shell variable
overrides `.env` for one command.
[Pins](#pins) cannot be overridden this way: the wrapper removes every
pin key from the shell and `.env`, and Compose reads `pins.env` itself.

The wrapper reads `.env` as `KEY=VALUE` lines and refuses what it cannot
use literally: a value with an unquoted `$`, a leading `~`, or a ` #`,
and a key set twice. Matching quotes around a value are removed and
nothing is expanded. A key that `.env.example` does not list is reported
as ignored at every start and has no effect. `LLM_GPU` and
`LLM_DASHBOARD` take `1/true/yes/on` or `0/false/no/off`, ignoring case. The
comma-separated lists (`LLM_SKILL_SETS`, `LLM_AGENT_SETS`, and `--sets`)
ignore spaces, empty entries, and repeats. `COMPOSE_PROJECT_NAME` takes
lowercase letters, digits, `-`, and `_`, starting with a letter or
digit. An empty `LLM_*_DIR` or `LLM_CLOUD_KEYS_FILE` is refused with the
key and the default (`LLM_MODELS_DIR must not be empty; omit the line to
take the default (./data/models)`); an empty required Compose setting is
refused at the Compose call, which names the variable; `LLM_SKILL_SETS`
may be empty.

Relative paths (`LLM_*_DIR` and `LLM_CLOUD_KEYS_FILE`) are resolved from
the repository root, whichever directory the wrapper runs from, and every
path is resolved to its real path. A storage directory must not be or
contain the checkout, whose `.env` would otherwise be mounted into every
agent container.

Containers run as the user who runs the wrapper; `.env` cannot change
that identity. The container engine must run on the same machine as the
wrapper. `CONTAINER_ENGINE` (`podman` or `docker`) selects the client
program, not its connection, so select a local Docker context or Podman
connection first.

## When a change takes effect

| Setting | Takes effect at |
| --- | --- |
| `LLM_GPU`, `GPU_DEVICE`, `LLM_TMPFS_SIZE`, `LLM_PIDS_LIMIT`, `RESTART_POLICY` | The next `up`, which recreates the llama container when its configuration changed |
| `LLM_DASHBOARD`, `LLM_DASHBOARD_PORT` | The next `up`, which starts the [dashboard](#dashboard) when the setting is on; `up` with the setting off leaves a running dashboard in place, and `down` removes it |
| `COMPOSE_PROJECT_NAME` | The next command, which selects a new Compose project and leaves the old stack running on its ports. Run `down` before changing the name |
| `LLM_PORT` | The next `up` for the published port; `status`, `smoke`, and `bench` use the new value at once, so run `up` first |
| `LLM_DEFAULT_PRESET` | The next `up` for the preset the router loads at start; the next `agent`, `ui`, `smoke`, `bench`, or `doctor` for the preset they use without `--preset` |
| `LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `LLM_PROJECT_ROOTS`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `UMASK`, `LLM_AGENT_TMPFS_SIZE` | The next `agent`, `ui`, or `smoke --agent` start; running sessions keep their values |
| `LLM_CLOUD_KEYS_FILE` and the file's contents | The next `agent --cloud` or `ui --cloud` start; a running session or UI keeps the keys it was given |
| `LLM_MODELS_DIR`, `LLM_AGENTS_DIR`, `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`, `CONTAINER_ENGINE` | The next command; `init` creates missing directories, and a running llama container keeps its mounts until `up` recreates it. While a stack runs, commands use the engine recorded in `build/stack.json`, and a disagreeing `CONTAINER_ENGINE` is refused until `down` |
| `HF_TOKEN` | The next `models fetch`, `models draft`, or `up --model-sets` |

[Agent configuration](agents.md#agent-configuration) describes the agent
settings files (`config/agents/pi/settings.json`,
`config/agents/omp/config.yml`).

## Built-in chat UI

[`config/llama/ui-config.json`](../config/llama/ui-config.json) sets defaults
for the built-in llama chat UI on `LLM_PORT`. The shipped file titles
conversations with the first message line instead of a model request,
excludes previous reasoning from later requests, and disables the
JavaScript sandbox tool.

llama-server reads the file at startup. After editing it, run `down`, then
`up`; [`down`](cli.md#down) also stops running agent and UI sessions. The
defaults apply to a browser's first visit; a browser keeps the
preferences it saved.

## Dashboard

With `LLM_DASHBOARD=true`, [`up`](cli.md#up) starts the Compose profile
`dashboard` beside the model: three more containers (four with
`LLM_GPU=true`), with Grafana on the port `LLM_DASHBOARD_PORT` names.
That port must differ from `LLM_PORT`.

| Container | Image | Role | Port or interval |
| --- | --- | --- | --- |
| `llama-exporter` | The pinned Node image, running `services/dashboard/llama-exporter.js` | Asks the router which preset is loaded and reads that preset's counters (`GET /metrics?model=`) only after two consecutive polls reported it loaded, because a request for another preset would load it. It is also Grafana's only way to the store: a query gate that forwards the Prometheus read paths and refuses everything else | Polls every 5 seconds |
| `victoriametrics` | VictoriaMetrics | Scrapes the exporter (`config/dashboard/scrape.yaml`) and keeps the samples for 90 days under `data/dashboard/victoria/` | Scrapes every 15 seconds |
| `grafana` | Grafana | Serves the datasource and the dashboard "TokenCrate model server" provisioned from `config/dashboard/grafana/`: the model server's requests, rates, slots, and loaded preset, and the GPU's utilization, memory, power, and temperature | `http://127.0.0.1:4211/` (`LLM_DASHBOARD_PORT`) |
| `gpu-exporter` (with `LLM_GPU=true`) | NVIDIA's dcgm-exporter, on the CDI device | Exports the GPU's numbers; without it the GPU panels show no data | Scraped like the llama exporter |

Grafana has no password: anyone on this host can read the dashboards
and query the samples as an anonymous viewer. Viewers cannot change
anything: the login form and basic authentication are off, and the
query gate refuses writes and deletions. A dashboard is a JSON file
under `config/dashboard/grafana/dashboards/`; after editing or adding
one, run `down`, then `up`. Grafana's own database and logs live on a
tmpfs; the samples are the only thing kept. [Privacy and
containment](privacy.md#telemetry-switches) lists Grafana's outbound
features and the switches that turn them off.

`down` removes the containers with the rest; `status` lists them. The
live panel of [`stats --serve`](cli.md#stats) shows the same counters
for the last ten minutes without the dashboard profile.

## Storage layout

| Default path | Contents |
| --- | --- |
| `data/models/<owner>/<repository>/<source>` | Model library (`LLM_MODELS_DIR`); `<source>` is the manifest's path: a filename, or a quantization directory and filename for a split set |
| `data/models/.../<file>.tokencrate-verified` | The record of a verified model file (checksum, size, modification time) that `models status`, `models fetch`, and `up --model-sets` trust while the file is unchanged |
| `data/agents/<agent>/<project>-<hash>/` | Retained state per agent and project; only the subdirectories listed below are mounted |
| `data/agents/pi/<set>-state/` | Per-UI-set state shared by all projects (see below) |
| `data/skills/<set>/<skill>/` | Fetched skill sets |
| `local/skills/<skill>/SKILL.md` | Private skills, read-only in agents |
| `build/models.ini` | Generated router presets for `llama-server --models-preset` |
| `build/agents/pi/models.json` | Generated pi model list; the wrapper reads it back for the loadable presets and their slots |
| `build/agents/pi/<digest>/Dockerfile` | Generated pi image: base stage plus selected agent sets |
| `build/agents/pi/<digest>/{pi-packages.txt,AGENTS.md,pi-lens.json,checks/}` | Generated set configuration and the sets' check scripts, copied into the image |
| `build/agents/omp/models.yml` | Generated oh-my-pi model list, stored as JSON text |
| `build/locks/<project>.lock` | Lock for the steps that change the stack; holds `<pid> <command>` of the holder, which a waiting command names |
| `build/stack.json` | The engine and project of the running stack, written by `up` and removed by `down` |
| `local/cloud-keys.env` | The cloud keys file (`LLM_CLOUD_KEYS_FILE`), copied from `cloud-keys.env.example`; mounted only by `agent --cloud` and `ui --cloud` |
| `reports/` | Smoke, bench, and stats reports; `bench` writes its measurements as JSON and `stats` its page as HTML next to the Markdown |
| `data/dashboard/victoria/` | The [dashboard](#dashboard)'s samples, 90 days of the model server's counters |

Do not delete a lock file while a TokenCrate command is running.

Each agent-set selection keeps its own `build/agents/pi/<digest>/`
directory and image; neither is removed automatically, and deleting
both for a selection you do not use is safe. A `build/agents/pi/<digest>/`
whose `Dockerfile` is missing refuses the next start (`has no
Dockerfile; remove the directory and retry`).

`data/`, `local/`, `build/`, and `reports/` are ignored by Git. To keep the
model library on another disk, point `LLM_MODELS_DIR` at it; symbolic links
below `LLM_MODELS_DIR` are followed only when they stay below that
directory.

The container home is tmpfs. These subdirectories of the per-project
host directory are bound read-write at the same relative paths below
`/home/agent`:

| Agent/service | Retained subdirectories | Purpose |
| --- | --- | --- |
| pi terminal and UI | `.pi/agent/sessions` | Transcripts shared by terminal and browser sessions |
| oh-my-pi | `.omp/agent/sessions`, `.omp/agent/blobs` | Transcripts and their externalized images |
| oh-my-pi | `.omp/agent/terminal-sessions`, `.omp/agent/custom-session-files` | Continue-selection breadcrumbs and references to custom session files for blob cleanup |
| pi UI only | The UI set's `state` directory: `.pi-web` or `.paseo` | UI configuration and session state |

The home and the two directories above the transcript directory
(`.pi` and `.pi/agent`, or `.omp` and `.omp/agent`) are separate tmpfs
mounts of 256 MiB each, allowing execution. The agent's `/tmp` is
limited by `LLM_AGENT_TMPFS_SIZE`. Everything else in the home
disappears when the container stops; save work in the project.

Each UI set also has one directory shared by all projects,
`LLM_AGENTS_DIR/pi/<set>-state/`, mounted read-write at
`/run/tokencrate/ui-state` in that set's UI container; [Browser
UIs](agents.md#browser-uis) says how Paseo shares its daemon identity
through it. [Agent configuration](agents.md#agent-configuration) says
what a session can change for a later one through the retained
directories.

Below `LLM_AGENTS_DIR` the retained mount sources and their ancestors
must be real paths: the wrapper refuses a symbolic link there, because a
session writes its home. Each per-project directory is readable by your
user only. Deleting it removes its saved sessions and UI state
permanently.

## Removing TokenCrate

Run `down`, remove the `tokencrate/*` images listed under [Pins](#pins)
with `podman image rm` or `docker image rm`, and prune the build cache.
Copy any sessions under `LLM_AGENTS_DIR` and model files you still need,
then delete the storage directories named in `.env` and the checkout.

## Pins

`pins.env` is a `KEY=VALUE` file at the repository root with these keys,
named as [Adding a pin](../CONTRIBUTING.md#adding-a-pin) says. Every
value is plain, without quotes or whitespace; the wrapper rejects
anything else.

| Key | Meaning |
| --- | --- |
| `LLAMA_CPP_TAG` | Tag of the `ghcr.io/ggml-org/llama.cpp` server image; its `-b<N>` suffix names the llama.cpp build |
| `LLAMA_CPP_DIGEST` | sha256 of that tag's manifest list, as 64 hex characters |
| `PI_VERSION` | npm version of the pi coding agent |
| `OMP_VERSION` | npm version of oh-my-pi |
| `NODE_TAG` | Tag of the `node` base image of the pi agent, the UI forwarder, and the dashboard's llama exporter |
| `NODE_DIGEST` | sha256 of that tag's manifest list |
| `BUN_TAG` | Tag of the `oven/bun` base image of the oh-my-pi agent |
| `BUN_DIGEST` | sha256 of that tag's manifest list |
| `VICTORIAMETRICS_TAG` | Tag of the `victoriametrics/victoria-metrics` image of the [dashboard](#dashboard) |
| `VICTORIAMETRICS_DIGEST` | sha256 of that tag's manifest list |
| `GRAFANA_TAG` | Tag of the `grafana/grafana` image of the dashboard |
| `GRAFANA_DIGEST` | sha256 of that tag's manifest list |
| `DCGM_EXPORTER_TAG` | Tag of the `nvcr.io/nvidia/k8s/dcgm-exporter` image of the dashboard's GPU exporter (a DCGM version paired with the exporter's) |
| `DCGM_EXPORTER_DIGEST` | sha256 of that tag's manifest list |
| `CUDA_MIN_DRIVER_MAJOR` | Minimum NVIDIA driver major that `doctor` enforces |

Compose reads `pins.env` through `--env-file` and refuses to build if a
pin is missing. Each base image is pulled as `<name>:<tag>@sha256:<digest>`,
so moving a tag cannot change the build's base image, and the builds
check that llama.cpp, Node, and Bun report the versions their tags name.
pi's dependency tree is locked by its `npm-shrinkwrap.json`; oh-my-pi's
is not (`bun install` has no lockfile), and distribution packages can
change between rebuilds, so images are not bit-for-bit reproducible.

Image names are fixed in `compose.yaml`; two checkouts on one engine share
the images of equal pins and selections:

| Image | Tag |
| --- | --- |
| `tokencrate/llama` | `<LLAMA_CPP_TAG>` |
| `tokencrate/agent-pi` | `<PI_VERSION>-node<NODE_TAG>-<selection>` |
| `tokencrate/agent-omp` | `<OMP_VERSION>-bun<BUN_TAG>` |

`<selection>` is a digest of the selected [agent sets](agent-sets.md),
printed by `agent pi`. Images of different pins and selections coexist.

### Upgrading

1. Find the new value and write it into `pins.env`:

   | Pin | How to find the value |
   | --- | --- |
   | `LLAMA_CPP_TAG`, `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG`, `VICTORIAMETRICS_TAG`, `GRAFANA_TAG`, and their `*_DIGEST` keys | [`pins check`](cli.md#pins) prints the eligible versions, release links, and `KEY=VALUE` lines to paste |
   | Every pin `pins check` prints as `no resolver`, and a new CUDA family or VictoriaMetrics/Grafana major | By hand ([`pins`](cli.md#pins) lists them) |
   | The versions an agent set pins | Its manifest and lockfile ([Upgrading a set](agent-sets.md#upgrading-a-set)), never `pins.env` |

   Update an image's tag and digest together; changing only the tag leaves
   the build on the old image. For llama.cpp, review the
   [release changes](https://github.com/ggml-org/llama.cpp/releases)
   between the two builds. If the build enables a waiting model set,
   follow [Adding a model](models.md#adding-a-model) for its gate.
2. Run the checks for the changed pin:

   | Changed pin | Run |
   | --- | --- |
   | Every pin | `bash tests/static.sh` and `python3 tests/integration.py` |
   | `LLAMA_CPP_TAG` | The [NVIDIA host baseline](validation.md#nvidia-host-baseline); the [router observations](../CONTRIBUTING.md#router-behavior-the-wrapper-relies-on); for a model set whose gate the new build opens, its presets' fallback ladder with `smoke` and `bench` |
   | `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG` | An agent session with a small task, then `bash bin/tokencrate smoke --agent pi` (with each `--sets` selection you use) and `bash bin/tokencrate smoke --agent omp` |

3. Record the run as [Validation](validation.md#recording-a-run)
   describes, with the measured columns of the
   [preset table](models.md#included-presets) for every preset the run
   re-measured.

## Updating the checkout

1. Run `git pull`, then `bash bin/tokencrate init` to create missing
   directories while keeping `.env`. `git diff ORIG_HEAD -- pins.env
   .env.example config/skill-sets` shows whether a pin, a default, or a
   skill set moved.
2. Copy any new setting you want to override from `.env.example` into
   `.env`.
3. When a skill set moved, run `skills fetch` for the sets in
   `LLM_SKILL_SETS` to apply changed pins and remove obsolete skills.
4. Run `down`, then `up` to apply the new configuration; `up` rebuilds
   the image when its inputs changed.
