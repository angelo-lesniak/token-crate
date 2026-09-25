# CLI reference

Run commands as `bash bin/tokencrate <command> ...`; `bash bin/tokencrate
help` prints the usage. The syntax blocks below show every command and
flag. Use the wrapper rather than direct Compose calls, which skip
TokenCrate's checks and generated configuration.

General rules:

- Commands run on the host as your user. The
  [README](../README.md#start-here) lists host tools and engine requirements;
  [Privacy and containment](privacy.md#what-leaves-the-machine) lists
  commands that use the network.
- A setting comes from the shell environment, then `.env`, then the
  defaults in `.env.example`; the pins in `pins.env` cannot be
  overridden (see
  [Configuration](configuration.md)).
- `CONTAINER_ENGINE=docker` or `CONTAINER_ENGINE=podman` overrides engine
  detection.
- `LLM_GPU=false` starts llama-server without a GPU device and skips the
  GPU checks of `doctor`. It is for CPU-only checks; real models are far
  too slow without a GPU.
- `--preset <id>` selects a preset instead of `LLM_DEFAULT_PRESET`.
  `doctor`, `smoke`, `agent`, and `ui` accept it once; `bench` accepts it
  several times, but not the same preset twice.
- Every other flag that takes a value (`--timeout`, `--iterations`,
  `--sets`, `--port`, `--dir`, `--agent`) is refused when given twice.
  `--model-set` can repeat.

## init

```text
bin/tokencrate init
```

Creates the host storage directories and, if missing, a `.env` that
holds only a comment: every setting and its default stays in
`.env.example`, and a line is copied into `.env` to change it
([Configuration](configuration.md)). An existing `.env` keeps its
content; every run sets its mode to `0600`. The cloud keys file is not
created; [Cloud providers](agents.md#cloud-providers) says how to copy
it from `cloud-keys.env.example`. Containers run as the user
who runs the wrapper; `.env` cannot change that identity.

## doctor

```text
bin/tokencrate doctor [--preset id]
```

Checks the host and prints one line per check; `up` runs the same checks
before it downloads anything and stops on a `[fail]` line. The checks
cover:

- Git and Linux on x86-64, as warnings: starting the stack needs neither;
- the container engine and its Compose provider against the engine
  requirements in the [README](../README.md#start-here); Podman older
  than 6, the oldest tested version, is a warning;
- with `LLM_GPU=true`: the NVIDIA driver against the pinned minimum, GPU
  memory against the preset's `[requires]` (a warning when less is free
  right now), the CDI device list, and under Podman that the CDI spec
  names the running driver;
- system memory against the preset's `[requires] ram_gib` when the preset
  declares one (a preset that keeps expert weights in system memory);
  the comparison allows 5 percent of slack for what the firmware and
  kernel reserve (a 96 GB machine reports about 93 GiB);
- a `[warn]` line when the preset's model set needs a newer llama.cpp
  build than `pins.env` pins
  ([the build requirement](models.md#adding-a-model)); `up` leaves such a
  preset out of the router;
- the storage directories;
- as warnings, a name in `LLM_AGENT_SETS` or `LLM_SKILL_SETS` that no
  agent set or skill set has (the first `agent` start would refuse it);
- whether `LLM_PORT` can be bound on loopback (a failure unless
  TokenCrate's own llama container publishes that port).

The preset's requirements come from its file under `config/presets/`;
nothing needs to be rendered or downloaded first. An unknown preset is a
warning, and only the host checks run; `smoke`, `bench`, `agent`, and
`ui` refuse an unknown preset and one the pinned build cannot load, and
`up` refuses such a default preset.

```bash
bash bin/tokencrate doctor --preset qwen3.8-27b-q4-mtp
```

## up

```text
bin/tokencrate up [--model-set name]... [--timeout seconds]
```

In order:

1. Runs the checks of [`doctor`](#doctor) for `LLM_DEFAULT_PRESET` and
   stops on a `[fail]` line.
2. Downloads and verifies only the model sets named with `--model-set`.
3. Renders every preset whose files are present into `build/`: the
   router preset file `models.ini` and the agent model lists. A preset
   whose model set needs a newer llama.cpp build is listed as waiting and
   left out.
4. Builds the runtime image when it is missing or its inputs changed.
5. Starts the llama container in the background. Compose recreates it
   when the rendered preset file or service configuration changed;
   otherwise it keeps the running container.
6. Waits for the router to answer `GET /models` on the published port.
   A new router loads `LLM_DEFAULT_PRESET` at start, and `up` waits for
   that preset to be ready. On an existing router, `up` requests a
   load if nothing is loaded. If another preset already occupies the
   slot, `up` reports it and leaves the default to load on first request.
   With no default set, the router's response is enough.
7. Prints the address of the API and the built-in chat UI.

`up` refuses before downloading if `LLM_DEFAULT_PRESET` names an unknown
preset or one that needs a newer llama.cpp build. Plain `up` downloads
no model files. After rendering, the default preset's files must be
present or startup fails.

On Docker, `up` also refuses before downloading if the `agents` or `ui`
network has a gateway address. `down` removes those networks; see
[Privacy and containment](privacy.md#defaults-and-their-limits) for the
reason. During startup, `up` fails if the container exits or disappears,
the model server exits while loading (reported as `unloaded`), or the
timeout expires.

| Flag | Meaning |
| --- | --- |
| `--model-set <name>` | Download and verify this model set first; repeat for more sets |
| `--timeout <seconds>` | Maximum time to wait for readiness, as a positive integer; default `600` |

```bash
bash bin/tokencrate up --model-set qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate up
```

## down

```text
bin/tokencrate down
```

Stops and removes the model, terminal-agent containers, all browser UIs
([`ui`](#ui)), and the Compose networks. This ends active agent sessions.
Images and host data are kept; see the
[storage layout](configuration.md#storage-layout). `down` finds the
containers and networks by the Compose project labels of the selected
engine, so it works even when the pins are invalid; a network of the
project's name made without those labels is left alone, and `up` says so.

## status

```text
bin/tokencrate status
```

Shows all containers labelled for the selected Compose project. Each
`UI <set>:` line adds the forwarder's state, published loopback address,
and mounted project, so a UI reassigned to another project is visible,
and ends with `egress` or `cloud` for a UI started with that flag.
When llama runs, it also shows one line per rendered preset with the
state the router reports on `GET /models`: `unloaded`, `loading`,
`loaded`, or `sleeping`. `status` works without valid pins or rendered
files and does not wait for a start or stop in progress.

## logs

```text
bin/tokencrate logs
```

Follows the llama container logs, including the output of every model
server the router starts (prefixed with the server's port), until
interrupted.

## smoke

```text
bin/tokencrate smoke [--preset id] [--basic]
bin/tokencrate smoke --agent <pi|omp> [--preset id] [--sets names (pi only)] [--egress]
```

**Model checks:** without `--agent`, runs API probes against the stack for one
preset (`LLM_DEFAULT_PRESET` unless `--preset` is given). The probes run
on the host against the published loopback port and write their report
to `reports/smoke-<timestamp>.md`. The first chat completion loads the
preset and unloads the previous one; loading a large model can take
minutes. The checks cover:

- the model listing;
- a chat completion and a system message in the middle of a
  conversation; both ask for the preset's lowest reasoning effort and
  judge the answer, not the reasoning;
- that both completions end on their own (`finish_reason` is `stop`; a
  reply that exhausts its token budget ends with `length`, which can
  indicate a reasoning loop);
- a streamed tool call;
- a chat-template render that must keep that later system message, only
  for a model set that ships the patched template;
- a render that must change with the reasoning effort (the first two
  efforts the preset declares; a preset with fewer than two passes it
  with `nothing to compare`);
- tokenization.

`--basic` skips the reply-termination and streamed-tool-call checks,
which need a capable model, so that a tiny model can still check the
transport and template.

**Agent checks:** with `--agent`, `smoke` starts the container the way `agent`
does, against a scratch project and agent home in a temporary directory,
and checks its network containment from inside the container. The preset
must be rendered as loadable, and every set in `LLM_SKILL_SETS` must be
fetched. The check proves that the routes are absent, not what the
reachable model does. It reports:

- one network interface, no route through a gateway (IPv4 or IPv6), and
  no name resolution;
- no active UI service or forwarder resolves by name or accepts a
  connection at its current container address;
- on Docker no gateway address at all on the agents network
  (`compose.docker.yaml` creates it without one; any gateway fails the
  check); on Podman a gateway that answers only from the user's network
  namespace; an `--egress` session is not on that network, and the report
  says so instead of probing;
- the container user, a writable agent home, the mounted project
  directory, and the skills linked at `~/.agents/skills`;
- a read-only root filesystem;
- for pi, that the selected [agent sets](agent-sets.md) are seeded:
  packages, tools note, and subagent definitions. `--sets` overrides
  `LLM_AGENT_SETS` for the check.

For pi, each selected set's `check` lines
([Agent sets](agent-sets.md#writing-a-set)) also run as the container user
without network access, one report line per set: the shipped sets build
the xunit template from the image's NuGet cache, answer a DAP request
over stdio, answer `--version` for Chromium and Paseo, resolve PI WEB's
pi and node-pty, and build and run an Odin program.

The report ends with the container's mount table and the number of
failures.

`--egress` runs the same check with the route out that `agent --egress`
and `agent --cloud` add: the session is then on the default network
instead of the `agents` network. A default route is required; whether
the internet answers is your network's business and is not probed. A
browser UI that answers is a failure. A UI started with `--egress` or
`--cloud` is the exception: its name and its default-network address
are reported as `[info] ... that UI was started with --egress or
--cloud`, and an offline check still fails on it. The set checks, which
prove a set with no route out, are skipped. The check never carries a
provider key.

Without a running browser UI the report prints `[warn] no browser UI
running; UI isolation not tested`; run the check while a UI runs to test
that boundary.

With `--agent` and neither `--preset` nor `LLM_DEFAULT_PRESET`, the
command fails (`smoke --agent needs --preset or LLM_DEFAULT_PRESET`);
`--basic` is not valid with `--agent`. `--sets` requires `--agent pi`, and
`--egress` requires `--agent`.

```bash
bash bin/tokencrate smoke
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate smoke --agent pi --egress
```

## bench

```text
bin/tokencrate bench [--preset id]... [--iterations n] [--long]
```

Measures prompt-processing and generation tokens per second per preset from
llama-server's `timings`, averaged over `--iterations` requests (default 3).
`--long` adds a run with a long prompt; the report's prompt-tokens column
shows the measured length of every run. Without `--preset`, the default
preset is measured. The report is written to
`reports/bench-<timestamp>.md`. Presets are loaded in turn, so measuring
several presets swaps models.

```bash
bash bin/tokencrate bench --preset qwen3.8-27b-q4 --preset qwen3.8-27b-q4-mtp
```

## agent

```text
bin/tokencrate agent <pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [--cloud] [-- args]
```

Opens a coding agent in a container with the project directory
mounted read-write at the same absolute path it has on the host. For pi,
the image uses `LLM_AGENT_SETS` unless `--sets` overrides it for this
session. The value is a comma-separated list (spaces, empty entries, and
repeats are ignored); an empty string selects plain pi. `--sets` applies
only to pi; oh-my-pi rejects it. A selection without an image is built
before startup; see
[Agent sets](agent-sets.md). The project defaults to the current directory;
`--dir` selects another. The project directory must:

- lie below your home directory, or below a directory listed in
  `LLM_PROJECT_ROOTS` (absolute paths separated by colons);
- not be the root or home directory itself;
- not be, contain, or lie inside the TokenCrate checkout or a storage
  directory named in `.env` (`LLM_MODELS_DIR`, `LLM_AGENTS_DIR`,
  `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`), because the next start
  trusts what those contain;
- carry no space, comma, colon, dollar sign, or quote in its path, which
  a Compose mount cannot express.

Git metadata must fit inside the project mount. A linked worktree,
submodule, or repository subdirectory that depends on metadata outside
that mount is refused before startup. Use the repository root or a
standalone clone; the wrapper does not mount another checkout's Git
directory implicitly.

The agent talks to the running llama service over an internal network with
no internet access. `--egress` puts the session on the default network
instead, for example to install packages, and the wrapper prints a
warning. `--egress` and `--cloud` are the only ways to give a session
internet access; no setting remembers either.

`--cloud` (pi only) also mounts the cloud keys file that
`LLM_CLOUD_KEYS_FILE` names, read-only, into this one session, and
implies `--egress`. The container's entrypoint exports the file's lines.
The wrapper never reads the file, and no key appears on the engine
command line or in a Compose file. The wrapper warns that the
conversation and file contents sent to a cloud model leave this machine
and that every process in the session can read the keys. `--cloud`
refuses to start when:

- the agent is oh-my-pi: it reads provider settings, base URLs included,
  from the project's `.env` files, so a project could send a key to a
  server of its choosing; pi reads no such file;
- the file does not exist or is not a regular file;
- the file lies inside the project, a storage directory, `config/`, or
  `local/agent-sets/`, which containers or image builds read;
- its path carries `:` or `,`, which a mount cannot express.

The container refuses to start when a line of the file is not
`NAME=value`, has a carriage return, or sets a variable the entrypoint
owns (`PATH`, `HOME`, `TOKENCRATE_*`, and the like). `--egress` alone
hands the container no key. See [Cloud
providers](agents.md#cloud-providers) for the file's grammar and what a
cloud session offers.

The session container is named `tokencrate-agent-<id>`. A hang-up or
`SIGTERM` to the wrapper stops it; a `SIGKILL` leaves it running with the
keys it exported, until `down` or the agent exits.

The llama service must be running and the preset rendered as loadable
(`up` does both). The running router must match the rendered
configuration; after a failed `up`, resolve its error and run `up`
again. On Docker the session refuses, as `up` does,
while the `agents` or `ui` network keeps a gateway address
([Privacy and containment](privacy.md#defaults-and-their-limits)).
Every skill set named in `LLM_SKILL_SETS` must be known, fetched, and
complete; otherwise the command refuses to start.

Arguments after `--` are passed to the agent binary. A print-only
command run under `timeout` from a terminal needs `</dev/null`;
otherwise Compose attaches the terminal and the process stops on
`SIGTTOU` before the container starts. See [Coding agents and
skills](agents.md) for what the container can and cannot touch.

Run the wrapper from the checkout and name the project with `--dir`:

```bash
bash bin/tokencrate agent pi --dir ~/src/my-project
bash bin/tokencrate agent omp --preset qwen3.8-27b-q4-mtp --egress --dir ~/src/my-project
bash bin/tokencrate agent pi --sets coding,debug,odin --dir ~/src/my-project
bash bin/tokencrate agent pi --cloud --dir ~/src/my-project
bash bin/tokencrate agent pi --dir ~/src/my-project -- -p "Summarize this repository"
```

## agent-sets

```text
bin/tokencrate agent-sets list
```

Prints every agent set under `config/agent-sets` and `local/agent-sets`
with its description, marks sets with a `[ui]` manifest as `[ui]`, and
prints the current `LLM_AGENT_SETS`. See
[Agent sets](agent-sets.md) for what a set is and how to write one.

## ui

```text
bin/tokencrate ui <set> [--preset id] [--sets names] [--dir path] [--port port] [--egress] [--cloud]
bin/tokencrate ui stop [<set>]
bin/tokencrate ui logs [<set>]
```

`ui <set>` starts one instance of that UI set in the background and
prints its loopback address. PI WEB defaults to `http://127.0.0.1:4224/`
and Paseo to `http://127.0.0.1:4250/`. The set must declare a `[ui]`
manifest, including a custom set under `local/agent-sets`.

`--port` selects a host port from `1` to `65535` for this launch only.
Precedence is `--port`, then the set's `LLM_UI_PORT_<SET>` setting in
`.env` (the set name in upper case, any other character as `_`:
`LLM_UI_PORT_PI_WEB`, `LLM_UI_PORT_PASEO`), then the `host_port` its
manifest declares. A set without `host_port` needs one of the other two.
An occupied port is accepted only when
the named UI's own forwarder holds it; another UI or program causes a refusal
before the existing UI changes. `--port` does not change the
container-internal ports, which come from the manifest.

Rootless Podman cannot publish a port below
`net.ipv4.ip_unprivileged_port_start` (normally `1024`), and the
wrapper's bind check runs as your user. Keep the default high ports, or
have the host administrator lower that setting; this lets every
unprivileged process bind ports from the new threshold upward. See
[Podman's rootless port limits](https://github.com/podman-container-tools/podman/blob/main/rootless.md).

The image contains `LLM_AGENT_SETS`, or `--sets` for this launch, plus the
named UI set. The first build downloads its npm packages (about 0.5 GB
for `paseo`). The project directory, `--preset`, and pre-flight checks
are those of [`agent`](#agent). A launch does not remember options
from an earlier launch. Only the named UI is replaced; the other UI and
llama keep running unchanged.

The UI container is named `tokencrate-ui-<set>` and its forwarder
`tokencrate-ui-forward-<set>`, so two Compose projects on one engine
cannot run the same UI set at once. The second launch fails on the
name; `ui stop <set>` in the other checkout frees it. The command
waits up to 90 seconds for both containers to run and the forwarder to
answer. A failed build leaves the previous UI intact. A
failed start or readiness check leaves that UI in place for
`ui logs <set>`, a retry, or `ui stop <set>`; it does not stop the other
UI. Readiness is an HTTP check, not proof of a completed assistant
response. Commands that start or stop containers in the same Compose
project wait for each other.

`ui stop <set>` removes that UI and its forwarder, and fails when the
set has no container. Plain `ui stop` removes every UI and says so when
none is running. Neither removes llama, the networks, or saved sessions
and UI state. `ui logs <set>` follows the UI daemon output until
interrupted; plain `ui logs` selects the only UI present and asks for a
set name when there are several. Both find stopped or failed containers
without the launch options or a custom manifest.

A terminal session and both UIs can use one project, with separate
conversations and live settings. See [the four-client
workflow](agents.md#use-four-clients-with-one-model).

`--egress` gives the UI container a route out: it joins the default
network in addition to the `ui` network, where its forwarder reaches it,
and the wrapper prints the warning of [`agent --egress`](#agent).
`--cloud` also mounts the cloud keys file into the UI container,
read-only, with the refusals and the warning of `agent --cloud`, and
implies `--egress`; every UI is pi. The forwarder gets neither. The UI
holds the route and the keys until `ui stop <set>`, `down`, or a launch
of the set without the flag. [Cloud providers](agents.md#cloud-providers)
says who can use them meanwhile and
[Privacy and containment](privacy.md#defaults-and-their-limits) states
the network boundaries.

```bash
bash bin/tokencrate ui pi-web --dir ~/src/my-project
bash bin/tokencrate ui paseo --dir ~/src/my-project
bash bin/tokencrate ui paseo --cloud --dir ~/src/my-project
bash bin/tokencrate ui logs pi-web
bash bin/tokencrate ui stop paseo
bash bin/tokencrate ui stop
```

## models

```text
bin/tokencrate models list
bin/tokencrate models fetch <set> [<set> ...] | all
bin/tokencrate models status <set> [<set> ...] | all
bin/tokencrate models draft hf:<owner>/<repo>:<file.gguf>
```

`fetch` prints the licenses and model cards, then downloads and verifies
every pending file of the named sets into `LLM_MODELS_DIR`; an interrupted
download resumes on the next run. Several sets may be named in one command;
shared files are downloaded once, and `all` selects every shipped set,
including sets whose architecture the pinned build cannot load yet;
`presets list` shows which presets wait (see [Adding a
model](models.md#adding-a-model)).
`status` runs the same verification without network access or file
changes. `draft` prints a manifest for one Hugging Face GGUF file, pinned to
the repository's current commit, with `TODO` markers for the fields the Hub
does not provide. For a split GGUF, name the first shard (`00001`); the
draft includes the remaining shards.

```bash
bash bin/tokencrate models fetch qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate models status all
bash bin/tokencrate models draft hf:unsloth/Qwen3.8-27B-GGUF:Qwen3.8-27B-UD-Q6_K_XL.gguf   # prints a manifest draft
```

See [Models and presets](models.md) for licenses, token handling, the
download and storage mechanics, and the manifest format.

## presets

```text
bin/tokencrate presets list
bin/tokencrate presets render
```

`list` prints each preset's model set, memory requirements, description,
and any newer llama.cpp build it needs; see the
[build gate](models.md#adding-a-model).

`render` validates every preset and model-set manifest. It writes nothing
and does not inspect downloaded model files. Each preset is listed as
`valid` or as waiting for a newer llama.cpp build. Run it after editing
a preset. [`up`](#up) writes the rendered files
([storage layout](configuration.md#storage-layout)).

```bash
bash bin/tokencrate presets render
```

## skills

```text
bin/tokencrate skills list
bin/tokencrate skills fetch <set> [<set> ...] | all
bin/tokencrate skills status <set> [<set> ...] | all
```

`fetch` clones each pinned commit, copies the skill directory, verifies its
tree digest and `SKILL.md` frontmatter, and publishes it below
`LLM_SKILLS_DIR/<set>/<skill>`. After a set succeeds, `fetch` removes
plain, non-hidden skill directories the set no longer declares, so keep
private skills in `LLM_LOCAL_SKILLS_DIR`. `status` recomputes the
digests of fetched skills without network access. Agents load the sets
named in `LLM_SKILL_SETS`.

```bash
bash bin/tokencrate skills fetch pocock-core skill-crate
bash bin/tokencrate skills status all
```

## pins

```text
bin/tokencrate pins
bin/tokencrate pins check [component|all]
```

With no arguments, prints the non-comment lines of `pins.env`.

`pins check` prints the current pin and the latest eligible upstream
version for one component or all of them (the default). For llama-cpp,
it also links the releases between the two builds and lists model sets
waiting for a newer build.

When an update is available, the output ends with a `Paste into pins.env:`
block of `KEY=VALUE` lines. An image pin has two lines: its tag and
manifest digest. The command writes nothing; paste the lines into
`pins.env` and review with `git diff pins.env`. If a source cannot be
resolved or its latest eligible version is older than the current pin,
the command fails without printing results.

| Component | Key | Selection policy |
| --- | --- | --- |
| `llama-cpp` | `LLAMA_CPP_TAG` | Newest GHCR tag of the `ghcr.io/ggml-org/llama.cpp` server image in the current CUDA family (`server-<family>-b<N>`); the build number names the llama.cpp release |
| `pi` | `PI_VERSION` | npm's stable `latest` version of `@earendil-works/pi-coding-agent` |
| `omp` | `OMP_VERSION` | npm's stable `latest` version of `@oh-my-pi/pi-coding-agent` |
| `node` | `NODE_TAG` | Latest stable `-bookworm-slim` tag of the `node` image on Docker Hub with the existing version granularity, among even (long-term-support) majors |
| `bun` | `BUN_TAG` | Latest stable `-slim` tag of the `oven/bun` image on Docker Hub with the existing version granularity |

`CUDA_MIN_DRIVER_MAJOR` and the CUDA family of the llama.cpp tag stay
manual, and an [agent set](agent-sets.md) pins its own versions, which
`pins check` does not cover. See
[Upgrading](configuration.md#upgrading) for the checks that follow an
upgrade.

```bash
bash bin/tokencrate pins
bash bin/tokencrate pins check llama-cpp
```
