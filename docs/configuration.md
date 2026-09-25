# Configuration

`.env` holds settings for one machine and is not committed to Git.
[`.env.example`](../.env.example) is the reference for settings and
defaults; `init` writes a `.env` that holds only a comment, so a line is
copied into it to change a setting.

Precedence is the shell environment, then `.env`, then `.env.example`.
The wrapper refuses to run without `.env.example`. A key omitted from
`.env` takes the example's default, not an empty value. Change local
settings in `.env` or the shell; editing `.env.example` changes the
defaults for every checkout.

The wrapper reads `.env` as `KEY=VALUE` lines:

- a line that starts with `#` is a comment, and a byte-order mark at
  the start of the file is skipped;
- matching quotes around a value are removed, and nothing is expanded or
  executed;
- an unquoted value with a `$`, a leading `~`, or a ` #` is refused
  with `values are used literally`: write the full path, put the comment
  on its own line, or quote the value;
- a key set twice is refused;
- a key that `.env.example` does not list, even as a comment, is reported
  as ignored at every start; neither the wrapper, the Compose files, nor
  the engine client receives it.

Relative paths (`LLM_*_DIR` and `LLM_CLOUD_KEYS_FILE`) are resolved from
the repository root, whichever directory the wrapper runs from. Every
path is resolved to its real path, so a linked directory is used under
its real name. A storage directory must not be or contain the checkout,
whose `.env` would otherwise be mounted into every agent container. Presets, model
sets, and skill sets are files under `config/`, not settings; see
[Models and presets](models.md) and [Coding agents and skills](agents.md).
The comma-separated lists (`LLM_SKILL_SETS`, `LLM_AGENT_SETS`, and
`--sets`) ignore spaces around a name, empty entries, and repeats; a name
with characters other than letters, digits, `.`, `_`, and `-` is
refused. `COMPOSE_PROJECT_NAME` takes lowercase letters, digits, `-`,
and `_`, starting with a letter or digit, which is what Compose keeps of
a name; the wrapper refuses another name.

Shell environment variables override `.env` for one command:

```bash
LLM_PORT=4307 bash bin/tokencrate up
```

[Pins](#pins) cannot be overridden this way: the wrapper removes any shell
or `.env` copy of a pin key, and Compose reads `pins.env` itself.

The container engine must run on the same machine as the wrapper;
remote engines are unsupported. `CONTAINER_ENGINE` (`podman` or
`docker`) selects the client program, not its connection: Docker
contexts, `DOCKER_HOST`, `DOCKER_CONTEXT`, and Podman's connection
settings still apply, so select a local connection first.

## When a change takes effect

| Setting | Takes effect at |
| --- | --- |
| `LLM_GPU`, `GPU_DEVICE`, `LLM_TMPFS_SIZE`, `LLM_PIDS_LIMIT`, `RESTART_POLICY` | The next `up`, which recreates the llama container when its configuration changed |
| `COMPOSE_PROJECT_NAME` | The next command, which selects a new Compose project and leaves the old stack running on its ports. Run `down` before changing the name |
| `LLM_PORT` | The next `up` for the published port; `status`, `smoke`, and `bench` use the new value at once, so run `up` first |
| `LLM_DEFAULT_PRESET` | The next `up` for the preset the router loads at start; the next `agent`, `ui`, `smoke`, `bench`, or `doctor` for the preset they use without `--preset` |
| `LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `LLM_PROJECT_ROOTS`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `UMASK`, `LLM_AGENT_TMPFS_SIZE` | The next `agent`, `ui`, or `smoke --agent` start; running sessions keep their values |
| `LLM_CLOUD_KEYS_FILE` and the file's contents | The next `agent --cloud` or `ui --cloud` start; a running session or UI keeps the keys it was given |
| `LLM_UI_PORT_<SET>` (for example `LLM_UI_PORT_PI_WEB`) | The next start of that UI; other running UIs keep their configuration |
| `LLM_MODELS_DIR`, `LLM_AGENTS_DIR`, `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`, `CONTAINER_ENGINE` | The next command; `init` creates missing directories, and a running llama container keeps its mounts until `up` recreates it |
| `HF_TOKEN` | The next `models fetch`, `models draft`, or `up --model-set` |

The agent settings files (`config/agents/pi/settings.json`,
`config/agents/omp/config.yml`) are described in
[Agent configuration](agents.md#agent-configuration).

## Built-in chat UI

[`config/llama/ui-config.json`](../config/llama/ui-config.json) sets defaults
for the built-in llama chat UI on `LLM_PORT`. The shipped file titles
conversations with the first message line instead of a model request,
excludes previous reasoning from later requests, and disables the
JavaScript sandbox tool.

llama-server reads the file at startup. After editing it, run `down`, then
`up`; [`down`](cli.md#down) also stops running agent and UI sessions.

The defaults apply on a browser's first visit. A browser that has
visited keeps its saved preferences; use **Reset to default** in the UI
settings to replace them with the current server defaults.

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
| `build/agents/pi/<digest>/{pi-packages.txt,AGENTS.md,pi-lens.json,checks/}` | Generated set configuration and the sets' check scripts, copied into the image |
| `build/agents/omp/models.yml` | Generated oh-my-pi model list, stored as JSON text |
| `build/locks/<engine>-<project-hash>.lock` | Lock for model/UI startup and shutdown; two checkouts with one `COMPOSE_PROJECT_NAME` on one engine share the stack but not the lock |
| `local/cloud-keys.env` | The cloud keys file (`LLM_CLOUD_KEYS_FILE`), copied from `cloud-keys.env.example`; mounted only by `agent --cloud` and `ui --cloud` |
| `reports/` | Smoke and benchmark reports |

In the model library, `<source>` is the manifest's path: a filename, or
a quantization directory and filename for a split set.

Do not delete a lock file while a TokenCrate command is running.

Each agent-set selection keeps its own `build/agents/pi/<digest>/`
directory and image; the digest is of the rendered files, so a directory
that exists is complete and is not rewritten. Neither is removed
automatically. For a selection you do not use, deleting both is safe;
the next `agent` or `ui` renders what it needs again.

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
| pi UI only | The UI set's `state` directory: `.pi-web` or `.paseo` | UI configuration, session state, and Paseo identity |

The home and the two directories above the transcript directory
(`.pi` and `.pi/agent`, or `.omp` and `.omp/agent`) are separate tmpfs
mounts of 256 MiB each, allocated as used and allowing execution. The
agent's `/tmp` is limited by `LLM_AGENT_TMPFS_SIZE`. Everything else in
the home, including downloaded tools, logs, caches, themes, and
keybindings, disappears when the container stops. Save work in the
project.

Paseo's shared identity store, `LLM_AGENTS_DIR/pi/paseo-identity/`, is
not mounted into containers. [Agent
configuration](agents.md#agent-configuration) says what a session can
change for a later one through the retained directories.

Below `LLM_AGENTS_DIR`, which the wrapper resolves to its real path,
the retained mount sources and their ancestors must be real paths; the
wrapper refuses a symbolic link there, because a session writes its
home. Move a linked retained path aside after inspecting it, then retry.
Paseo identity copies skip linked paths. Each per-project directory is
readable by your user only.

Deleting the per-project directory removes its saved sessions and UI
state permanently.

## Removing TokenCrate

Run `down`, remove the `tokencrate/*` images listed under [Pins](#pins)
with `podman image rm` or `docker image rm`, and prune the build cache.
Copy any sessions under `LLM_AGENTS_DIR` and model files you still need,
then delete the storage directories named in `.env` and the checkout.

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

Image names are fixed in `compose.yaml`; two checkouts on one engine share
the images of equal pins and selections:

| Image | Tag |
| --- | --- |
| `tokencrate/llama` | `<LLAMA_CPP_TAG>` |
| `tokencrate/agent-pi` | `<PI_VERSION>-node<NODE_TAG>-<selection>` |
| `tokencrate/agent-omp` | `<OMP_VERSION>-bun<BUN_TAG>` |

`<selection>` is a digest of the selected [agent sets](agent-sets.md),
printed by `agent pi`. Images of different pins and selections coexist.

Use full release tags such as `26.9.0-bookworm-slim`: `pins check` keeps
the tag's version depth, so it never offers a newer version for a
major-only tag such as `26-bookworm-slim`.

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
   Omitted settings take the example's new defaults; keys the example
   does not list are reported as ignored.
3. Run `skills fetch` for the sets in `LLM_SKILL_SETS` to apply changed
   pins and remove obsolete skills.
4. Run `down`, then `up` to apply the new configuration.
