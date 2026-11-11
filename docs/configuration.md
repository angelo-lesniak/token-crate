# Configuration

`.env` holds the settings of one machine, and
[`.env.example`](../.env.example) is the reference for every setting and
its default.

## The `.env` file

`.env` is not committed to Git. `init` writes a `.env` that holds only a
comment; copy a line from `.env.example` into it to change a setting.
The file must be owned by your user and readable by your user only
(mode `0600`); the wrapper refuses it otherwise and names the fix.

Precedence is the shell environment, then `.env`, then `.env.example`,
so a shell variable overrides `.env` for one command. [Pins](#pins)
cannot be overridden this way.

The wrapper reads `KEY=VALUE` lines and uses each value literally:
matching quotes are removed and nothing is expanded. It refuses a value
it cannot use literally (an unquoted `$` or ` #`, or a leading `~`), a
key set twice, and an empty `LLM_*_DIR` or `LLM_CLOUD_KEYS_FILE`; each
refusal names the key and the rule. A key that `.env.example` does not
list is reported as ignored at every start. The comma-separated lists
(`LLM_SKILL_SETS`, `LLM_AGENT_SETS`, and `--sets`) ignore spaces, empty
entries, and repeats.

A storage directory must not be or contain the checkout, whose `.env`
would otherwise be mounted into every agent container. The container
engine must run on the same machine as the wrapper: `CONTAINER_ENGINE`
(`podman` or `docker`) selects the client program, not its connection,
so select a local Docker context or Podman connection first.

## When a change takes effect

| Setting | Takes effect at |
| --- | --- |
| `LLM_GPU`, `GPU_DEVICE`, `LLM_TMPFS_SIZE`, `LLM_PIDS_LIMIT`, `RESTART_POLICY` | The next `up`, which recreates the llama container |
| `LLM_DASHBOARD`, `LLM_DASHBOARD_PORT` | The next `up`; `up` with the dashboard off leaves a running one in place, and `down` removes it |
| `COMPOSE_PROJECT_NAME` | The next command, which addresses a new project and leaves the old stack running on its ports; run `down` before changing it |
| `LLM_PORT` | The next `up`; `status`, `smoke`, and `bench` use the new value at once, so run `up` first |
| `LLM_DEFAULT_PRESET` | The next `up` for the preset loaded at start; the next command for the commands that use it without `--preset` |
| `LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `LLM_PROJECT_ROOTS`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `UMASK`, `LLM_AGENT_TMPFS_SIZE`, and the [agent settings files](agents.md#agent-configuration) | The next `agent`, `ui`, or `smoke --agent` start; running sessions keep their values |
| `LLM_CLOUD_KEYS_FILE` and the file's contents | The next `agent --cloud` or `ui --cloud` start |
| `LLM_MODELS_DIR`, `LLM_AGENTS_DIR`, `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`, `CONTAINER_ENGINE` | The next command; a running llama container keeps its mounts until `up` recreates it. While a stack runs, a `CONTAINER_ENGINE` other than the one in `build/stack.json` is refused until `down` |
| `HF_TOKEN` | The next `models fetch`, `models draft`, or `up --model-sets` |

## Ports

Every port below listens on `127.0.0.1` only; [Privacy and
containment](privacy.md#ports) states what that exposes and what it
does not.

| Port | Serves | Changed by | Default |
| --- | --- | --- | --- |
| API | The model server's API and the built-in chat UI | `LLM_PORT` | `4207` |
| Dashboard | Grafana, with `LLM_DASHBOARD=true` | `LLM_DASHBOARD_PORT`, which must differ from `LLM_PORT` | `4211` |
| Browser UI | One UI set's forwarder | `--port` of [`ui <set>`](cli.md#ui), else the manifest's `host_port` | `4224` for `pi-web`, `4250` for `paseo` |
| Stats page | `stats --serve`, a host process | `--port` of [`stats`](cli.md#stats) | `4210` |

## Built-in chat UI

[`config/llama/ui-config.json`](../config/llama/ui-config.json) sets the
defaults of the built-in llama chat UI on `LLM_PORT` for a browser's
first visit; a browser keeps the preferences it saved. llama-server
reads the file at startup, so after editing it run `down`, then `up`;
[`down`](cli.md#down) also stops running agent and UI sessions.

## Dashboard

With `LLM_DASHBOARD=true`, [`up`](cli.md#up) starts the Compose profile
`dashboard` beside the model server: Grafana on `LLM_DASHBOARD_PORT`,
VictoriaMetrics, which keeps the samples under `data/dashboard/victoria/`
for 90 days, an exporter for the model server's counters, and, with
`LLM_GPU=true`, NVIDIA's dcgm-exporter, without which the GPU panels show
no data. The exporter reads the counters only of a preset the router
reported loaded on two consecutive polls, because a request for another
preset would load it. It is also Grafana's only way to the samples: a
query gate that forwards the Prometheus read paths and refuses
everything else.

Grafana has no password: anyone on this host can read the dashboards
and query the samples as an anonymous viewer. Viewers cannot change
anything: the login form and basic authentication are off, and the
query gate refuses writes and deletions. A dashboard is a JSON file
under `config/dashboard/grafana/dashboards/`; after editing or adding
one, run `down`, then `up`. [Privacy and
containment](privacy.md#telemetry-switches) lists what TokenCrate
switches off in Grafana. Without the profile, the
live panel of [`stats --serve`](cli.md#stats) shows the same counters
for the last ten minutes.

## Storage layout

| Default path | Contents |
| --- | --- |
| `data/models/<owner>/<repository>/<source>` | Model library (`LLM_MODELS_DIR`); `<source>` is the manifest's path of the file |
| `data/models/.../<file>.tokencrate-verified` | Verification stamp of a model file ([`models`](cli.md#models) says when it is trusted) |
| `data/agents/<agent>/<project>-<hash>/` | Retained state per agent and project; only the subdirectories listed below are mounted |
| `data/agents/pi/<set>-state/` | Per-UI-set state shared by all projects (see below) |
| `data/skills/<set>/<skill>/` | Fetched skill sets |
| `local/skills/<skill>/SKILL.md` | Private skills, read-only in agents |
| `local/cloud-keys.env` | The cloud keys file (`LLM_CLOUD_KEYS_FILE`); mounted only by `agent --cloud` and `ui --cloud` |
| `build/models.ini`, `build/agents/` | Generated router presets, agent model lists, and one `build/agents/pi/<digest>/` directory per agent-set selection |
| `build/locks/` | Locks for the steps that change the stack; never delete them ([CLI reference](cli.md) says why) |
| `build/stack.json` | The engine and project of the running stack, written by `up` and removed by `down` |
| `reports/` | Smoke, bench, and stats reports |
| `data/dashboard/victoria/` | The [dashboard](#dashboard)'s samples |

`data/`, `local/`, `build/`, and `reports/` are ignored by Git. To keep
the model library on another disk, point `LLM_MODELS_DIR` at it;
symbolic links below `LLM_MODELS_DIR` are followed only when they stay
below that directory.

Neither a `build/agents/pi/<digest>/` directory nor its image is removed
automatically; deleting both for a selection you do not use is safe. A
directory whose `Dockerfile` is missing refuses the next start (`has no
Dockerfile; remove the directory and retry`).

The container home is tmpfs. These subdirectories of the per-project
host directory are bound read-write at the same relative paths below
`/home/agent`:

| Agent | Retained subdirectories | Purpose |
| --- | --- | --- |
| pi, terminal and UI | `.pi/agent/sessions` | Transcripts shared by terminal and browser sessions |
| oh-my-pi | `.omp/agent/sessions`, `.omp/agent/blobs`, `.omp/agent/terminal-sessions`, `.omp/agent/custom-session-files` | Transcripts, their images, and the state of session selection |
| pi UI only | The UI set's `state` directory: `.pi-web` or `.paseo` | UI configuration and session state |

The home and the two directories above the transcript directory
(`.pi` and `.pi/agent`, or `.omp` and `.omp/agent`) are separate
executable tmpfs mounts of 256 MiB each; `/tmp` is limited by
`LLM_AGENT_TMPFS_SIZE`. Everything else in the home disappears when the
container stops; save work in the project.

Each UI set also has `LLM_AGENTS_DIR/pi/<set>-state/`, shared by all
projects and mounted at `/run/tokencrate/ui-state` in that set's UI
container ([Browser UIs](agents.md#browser-uis) says what Paseo keeps
there). [Agent configuration](agents.md#agent-configuration) says what a
session can change for a later one through the retained directories.

Below `LLM_AGENTS_DIR` the retained mount sources and their ancestors
must be real paths: the wrapper refuses a symbolic link there, because a
session writes its home. Each per-project directory is readable by your
user only. Deleting it removes its saved sessions and UI state
permanently.

## Remove TokenCrate

1. Run `bash bin/tokencrate down`.
2. Remove the images TokenCrate built, which Podman names
   `localhost/tokencrate/...` and Docker `tokencrate/...`:

   ```bash
   podman images --filter reference='localhost/tokencrate/*'   # list them on Podman
   docker images --filter reference='tokencrate/*'             # list them on Docker
   podman image rm <image> ...                                 # or docker image rm
   ```

3. Remove the build cache with `podman image prune` (after step 2, it
   removes the intermediate images of TokenCrate's builds) or
   `docker builder prune --all`. Both also remove what other projects
   left.
4. Copy any sessions under `LLM_AGENTS_DIR` and model files you still
   need, then delete the storage directories and the cloud keys file
   that `.env` names, and the checkout.

The base images `pins.env` pins and the CDI specification
`/etc/cdi/nvidia.yaml` from [Start here](../README.md#start-here)
can remain. Other projects can use them, so remove them only when nothing
else does.

## Pins

[`pins.env`](../pins.env) holds the tag and digest of every image, the
version of each agent, and `CUDA_MIN_DRIVER_MAJOR`, the minimum NVIDIA
driver major `doctor` enforces; [Add a
pin](../CONTRIBUTING.md#add-a-pin) gives the key and value rules.

Pins cannot be overridden: the wrapper drops every pin key from the
shell environment and `.env`, and Compose reads `pins.env` itself,
refusing to build when a pin is missing. Each base image is pulled by
tag and digest, and the builds check that llama.cpp, Node, and Bun
report the versions their tags name. Images are still not bit-for-bit
reproducible: pi's dependency tree is locked by its
`npm-shrinkwrap.json`, but oh-my-pi's has no lockfile, and distribution
packages change between rebuilds.

The `tokencrate/*` image tags carry the pins and, for pi, the `<digest>`
of the agent-set selection, which pairs the image with its
`build/agents/pi/<digest>/` directory. Checkouts on one engine share the
images of equal pins and selections.

### Upgrade a pin

1. Find the new value and write it into `pins.env`:

   | Pin | How to find the value |
   | --- | --- |
   | `LLAMA_CPP_TAG`, `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG`, `VICTORIAMETRICS_TAG`, `GRAFANA_TAG`, and their `*_DIGEST` keys | [`pins check`](cli.md#pins) prints the eligible versions, release links, and `KEY=VALUE` lines to paste |
   | Every pin `pins check` prints as `no resolver`, and a new CUDA family or VictoriaMetrics/Grafana major | By hand: the image's repository is in its `image:` line in `compose.yaml` or its `FROM` line in the Dockerfile, and the `*_DIGEST` is the registry's manifest digest for the new tag, without `sha256:` |
   | The versions an agent set pins | Its manifest and lockfile ([Upgrade a set](agent-sets.md#upgrade-a-set)), never `pins.env` |

   Update an image's tag and digest together; changing only the tag leaves
   the build on the old image. For llama.cpp, review the
   [release changes](https://github.com/ggml-org/llama.cpp/releases)
   between the two builds, and if the new build loads a model set that
   waits behind the [build gate](models.md#build-gate), write the build
   number into that set.
2. Run the checks for the changed pin:

   | Changed pin | Run |
   | --- | --- |
   | Every pin | `bash tests/static.sh` and `python3 tests/integration.py` |
   | `LLAMA_CPP_TAG` | The [NVIDIA host baseline](validation.md#nvidia-host-baseline); the [router observations](../CONTRIBUTING.md#router-behavior-the-wrapper-relies-on); for a model set whose gate the new build opens, its presets' fallback ladder with `smoke` and `bench` |
   | `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG` | An agent session with a small task, then `bash bin/tokencrate smoke --agent pi` (with each `--sets` selection you use) and `bash bin/tokencrate smoke --agent omp`; for `NODE_TAG`, which also runs the UI forwarder and the dashboard's exporter, also one `ui <set>` launch and, if you use it, the dashboard |
   | `VICTORIAMETRICS_TAG`, `GRAFANA_TAG`, `DCGM_EXPORTER_TAG` | `up` with `LLM_DASHBOARD=true`, then open Grafana |

3. Record the run as [Validation](validation.md#record-a-run)
   describes.

## Update the checkout

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
