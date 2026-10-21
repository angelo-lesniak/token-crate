# CLI reference

Run commands as `bash bin/tokencrate <command> ...`; `bash bin/tokencrate
help` prints the usage. The syntax blocks below show every command and
flag. Use the wrapper rather than direct Compose calls, which skip
TokenCrate's checks and generated configuration. "The model server" on
this page is llama-server in router mode: it loads the presets and routes
each request by its `model` field.

General rules:

- Commands run on the host as your user. The
  [README](../README.md#start-here) lists host tools and engine
  requirements. [Privacy and containment](privacy.md#what-leaves-the-machine)
  lists commands that use the network.
- While a stack runs, every command uses the engine `up` recorded;
  [When a change takes effect](configuration.md#when-a-change-takes-effect)
  states the `CONTAINER_ENGINE` rule.
- `--preset <id>` selects a preset instead of `LLM_DEFAULT_PRESET` for
  `doctor`, `smoke`, `agent`, and `ui`; `bench --presets <ids>` takes a
  comma-separated list. `smoke`, `bench`, `agent`, and `ui` need one or
  the other and refuse otherwise: `no preset selected; set
  LLM_DEFAULT_PRESET in .env or pass --preset`.
- Every flag that takes a value is refused when given twice. A list
  (`--sets`, `--model-sets`, `--presets`) is comma-separated and ignores
  spaces, empty entries, and repeats.

**Lock:** commands that change the stack take one lock per checkout; a
waiting command names the holder (``TokenCrate: waiting for `up` (pid N)
to finish``); do not delete `build/locks/`. A terminal `agent` session
never takes it: its pre-flight checks refuse on their own when the stack
moves.

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
line. The preset checks compare the host against the requirements a
[preset](models.md) declares in its file under `config/presets/`, so
nothing needs to be rendered or downloaded first; with no preset
selected they are skipped.

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
2. Checks that the `agents`, `ui`, and `dashboard` networks, when they
   exist, are the ones the Compose files declare ([Internal
   networks](privacy.md#internal-networks) states the rule). A mismatch
   is refused before downloading.
3. Downloads and verifies only the model sets named with `--model-sets`.
   Plain `up` downloads nothing, and the default preset's files must be
   present or startup fails.
4. Renders every preset whose files are present into `build/`: the
   router preset file `models.ini` and the agent model lists. A preset
   whose model set needs a newer llama.cpp build is listed as waiting and
   left out.
5. Builds the runtime image when it is missing or its inputs changed.
6. Under the lock, starts the llama container in the background and
   records the engine in `build/stack.json`. Compose recreates the
   container when the rendered preset file or service configuration
   changed; otherwise it keeps the running container.
7. Waits for the router to answer `GET /models` on the published port
   and for `LLM_DEFAULT_PRESET` to be ready. On a model server that was
   already running, `up` requests a load if nothing is loaded and allows
   three polls for the preset to leave `unloaded`; if another preset
   occupies the slot, `up` reports it and leaves the default to load on
   first request. With no default set, the router's response is enough.
   The wait fails if the container exits or disappears (a `down`
   meanwhile, since the build and the wait run without the lock), the
   preset's llama-server process exits while loading (reported as
   `unloaded`), or the timeout expires.
8. Prints the address of the API and the built-in chat UI.
9. With `LLM_DASHBOARD=true`, starts the
   [dashboard](configuration.md#dashboard) profile beside the model
   (pulling its pinned images on the first start) and prints Grafana's
   loopback address. `LLM_DASHBOARD_PORT` must be free like `LLM_PORT`.

| Flag | Meaning |
| --- | --- |
| `--model-sets <names>` | Download and verify these model sets first, as a comma-separated list |
| `--timeout <seconds>` | Maximum time to wait for readiness, as a positive integer; default `600`. On expiry the container keeps loading; `status` shows the preset once it is loaded, and a second `up` keeps the container |

```bash
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
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
(or the detected one), so it works even when the pins are invalid, and
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
When the model server runs, it also shows one line per rendered preset
with the state the router reports on `GET /models`: `unloaded`,
`loading`, `loaded`, or `sleeping`. `status` works without valid pins
or rendered files and does not wait for a start or stop in progress.

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

**Model checks:** without `--agent`, runs API probes on the host against
the published loopback port for one preset and writes the report to
`reports/smoke-<timestamp>.md`. The first chat completion loads the
preset and unloads the previous one; loading a large model can take
minutes. The probes cover:

- the model listing;
- two chat completions at the preset's lowest reasoning effort, which
  must return a non-empty answer that ends on its own (`finish_reason`
  `length` fails and can indicate a reasoning loop);
- a streamed tool call;
- the chat template, which must render the preset's first two efforts
  to different prompts (a preset that declares fewer than two passes
  with `nothing to compare`) and, for the Qwen sets, accept a system
  message in the middle of a conversation ([the patched chat
  template](models.md#the-patched-chat-template));
- tokenization;
- the Prometheus counters (`GET /metrics?model=`).

`--basic` skips the reply-termination and streamed-tool-call checks,
which need a capable model, so that a tiny model can still check the
transport and template.

**Agent checks:** with `--agent`, `smoke` starts the container the way
[`agent`](#agent) does, against a scratch project and agent home in a
temporary directory, and checks the network containment from inside the
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
A reachable browser UI is always a failure. Name resolution for a UI
started with `--egress` or `--cloud` is informational in an egress check;
an offline check still fails on it. The set checks are skipped. The
check never carries a provider key.

`--basic` is not valid with `--agent`; `--sets` requires `--agent pi`,
and `--egress` requires `--agent`.

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
(default 3). `--long` adds a run with a long prompt; the report's
prompt-tokens column shows the measured length of every run. Without
`--presets`, the default preset is measured. The report is written to
`reports/bench-<timestamp>.md`. `reports/bench-<timestamp>.json` holds
the same measurements (`schema` 2): six `timings` values per iteration
and, on every row, the measured preset's context per slot (`n_ctx`,
`ctx_size` over `parallel`), server build, and model path, read right
after that preset's warm-up. Presets
are loaded in turn, so measuring several presets swaps models.

```bash
bash bin/tokencrate bench --presets qwen3.8-27b-q4,qwen3.8-27b-q4-mtp
```

## stats

```text
bin/tokencrate stats [--since when] [--agent <pi|omp>]
bin/tokencrate stats --serve [--port port] [--since when] [--agent <pi|omp>]
```

Summarizes the retained transcripts below `LLM_AGENTS_DIR` ([storage
layout](configuration.md#storage-layout)): every conversation the agent
retained as a transcript (a pi session; a terminal or browser-UI session
can hold several) that received at least one answer counts. The command
reads only the host directories, so it works with the stack down. It
reads usage numbers and metadata only, never message content; the
report carries no conversation text, session names, or project paths
([Privacy](privacy.md#what-leaves-the-machine)). `smoke --agent` uses a
temporary home and adds nothing; deleting a project's directories below
`LLM_AGENTS_DIR` removes it from the report. The report is printed and
written to `reports/stats-<timestamp>.md`, and
`reports/stats-<timestamp>.html` holds the same report as a
self-contained page (open it from its file path) with sortable tables
and a chart of the context-size distribution; the page loads no
external scripts, styles, or fonts.

The first table, Preset fit, has one row per preset rendered into the
agent model list by [`up`](#up), with its slot (`ctx_size` /
`parallel`), the requests and the sessions whose context exceeded that
slot, and `fits` or `too small`. Every request in the report counts,
whichever preset or provider served it, so the table judges a preset you
have not run yet. Before the first `up` the table says `No rendered
presets: `up` renders them and writes the model list the wrapper reads
back.` The other tables show, per agent and per provider and model:
requests, tokens, the cache-read share, the context-size distribution,
sessions, turns, tool calls, stop reasons, compactions, thinking levels,
and time to first token and request duration; the Definitions list at
the end defines each measure. oh-my-pi records the timings itself; pi
records them when the [`metrics` agent set](agent-sets.md#shipped-sets),
part of the default selection, is loaded. Invalid timings are ignored
without dropping the request. Requests against a cloud provider appear
under that provider's name. The summary line states the scope (sessions,
requests, the filters or their absence) and how much of it is from the
last 24 hours.

`--since <when>` keeps the sessions whose last message is at or after
a point in time: a duration back from now (`30m`, `12h`, `7d`, `2w`) or
an ISO date or date-time (`2026-09-20`, `2026-09-20T10:00`, a naive
value in local time). A session that spans the cutoff counts whole, so
its earlier requests are in the numbers too. `--agent pi` or `--agent
omp` keeps one agent's sessions. Both apply to `--serve`, where the
cutoff is fixed when the server starts. A filter that matches no session
is refused with a sentence that says so.

`--serve` serves the page at `http://127.0.0.1:4210/` (`--port` selects
another port), re-reading the transcripts every 60 seconds, and saves
nothing. The served page leads with a verdict on the loaded preset (its
slot, and whether every request in the report would have fit it or how
many would not) and adds a live panel: the model server's processing
and queued requests, its prompt and generation rates, the share of
drafted tokens an MTP preset accepted since its load, the GPU's memory
in use and power draw (when `LLM_GPU` is true and `nvidia-smi` is on the
host's `PATH`), and two charts of the last ten minutes. A tile without
a number says why (a GPU tile shows `GPU query failed`). The rates
follow counters that llama.cpp advances when a request completes, so a
long answer shows as one burst at its end.
The panel polls the model server's loopback port at most every 2
seconds and only while a page is open, with the same two-poll rule as
the [dashboard](configuration.md#dashboard)'s exporter, so a poll never
loads a preset; the dashboard is what keeps the counters beyond ten
minutes. The server binds loopback only and answers only requests whose
`Host` header names its own address; anything local that can open the
port can read the report's numbers and the live samples. It runs in the
foreground until Ctrl-C; [`down`](#down) does not stop it.

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
session; an empty string selects plain pi, and oh-my-pi rejects the
flag. Each combination of sets has its own image, built before the
first session that uses it ([Agent sets](agent-sets.md)). The project
defaults to the current directory; `--dir` selects another. The rules
below apply to the path after symbolic links are resolved. The project
directory must:

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
above it. When the walk meets a `.git` file or symbolic link (a linked
worktree or a submodule), a worktree's `commondir`, or a repository
above the project, the start is refused. The refusal names that `.git`:
`Git metadata lies outside the project mount (<path>/.git); choose the
repository root or a standalone clone instead of a linked worktree or
submodule`. A repository that manages the home directory itself lies
outside the walk.

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
- the file lies inside the project, a storage directory, `config/`,
  `local/agent-sets/`, `services/`, or `build/agents/pi/`, which
  containers mount or image builds read;
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
- the model server is running with the configuration the last `up`
  rendered; after a failed `up`, fix its error and run `up` again;
- every skill set named in `LLM_SKILL_SETS` is known, fetched, and
  complete;
- the `agents`, `ui`, and `dashboard` networks are the ones the Compose
  files declare ([Internal networks](privacy.md#internal-networks)
  states the rule).

Arguments after `--` are passed to the agent binary; with pi's `-p`, the
agent answers one prompt, prints the reply, and exits. Compose attaches
your terminal only when both standard streams are a terminal and the
wrapper runs in the foreground; otherwise (under `timeout`, in a
pipeline, from cron) the wrapper passes `-T`, and a terminal it may not
read from is replaced by `/dev/null`, so a scripted call needs no
redirection and a pipe on standard input still reaches the agent. See
[Coding agents and skills](agents.md) for what the container can and
cannot touch.

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
including a custom set under `local/agent-sets`. The image contains
`LLM_AGENT_SETS`, or `--sets` for this launch, plus the named UI set
([Agent sets](agent-sets.md#shipped-sets) names each set's download).
The project directory, `--preset`, and pre-flight checks are those of
[`agent`](#agent). A launch does not remember options from an earlier
launch. Only the named UI is replaced; the other UI and the model server
keep running unchanged. A terminal session and both UIs can use one
project, with separate conversations and live settings ([the
four-client workflow](agents.md#use-four-clients-with-one-model)).

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

The UI container is named `tokencrate-ui-<set>` and its forwarder
`tokencrate-ui-forward-<set>`, so two Compose projects on one engine
cannot run the same UI set at once; the second launch is refused before
it changes anything (`the container tokencrate-ui-<set> belongs to
another checkout's UI; free it there with: bash bin/tokencrate ui stop
<set>`). The command waits up to 90 seconds for both containers to run
and the forwarder to answer HTTP, which is not proof of a completed
assistant response. A failed build leaves the previous UI intact; a
failed start or readiness check leaves that UI in place for `ui logs
<set>`, a retry, or `ui stop <set>`.

`ui stop <set>` removes that UI and its forwarder, and fails when the
set has no container. Plain `ui stop` removes every UI and says so when
none is running. Neither removes the model server, the networks, or
saved sessions and UI state. The UI daemon gets the engine's stop
timeout, 20 seconds on Docker and 10 on Podman. `ui logs <set>` follows
the UI daemon output until interrupted; plain `ui logs` selects the only
UI present and asks for a set name when there are several. Both find
stopped or failed containers without the launch options or a custom manifest.

A terminal session and both UIs can use one project, with separate
conversations and live settings ([the four-client
workflow](agents.md#use-four-clients-with-one-model)).

`--egress` and `--cloud` grant the UI container the access described for
[`agent`](#agent). The forwarder receives neither internet access nor
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
runs of `status`, `fetch`, and `up --model-sets` trust the stamp while the
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
the download and storage mechanics; [Manifest
keys](models.md#manifest-keys) lists the keys a model-set entry must
contain.

## presets

```text
bin/tokencrate presets list
bin/tokencrate presets check
```

`list` prints each preset's model set, memory requirements, description,
and any newer llama.cpp build it needs; see the [build
gate](models.md#adding-a-model).

`check` validates every preset and model-set manifest. It writes
nothing and does not inspect downloaded model files. Each preset is
listed as `valid` or as waiting for a newer llama.cpp build. Run it
after editing a preset. [`up`](#up) writes the rendered files ([storage
layout](configuration.md#storage-layout)).

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
`LLM_SKILLS_DIR/<set>/<skill>`: it clones the pinned commit, copies the
skill's directory, and checks its tree digest and the frontmatter of its
`SKILL.md`. It then deletes every other skill directory in the set's
folder, so a skill you put there yourself is lost on the next fetch. Keep your
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
its tag): the current value and the latest eligible upstream version,
for one component or all of them (the default). A component is named by
its key without `_TAG` or `_VERSION`, in lower case with hyphens
(`LLAMA_CPP_TAG` is `llama-cpp`). For llama-cpp, the output also links
the releases between the two builds and lists model sets waiting for a
newer build. `dcgm-exporter` (its tag on nvcr.io) and
`cuda-min-driver-major` have no resolver; their rows print the current
value with `(no resolver; look it up by hand)`.

When an update is available, the output ends with a `Paste into pins.env:`
block of `KEY=VALUE` lines; an image pin has two lines, its tag and
manifest digest. The command writes nothing; paste the lines into
`pins.env` and review with `git diff pins.env`. When nothing is newer,
the last line is `pins.env has the latest eligible pins.`, or `The
resolved pins are the latest eligible.` when a row had no resolver. When
a source cannot be read, or its latest eligible version is older than
the current pin, that pin's row ends with `(lookup failed: ...)`, the
other rows are still printed, and the command exits with status 1.

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
