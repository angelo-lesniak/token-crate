# CLI reference

Run commands as `bash bin/tokencrate <command> ...`; `bash bin/tokencrate
help` prints the usage. The syntax blocks below show every command and
flag. Use the wrapper rather than direct Compose calls, which skip
TokenCrate's checks and generated configuration. "The model server" on
this page is llama-server in router mode, which routes each request to a
preset by its `model` field.

General rules:

- Commands run on the host as your user. The
  [README](../README.md#start-here) lists host tools and engine
  requirements. [Privacy and containment](privacy.md#what-leaves-the-machine)
  lists commands that use the network.
- While a stack runs, every command uses the engine `up` recorded
  ([When a change takes effect](configuration.md#when-a-change-takes-effect)).
- `--preset <id>` selects a preset instead of `LLM_DEFAULT_PRESET` for
  `doctor`, `smoke`, `agent`, and `ui`; `bench --presets <ids>` takes a
  list. `smoke`, `bench`, `agent`, and `ui` refuse when neither names a
  preset.
- Every flag that takes a value is refused when given twice. A list
  (`--sets`, `--model-sets`, `--presets`) is comma-separated and parsed
  like the list settings in [The `.env` file](configuration.md#the-env-file).
- The commands that change the stack (`up`, `down`, `ui`, and
  `smoke --agent`) take one lock per checkout and Compose project,
  `build/locks/<COMPOSE_PROJECT_NAME>.lock`; a waiting command names the
  holder. A terminal `agent` session never takes it: its pre-flight
  checks refuse on their own when the stack moves. Do not delete
  `build/locks/`: the lock is an `flock` on the open file, so a command
  that starts after the deletion takes a new lock and changes the stack
  while the holder still does.

## init

```text
bin/tokencrate init
```

Creates the host storage directories and, if missing, a `.env` that
holds only a comment, with mode `0600`. An existing `.env` keeps its
content and must already pass the owner and mode rule in [The `.env`
file](configuration.md#the-env-file). The cloud keys file is not created
([Cloud providers](agents.md#cloud-providers)).

## doctor

```text
bin/tokencrate doctor [--preset id]
```

Checks the host and prints one `[ok]`, `[warn]`, or `[fail]` line per
check. `up` runs the same checks before it downloads anything and stops
on a `[fail]` line; a `[warn]` line is something `up` can start without,
such as a preset waiting behind the [build gate](models.md#build-gate).
The preset checks compare the host with the `[requires]` of the
[preset](models.md) file, so nothing needs to be rendered or downloaded
first; with no preset selected they are skipped. System memory is
compared with `ram_gib` with 5 percent of slack for what the firmware
and kernel reserve (a 96 GB machine reports about 93 GiB).

```bash
bash bin/tokencrate doctor --preset qwen3.8-27b-q4-mtp
```

## up

```text
bin/tokencrate up [--model-sets names] [--timeout seconds]
```

In order:

1. Runs the checks of [`doctor`](#doctor) for `LLM_DEFAULT_PRESET` and
   stops on a `[fail]` line.
2. Refuses, before downloading, an existing `agents`, `ui`, or
   `dashboard` network that breaks the [internal-network
   rule](privacy.md#internal-networks).
3. Downloads and verifies only the model sets named with `--model-sets`.
   Plain `up` downloads nothing, and the default preset's files must be
   present or startup fails.
4. Renders every preset whose files are present into `build/`: the
   router preset file `models.ini` and the agent model lists. A preset
   behind the [build gate](models.md#build-gate) is left out.
5. Builds the runtime image when it is missing or its inputs changed.
6. Under the lock, starts the llama container and records the engine in
   `build/stack.json`. Compose recreates the container only when the
   rendered preset file or service configuration changed.
7. Waits for the router to answer and for `LLM_DEFAULT_PRESET` to be
   ready. On a model server that was already running, if another preset
   occupies the slot, `up` reports it and leaves the default to load on
   first request. The wait fails if the container exits or disappears (a
   `down` meanwhile, since the build and the wait run without the lock),
   the preset's llama-server process exits while loading, or the timeout
   expires.
8. With `LLM_DASHBOARD=true`, starts the
   [dashboard](configuration.md#dashboard) profile (pulling its pinned
   images on the first start).

| Flag | Meaning |
| --- | --- |
| `--model-sets <names>` | Download and verify these model sets first |
| `--timeout <seconds>` | Maximum time to wait for readiness; default `600`. On expiry the container keeps loading; `status` shows the preset once it is loaded, and a second `up` keeps the container |

```bash
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate up
```

## down

```text
bin/tokencrate down
```

Stops and removes the model server, terminal-agent containers, all
browser UIs, the [dashboard](configuration.md#dashboard), and the
Compose networks, which ends active agent sessions. Images and host data
are kept. `down` finds its containers and networks by the Compose
project labels, so it works even when the pins are invalid. A network of
the project's name made without those labels is left alone, and `up`
refuses until it is removed by hand.

## status

```text
bin/tokencrate status
```

Shows all containers of the selected Compose project, each browser UI
with its forwarder, address, mounted project, and any `egress` or
`cloud` flag, and, while the model server runs, the state the router
reports for each rendered preset. It works without valid pins or
rendered files and does not wait for a start or stop in progress.

## logs

```text
bin/tokencrate logs
```

Follows the llama container logs, including the output of every
llama-server process the router starts for a preset (prefixed with the
process's port), until interrupted.

## smoke

```text
bin/tokencrate smoke [--preset id] [--basic]
bin/tokencrate smoke --agent <pi|omp> [--preset id] [--sets names (pi only)] [--egress]
```

**Model checks:** without `--agent`, runs the API probes of
[`probe.py`](../tokencrate/probe.py) for one preset against the published
port, prints the report, and writes it to `reports/smoke-<timestamp>.md`.
The first chat completion loads the preset, which can take minutes for a
large model. `--basic` skips the checks that need a capable model, so
that a tiny model can still check the transport and template.

**Agent checks:** with `--agent`, `smoke` starts the container the way
[`agent`](#agent) does, against a scratch project and home in a
temporary directory, and needs what `agent` needs. It checks from inside
the container that there is no route out, no name resolution, no
reachable browser UI, and on Docker no gateway address, plus the user,
home, project, skills, and read-only root filesystem
([`agent-check.sh`](../services/agents/agent-check.sh) defines the
checks). It saves no report, and it proves that the routes are absent,
not what the reachable model does. For pi, `--sets` overrides
`LLM_AGENT_SETS`, and each selected set's `check` lines ([Agent
sets](agent-sets.md#write-a-set)) add one line per set. UI isolation is
tested only while a browser UI runs.

`--egress` runs the same check with the route out that `agent --egress`
and `agent --cloud` add: a default route is required, whether the
internet answers is not probed, a reachable browser UI is still a
failure, and the set checks are skipped. The check never carries a
provider key.

```bash
bash bin/tokencrate smoke
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate smoke --agent pi --egress
```

## bench

```text
bin/tokencrate bench [--presets ids] [--iterations n] [--long]
```

Measures prompt-processing and generation tokens per second per preset
from llama-server's `timings`, averaged over `--iterations` requests
(default 3); `--long` adds a run with a long prompt. Without
`--presets`, the default preset is measured. Presets are loaded in turn,
so measuring several presets swaps models. The report is printed and
written to `reports/bench-<timestamp>.md`, with the per-iteration
measurements in `reports/bench-<timestamp>.json`.

```bash
bash bin/tokencrate bench --presets qwen3.8-27b-q4,qwen3.8-27b-q4-mtp
```

## stats

```text
bin/tokencrate stats [--since when] [--agent <pi|omp>]
bin/tokencrate stats --serve [--port port] [--since when] [--agent <pi|omp>]
```

Summarizes the retained transcripts below `LLM_AGENTS_DIR` ([storage
layout](configuration.md#storage-layout)), so it works with the stack
down; each transcript with at least one model answer counts as one
session. `smoke --agent` adds nothing, and deleting a project's
directories removes it from the report. The command reads usage numbers
and metadata only, never message content; the report carries no
conversation text, session names, or project paths
([Privacy](privacy.md#what-leaves-the-machine)).

The report is printed and written to `reports/stats-<timestamp>.md` and,
as a self-contained page that loads nothing external,
`reports/stats-<timestamp>.html`. Its first table judges every preset
[`up`](#up) rendered against the context of every request in the
report, so it also judges a preset you have not run yet; the report's
Definitions list defines each measure. pi records request timings only
when the [`metrics` agent set](agent-sets.md#shipped-sets), part of the
default selection, is loaded.

`--since <when>` keeps the sessions whose last message is at or after a
duration back from now (`30m`, `12h`, `7d`, `2w`) or an ISO date or
date-time in local time (`2026-09-20`, `2026-09-20T10:00`); a session
that spans the cutoff counts whole. `--agent` keeps one agent's
sessions. With `--serve`, the cutoff is fixed when the server starts.

`--serve` serves the page at `http://127.0.0.1:4210/` (`--port` selects
another [port](configuration.md#ports)), re-reading the transcripts
every 60 seconds, and saves nothing. The served page adds a verdict on
the loaded preset and a live panel of the model server's requests and
token rates over the last ten minutes, with GPU tiles when `LLM_GPU` is
true and `nvidia-smi` is on the host's `PATH`. The rates follow counters
that llama.cpp advances when a request completes, so a long answer
shows as one burst at its end. The panel polls only while a page is
open, with the [dashboard](configuration.md#dashboard)'s two-poll rule,
so a poll never loads a preset. The server binds loopback only and
answers only requests whose `Host` header names its own address;
anything local that can open the port can read the report's numbers and
the live samples. It runs in the foreground until Ctrl-C;
[`down`](#down) does not stop it.

```bash
bash bin/tokencrate stats --serve
bash bin/tokencrate stats --since 7d --agent pi
```

## agent

```text
bin/tokencrate agent <pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [--cloud] [-- args]
```

Opens a coding agent in a container with the project directory mounted
read-write at the same absolute path it has on the host. For pi,
`--sets` overrides `LLM_AGENT_SETS` for this session (an empty string
selects plain pi); each combination of sets has its own image, built
before its first session ([Agent sets](agent-sets.md)). oh-my-pi rejects
the flag. The project defaults to the current directory; `--dir` selects
another. After symbolic links are resolved, the project directory must:

- lie below your home directory or an `LLM_PROJECT_ROOTS` entry, without
  being that directory itself or the root;
- not be, contain, or lie inside the TokenCrate checkout, a storage
  directory, or the cloud keys file, because the next start trusts what
  those contain;
- carry no space, comma, colon, dollar sign, or quote, which a Compose
  mount cannot express.

The container sees only the project directory, so Git works there only
when the repository's `.git` data lies inside it. A start is refused on
a `.git` file or symbolic link (a linked worktree or a submodule), a
worktree's `commondir`, or a repository above the project, below your
home directory or its `LLM_PROJECT_ROOTS` entry; choose the repository
root or a standalone clone.

`--cloud` (pi only) also mounts the cloud keys file that
`LLM_CLOUD_KEYS_FILE` names, read-only, into this one session, and
implies `--egress`. The wrapper warns that the conversation and file
contents sent to a cloud model leave this machine and that every process
in the session can read the keys. `--cloud` refuses a file that is
missing, not a regular file, not private to your user, carries `:` or
`,` in its path, or lies inside the project, a storage directory,
`config/`, `local/agent-sets/`, `services/`, or `build/agents/pi/`, which
containers mount or image builds read. The entrypoint then refuses a
line it cannot use, naming it; [Cloud
providers](agents.md#cloud-providers) states the line rule. `--egress`
alone hands the container no key.

The session container is named `tokencrate-agent-<id>`. A hang-up or
`SIGTERM` to the wrapper stops it; a `SIGKILL` leaves it running with the
keys it exported, until `down` or the agent exits.

The command refuses to start unless:

- the last `up` added the preset to the router, which it does when the
  preset's model files are downloaded and the pinned llama.cpp build can
  load them;
- the model server runs the configuration the last `up` rendered; after
  a failed `up`, fix its error and run `up` again;
- every skill set in `LLM_SKILL_SETS` is known, fetched, and complete;
- the `agents`, `ui`, and `dashboard` networks satisfy the [internal-network
  rule](privacy.md#internal-networks).

Arguments after `--` are passed to the agent binary; with pi's `-p`, the
agent answers one prompt and exits. Compose attaches your terminal only
when both standard streams are a terminal and the wrapper runs in the
foreground; otherwise (under `timeout`, in a pipeline, from cron) a
terminal it cannot read from is replaced by `/dev/null`, so a scripted
call needs no redirection and a pipe on standard input still reaches the
agent. [Coding agents and skills](agents.md) says what the container can
and cannot touch.

```bash
bash bin/tokencrate agent pi --dir ~/src/my-project
bash bin/tokencrate agent omp --preset qwen3.8-27b-q4-mtp --egress --dir ~/src/my-project
bash bin/tokencrate agent pi --dir ~/src/my-project -- -p "Summarize this repository"
```

## agent-sets

```text
bin/tokencrate agent-sets list
```

Prints every agent set under `config/agent-sets` and `local/agent-sets`
with its description, marks the UI sets, and prints the current
`LLM_AGENT_SETS`. [Agent sets](agent-sets.md) says what a set is and how
to write one.

## ui

```text
bin/tokencrate ui <set> [--preset id] [--sets names] [--dir path] [--port port] [--egress] [--cloud]
bin/tokencrate ui stop [<set>]
bin/tokencrate ui logs [<set>]
```

`ui <set>` starts one instance of that UI set in the background and
prints its loopback address. The set must declare a `[ui]` manifest. The
image contains `LLM_AGENT_SETS`, or `--sets` for this launch, plus the
named UI set. The project directory, `--preset`, and pre-flight checks
are those of [`agent`](#agent). A launch does not remember options from
an earlier one and replaces only the named UI; the other UI and the
model server keep running. A terminal session and both UIs can use one
project ([the four-client
workflow](agents.md#use-four-clients-with-one-model)).

`--port` selects a host port for this launch only; without it the
forwarder publishes the manifest's `host_port` ([Ports](configuration.md#ports)).
An occupied port is accepted only when the named UI's own forwarder
holds it. Rootless Podman cannot publish a port below
`net.ipv4.ip_unprivileged_port_start` (normally `1024`).

The UI container is named `tokencrate-ui-<set>` and its forwarder
`tokencrate-ui-forward-<set>`, so two Compose projects on one engine
cannot run the same UI set at once; the second launch is refused before
it changes anything. The command waits up to 90 seconds for the
forwarder to answer HTTP, which does not prove that the assistant
answers. A failed build leaves the previous UI intact; a failed start
leaves the UI in place for `ui logs <set>`, a retry, or `ui stop <set>`.

`ui stop <set>` removes that UI and its forwarder; plain `ui stop`
removes every UI. Neither removes the model server, the networks, or
saved sessions and UI state. `ui logs <set>` follows the UI daemon
output; plain `ui logs` selects the only UI present.

`--egress` and `--cloud` grant the UI container the access described for
[`agent`](#agent); the forwarder receives neither internet access nor
keys. The UI holds its access until `ui stop <set>`, `down`, or a launch
of the set without the flag. [Cloud providers](agents.md#cloud-providers)
explains who can use the keys while the UI runs; [Egress](privacy.md#egress)
explains its network access.

```bash
bash bin/tokencrate ui pi-web --dir ~/src/my-project
bash bin/tokencrate ui paseo --cloud --dir ~/src/my-project
bash bin/tokencrate ui stop paseo
```

## models

```text
bin/tokencrate models list
bin/tokencrate models fetch <set> [<set> ...] | all
bin/tokencrate models status [--verify] <set> [<set> ...] | all
bin/tokencrate models draft hf:<owner>/<repo>:<file.gguf>
```

`fetch` prints the licenses and model cards, then downloads and verifies
every pending file of the named sets into `LLM_MODELS_DIR`; shared files
are downloaded once. `all` selects every shipped set, including sets
behind the [build gate](models.md#build-gate).

`status` runs the same verification without network access and prints
one state per file. A file is read in full once, and its checksum match
is recorded in a `<file>.tokencrate-verified` stamp beside it; later
runs of `status`, `fetch`, and `up --model-sets` trust the stamp while
the file's size and modification time are unchanged. `status --verify`
re-reads every present file and rewrites the stamps.

`draft` prints a manifest for one Hugging Face GGUF file, pinned to the
repository's current commit, with `TODO` markers for the fields the Hub
does not provide. For a split GGUF, name the first shard (`00001`); the
draft includes the remaining shards.

```bash
bash bin/tokencrate models fetch qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate models status --verify all
bash bin/tokencrate models draft hf:unsloth/Qwen3.8-27B-GGUF:Qwen3.8-27B-UD-Q6_K_XL.gguf   # prints a manifest draft
```

[Hugging Face access and
storage](models.md#hugging-face-access-and-storage) covers the token,
download resume, and free-space check; [Manifest
keys](models.md#manifest-keys) lists the keys of a model set.

## presets

```text
bin/tokencrate presets list
bin/tokencrate presets check
```

`list` prints each preset's model set, memory requirements, description,
and any newer llama.cpp build it needs ([Build gate](models.md#build-gate)).
`check` validates every preset and model-set manifest without writing
anything or inspecting model files; run it after editing a preset.

```bash
bash bin/tokencrate presets check
```

## skills

```text
bin/tokencrate skills list
bin/tokencrate skills fetch <set> [<set> ...] | all
bin/tokencrate skills status <set> [<set> ...] | all
```

A skill set is a group of [skills](agents.md#skills), each pinned to an
upstream commit in `config/skill-sets/<set>.toml`; agents load the
fetched sets that `LLM_SKILL_SETS` names.

`fetch` downloads each skill of the named sets into
`LLM_SKILLS_DIR/<set>/<skill>` and checks its tree digest and the
frontmatter of its `SKILL.md`. It then deletes every other skill
directory in the set's folder, so a skill you put there yourself is lost
on the next fetch. Keep your own skills in `LLM_LOCAL_SKILLS_DIR`, which
`fetch` never touches. `status` checks, without network access, that the
fetched files still match their pinned digests.

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

`pins check` prints, per pin, the current value and the latest eligible
upstream version, for one component or all of them (the default). A
component is named by its key without `_TAG` or `_VERSION`, in lower
case with hyphens (`LLAMA_CPP_TAG` is `llama-cpp`). For llama-cpp, the
output also links the releases between the two builds and lists model
sets waiting for a newer build. When an update is available, the output
ends with `KEY=VALUE` lines to paste into `pins.env`, an image's tag and
digest together; the command writes nothing. A pin whose source cannot
be read is marked `lookup failed`, and the command exits with status 1.

`RESOLVERS` in `tokencrate/checkpins.py` holds each component's
selection policy; a pin without a resolver is set by hand as [Upgrade a
pin](configuration.md#upgrade-a-pin) says, which also names the checks
that follow an upgrade.

```bash
bash bin/tokencrate pins
bash bin/tokencrate pins check llama-cpp
```
