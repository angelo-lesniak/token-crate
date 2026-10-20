# CLI reference

Run commands as `bash bin/tokencrate <command> ...`; `bash bin/tokencrate
help` prints the usage. The syntax blocks below show every command and
flag. Use the wrapper rather than direct Compose calls, which skip
TokenCrate's checks and generated configuration.

General rules:

- Commands run on the host as your user. The
  [README](../README.md#start-here) lists host tools and engine
  requirements. [Privacy and containment](privacy.md#what-leaves-the-machine)
  lists commands that use the network.
- A setting comes from the shell environment, then `.env`, then the
  defaults in `.env.example`; the pins in `pins.env` cannot be
  overridden. [Configuration](configuration.md) says when a change takes
  effect.
- `CONTAINER_ENGINE=docker` or `CONTAINER_ENGINE=podman` overrides engine
  detection. While a stack runs, every command uses the engine `up`
  recorded in `build/stack.json`. A `CONTAINER_ENGINE` that disagrees is
  refused until `down`, naming the engine to use.
- `LLM_GPU=false` starts llama-server without a GPU device and skips the
  GPU checks of `doctor`; it is for CPU-only checks.
- `--preset <id>` selects a preset instead of `LLM_DEFAULT_PRESET`.
  `doctor`, `smoke`, `agent`, and `ui` accept it once; `bench` accepts it
  several times, but not the same preset twice. `smoke`, `bench`, `agent`,
  and `ui` need one or the other and refuse otherwise: `no preset
  selected; set LLM_DEFAULT_PRESET in .env or pass --preset`.
- Every other flag that takes a value (`--timeout`, `--iterations`,
  `--sets`, `--port`, `--dir`, `--agent`, `--since`) is refused when
  given twice. `--model-set` can repeat.

**Lock:** commands that change the stack take one lock per checkout
(`build/locks/<project>.lock`). `up` holds it while it starts the llama
container and records the engine, and again while it starts the
dashboard profile. `down` holds it throughout, `ui` while it re-checks
the port and replaces or removes a UI's containers, and `smoke --agent`
for its run. A terminal `agent` session waits for the lock before its
pre-flight and holds nothing while it runs. Image builds and readiness
waits run without the lock. A command that has to wait says for whom:
`TokenCrate: waiting for `up` (pid N) to finish`.

## init

```text
bin/tokencrate init
```

Creates the host storage directories and, if missing, a `.env` that
holds only a comment ([Configuration](configuration.md)). An existing
`.env` keeps its content. It must already be your user's and readable by
your user only (`<path> must be readable by your user only; run: chmod
600 <path>`); every run sets its mode to `0600`. The cloud keys file is
not created; [Cloud providers](agents.md#cloud-providers) says how to
copy it from `cloud-keys.env.example`.

## doctor

```text
bin/tokencrate doctor [--preset id]
```

Checks the host and prints one line per check, each with `[ok]`,
`[warn]`, or `[fail]` and a sentence that says what was found. `up` runs
the same checks before it downloads anything and stops on a `[fail]`
line.

A [preset](models.md) says how llama-server runs a downloaded model and
declares the GPU and system memory it needs. `doctor` checks the host
against the preset named with `--preset`, or `LLM_DEFAULT_PRESET`
without the flag. It reads the requirements from the preset's file under
`config/presets/`, so nothing needs to be rendered or downloaded first.
With neither set, the preset checks are skipped.

A `[warn]` line is something `up` can start without, for example:

- Git missing;
- a host other than Linux on x86-64;
- Podman older than 6 (see [Validation](validation.md#status));
- less GPU memory free right now than the preset needs;
- a storage directory `init` has not created yet;
- a CDI specification that names another driver than the host runs
  (Podman);
- a name in `LLM_AGENT_SETS` or `LLM_SKILL_SETS` that no set has;
- a preset whose model set needs a newer llama.cpp build than `pins.env`
  pins (`up` leaves such a preset out of the router; see
  [the build requirement](models.md#adding-a-model)).

System memory is compared against the preset's `[requires] ram_gib` with
5 percent of slack for what the firmware and kernel reserve (a 96 GB
machine reports about 93 GiB). `LLM_PORT` must be bindable on loopback,
a `[fail]` unless TokenCrate's own llama container publishes that port.

For an unknown preset name, `doctor` prints a warning and runs every
other check. The commands that use a preset are stricter: `smoke`,
`bench`, `agent`, and `ui` refuse a preset that is unknown or that the
pinned llama.cpp build cannot load. `up` refuses such an
`LLM_DEFAULT_PRESET`.

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
2. Checks the `agents`, `ui`, and `dashboard` networks when they exist:
   each must be internal and created by this project, on Docker without
   a gateway address, and on rootless Podman with a bridge that does not
   forward IPv4 traffic
   ([Privacy and containment](privacy.md#defaults-and-their-limits)).
   Otherwise `up` refuses before downloading, for example with `the
   agents network's bridge podman1 forwards IPv4 traffic, so a session on
   another network can reach it. Run: bash bin/tokencrate down, then up`.
3. Downloads and verifies only the model sets named with `--model-set`.
4. Renders every preset whose files are present into `build/`: the
   router preset file `models.ini` and the agent model lists. A preset
   whose model set needs a newer llama.cpp build is listed as waiting and
   left out.
5. Builds the runtime image when it is missing or its inputs changed.
6. Under the lock, starts the llama container in the background and
   records the engine in `build/stack.json`. Compose recreates the
   container when the rendered preset file or service configuration
   changed; otherwise it keeps the running container.
7. Waits for the router to answer `GET /models` on the published port.
   A new router loads `LLM_DEFAULT_PRESET` at start, and `up` waits for
   that preset to be ready. On an existing router, `up` requests a
   load if nothing is loaded and allows three polls for the model server
   to appear. If another preset already occupies the slot, `up` reports
   it and leaves the default to load on first request. With no default
   set, the router's response is enough.
8. Prints the address of the API and the built-in chat UI.
9. With `LLM_DASHBOARD=true`, starts the
   [dashboard](configuration.md#dashboard) profile beside the model
   (pulling its pinned images on the first start) and prints Grafana's
   loopback address. `LLM_DASHBOARD_PORT` must be free like `LLM_PORT`.

Plain `up` downloads no model files; after rendering, the default
preset's files must be present or startup fails. The build and the
readiness wait run without the lock, so a `down` meanwhile goes first or
removes the container, and the wait reports that. During startup, `up`
fails if the container exits or disappears, the model server exits while
loading (reported as `unloaded`), or the timeout expires.

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
([`ui`](#ui)), the [dashboard](configuration.md#dashboard) when it runs,
and the Compose networks. This ends active agent sessions. Images and
host data are kept; see the [storage
layout](configuration.md#storage-layout). `down` finds the containers
and networks by the Compose project labels of the engine `up` recorded
(or the detected one), so it works even when the pins are invalid. It
removes the stack record last. A network of the project's name made
without those labels is left alone, and `up` refuses until it is removed
by hand.

## status

```text
bin/tokencrate status
```

Shows all containers labelled for the selected Compose project. Each
`UI <set>:` line adds the forwarder's state, published loopback address,
and mounted project, so a UI reassigned to another project is visible.
The line ends with `egress` or `cloud` for a UI started with that flag.
When llama runs, it also shows one line per rendered preset with the state
the router reports on `GET /models`: `unloaded`, `loading`, `loaded`, or
`sleeping`. `status` works without valid pins or rendered files and does
not wait for a start or stop in progress.

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

**Model checks:** without `--agent`, runs API probes on the host against
the published loopback port for one preset and writes the report to
`reports/smoke-<timestamp>.md`. The first chat completion loads the
preset and unloads the previous one; loading a large model can take
minutes. The probes cover the model listing, two chat completions, a
streamed tool call, the chat template, tokenization, and the Prometheus
counters (`GET /metrics?model=`). The completions ask for the preset's
lowest reasoning effort and are judged on the answer. They must end on
their own: a reply that exhausts its token budget ends with
`finish_reason` `length`, which can indicate a reasoning loop. The
template must render the preset's first two efforts to different
prompts; a preset that declares fewer than two passes with `nothing to
compare`. The [patched chat
template](models.md#the-patched-chat-template) of the Qwen sets must
accept a system message in the middle of a conversation, which the
model's own template rejects. `--basic` skips the reply-termination and
streamed-tool-call checks, which need a capable model, so that a tiny
model can still check the transport and template.

**Agent checks:** with `--agent`, `smoke` starts the container the way
[`agent`](#agent) does, against a scratch project and agent home in a
temporary directory. It checks the network containment from inside the
container. It needs what `agent` needs: a preset the running router
serves, and every set in `LLM_SKILL_SETS` fetched. Each finding is one
`[ok]` or `[fail]` line: no route out and no name resolution, no browser
UI reachable by name or address, on Docker no gateway address on the
`agents` network, the container user, a writable home, the mounted
project, the linked skills, and a read-only root filesystem. The report
ends with the mount table and the number of failures. It proves that the
routes are absent, not what the reachable model does. For pi, it also
reports that the selected [agent sets](agent-sets.md) are seeded (the
package count and the tools note); `--sets` overrides `LLM_AGENT_SETS`
for the check. Each set's own `check` lines ([Agent
sets](agent-sets.md#writing-a-set)) run as the container user without
network access and add one line per set. Without a running browser UI
the report prints `[warn] no browser UI running; UI isolation not
tested`; run the check while a UI runs to test that boundary.

`--egress` runs the same check with the route out that `agent --egress`
and `agent --cloud` add. The session is on the default network and a
default route is required; whether the internet answers is not probed.
A browser UI that answers is still a failure, except one started with
`--egress` or `--cloud`, which is reported as `[info] ... that UI was
started with --egress or --cloud`. An offline check still fails on it.
The set checks are skipped. The check never carries a provider key.

`--basic` is not valid with `--agent`; `--sets` requires `--agent pi`,
and `--egress` requires `--agent`.

```bash
bash bin/tokencrate smoke
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate smoke --agent pi --egress
```

## bench

```text
bin/tokencrate bench [--preset id]... [--iterations n] [--long]
bin/tokencrate bench --history
```

Measures prompt-processing and generation tokens per second per preset
from llama-server's `timings`, averaged over `--iterations` requests
(default 3). `--long` adds a run with a long prompt; the report's
prompt-tokens column shows the measured length of every run. Without
`--preset`, the default preset is measured. The report is written to
`reports/bench-<timestamp>.md`. `reports/bench-<timestamp>.json` holds
the same measurements (`schema` 2): six `timings` values per iteration
and, on every row, the measured preset's context size (`n_ctx`), server
build, and model path, read right after that preset's warm-up. Presets
are loaded in turn, so measuring several presets swaps models.

`--history` prints those JSON files as one table, one row per measured
run, grouped by preset and run and oldest first within a group. The
columns are preset, run, date, `n_ctx`, build, prompt tokens, the two
speeds, the change in generation speed against the row above (only when
both ran at the same `n_ctx`), and the iterations. A file of an earlier
`bench` (`schema` 1) recorded one build and `n_ctx` for the whole file,
and the history shows those on each of its rows. It reads the host's
`reports/` directory and needs no engine or stack, so a llama.cpp
[upgrade](configuration.md#upgrading) or a preset change shows next to
the runs before it. The history is this machine's, because `reports/` is
not tracked.

```bash
bash bin/tokencrate bench --preset qwen3.8-27b-q4 --preset qwen3.8-27b-q4-mtp
bash bin/tokencrate bench --history
```

## stats

```text
bin/tokencrate stats [--since when] [--agent <pi|omp>]
bin/tokencrate stats --serve [--port port] [--since when] [--agent <pi|omp>]
```

Summarizes the retained transcripts below `LLM_AGENTS_DIR` ([storage
layout](configuration.md#storage-layout)): every terminal and browser-UI
session that received at least one answer counts. The command reads only
the host directories, so it works with the stack down. It reads usage
numbers and metadata only, never message content; the report carries no
conversation text, session names, or project paths
([Privacy](privacy.md#what-leaves-the-machine)). `smoke --agent` uses a
temporary home and adds nothing; deleting a project's directories below
`LLM_AGENTS_DIR` removes it from the report. The report is printed and
written to `reports/stats-<timestamp>.md`.
`reports/stats-<timestamp>.html` holds the same report as a
self-contained page for a browser (open it from its file path): the
tables, sortable by a click on a column header, and a chart of the
context-size distribution. The page loads no external scripts, styles,
or fonts.

The first table, Preset fit, answers whether a preset fits. It has one
row per preset rendered into the agent model list by [`up`](#up), with
its slot (`ctx_size` / `parallel`), the requests and the sessions whose
context exceeded that slot, and `fits` or `too small`. Every request in
the report counts, whichever preset or provider served it, so the table
judges a preset you have not run yet. Before the first `up` the table
says `No rendered presets: `up` renders them and writes the model list
the wrapper reads back.` The chart draws the compaction p50 and one
preset's slot as labelled lines: the loaded preset on the served page,
otherwise the rendered preset that served the most requests.

The other tables show, per agent and per provider and model: requests,
tokens, the cache-read share, the context-size distribution, sessions,
turns, tool calls, stop reasons, compactions, thinking levels, and time
to first token and request duration. The Definitions list at the end of
the report defines each measure. oh-my-pi records the timings itself; pi
records them when the [`metrics` agent set](agent-sets.md#shipped-sets),
part of the default selection, is loaded. A session's requests against a
cloud provider appear under that provider's name. The summary line
states the scope (sessions, requests, the agent and time filters or
their absence) and how much of it is from the last 24 hours.

`--since <when>` keeps the sessions whose last message is at or after
a point in time: a duration back from now (`30m`, `12h`, `7d`, `2w`) or
an ISO date or date-time (`2026-09-20`, `2026-09-20T10:00`, a naive
value in local time). A session that spans the cutoff counts whole, so
its earlier requests are in the numbers too. `--agent pi` or `--agent
omp` keeps one agent's sessions. Both apply to `--serve`, where the
cutoff is fixed when the server starts. The summary line names the
filters, and a filter that matches no session is refused with a
sentence that says so.

`--serve` serves the page at `http://127.0.0.1:4210/` (`--port` selects
another port), re-reading the transcripts every 60 seconds, and saves
nothing. The served page leads with a verdict on the loaded preset: its
slot, and whether every request in the report would have fit it or how
many would not. It adds a live panel with tiles for the requests the
model server is processing and has queued, its prompt and generation
rates in tokens per second, the share of drafted tokens an MTP preset
accepted since its load, and the GPU's memory in use and power draw,
plus two charts of the requests and rates over the last ten minutes.

A tile without a number says why (no preset loaded, first sample, no
draft model); a GPU tile shows `–` with `GPU query failed`. The rates
follow the server's counters, which llama.cpp advances when a request
completes, so a long answer shows as one burst at its end rather than a
steady line.

The server polls the model server's loopback port (`LLM_PORT`) at most
every 2 seconds and only while a page is open: `GET /models`, and `GET
/metrics?model=` for the preset that was loaded on this and the previous
poll. A poll that lands in a model swap therefore does not load the
unloaded preset again. When `LLM_GPU` is true and `nvidia-smi` is on the
host's `PATH`, it runs once per poll for the GPU numbers; without the
tool the page has no GPU tiles.

The samples live in the server's memory for ten minutes and are never
saved; a saved page has no panel, and the
[dashboard](configuration.md#dashboard) keeps the server's counters for
90 days.

The server binds loopback only and answers only requests whose `Host`
header names its own address, so a web page cannot reach it through the
browser's name resolution. Anything local that can open the port can
read the report's numbers and the live samples.

The server runs in the foreground until Ctrl-C. To keep it running in
the background, start it as its own session and end it with `kill`:
`setsid bash bin/tokencrate stats --serve </dev/null >build/stats.log
2>&1 &`. [`down`](#down) stops containers only.

```bash
bash bin/tokencrate stats --serve
bash bin/tokencrate stats --since 7d --agent pi
```

## agent

```text
bin/tokencrate agent <pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [--cloud] [-- args]
```

Opens a coding agent in a container with the project directory mounted
read-write at the same absolute path it has on the host. For pi, the
image uses `LLM_AGENT_SETS` unless `--sets` overrides it for this
session. The value is a comma-separated list (spaces, empty entries, and
repeats are ignored); an empty string selects plain pi. `--sets` applies
only to pi; oh-my-pi rejects it. Each combination of sets has its own
image, built before the first session that uses it ([Agent
sets](agent-sets.md)). The project defaults to the current directory;
`--dir` selects another. The rules below apply to the path after
symbolic links are resolved. The project directory must:

- lie below your home directory, or below a directory listed in
  `LLM_PROJECT_ROOTS` (absolute paths separated by colons);
- not be the root or home directory itself, or an `LLM_PROJECT_ROOTS`
  entry;
- not be, contain, or lie inside the TokenCrate checkout, a storage
  directory named in `.env` (`LLM_MODELS_DIR`, `LLM_AGENTS_DIR`,
  `LLM_SKILLS_DIR`, `LLM_LOCAL_SKILLS_DIR`), or the cloud keys file
  (`LLM_CLOUD_KEYS_FILE`), because the next start trusts what those
  contain;
- carry no space, comma, colon, dollar sign, or quote in its path, which
  a Compose mount cannot express.

The container sees only the project directory, so Git works there only
when the repository's `.git` data lies inside it. The wrapper walks from
the project up to your home directory or the `LLM_PROJECT_ROOTS` entry
above it. It refuses when it meets a `.git` file (a linked worktree or
a submodule), a worktree's `commondir`, or a repository above the
project, naming that `.git`: `Git metadata lies outside the project
mount (<path>/.git); choose the repository root or a standalone clone
instead of a linked worktree or submodule`. A repository that manages
the home directory itself lies outside the walk.

The agent talks to the running llama service over an internal network with
no internet access. `--egress` puts the session on the default network
instead, for example to install packages, and the wrapper prints a
warning. `--egress` and `--cloud` are the only ways to give a session
internet access. Neither can be turned on in `.env` or any other
setting, so each session that needs a route out must pass the flag
again.

`--cloud` (pi only) also mounts the cloud keys file that
`LLM_CLOUD_KEYS_FILE` names, read-only, into this one session, and
implies `--egress`. The wrapper warns that the conversation and file
contents sent to a cloud model leave this machine and that every process
in the session can read the keys. `--cloud` refuses to start when:

- the agent is oh-my-pi ([Cloud providers](agents.md#cloud-providers)
  says why);
- the file does not exist or is not a regular file;
- the file is not your user's or is readable by others (`<path> must be
  readable by your user only; run: chmod 600 <path>`);
- the file lies inside the project, a storage directory, `config/`, or
  `local/agent-sets/`, which containers or image builds read;
- its path carries `:` or `,`, which a mount cannot express.

The container refuses to start when a line of the file is not
`NAME=value`, has a carriage return, or sets a variable the agent image
owns. Cloud providers lists those names, the file's grammar, and what a
cloud session offers. `--egress` alone hands the container no key.

The session container is named `tokencrate-agent-<id>`. A hang-up or
`SIGTERM` to the wrapper stops it; a `SIGKILL` leaves it running with the
keys it exported, until `down` or the agent exits.

The command refuses to start unless:

- the last `up` added the preset to the router, which it does when the
  preset's model files are downloaded and the pinned llama.cpp build can
  load them;
- the llama service is running with the configuration the last `up`
  rendered; after a failed `up`, fix its error and run `up` again;
- every skill set named in `LLM_SKILL_SETS` is known, fetched, and
  complete;
- the `agents`, `ui`, and `dashboard` networks pass the check
  [`up`](#up) makes: internal, created by this project, on Docker
  without a gateway address, on rootless Podman with a bridge that does
  not forward IPv4 traffic
  ([Privacy and containment](privacy.md#defaults-and-their-limits)).

Arguments after `--` are passed to the agent binary; with pi's `-p`, the
agent answers one prompt, prints the reply, and exits. Compose attaches
your terminal only when both standard streams are a terminal and the
wrapper runs in the foreground. Under `timeout`, in a pipeline, or from
cron, the wrapper passes `-T` instead; when standard input is a terminal
it may not read from, it gives the container `/dev/null` in its place. A
scripted call needs no redirection, and a pipe on standard input still
reaches the agent. See [Coding agents and skills](agents.md) for what
the container can and cannot touch.

Run the wrapper from the checkout and name the project with `--dir`:

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
with its description, marks sets with a `[ui]` manifest as `[ui]`, and
prints the current `LLM_AGENT_SETS`. See [Agent sets](agent-sets.md) for
what a set is and how to write one.

## ui

```text
bin/tokencrate ui <set> [--preset id] [--sets names] [--dir path] [--port port] [--egress] [--cloud]
bin/tokencrate ui stop [<set>]
bin/tokencrate ui logs [<set>]
```

`ui <set>` starts one instance of that UI set in the background and
prints its loopback address. The set must declare a `[ui]` manifest,
including a custom set under `local/agent-sets`.

`--port` selects a host port from `1` to `65535` for this launch only.
Without it the forwarder publishes the `host_port` the set's manifest
declares (`4224` for PI WEB, `4250` for Paseo). A set without
`host_port` needs `--port`: `UI set <name> declares no host_port; pass
--port`. An occupied port is accepted only when the named UI's own
forwarder holds it; another UI or program causes a refusal before the
existing UI changes. `--port` does not change the container-internal
ports, which come from the manifest. Rootless Podman cannot publish a
port below `net.ipv4.ip_unprivileged_port_start` (normally `1024`); keep
the default high ports, or have the host administrator lower that
setting.

The image contains `LLM_AGENT_SETS`, or `--sets` for this launch, plus
the named UI set ([Agent sets](agent-sets.md#shipped-sets) names each
set's download). The project directory, `--preset`, and pre-flight
checks are those of [`agent`](#agent). A launch does not remember
options from an earlier launch. Only the named UI is replaced; the other
UI and llama keep running unchanged.

The UI container is named `tokencrate-ui-<set>` and its forwarder
`tokencrate-ui-forward-<set>`, so two Compose projects on one engine
cannot run the same UI set at once. The second launch fails on the
name; `ui stop <set>` in the other checkout frees it. The command
waits up to 90 seconds for both containers to run and the forwarder to
answer. A failed build leaves the previous UI intact. A failed start or
readiness check leaves that UI in place for `ui logs <set>`, a retry, or
`ui stop <set>`; it does not stop the other UI. Readiness is an HTTP
check, not proof of a completed assistant response.

`ui stop <set>` removes that UI and its forwarder, and fails when the
set has no container. Plain `ui stop` removes every UI and says so when
none is running. Neither removes llama, the networks, or saved sessions
and UI state. The UI daemon gets the engine's stop timeout, 20 seconds
on Docker and 10 on Podman. `ui logs <set>` follows the UI daemon output
until interrupted; plain `ui logs` selects the only UI present and asks
for a set name when there are several. Both find stopped or failed
containers without the launch options or a custom manifest.

A terminal session and both UIs can use one project, with separate
conversations and live settings ([the four-client
workflow](agents.md#use-four-clients-with-one-model)).

`--egress` gives the UI container a route out: it joins the default
network in addition to the `ui` network, where its forwarder reaches it.
The wrapper prints the warning of [`agent --egress`](#agent). `--cloud`
also mounts the cloud keys file into the UI container, read-only,
implies `--egress`, and prints the warning of `agent --cloud`. It
refuses in the same cases except the one for oh-my-pi, since every UI
runs pi. The forwarder, which publishes the UI's port on the host, gets
neither the route out nor the keys. The UI holds them until `ui stop
<set>`, `down`, or a launch of the set without the flag. [Cloud
providers](agents.md#cloud-providers) says who can use them meanwhile,
and [Privacy and containment](privacy.md#defaults-and-their-limits)
states the network boundaries.

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
every pending file of the named sets into `LLM_MODELS_DIR`; an
interrupted download resumes on the next run. Several sets may be named
in one command; shared files are downloaded once. `all` selects every
shipped set, including sets whose architecture the pinned build cannot
load yet; `presets list` shows which presets wait ([Adding a
model](models.md#adding-a-model)).

`status` runs the same verification without network access and prints
one state per file (`ready`, `missing`, `wrong size`, `wrong checksum`,
and the like). A file is read in full once; its checksum match is
recorded in a `<file>.tokencrate-verified` stamp beside it. Later
runs of `status`, `fetch`, and `up --model-set` trust the stamp while the
file's size, modification time, and inode are unchanged. A run that has
to read files says so first (`verifying: N file(s) (X.X GB) by checksum;
later runs trust the record written beside each verified file`).
`status --verify` re-reads every present file and rewrites the stamps;
`fetch` does not accept the flag.

`draft` prints a manifest for one Hugging Face GGUF file, pinned to the
repository's current commit, with `TODO` markers for the fields the Hub
does not provide. For a split GGUF, name the first shard (`00001`); the
draft includes the remaining shards.

```bash
bash bin/tokencrate models fetch qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate models status --verify all
bash bin/tokencrate models draft hf:unsloth/Qwen3.8-27B-GGUF:Qwen3.8-27B-UD-Q6_K_XL.gguf   # prints a manifest draft
```

See [Models and presets](models.md) for licenses, token handling, and
the download and storage mechanics; the [manifest field
rule](../CONTRIBUTING.md#model-sets-presets-and-skill-sets) says what a
model-set entry must contain.

## presets

```text
bin/tokencrate presets list
bin/tokencrate presets render
```

`list` prints each preset's model set, memory requirements, description,
and any newer llama.cpp build it needs; see the [build
gate](models.md#adding-a-model).

`render` validates every preset and model-set manifest. It writes
nothing and does not inspect downloaded model files. Each preset is
listed as `valid` or as waiting for a newer llama.cpp build. Run it
after editing a preset. [`up`](#up) writes the rendered files ([storage
layout](configuration.md#storage-layout)).

```bash
bash bin/tokencrate presets render
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
`LLM_SKILLS_DIR/<set>/<skill>`: it clones the pinned commit, copies the
skill's directory, and checks its tree digest and the frontmatter of its
`SKILL.md`. It then deletes every other directory in the set's folder,
so a skill you put there yourself is lost on the next fetch. Keep your
own skills in `LLM_LOCAL_SKILLS_DIR`, which `fetch` never touches.

`status` checks, without network access, that the fetched files still
match their pinned digests.

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

`pins check` prints one row per pin of `pins.env` (a digest rides with
its tag): the current value and the latest eligible upstream version.
It covers one component or all of them (the default). A component is named by
its key without `_TAG` or `_VERSION`, in lower case with hyphens
(`LLAMA_CPP_TAG` is `llama-cpp`). For llama-cpp, the output also links
the releases between the two builds and lists model sets waiting for a
newer build. A pin the command cannot look up prints its value with
`(no resolver; look it up by hand)`: `dcgm-exporter` (its tag on
nvcr.io) and `cuda-min-driver-major`.

When an update is available, the output ends with a `Paste into pins.env:`
block of `KEY=VALUE` lines. An image pin has two lines: its tag and
manifest digest. The command writes nothing; paste the lines into
`pins.env` and review with `git diff pins.env`. When nothing is newer,
the last line is `pins.env has the latest eligible pins.`, or `The
resolved pins are the latest eligible.` when a row had no resolver. When
a source cannot be read, that pin's row ends with `(lookup failed: ...)`,
the other rows are still printed, and the command exits with status 1.
A source whose latest eligible version is older than the current pin
fails the same way. Docker Hub listings are read newest first and stop
after the first page that adds nothing newer, so a check normally reads
two pages of an image's tags.

| Component | Key | Selection policy |
| --- | --- | --- |
| `llama-cpp` | `LLAMA_CPP_TAG` | Newest llama.cpp GitHub release (`b<N>`) whose `server-<family>-b<N>` image GHCR serves, in the pinned CUDA family |
| `pi` | `PI_VERSION` | npm's stable `latest` version of `@earendil-works/pi-coding-agent` |
| `omp` | `OMP_VERSION` | npm's stable `latest` version of `@oh-my-pi/pi-coding-agent` |
| `node` | `NODE_TAG` | Latest stable `-bookworm-slim` tag of the `node` image on Docker Hub with the existing version granularity, among even (long-term-support) majors |
| `bun` | `BUN_TAG` | Latest stable `-slim` tag of the `oven/bun` image on Docker Hub with the existing version granularity |
| `victoriametrics` | `VICTORIAMETRICS_TAG` | Latest release tag of `victoriametrics/victoria-metrics` on Docker Hub within the pinned major |
| `grafana` | `GRAFANA_TAG` | Latest release tag of `grafana/grafana` on Docker Hub within the pinned major |

The CUDA family of the llama.cpp tag, a new major of VictoriaMetrics or
Grafana, and the GPU exporter's tag are manual choices. An
[agent set](agent-sets.md) pins its own versions, which `pins check`
does not cover. See [Upgrading](configuration.md#upgrading) for the
checks that follow an upgrade.

```bash
bash bin/tokencrate pins
bash bin/tokencrate pins check llama-cpp
```
