# Configuration

`.env` holds settings for one machine and is not committed to Git.
[`.env.example`](../.env.example), copied by `init`, is the reference for
settings and defaults.

Precedence is the shell environment, then `.env`, then `.env.example`.
The wrapper reads `.env.example` at every start and refuses to run
without it. Omitting a key from `.env` uses the example's default; it
does not make the value empty. Change local settings in `.env` or the
shell. Editing `.env.example` changes the defaults for every checkout.

The wrapper reads `.env` as `KEY=VALUE` lines:

- a line that starts with `#` is a comment;
- matching quotes around a value are removed, and nothing is expanded or
  executed;
- a value with an unquoted `$`, a leading `~`, or a ` #` after it is
  refused with `values are used literally`: write the full path, or quote
  the value to use it literally;
- a key that `.env.example` does not list is reported as unknown; the
  wrapper and the Compose files ignore it, but it still reaches the
  engine's environment.

Paths given in `.env` without a leading `/` are resolved from the
repository root, whichever directory you run the wrapper from.
`pins.env` at the repository root holds the checked-in pins. Presets, model
sets, and skill sets under `config/` are reviewed data; see
[Models and presets](models.md) and [Coding agents and skills](agents.md).

Shell environment variables override `.env` for one command:

```bash
LLM_PORT=4307 bash bin/tokencrate up
```

The values in `pins.env` cannot be overridden this way; the wrapper removes
any shell or `.env` copy of a pin key from the environment it hands to
Compose, which reads the file itself.

The container engine must run on the same machine as the wrapper.
`CONTAINER_ENGINE` selects the client program; it does not override that
client's connection settings. Docker contexts, `DOCKER_HOST`,
`DOCKER_CONTEXT`, and Podman's connection settings still apply. Select a
local connection before running TokenCrate. Mounted paths and published
loopback ports belong to the engine's host; TokenCrate checks paths and
calls ports on the wrapper's host. Remote engines are unsupported.

## When a change takes effect

| Setting | Takes effect at |
| --- | --- |
| `LLM_GPU`, `GPU_DEVICE`, `NVIDIA_DRIVER_CAPABILITIES`, `LLM_TMPFS_SIZE`, `LLM_PIDS_LIMIT`, `STOP_GRACE_PERIOD`, `RESTART_POLICY`, `TOKENCRATE_IMAGE` | The next `up`, which recreates the llama container when its configuration changed |
| `COMPOSE_PROJECT_NAME` | The next command selects the new Compose project; it does not rename or stop the old stack. Run `down` before changing the name; otherwise the old stack remains and can occupy the ports the new one needs |
| `LLM_PORT` | The next `up` for the published port; `status`, `smoke`, and `bench` use the new value at once, so run `up` first |
| `LLM_DEFAULT_PRESET` | The next `up` for the preset the router loads at start; the next `agent`, `ui`, `smoke`, `bench`, or `doctor` for the preset they use without `--preset` |
| `LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `LLM_PROJECT_ROOTS`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `UMASK`, `LLM_AGENT_TMPFS_SIZE`, `TOKENCRATE_AGENT_PI_IMAGE`, `TOKENCRATE_AGENT_OMP_IMAGE` | The next `agent`, `ui`, or `smoke --agent` start; running sessions keep their values |
| `LLM_PI_WEB_PORT`, `LLM_PASEO_PORT` | The next start of the corresponding UI; other running UIs keep their configuration |
| `LLM_MODELS_DIR`, `LLM_AGENTS_DIR`, `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`, `CONTAINER_ENGINE` | The next command; `init` creates missing directories, and a running llama container keeps its mounts until `up` recreates it |
| `HF_TOKEN` | The next `models fetch`, `models draft`, or `up --model-set` |

The repository agent settings (`config/agents/pi/settings.json`,
`config/agents/omp/config.yml`) are not `.env` settings;
[Agent configuration](agents.md#agent-configuration) says which of their
defaults reach the next container.

## Built-in chat UI

[`config/llama/ui-config.json`](../config/llama/ui-config.json) sets defaults
for the built-in llama chat UI on `LLM_PORT`. The shipped file uses the
first non-empty message line for conversation titles without an extra
model request, excludes previous reasoning from later requests, and
disables the JavaScript sandbox tool.

llama-server reads the file at startup. After editing it, run `down`, then
`up` to apply the change; [`down`](cli.md#down) also stops running agent
and UI sessions. Reload the browser afterwards.

The defaults apply on the browser's first visit. Existing browsers retain
their saved preferences; change individual settings in the UI, or use
**Reset to default** in its settings to replace all preferences with the
current server defaults.

## Storage layout

| Default path | Contents |
| --- | --- |
| `data/models/<owner>/<repository>/<source>` | Model library (`LLM_MODELS_DIR`) |
| `data/agents/<agent>/<project>-<hash>/` | Retained state per agent and project; only the subdirectories listed below are mounted |
| `data/skills/<set>/<skill>/` | Fetched skill sets |
| `local/skills/<skill>/SKILL.md` | Private skills, read-only in agents |
| `build/models.ini` | Generated router presets for `llama-server --models-preset` |
| `build/agents/pi/models.json` | Generated pi model list |
| `build/agents/pi/<digest>/Dockerfile` | Generated pi image: base stage plus selected agent sets |
| `build/agents/pi/<digest>/{pi-packages.txt,AGENTS.md,pi-lens.json}` | Generated set configuration, copied into the image |
| `build/agents/omp/models.yml` | Generated oh-my-pi model list, stored as JSON text |
| `build/locks/<engine>-<project-hash>.lock` | Lock for model/UI startup and shutdown |
| `reports/` | Smoke and benchmark reports |

In the model library, `<source>` is the manifest's path: a filename, or
a quantization directory and filename for a split set.

UI launches resolve Compose settings into a private temporary directory
for the build and start. The files are removed when the command finishes;
later lifecycle commands discover containers by their labels. Do not
delete a lifecycle lock file while a TokenCrate command is running.

Each agent-set selection keeps its own `build/agents/pi/<digest>/`
directory and its own image, and neither is removed when the selection
stops being used. They are small next to the models, but they
accumulate: `rm -rf build/agents/pi/<digest>` and the engine's own
image removal are safe for a selection you no longer build, and the
next `agent` or `ui` renders what it needs again.

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
| pi UI only | `.pi-web`, `.paseo` | UI configuration, session state, and Paseo identity |

Each agent has three separate tmpfs mounts: the home and the two nested
directories above its transcript directory. Each is limited to 256 MiB,
allocated as used, with no combined cap. They are writable by the host
user and allow execution for toolchains. The agent's `/tmp` has its own
limit, `LLM_AGENT_TMPFS_SIZE`.

Other home contents, including downloaded tools, logs, caches, themes,
and keybindings, disappear when the container stops. Save work in the
project.

Paseo's shared identity store at `LLM_AGENTS_DIR/pi/paseo-identity/`
stays outside the container mounts. [Agent
configuration](agents.md#agent-configuration) says what a session can
change for a later one through the retained directories.

Retained mount sources and every ancestor must be real paths. The
wrapper refuses detected symbolic links before creating retained
directories. If `LLM_AGENTS_DIR` uses a link to another disk, set it to
the real directory instead. Inspect a linked retained path and move it
aside before retrying. Paseo identity copies also skip linked source or
destination paths, including the home and identity-store roots.

Deleting the per-project directory removes its saved sessions and UI
state permanently.

## Removing TokenCrate

Deleting `LLM_AGENTS_DIR` permanently removes saved agent sessions.
Keep any sessions and model files needed later before removing storage.

Run `down`, remove the `tokencrate/*` images listed under [Pins](#pins)
with `podman image rm` or `docker image rm`, and prune the build cache.
Then delete the storage directories listed in `.env` and the checkout.

## Pins

`pins.env` is a `KEY=VALUE` file at the repository root with exactly these
keys. Every value is plain, without quotes or whitespace; the wrapper
rejects anything else.

| Key | Meaning |
| --- | --- |
| `LLAMA_CPP_TAG` | Tag of the `ghcr.io/ggml-org/llama.cpp` server image; its `-b<N>` suffix names the llama.cpp build |
| `LLAMA_CPP_DIGEST` | sha256 of that tag's manifest list, as 64 hex characters |
| `PI_VERSION` | npm version of the pi coding agent |
| `OMP_VERSION` | npm version of oh-my-pi |
| `NODE_TAG` | Tag of the `node` base image of the pi agent and the UI forwarder |
| `NODE_DIGEST` | sha256 of that tag's manifest list |
| `BUN_TAG` | Tag of the `oven/bun` base image of the oh-my-pi agent |
| `BUN_DIGEST` | sha256 of that tag's manifest list |
| `CUDA_MIN_DRIVER_MAJOR` | Minimum NVIDIA driver major that `doctor` enforces |

Base images are pinned by tag and manifest digest. pi includes its
dependency tree in `npm-shrinkwrap.json`; oh-my-pi pins only its top-level
version because its `bun install` has no lockfile. Each agent set pins
dependencies through a lockfile, checksums, or a commit. Distribution
packages can change between rebuilds, so images are not bit-for-bit
reproducible.

Compose reads `pins.env` through `--env-file` and refuses to build if a
required pin is missing. Each base image is pulled as
`<name>:<tag>@sha256:<digest>`, so moving a tag cannot change the build's
base image. Builds also check that llama.cpp, Node, and Bun report the
versions named by their tags.

Image names are defined in `compose.yaml` and the Dockerfiles:

| Image | Tag |
| --- | --- |
| `tokencrate/llama` | `<LLAMA_CPP_TAG>` |
| `tokencrate/agent-pi` | `<PI_VERSION>-node<NODE_TAG>-<selection>` |
| `tokencrate/agent-omp` | `<OMP_VERSION>-bun<BUN_TAG>` |

`<selection>` is a digest of the selected [agent sets](agent-sets.md),
printed by `agent pi`. Different pins and selections can coexist in the
engine.

Use full release tags such as `26.9.0-bookworm-slim`. `pins check`
preserves the tag's version depth, so a moving major-only tag such as
`26-bookworm-slim` would never show a newer version.

### Upgrading

1. Find the new value and write it into `pins.env`:

   | Pin | How to find the value |
   | --- | --- |
   | `LLAMA_CPP_TAG`, `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG`, and image `*_DIGEST` keys | `bash bin/tokencrate pins check` prints eligible versions, release links, and `KEY=VALUE` lines to paste |
   | `CUDA_MIN_DRIVER_MAJOR`, the CUDA family in the llama.cpp tag | By hand, from the llama.cpp image tags and the NVIDIA driver requirements |
   | The versions an agent set pins | Its manifest and lockfile ([Upgrading a set](agent-sets.md#upgrading-a-set)), never `pins.env` |

   Update an image's tag and digest together; changing only the tag leaves
   the build on the old image. For llama.cpp, review the
   [release changes](https://github.com/ggml-org/llama.cpp/releases)
   between the two builds.

   If the build enables a waiting model set, write its first supported
   build number into `[requires] llama_build` and raise the pin to at
   least that build; see [Adding a model](models.md#adding-a-model).
2. Review the change with `git diff pins.env`.
3. Run the checks for the changed pin:

   | Changed pin | Run |
   | --- | --- |
   | Every pin | `bash tests/static.sh` and `python3 tests/integration.py` |
   | `LLAMA_CPP_TAG` | The [NVIDIA host baseline](validation.md#nvidia-host-baseline); the [router observations](validation.md#router-behavior-the-wrapper-relies-on); for a model set whose gate the new build opens, its presets' fallback ladder with `smoke` and `bench` |
   | `PI_VERSION`, `OMP_VERSION`, `NODE_TAG`, `BUN_TAG` | An agent session with a small task, then `bash bin/tokencrate smoke --agent pi` (with each `--sets` selection you use) and `bash bin/tokencrate smoke --agent omp` |

4. Record the result in the [validation records](validation.md#records)
   and refresh the measured columns of the
   [preset table](models.md#included-presets) for every preset the run
   re-measured.

## Updating the checkout

1. Run `git pull`, then `bash bin/tokencrate init` to create missing
   directories while keeping `.env`.
2. Review `.env.example` and copy any settings to override into `.env`.
   Omitted settings take the example's new defaults. Keys no longer
   listed in the example are reported as unknown at every start.
   Run `down` before changing the engine or `COMPOSE_PROJECT_NAME` so
   shutdown can still find the old stack.
3. Run `skills fetch` for the sets in `LLM_SKILL_SETS` to apply changed
   pins and remove obsolete skills.
4. Run `down`, then `up` to apply the new configuration.
