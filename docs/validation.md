# Validation

This page records what has been checked, on which versions and hosts,
and what remains unverified. It also defines the validation procedures
and the router behavior the wrapper relies on.

Unless stated otherwise, records are dated 2026-09-20 and use the shipped
tree and pins in [Environment](#environment). Results apply only to their
tested versions and environments. After changing a pinned component,
Compose file, entrypoint, renderer, or package code, repeat the relevant
procedure before reusing a result.

## Status

The table summarizes the [records](#records). The [PI WEB](#pi-web) and
[Paseo](#paseo) records cover individual UIs; the
[local services record](#local-services-and-agent-builds) covers both UIs
running independently on the CPU, and
[Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools)
covers all four clients on the GPU.

- **Supported**: the project intends to maintain the stated feature, version,
  or environment. This is a maintenance promise, not proof that it works.
- **Expected**: technical evidence supports the claim, but no recorded
  validation run has confirmed it.
- **Validated**: a defined procedure passed, with a record in
  [Records](#records).
- **Unverified**: no recorded evidence supports the claim yet.

| Claim | Term | Engine and host | Record |
| --- | --- | --- | --- |
| The CLI refuses a malformed `LLM_PORT`, `--sets` with oh-my-pi, a repeated single-valued flag, a benched preset named twice, an unknown default preset, and `ui stop` of an unknown set, each with one sentence and before the pre-flight | Validated | RTX 5090, rootless Podman 6.1.1 | [The pre-release polish pass](#the-pre-release-polish-pass) |
| A browser UI stops through its launcher's signal handler in 1 to 3 seconds rather than through the container's 20-second stop grace period, and the pi image supervising a UI runs 4 processes for PI WEB and 11 for Paseo against its 512 `pids_limit` | Validated | RTX 5090, rootless Podman 6.1.1 | [The pre-release polish pass](#the-pre-release-polish-pass) |
| Local model and UI API requests bypass host HTTP proxies; the ordinary urllib transport retains proxy handling | Validated | Python 3.14.7, engine-free harness with loopback listeners | [Local services and agent builds](#local-services-and-agent-builds) |
| Whole-stack shutdown removes live terminal agents, the model, and all project networks; startup succeeds afterwards | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture | [Local services and agent builds](#local-services-and-agent-builds) |
| HTTP and WebSocket authorization accepts implicit and explicit port 80 for the exact loopback authorities and rejects foreign hosts, origins, sibling ports, and disallowed Fetch Metadata | Validated | Node.js 24.20.0, engine-free harness with unprivileged listeners | [HTTP authorities and label discovery](#http-authorities-and-label-discovery) |
| Terminal pi and omp in RPC mode, PI WEB through its HTTP API, and Paseo through its daemon CLI answer sequentially while all clients stay alive, with one unchanged router and loaded model process | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture; RTX 5090 on the shipped preset | [Local services and agent builds](#local-services-and-agent-builds), [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| Both terminal agents cannot reach either live UI or forwarder by name or effective container address, with and without egress | Validated | Both engines, CPU fixture | [Local services and agent builds](#local-services-and-agent-builds) |
| The nine loadable presets in the linked record run through CDI, pass every `smoke` check (including streamed tool calls and mid-conversation system messages), and hold 3 to 7 GiB less than `[requires]`. `bench` measures the MTP preset at about twice the generation speed of the two-slot preset using the same file | Validated | RTX 5090, driver 610.57.04, rootless Podman 6.1.1 | [The llama API and the presets](#the-llama-api-and-the-presets) |
| `gpt-oss-20b-small` and `qwen3.8-27b-q3-small` pass every `smoke` check and hold 12.7 and 13.5 GiB, 2.3 and 1.5 GiB less than the 15 GiB they declare | Validated | RTX 5090, driver 610.57.04, rootless Podman 6.1.1 | [The 16 GB presets](#the-16-gb-presets) |
| The 96 GB tier and the 27B variants hold less than `[requires]` and pass every `smoke` check; Flash-Next reuses a session's growing prompt, and the settings behind `n_cpu_moe`, the 2048 micro-batch, and the unset `load-mode` are measured | Validated | RTX 5090 with 96 GB of RAM | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| The pi image renders and builds for `coding`, `coding,debug,dotnet,web,browser`, and `coding,debug,odin` from the pinned Node base image; each passes the agent check with the toolchain probes; prompts complete on CPU and GPU, with answers checked in the GPU record | Validated | Rootless Podman, with and without a GPU; Docker Engine 29.7.2 without one | [pi and the agent sets](#pi-and-the-agent-sets), [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Both agents run on the GPU with one scripted prompt each: pi edits and commits a file, every agent check passes for the default and the toolchain selections and for oh-my-pi, and both resume a transcript with `--continue` in a new container | Validated | RTX 5090, rootless Podman 6.1.1 | [pi and the agent sets](#pi-and-the-agent-sets), [oh-my-pi](#oh-my-pi) |
| The thinking levels reach the Qwen template; on a task that needs reasoning the 27B generated monotonically more tokens at each level, and on a one-line answer the level made no difference (the effort is an instruction, not a budget) | Validated | RTX 5090 | [pi and the agent sets](#pi-and-the-agent-sets) |
| `ui pi-web` and `ui paseo` start from their sets, answer through the forwarder on loopback, refuse a foreign origin, and run one prompt through pi | Validated | Rootless Podman 6.1.1 with the GPU; both engines without one | [PI WEB](#pi-web), [Paseo](#paseo), [Docker Engine](#docker-engine) |
| PI WEB answers successive sessions, reopens its transcript after a restart, runs browser terminal panels, and shares a project with a terminal agent; Paseo answers after recreation and keeps its identity | Validated | RTX 5090, rootless Podman 6.1.1 | [PI WEB](#pi-web), [Paseo](#paseo) |
| A terminal agent of another project cannot resolve a running UI or its forwarder, with or without `--egress`, and its agent check finds nothing but the three egress routes it asked for; on Docker the internal networks have no gateway address | Validated | Both engines | [Cross-project containment](#cross-project-containment), [Docker Engine](#docker-engine) |
| `tests/integration.py` passes on the GPU: the fixture presets through the router, the full and basic probes with the swap between them, `bench`, the three pi selections and oh-my-pi contained and answering, each agent's thinking level reaching the template, and the four home lifecycles | Validated | RTX 5090, rootless Podman 6.1.1 | [The integration run and the home lifecycles](#the-integration-run-and-the-home-lifecycles) |
| Agent homes keep transcripts, oh-my-pi blobs, and browser-UI state and identity through stop/start and recreation; live settings and other home files do not persist, and a terminal and a UI container on one project share transcripts only | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2 | [Local services and agent builds](#local-services-and-agent-builds) |
| `tests/integration.py` passes on the CPU with the fixture models | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, Arch Linux VM, no GPU | [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Four clients answer in turn on the shipped MTP preset with one unchanged router and model process, each forwarder refuses foreign and sibling authorities, and a second client queues behind the first: one request takes 7.5 seconds alone and two issued together 14.6 seconds, at unchanged generation speed | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The default preset serves a coding session of a dozen turns in its 64K slot: pi compacts the prompt when it fills and continues, and a session whose turns read 20 KB files refills the slot within two turns; one overflow compaction at 63,312 tokens failed because its summary hit the token cap | Validated | RTX 5090 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| A GPU session calls `lens_diagnostics`, the `debug` tool over js-debug, the subagent tool, and the browser tools | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The `coding` set seeds its subagent definitions without a `model:` line, so a subagent runs on the session's own model: the scout returned a delegated result on the GPU in 24 seconds. The image build and the agent check refuse a definition that names a model of its own | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| Long sessions stay far inside the 256 MiB home tmpfs: 424 KiB after twelve pi turns, and oh-my-pi keeps its growth in the retained directories on disk (8.6 MiB after six turns) | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| oh-my-pi starts on the selected preset at `xhigh` without its onboarding wizard, and its model picker saves a choice for the session: the entrypoint writes its settings into the home, where the picker's rewrite lands, and keeps the repository file as the overlay above it | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The abliterated 27B does not loop in longer runs: five of six long completions ended on their own, exactly as on the shipped preset, and a six-turn session ended every turn | Validated | RTX 5090 | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| `load-mode = "none"` on Flash-Next doubles prompt processing in an agent session too, and leaves the host 5 GiB of memory and 32 GiB of swap in use; the presets keep the memory map | Validated | RTX 5090 with 96 GB of RAM | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| Either 16 GB preset runs on a 16 GB card: both were measured on a 32 GB one, and the fit follows from what they held | Expected | RTX 5090 | [The 16 GB presets](#the-16-gb-presets) |
| Loading and inference with `glm-5.3-flash-q2` and `glm-5.3-flash-q2-uncensored` on a build with `glm5next`; the pinned build lacks the architecture, and the preset settings await smoke and benchmark measurements | Unverified | RTX 5090 with 96 GB of RAM | [The GLM-5.3-Flash presets](#the-glm-53-flash-presets) |
| Docker Engine 29.7.2 with Compose 5.5.1 runs every part of the procedure that needs no GPU: `doctor`, `tests/integration.py` to completion with a first build of the agent images on Docker's store, the agent checks of the `pi-web` and `paseo` sets, both UIs through the forwarder, the cross-project check, and the four home lifecycles; the Compose files render with the Docker CLI in the static gate | Validated | Docker Engine 29.7.2, Arch Linux VM, no GPU | [Docker Engine](#docker-engine) |
| Gateway mode `isolated` keeps host services off the agents network on Docker Engine versions between 28 and 29.6; only 29.7.2 has a record, where the agent check also found no default route and no external name resolution. The mode is documented from 28 on and `doctor` checks for 28 | Expected | Docker Engine 29.7.2 | [Docker Engine](#docker-engine) |

### Still unverified

These checks remain open. Passing the engine-free gate or CPU integration
does not complete them:

- the GLM presets on a llama.cpp release that carries `glm5next`: run the
  fallback ladder of `glm-5.3-flash-q2`, then `glm-5.3-flash-q2-uncensored`,
  each with `smoke` and `bench`, and record the build number with the
  numbers;
- Docker Engine with the GPU, and the Docker integration workflow in CI;
  the GPU host has no Docker Engine installed;
- a task that a subagent or the `debug` tool carries through to the end:
  the [GPU record](#four-clients-long-sessions-and-the-tools) shows both
  tools running, and the model finished neither task;
- whether the `[requires]` values of the presets no session has filled
  leave the right headroom; the default preset held the same 20.1 GiB
  with an empty and a full 64K slot;
- the UI launchers' readiness timeouts, which report a daemon that
  never answers: no recorded run has had one fail to start.

## Environment

The pins under test, as `bash bin/tokencrate pins` prints them:
`LLAMA_CPP_TAG=server-cuda13-b11028` (`llama-server --version` prints
`build 11028, commit 972d2313b`), `PI_VERSION=0.85.1`,
`OMP_VERSION=18.2.5`, `NODE_TAG=26.9.0-bookworm-slim`,
`BUN_TAG=1.4.2-slim`, `CUDA_MIN_DRIVER_MAJOR=580`, each image with the
digest in `pins.env`. The agent sets pin PI WEB 1.202609.0, Paseo 0.8.0,
the .NET SDK 10.0.401, Chromium 153.0.8010.52, and Odin
`dev-2026-08-nightly:902106f`. Unless a record states otherwise, agent
sessions used `LLM_AGENT_SETS=coding`, with
`LLM_SKILL_SETS=pocock-core,skill-crate`, and on the GPU with the model
set `qwen3.8-27b-ud-q4-k-xl` and the preset `qwen3.8-27b-q4-mtp`
(`n_ctx` 65536).

Two machines appear in the records. **The GPU host** is Linux x86-64
(kernel 7.2.4) with an NVIDIA GeForce RTX 5090 (32607 MiB, driver
610.57.04, CUDA 13.3, CDI device `nvidia.com/gpu=all`), 93.35 GiB of
system memory (MemTotal 97883376 kB) and 46 GiB of swap, rootless Podman
6.1.1 with podman-compose 1.6.0, `crun`, and netavark 2.1.0, Python
3.14.7, host UID:GID `1000:1000` with `keep-id`, and no Node.js, so the
engine-free gate cannot run there. **The virtual machine** is Arch Linux
(kernel 7.2.4) with no GPU, rootless Podman
6.1.1 with `crun` and podman-compose 1.6.0, Docker Engine 29.7.2 with
Compose 5.5.1 for the Docker runs, Python 3.14.7, Node.js, and Ruff.
The CPU and Docker integration records used 12 virtual CPUs and
31.3 GiB of RAM. Each record names its relevant resource allocation.

## Procedure

### Engine-free and CPU checks

Run on any Linux machine with a container engine:

```bash
bash tests/static.sh
python3 tests/integration.py
```

The static gate needs no engine beyond a Compose render; the integration
check runs the real commands against the fixture models on the CPU
([CONTRIBUTING.md](../CONTRIBUTING.md#tests) says what each runs). Neither
proves anything about the GPU or about the quality of the shipped
presets.

### NVIDIA host baseline

On the NVIDIA host under test, with the pins under test in `pins.env`:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-set qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate status
bash bin/tokencrate smoke
bash bin/tokencrate bench --preset qwen3.8-27b-q4 --preset qwen3.8-27b-q4-mtp
```

Then `smoke --preset` and `bench --preset` for every other shipped preset
the host can load, and these hands-on checks:

- Open the built-in UI at the root address, select the default preset,
  send a message, and confirm the answer arrives and the reasoning block is
  shown; select another preset and confirm the model swap in `status`.
- Confirm in `nvidia-smi` that llama-server holds GPU memory and that the
  bench report's generation speed is within a few percent of the
  record for the same preset.
- Start `bash bin/tokencrate agent pi --dir <project>` in a small project,
  ask for a one-line change, and confirm the file changes and a commit
  succeeds.
- Run `bash bin/tokencrate smoke --agent pi`.
- Recreate the container with `down` and `up`, and confirm the agent
  sessions under `data/agents/pi/` are still present.

Repeat with `CONTAINER_ENGINE=docker` when the Docker path changed. Stop
after a failure; fix it or describe it before calling the result validated.
After a pin upgrade, [Upgrading](configuration.md#upgrading) says which
part of the procedure applies.

### Agent home check

Run on both engines after a change to the agent volumes in
`compose.yaml`, the entrypoint, or a UI launcher:

```bash
python3 tests/integration.py -k home_lifecycle
```

This selects the pi, oh-my-pi, PI WEB, and Paseo home checks, with the
integration setup and `down` around them; see
[setup requirements](../CONTRIBUTING.md#tests). The checks themselves use
no model.

Each check renders the production agent service through the wrapper and
keeps its tmpfs, hardening, user mapping, and retained mounts. It uses the
built image in a disposable Compose project with scratch retained
directories and networking disabled. Terminal containers run `sleep`;
UI containers run their launchers and daemons. The checks verify that:

- every home tmpfs is owned by the host user and writable;
- host files outside the retained directories never enter the home;
- the agent's session manager saves and reopens a transcript;
- a second container on the same project shares the transcript without
  sharing live settings or UI state;
- stop/start and recreation preserve retained directories, including
  Paseo's identity, and reset the rest of the home.

Repeat with `CONTAINER_ENGINE=docker`. These checks do not test the
production network, forwarder, or model.

### Cross-project containment check

Run on both engines after a change to the Compose networks, the forwarder,
or the agent check. Copy `tests/fixtures/model-sets/ci-small.toml` into
`config/model-sets/` and `tests/fixtures/presets/ci-small.toml` into
`config/presets/`, set `LLM_DEFAULT_PRESET=ci-small` (and `LLM_GPU=false`
on a host without a GPU), create two scratch projects A and B below the
home directory, then:

1. `bash bin/tokencrate up --model-set ci-small`, then
   `bash bin/tokencrate ui pi-web --dir A` and
   `bash bin/tokencrate ui paseo --dir A`.
2. `bash bin/tokencrate smoke --agent pi`: the check must report that
   every active UI service and forwarder is unreachable by name and
   current container address and, on Docker, that the agents network has
   no gateway address.
3. Run the agent check for project B without and with the egress
   overlay (a terminal session cannot run a shell command through
   `agent`, so the script starts the container the way the wrapper
   does and passes the active UI names and addresses into the image's
   agent check):

   ```bash
   .venv/bin/python tests/manual/cross-project-check.py B
   ```

   Without egress every line must pass. With egress the route checks
   fail by design; every UI peer must still be unreachable. On a host
   with a GPU and the shipped model set, name the loaded preset as the
   second argument instead of copying the fixture.
4. `bash bin/tokencrate ui stop`, `bash bin/tokencrate down`, and remove
   the fixture copies.

### Independent-client check

Inspect existing containers first. Use an isolated checkout, Compose
project, scratch client directories, retained state, and free host ports;
`tests/integration.py` takes over the configured project. Run the focused
check on each engine:

```bash
python3 tests/integration.py -k concurrent_clients
```

`tests/concurrent_clients.py` keeps pi and omp alive in RPC mode,
creates a fresh PI WEB session through its published API, and drives a
Paseo session through the daemon. It checks assistant messages and the
effective `ci-small` model, including Paseo's saved provider model and
that invocation's own transcript. It repeats the pi prompt, checks both
UI IDs, and compares router/model PIDs and kernel start times within an
unchanged router container. It also exercises targeted stops, retained
state, project and image changes, near-simultaneous starts, occupied
ports, failed custom-set launches, both forwarders' Host/Origin checks,
and name/address containment from both terminal agents with and without
egress.

For browser and terminal-screen acceptance, follow the
[four-client workflow](agents.md#use-four-clients-with-one-model) with
separate conversations. Confirm the effective preset in each client,
especially Paseo's retained profile; wait for PI WEB's title request
before the next prompt. Record actual assistant responses, router and
model-process identities, UI IDs, and listener addresses before and
after. Test the defaults separately from free-port integration runs.
A banner, health response, or live process does not establish a prompt
response. Keep GPU and browser claims unverified until those runs exist.

### Recording a result

Add a section under [Records](#records), headed by the subject, with:

- Purpose and the run date;
- Environment: pins from `bash bin/tokencrate pins`, tested tree, engine
  and version, GPU and driver; name differences from
  [Environment](#environment) instead of repeating it;
- results, including the smoke and benchmark reports;
- a closing "Not covered" paragraph.

Replace records for subjects the run repeated, using the new run's date.
Update the affected [Status](#status) rows and measured columns in the
[preset table](models.md#included-presets). Keep dates and evidence for
subjects the run did not repeat.

## Router behavior the wrapper relies on

These observations guide changes to the wrapper. They used llama.cpp
build b10920's official image in router mode (`--models-preset`,
`--models-max 1`) with CPU fixture models. They are not a complete
validation record.

On b11028, CPU integration confirms readiness polling, preset switching,
and preset-file behavior. It does not cover the failure codes, offline
behavior, or image details below. Repeat these observations after a
`LLAMA_CPP_TAG` change.

- Readiness: `GET /health` answers `{"status":"ok"}` while the default
  preset is still `loading` in `GET /models`, so `up` polls `/models` for
  `loaded` (`runtime.wait_until_ready`).
- Swap: a request whose `model` names another preset waits until the
  running request has finished, then the router unloads the loaded model
  and loads the other one; `POST /models/load` answers 400 for the model
  that is loading or loaded and 500 `model limit reached` for another
  model while one is loaded, so `up` asks for a load only when nothing is
  loaded.
- Failure: a preset whose model server exits leaves the router running,
  `/models` reports it `unloaded`, and a request for it answers 500; `up`
  fails when the default preset turns `unloaded` after `loading`.
- Requests without `model` answer 400 `model name is missing from the
  request`; `GET /props`, `POST /tokenize`, and `GET /metrics` need
  `?model=` or a `model` field, which the probe sends.
- Preset file: keys are llama-server option names without dashes
  (`jinja = true` becomes `--jinja`, `ui-config-file`
  `--webui-config-file`, `gpu-layers` `--n-gpu-layers`); a key given twice
  keeps the last value silently; keys in `[*]` reach every child; an
  unknown key stops the router at start with `option '<key>' not
  recognized in preset '<name>'`, which is why the renderer keeps a typed
  vocabulary and passes `[server.extra]` through unchanged.
- Offline: with `LLAMA_ARG_OFFLINE=1` a `mmproj-url` section looks in the
  cache and never contacts the host; a `docker-repo` section fetches the
  Docker Hub manifest in both modes, so the renderer refuses that option.
- Image: `/usr/local/cuda*/compat` exists in the official image, so
  `services/llama/Dockerfile` removes it; the image sets
  `LLAMA_ARG_HOST=0.0.0.0`, which the router's `--host` overrides for every
  child; every child's log line is re-logged with the child's port in
  brackets.
- The UI at the root is a build with router-mode model selection.

## Records

### The llama API and the presets

Purpose: the GPU path for the nine presets listed below, following the
[NVIDIA host baseline](#nvidia-host-baseline). Date: 2026-09-20.
Environment: the GPU host on the shipped pins. `bench` ran
three iterations with a 262-token and a 6,052-token prompt, prompt
caching off. "Held" is `nvidia-smi` after `smoke` minus what the desktop
held before the run (995 MiB).

- `doctor`: 20 `[ok]` lines, 0 failures and 0 warnings; the driver, the
  CDI device, `Podman 6 keeps bridge networks apart`, and 32 GiB against
  the default preset's 24 GiB.
- `up` rendered every preset except the two GLM ones and reported the
  default preset loaded in 7 seconds with the files on disk and the
  runtime image already built. The two GLM presets were listed as
  `waits for an unreleased llama.cpp build (pinned: b11028)`, and the
  router listed every rendered preset.
- `smoke` on the default preset, 8 of 8 checks `pass`: the model listing,
  a chat completion of 42 characters in 0.4 seconds at 134.8
  tokens per second, the streamed tool call `get_weather({"city":
  "Paris"})`, the mid-conversation system message (answer `42`),
  `finish_reason stop` on both completions, the template render of 466
  characters including the later system message, efforts `low` and
  `medium` rendering different prompts, and `tokenize`. The same checks
  passed on the other eight presets in this record.
- GPU memory held while each preset was loaded, against its
  `[requires]`:

  | Preset | Held | `[requires]` |
  | --- | ---: | ---: |
  | `qwen3.8-27b-q4-mtp` | 19.8 GiB | 24 GiB |
  | `qwen3.8-27b-q4` | 18.8 GiB | 24 GiB |
  | `qwen3.8-27b-q4-long` | 21.1 GiB | 28 GiB |
  | `qwen3.8-27b-q4-mtp-f16kv` | 21.5 GiB | 25 GiB |
  | `qwen3.8-27b-q4-mtp-uncensored` | 19.7 GiB | 24 GiB |
  | `qwen3.8-27b-q6-quality` | 25.9 GiB | 30 GiB |
  | `qwen3.8-flash-next-q4` | 26.2 GiB | 30 GiB |
  | `qwen3.8-flash-next-q4-uncensored` | 26.4 GiB | 30 GiB |
  | `gpt-oss-20b-fast` | 15.1 GiB | 20 GiB |

- `bench` per preset (llama-server timings): generation and prompt
  speeds in tokens per second, for the short and the long prompt:

  | Preset | Generation (short, long) | Prompt (short, long) |
  | --- | --- | --- |
  | `qwen3.8-27b-q4-mtp` | 138, 154 | 1,139, 3,064 |
  | `qwen3.8-27b-q4` | 75, 74 | 1,350, 3,320 |
  | `qwen3.8-27b-q4-long` | 76, 75 | 2,089, 3,517 |
  | `qwen3.8-27b-q4-mtp-f16kv` | 143, 144 | 1,838, 3,205 |
  | `qwen3.8-27b-q4-mtp-uncensored` | 151, 143 | 1,803, 3,221 |
  | `qwen3.8-27b-q6-quality` | 113, 100 | 1,000, 2,707 |
  | `qwen3.8-flash-next-q4` | 34, 33 | 119, 740 |
  | `qwen3.8-flash-next-q4-uncensored` | 34, 35 | 111, 774 |
  | `gpt-oss-20b-fast` | 264, 246 | 7,601, 22,449 |

  The MTP preset generated about twice as fast as the two-slot preset of
  the same file. A second run of both repeated the generation numbers
  within one percent; its prompt speeds differed by up to half, which is
  cache state, not the preset. The `qwen3.8-flash-next-q4` row is from
  the runs of [the 96 GB tier record](#the-settings-of-the-96-gb-ram-tier)
  on llama.cpp build b10920; every other row is from the pinned build.

Not covered: the two GLM presets, which the pinned build does not load
([The GLM-5.3-Flash presets](#the-glm-53-flash-presets)); the two
[16 GB presets](#the-16-gb-presets), measured separately.

### The 16 GB presets

Purpose: the first GPU measurement of `gpt-oss-20b-small` and
`qwen3.8-27b-q3-small`, following the [NVIDIA host
baseline](#nvidia-host-baseline) with the steps `init facts doctor up
status presets down`. Environment: the GPU host; the desktop held 649 MiB
before the run, which "Held" subtracts. Date: 2026-09-20.

- `doctor`: 19 `[ok]` lines, 0 failures and 0 warnings. `up` rendered 10
  of the 13 presets and skipped `qwen3.8-27b-q3-small` for its missing
  file, downloaded the 13.1 GB UD-Q3_K_XL file, then rendered 11 of 13;
  the router listed 11 models.
- `smoke`: every check `pass` on both presets, the streamed tool call and
  the mid-conversation system message included. The three-bit 27B also
  passed the 466-character template render and ended both completions
  with `stop`, so nothing looped in its reasoning.
- Held against `[requires]`, and what a 16 GB card (about 16.0 GiB) has
  left, before whatever its desktop takes:

  | Preset | Held | `[requires]` | Free on a 16 GB card |
  | --- | ---: | ---: | ---: |
  | `gpt-oss-20b-small` | 12.7 GiB | 15 GiB | 3.3 GiB |
  | `qwen3.8-27b-q3-small` | 13.5 GiB | 15 GiB | 2.5 GiB |
  | `gpt-oss-20b-fast` | 15.1 GiB | 20 GiB | none |

- `bench`, three iterations with a 278-token and a 6,068-token prompt for
  gpt-oss and a 262-token and a 6,052-token one for the 27B, prompt
  caching off:

  | Preset | Generation (short, long) | Prompt (short, long) |
  | --- | --- | --- |
  | `gpt-oss-20b-small` | 260, 244 | 7,544, 22,279 |
  | `gpt-oss-20b-fast` | 263, 248 | 7,619, 22,396 |
  | `qwen3.8-27b-q3-small` | 91, 89 | 1,282, 3,465 |

  The shorter slot costs gpt-oss nothing but context: both presets of that
  file are within two percent of each other, and `gpt-oss-20b-fast`
  repeated its 15.1 GiB from [the preset
  record](#the-llama-api-and-the-presets). The three-bit 27B generated
  faster than `qwen3.8-27b-q4`, the Q4 preset that also does not draft
  (75, 74), because less of a smaller file is read per token. Drafting
  would take it to about 14.5 GiB, which is why the preset leaves MTP off.

Not covered: a 16 GB card, which no run here has; an agent session on
either preset; what three bits cost the 27B on agent work.

### pi and the agent sets

Purpose: the pi image for the three shipped selections, its agent check,
a scripted task, the thinking levels, and terminal resume, all on the
default 27B preset. Environment: the GPU host; the pi images built from
the pinned Node base image, pulled by its digest, `coding` from scratch
and the other selections reusing its cached layers.

- `smoke --agent pi` for `coding`, `coding,debug,dotnet,web,browser`,
  and `coding,debug,odin`: `Agent check completed with 0 failure(s).`
  each time, with every containment line `[ok]`: the model endpoint
  reachable, no default route, no route to `1.1.1.1`, no name resolution,
  `agent-ui` and `ui-forward` not resolving, the gateway `10.89.1.1`
  answering from the user's network namespace, the root filesystem
  read-only, the project mounted, and 5, 7, and 6 pi packages seeded. The
  toolchain probes: `dotnet 10.0.401 builds the xunit template from the
  cached packages`, `js-debug answers a DAP initialize request over
  stdio`, `Chromium 153.0.8010.52 built on Debian GNU/Linux 12 (bookworm)
  runs headless`, `odin version dev-2026-08-nightly:902106f builds and
  runs a program`.
- `agent pi -p ...` at `xhigh` in a fresh Git project: pi created
  `hello.txt` with the `write` tool, committed `add hello` with the
  `bash` tool, and answered `done` in 13 seconds of wall time including
  the container start; `.git/config` held only `[core]` and no hook was
  installed. Its first request was 8,011 prompt tokens; the first
  requests of the two toolchain selections were 9,704 and 8,942.
- A one-line answer through `agent pi` at `low`, `medium`, and `xhigh`
  took 12, 12, and 10 seconds; through the two toolchain selections 13
  seconds each. The router's `usage.input` counts only the prompt tokens
  it processed, so a later turn with a prompt-cache hit reports a few
  tokens; a request-size figure is the first, uncached request.
- The thinking levels, through `agent pi` on the `coding` selection, on
  a task that needs reasoning, with the tokens generated per turn
  (thinking and answer together, from the router log) and the turn time:

  | Level | Tokens | Turn |
  | --- | ---: | ---: |
  | `low` | 258 | 12s |
  | `medium` | 503 | 13s |
  | `high` | 573 | 16s |
  | `xhigh` | 714 | 13s |

  The level reaches the template and, on this task, the model spent
  monotonically more tokens at each step; on a one-line answer the
  levels made no difference. The effort is an instruction, not a budget.
- pi answered a marker prompt and recovered the marker with `--continue`
  in a new container. A command-valued credential planted in the host
  directory of the agent home, outside the retained subdirectories,
  never entered the container: its marker was not created.
- The transcripts of every session are under the project's
  `.pi/agent/sessions` directory below `LLM_AGENTS_DIR/pi/`. GPU memory
  after the sessions was 21296 MiB in use, against 21239 MiB after
  `smoke`; the image builds, the agent checks, and the prompts of both
  agents took 350 seconds in all.

Not covered: a task a subagent carries out end to end; the `odin` set's
debug adapter in a session.

### oh-my-pi

Purpose: the oh-my-pi image, its agent check, a prompt, and terminal
resume on the default 27B preset. Environment: the GPU host; the image
`agent-omp:18.2.5-bun1.4.2-slim` from the pinned Bun base image.

- `smoke --agent omp`: `Agent check completed with 0 failure(s).` with
  every containment line `[ok]`; the mount list showed the four retained
  binds (`sessions`, `custom-session-files`, `blobs`,
  `terminal-sessions`) and the read-only `AGENTS.md`.
- `agent omp -p ...` answered `hello` in 11 seconds of wall time
  including the container start. The retained transcript records
  `model_change tokencrate/qwen3.8-27b-q4-mtp`, `thinking_level_change
  xhigh`, the prompt, and the answer with `usage.input 19028` and
  `usage.output 16`; the terminal breadcrumb `terminal-sessions/pts-0`
  was written too.
- oh-my-pi answered a marker prompt and recovered the marker with
  `--continue` in a new container.

Not covered: the language-server, subagent, and MCP features.

### Cross-project containment

Purpose: what a terminal agent of another project can resolve while a
browser UI serves a project, following the [cross-project containment
check](#cross-project-containment-check) with the shipped model set
instead of the fixture. Environment: the GPU host; PI WEB serving
project A on `tokencrate_ui` at `10.89.2.3:8504`, reached by the
forwarder from `10.89.2.4`; the agents network with its gateway
`10.89.1.1`.

- `smoke --agent pi` while the UI ran: 0 failures, with `[ok] agent-ui
  does not resolve` and `[ok] ui-forward does not resolve`.
- `tests/manual/cross-project-check.py B qwen3.8-27b-q4-mtp`: without
  egress, `getent hosts agent-ui ui-forward` printed nothing and the
  agent check passed with 0 failures, every containment line `[ok]`.
  With the egress overlay, exactly the three route findings failed (a
  default route, `1.1.1.1` reached, `example.com` reached), the two UI
  names still did not resolve, the check ended with 3 failures, and the
  wrapper reported the non-zero exit, which is the expected result of
  that run. Project B's agent home gained an empty `sessions` directory
  and no session.

Not covered: a connection attempt to the UI container's and the
forwarder's addresses ([Still unverified](#still-unverified)); the same
check with `agent omp`.

### PI WEB

Purpose: the `pi-web` set through `ui pi-web`: readiness through the
forwarder, the retained binds, successive sessions, a restart, and a
terminal agent on the same project. Environment: the GPU host; the
image for `coding,pi-web`; the forwarder on the set's default port,
`127.0.0.1:4224`.

- `ui pi-web --dir A` was ready about 40 seconds after the command
  started, image build included; the launcher seeded
  `.pi-web/projects.json`, the session daemon started, and the web
  server listened on the container's addresses with `offline mode is
  enabled`. Through the forwarder a plain request got `200` and a
  foreign `Origin` `403`.
- The read-write binds below `/home/agent` were exactly `.paseo`,
  `.pi-web`, and `.pi/agent/sessions`, with no bind at `/home/agent`
  itself, equal to `agents.persistent_directories('pi', ui=True)`; the
  home held 104 KiB before the first session, the retained terminal
  transcripts included.
- Session 1 answered `PI_WEB_OK_1` at `thinkingLevel low` on
  `qwen3.8-27b-q4-mtp` with 8,508 input tokens, about 3.5 seconds after
  the prompt was posted.
- `podman restart --time 10` of the UI container: the session daemon
  restarted, the web server listened again, and `GET
  /api/sessions/<id>/messages` for session 1 answered `200` about 8.5
  seconds after the restart; a file planted in the home before the
  restart was gone. Session 2 then answered `PI_WEB_OK_2` with 11,276
  input tokens, about 4.8 seconds after its prompt. Both transcripts are
  in the retained `sessions` directory; `.pi-web/` holds
  `projects.json`, `session-unread.json`, `sessiond-owner.json`, and
  `pi-package-dismissals.json`, which names `@jmfederico/pi-relay`, so
  the relay package stays out of pi's package list.
- A terminal pi process answered while the UI stayed running on the same
  project; its start left the UI's live settings and temporary files
  intact, and a restart reset both while PI WEB reopened its saved
  transcript. PI WEB then resumed the terminal transcript, accepted a
  plan-mode question response, and wrote files in the scratch project.
  Two browser terminal panels accepted keyboard input and displayed the
  output of `printf`. Host files outside the retained subdirectories
  stayed invisible to the container.

Not covered: the session title request; a conversation that several
browser tabs write at once.

### Paseo

Purpose: the `paseo` set through `ui paseo`: readiness through the
forwarder, a prompt through Paseo's CLI, and the identity through `ui
stop` and a new `ui paseo`. Environment: the GPU host; the image for
`coding,paseo`; Paseo reports `daemonVersion 0.8.0`, listens on port 6767
inside the container with `authRequired false`, and logs its speech
providers as unavailable.

- `ui paseo --dir A` printed `paseo is ready`; through the forwarder
  `/api/health` got `200` and a foreign `Origin` `403`. The launcher
  registered the project as a workspace.
- `paseo run --provider pi --thinking low 'Reply with exactly
  PASEO_OK_1.'` reported the agent `completed`; the daemon created the
  agent in 6.4 seconds and it finished 3.0 seconds later, and its pi
  transcript holds `PASEO_OK_1` at `low` with 7,970 prompt tokens. The
  home held 788 KiB after this prompt.
- `ui stop`, then `ui paseo --dir A` again: the daemon loaded its
  keypair about 6.4 seconds after the shutdown call; the `server-id` and
  `daemon-keypair.json` files were byte for byte the same before and
  after and equal to the copies under
  `LLM_AGENTS_DIR/pi/paseo-identity/`; a file planted in the home before
  the stop was gone; `Agent registry loaded (1 record)`.
- A second `paseo run` reported `completed` with `PASEO_OK_2`: the agent
  was created in 6.5 seconds and finished in 0.4 seconds, because the
  router processed only 20 new prompt tokens on a prompt-cache hit. Both
  agent records persisted under `.paseo/agents/` with `lastStatus
  closed`, `config.model tokencrate/qwen3.8-27b-q4-mtp`, and
  `thinkingOptionId low`; the seeded `config.json` keeps the single
  `tokencrate-qwen3.8-27b-q4-mtp` profile at `xhigh` and every other
  provider disabled. The daemon logged nothing above a warning.
- Through a Firefox 155 connection after a recreation the same
  transcript gained a user message and an assistant reply, and a new
  browser conversation answered.
- Each `paseo run` without `--workspace` created a workspace of its own
  for the same checkout, so `workspaces.json` lists three `master`
  workspaces for project A after the run; the launcher registers one.

Not covered: what a Paseo agent does with a task beyond one prompt.

### Four clients, long sessions, and the tools

Purpose: the items that only a GPU host can settle: four clients on the
shipped MTP preset, whether a second client queues on it, sessions beyond
one prompt for pi, oh-my-pi, and PI WEB, long-session home capacity, and a
session that calls `lens_diagnostics`, the `debug` tool, the subagent tool,
and the browser tools. Environment: the GPU host, `LLM_AGENT_SETS=coding`,
the default preset unless a line names another, both browser UIs on their
own default host ports (`4224` and `4250`); the desktop held 683 MiB before
the run, which "held" subtracts. Date: 2026-09-20.

- `doctor` passed with 0 failures and 0 warnings, `up` rendered 11 of 13
  presets and reported the default preset loaded in 7 seconds, and `smoke`
  passed all 8 checks (42 characters at 133.5 tokens per second). The
  agent check passed with 0 failures for `coding`,
  `coding,debug,dotnet,web,browser`, `coding,pi-web`, `coding,paseo`, and
  oh-my-pi, with every containment line and the .NET, js-debug, and
  Chromium probes.
- Four clients on `qwen3.8-27b-q4-mtp`, in turn: terminal pi answered in
  2.7 seconds (first request 7,986 tokens), terminal omp in 7.8 seconds
  (19,032), PI WEB through its HTTP API, and Paseo through its daemon,
  whose saved agent record and own pi transcript both name the preset;
  a repeat pi prompt followed. The router kept one model process
  throughout (the same two PIDs and kernel start times before, between,
  and after). Each forwarder answered `403` to a foreign `Origin`, a
  foreign `Host`, and its sibling UI's origin, and a terminal agent of
  another project could neither resolve nor reach any UI peer, with and
  without `--egress`.
- A second client queues. The same prompt with an 800-token budget at
  effort `low`, three times: alone 7.5 seconds; two issued together
  finished after 7.4 and 14.6 seconds, 14.6 seconds for the pair. Generation
  stayed at 110 to 114 tokens per second in all three and the drafting
  numbers matched (about 1,100 tokens drafted, 420 to 434 accepted), so
  the second request waited for the slot instead of sharing it, as the
  preset's one slot implies.
- A pi session of 12 turns in one container, reading and editing files of
  8 to 21 KB: turns took 3.7 to 141 seconds and used `read`, `write`,
  `replace`, `insert`, `bash`, and `lens_diagnostics`. The prompt grew
  from 8,013 to 51,822 tokens by turn 10; pi compacted there and continued
  at 28,292; turn 12 reached 63,312 tokens of the 64K slot, ended with
  `length`, and its overflow compaction failed
  (`Summarization failed: generation hit the token cap and the summary is
  incomplete`), after which the agent stayed busy and refused the next
  prompt. The card held 21,238 MiB before the first turn and after the
  last, 20.1 GiB against the preset's 24 GiB `[requires]`: a full slot
  holds no more than an empty one, because llama.cpp allocates the cache
  when the model loads.
- An oh-my-pi session of 6 turns in one container, on
  `qwen3.8-flash-next-q4`: every turn ended on its own, the prompt grew
  from 26,845 to 39,298 tokens, and the home tmpfs stayed empty while its
  retained `.omp` directories grew to 8.6 MiB on disk.
- Home capacity in a long session: pi's home tmpfs held 96 KiB before the
  first turn and 424 KiB after the twelfth, of the 256 MiB the tmpfs
  offers, and its `/tmp` 10.5 MiB of 1 GiB. The homes these sessions left
  on the host are 336 to 864 KiB. Nothing approached a limit.
- PI WEB in a browser, resuming the 12-turn conversation: a reply ended
  with `length` at 63,359 tokens, PI WEB compacted (a 12,275-character
  summary), and the session continued at 15,076 tokens, read four files,
  and reached 63,729 two turns later. Compaction recovers the slot, and a
  session whose turns read 20 KB files refills it within two turns. Two
  other conversations in the same project answered normally, at 8,050 to
  8,539 tokens.
- The tool families, one scripted session each on the
  `coding,debug,dotnet,web,browser` image, with the tools the transcripts
  record:

  | Objective | Session | Tools called | Result |
  | --- | ---: | --- | --- |
  | `lens_diagnostics` on a type error | 77 s | `lens_diagnostics`, `read`, `anchor_grep`, `replace` | reported the diagnostic, fixed the file, and confirmed it clean |
  | the `debug` tool over js-debug | stopped at the run's 1,200 s limit | `debug`, `bash`, `read` | the adapter answered and the model kept debugging for 74 assistant messages, compacting once, without finishing the task |
  | the subagent tool | 51 s | `subagent`, `read`, `bash`, `replace` | the scout returned all three TODO comments with file and line |
  | the browser tools | 20 s | `chrome_devtools_navigate`, `chrome_devtools_evaluate` | returned the title, the `h1`, and the text the page's script wrote |

- The subagent definitions the pi package ships name models no container
  here can reach (`claude-haiku-4-5` in `scout.md`, `claude-sonnet-4-5` in
  `planner.md`, `reviewer.md`, and `worker.md`), which is why the `coding`
  set seeds them with the `model:` line removed. In this session the
  delegation reached the scout once the definition named the loaded
  preset.
- The four clients by hand, in real browser windows and terminal screens:
  every client answered its own conversation, nothing hung, and the model
  stayed loaded. Paseo's browser form created an agent that ran on
  `tokencrate/qwen3.8-27b-q4-mtp` at `xhigh` and closed normally; PI WEB
  served its terminal panel and an extension dialog, and its compaction
  of the long conversation above took a visible pause. oh-my-pi needs two
  settings of its own to open the same way: its onboarding wizard opens
  whenever the stored setup version is older than the binary's, which a
  home that is a fresh tmpfs makes every session, and its model picker
  saves by renaming a temporary file over `~/.omp/agent/config.yml`,
  which fails with `EBUSY` unless that path is writable. The next
  paragraph measures what the settings do about both ([Agent
  configuration](agents.md#agent-configuration) describes them).

What the shipped settings do about those two, and about the subagent
definitions, measured on the same host:

- The `coding` set strips the `model:` line from the subagent definitions
  it seeds, so each subagent runs on the session's own model and thinking
  level; the image build and the agent check refuse a definition that
  names a model of its own
  (`4 subagent definition(s) seeded, none pinned to another model` for
  every pi selection). A session then delegated with one `subagent` call
  and the scout reported all three TODO comments of a scratch project
  with file and line, in 24 seconds, ending on its own.
- The entrypoint writes oh-my-pi's settings into the home, where the
  picker's rewrite lands, and keeps the repository file as the overlay
  above it; the agent check performs that write (`the agent can save
  its settings for this session`). oh-my-pi answered a prompt in 10
  seconds, and its transcript records `model_change
  tokencrate/qwen3.8-27b-q4-mtp` with `resolvedModelIsFallback false` and
  `thinking_level_change xhigh`, so the seeded settings carry both. In an
  interactive session the model picker saved a choice, which the
  transcript shows as a `model_change` with `role default`, and no
  `EBUSY` followed.
- `startup.setupWizard: false` in the repository settings closes the
  onboarding wizard, whose first step asks to sign in to a provider no
  container here can reach; an interactive session started on the preset
  without it.

Not covered: Docker Engine with a GPU, which this host has no Docker
Engine for; a `debug` task the model finishes; the GLM presets.

### The integration run and the home lifecycles

Purpose: `tests/integration.py` on the GPU, whose four
`test_home_lifecycle_*` checks are the [agent home
check](#agent-home-check), and the same four checks on both engines of
the virtual machine. Environment: the GPU host with `CONTAINER_ENGINE=podman
LLM_GPU=true`, run as `python3 tests/integration.py -v --durations 0` on
the fixture models (`ci-small`, Qwen3-0.6B Q4_K_M; `ci-tiny`,
stories260K; the preset `ci-think`); the virtual machine with rootless
Podman 6.1.1 and with Docker Engine 29.7.2, no model, for the lifecycle
checks alone.

The GPU run: the setup fetched the skill sets, `doctor` passed with 0
failures and 0 warnings, `up` rendered 12 of 14 presets and reported
`ci-small` loaded; `Ran 9 tests in 179.956s`, `OK`; `git status --short`
printed nothing afterwards.

| Test | Duration | Result |
| --- | ---: | --- |
| `test_pi_answers_with_a_tool_call` | 38.2 s | the three selections exited 0 with output and without a load error; no file added to the project |
| `test_home_lifecycle_pi_web` | 30.8 s | the saved session reopened with text and image data; home 64 KiB |
| `test_agent_checks_pass` | 20.4 s | four checks with 0 failures |
| `test_home_lifecycle_paseo` | 18.7 s | passed; home 616 KiB |
| `test_thinking_level_reaches_the_template` | 16.6 s | both agents' `low` reached the `ci-think` template |
| `test_probes_swap_the_loaded_model` | 11.3 s | `smoke` on `ci-small`, the basic probe on `ci-tiny`, `bench` |
| `test_home_lifecycle_omp` | 9.8 s | the saved session reopened with text and image data; home 28 KiB |
| `test_home_lifecycle_pi` | 9.5 s | passed; home 40 KiB |
| `test_omp_answers` | 8.0 s | `hello` |

The lifecycle checks on the virtual machine ran for five selections on
each engine, ten runs, and every run passed: pi with the `dotnet`,
`web`, and `browser` sets; pi with the `odin` set; oh-my-pi; PI WEB;
Paseo.

- Every home mount ancestor was writable as `1000:1000` with mode
  `0750`. Podman needs the tmpfs option `U` and Docker `uid=1000,gid=1000`
  for that, and a tmpfs on the home alone leaves the nested mount
  ancestors root-owned, which is why every ancestor of a retained bind
  has an owned tmpfs of its own.
- The session managers saved and reopened text and image messages.
  Oh-my-pi's JSONL held a `blob:sha256:` reference and restored the
  image bytes from the retained blob store after stop/start and
  recreation. Its pinned sources (`session-paths.ts`,
  `session-manager.ts`, `pi-utils/src/dirs.ts`) name the terminal
  breadcrumbs and the custom session-file registry as its other resume
  and cleanup inputs, which is why those directories are retained too.
- Two concurrent containers shared a transcript without sharing live pi
  settings or other home files, and the terminal peer saw no UI state.
  Host files outside the retained directories stayed untouched and
  invisible to the container. Stop/start and recreation removed planted
  home files and settings changes, kept every retained-directory marker,
  and recreated the generated model list and the skills link.
- Both UI launchers reached HTTP readiness after the first start, after
  stop/start, and after recreation. PI WEB's terminal backend ran two
  shells. Paseo registered the scratch workspace and kept the exact
  keypair and server id through both restarts. Odin built and ran a
  program under `/tmp`.
- Home usage, retained binds included, stayed below 0.7 MiB: 464 KiB
  after the .NET first run, 248 KiB for oh-my-pi, 72 KiB for PI WEB, and
  656 KiB for Paseo; `/tmp` stayed below 8 MiB. These samples support
  the 256 MiB limit of each home tmpfs for these workloads, not an
  aggregate memory bound or a long-session capacity claim.

Not covered: the production network and the forwarder (the lifecycle
checks run with networking disabled), a real browser, and long-session
capacity.

### The settings of the 96 GB RAM tier

Purpose: the measurements behind the settings of the 96 GB tier: the
expert split, the micro-batch, the memory map, and the alternatives that
were tried and dropped. The presets' own results are in [The llama API
and the presets](#the-llama-api-and-the-presets). Environment: the GPU host
on llama.cpp build b10920; the [baseline procedure](#nvidia-host-baseline)
for the shipped settings and hand-run `smoke` and `bench` commands for
the alternatives, each alternative a temporary edit of a preset on the
host, reverted afterwards. `bench` ran three iterations with a 262-token and a
6,052-token prompt, prompt caching off. "Held" is `nvidia-smi` after
`smoke` minus what the desktop held before the run (739 to 1041 MiB).

The shipped settings:

- `up` downloaded and verified the abliterated 27B file (17.4 GB) in
  311 seconds in all; with the files on disk, `up` took 9 seconds.
- `smoke`: every check passed on every run of the four presets (three
  runs of the abliterated 27B, two of the f16 preset, and the Flash-Next
  presets after each change of their settings), and again on the three
  measured 27B Q4 presets. The `reply terminates` check found `stop` on
  all six completions of the abliterated 27B; the mid-conversation
  answer was `42` everywhere. The orcarouter Flash-Next file embeds
  Qwen's own template (8,952 characters, read from its header on the
  host), not the 27B's that the Unsloth file embeds; the patched
  template replaced it and the streamed tool call, the later system
  message, and the effort comparison passed.
- GPU memory held while loaded, generation and prompt speed in tokens
  per second for the short and the long prompt, against `[requires]`:

  | Preset | Held | `[requires]` | Generation | Prompt |
  | --- | ---: | ---: | --- | --- |
  | `qwen3.8-flash-next-q4` | 26.2 GiB | 30 GiB | 34, 33 | 119, 740 |
  | `qwen3.8-flash-next-q4-uncensored` | 26.1 GiB | 30 GiB | 37, 36 | 118, 776 |

  A second run repeated the 27B numbers within a few percent. The card
  had 4.2 and 4.3 GiB free with the two Flash-Next presets loaded (27916
  and 27803 MiB in use).
- Flash-Next at the 2048 micro-batch: two uncached 12,052-token prompts
  on `qwen3.8-flash-next-q4` processed at 729 and 788 tokens per second
  with no error in the log, so llama.cpp issue 28282 (a CUDA illegal
  memory access at this micro-batch on this card class, reported on a
  GLM model) did not show.
- The model server's load lines, with `verbosity = 4` in
  `[server.extra]` (the default 3 prints the library's warnings but none
  of its info lines), are where the memory split in the preset's own
  comment comes from. Two behaviours they show that the split does not:
  the loader reports `load_mode = mmap` and warns that tensor overrides
  to the CPU with mmap are slower than `--load-mode none`, and the
  server logs `forcing full prompt re-processing due to lack of cache
  data (likely due to SWA or hybrid/recurrent memory)` between requests
  that share no prefix.
- Flash-Next in system memory: `free` showed 7 GiB used, 86 GiB of page
  cache, and 86 GiB available while the Unsloth file was loaded, because
  llama.cpp memory-maps the weights and the kernel counts mapped file
  pages as cache; a desktop system monitor showed under 8 GiB in use
  throughout, and 3 GiB sat in swap with little swap traffic in `vmstat`.
  The first completion after a load took 23 and 38 seconds: the first
  request processed its 55-token prompt at 7.7 tokens per second and the
  second its 347 at 49, the page faults of the memory map.
- Prefix reuse on `qwen3.8-flash-next-q4` with prompt caching on: a
  6,052-token request processed at 606 tokens per second; the same
  conversation with the answer and one more turn appended reported
  `cache_n` 6048 and `prompt_n` 39, processed in 0.5 seconds. A
  session's growing prompt is reused, so a turn pays for its new tokens.
- An agent on Flash-Next: `agent pi --preset qwen3.8-flash-next-q4` in a
  fresh Git project created `hello.txt`, committed `add hello`, and
  answered `done` in six requests; the router log gives 8,011 prompt
  tokens for the first request, processed at 187 tokens per second at the
  default micro-batch (43 seconds before the first word), and 34 to 35
  tokens per second of generation. The run exported no Git identity, so
  the model set a repository-local `user.name` and `user.email` before
  committing, and said so.
- `smoke --agent pi --preset qwen3.8-flash-next-q4` ended with 0
  failures: the model endpoint reachable, no route and no name
  resolution, the root filesystem read-only, 5 pi packages seeded. It is
  the container check, so it proves reachability of Flash-Next, not a
  session on it.

The alternatives measured on Flash-Next, none adopted; every `smoke`
run passed, and "mapped" is the memory-mapped default:

| Preset and setting | Held | Prompt (short, long) | Generation | Verdict |
| --- | ---: | --- | --- | --- |
| `qwen3.8-flash-next-q4`, default micro-batch (512), 36 layers in system memory | 27.1 GiB | 119, 324 | 35, 34 | Less than half the long-prompt speed of the 2048 micro-batch |
| `qwen3.8-flash-next-q4`, 2048 micro-batch, 36 layers | 29.3 GiB (1.0 GiB free) | 102, 720 | 33, 32 | Too little headroom for a session; the shipped preset keeps 38 layers in system memory, which costs about 1 token per second of generation against the default-micro-batch row |
| `qwen3.8-flash-next-q4-uncensored`, default micro-batch, 36 layers | 23.8 GiB | 107, 328 | 37, 36 | The orcarouter file holds 3 GiB less at the same layer count, so its preset keeps 36 |
| `qwen3.8-flash-next-q4-uncensored`, default micro-batch, 34 layers | 26.6 GiB (3.8 GiB free) | 115, 346 | 38, 31 | No gain from two more expert layers on the card |
| `qwen3.8-flash-next-q4`, `load-mode = "none"`, default micro-batch, 36 layers | 27.2 GiB | 272, 689 | 34, 34 | `smoke` took 61 seconds including the load |
| `qwen3.8-flash-next-q4`, `load-mode = "none"` at the shipped settings (38 layers, 2048 micro-batch) | 26.2 GiB | 242, 1,315 | 33, 33 | Prompt processing doubles again, but `free` afterwards showed 69 GiB used, 58 shared, 24 available, under 1 GiB free, swap 9 to 10 GiB, and `vmstat` up to 2,953 pages swapped in per second during the bench: the experts sit in memory the kernel cannot reclaim, and the bench prompt touches little of the n-gram table, whose on-demand reads share the 24 GiB in real use. Not set; the preset comment gives the two lines that turn it on |

The KV-cache types on the 27B Q4 file with MTP, two runs that agree
within 1 percent: prompt speed the same for all three types; generation
for the short and the long prompt 135 and 152 (`q8_0`), 139 and 141
(`f16`), 142 and 136 (`bf16`). `nvidia-smi` right after `smoke` showed
22871 MiB in use with `qwen3.8-27b-q4-mtp-f16kv` (21.3 GiB held) and
23073 MiB with a bf16 copy of it (21.5 GiB held); both passed every
check at 145 and 143 tokens per second. bf16 holds as much as f16, as
the same element size predicts.

Checked from sources before the runs (the file headers were read from the
first megabytes of each file at the pinned commits, with a Hugging Face
token for the gated repositories):

- The abliterated 27B: huihui-ai's
  `Huihui-Qwen3.8-27B-abliterated-UD-Q4_K_XL.gguf` and Unsloth's
  `Qwen3.8-27B-UD-Q4_K_XL.gguf` are both `qwen35` with 866 tensors and
  the `blk.64.nextn.*` MTP tensors, and their embedded chat templates are
  identical (9,993 characters, the same SHA-256), so the shipped patched
  template applies to the abliterated file.
- Unsloth's Flash-Next UD-Q4_K_XL names the architecture `qwen4exp`,
  which the pinned build carries, and embeds the same 9,993-character
  template; orcarouter's Q4_K_S names `qwen4exp` too and embeds a
  different template (8,952 characters). The cards name the method of
  both uncensored files as abliteration.
- The bf16 question, from `ggml/src/ggml-cuda/fattn.cu` at b10920: bf16
  is in the type list of the flash-attention vector kernel (single-token
  generation on Ada and newer), and the mma kernel that processes prompts
  (`fattn-mma-f16.cuh`) has no bf16 path, so K and V are converted to
  f16 for it; bf16 therefore buys nothing over f16 for prompt processing
  on this build, which the runs confirmed.
- The memory split of Flash-Next is arithmetic from the file sizes and
  layer counts: about 60 GiB of experts in system memory (38 of 48
  layers) plus up to 27 GiB of memory-mapped n-gram table, against the
  93.35 GiB the host reports.

`load-mode = "none"` in real use, measured on the shipped settings with
the setting added and removed again afterwards (the pinned build, an
agent session of six turns on `qwen3.8-flash-next-q4`):

- The load cost 132 seconds including `smoke`, whose every check passed;
  its first completion took 125 seconds at 31.8 tokens per second.
- The host had 44 GiB in use, 48 GiB available, and no swap in use before
  the load; 84 and 9 GiB with 31 GiB of swap after it; and 88 and 5 GiB
  with 32 GiB of swap after the session, which swapped out 7.6 million
  pages and swapped in 305 thousand, up to 27,397 pages per second in the
  busiest interval of `vmstat`.
- The session's turns took 23 to 161 seconds and grew the prompt to
  40,996 tokens; the card held 27,991 MiB throughout.
- `bench` on the same loaded model measured 260 and 1,352 prompt tokens
  per second for the short and the long prompt and 34.5 and 33.2 of
  generation, so the doubled prompt speed of the hand-run measurement
  above reproduces, and generation is unchanged.

The setting stays off: it buys prompt speed with the host's last
reclaimable memory, and the preset's comment keeps the two lines that
turn it on.

The abliterated 27B in longer runs, against `qwen3.8-27b-q4-mtp` measured
the same way: six prompts at `xhigh` with a 4,096-token budget, five of
which ended on their own on both presets. The sixth, a 600-word story,
spent the whole budget on reasoning and returned no answer on both, so
that is what `xhigh` does with a creative prompt, not what abliteration
does. No answer repeated itself beyond a LaTeX delimiter (13 times on the
shipped preset, 7 on the abliterated one), and the prompt that asks for
200 numbered lines produced 200 distinct ones on both. A six-turn agent
session on the abliterated preset ended every turn on its own, grew the
prompt from 8,208 to 25,768 tokens, and left the files it was asked to
write.

Not covered: what the f16 cache buys in quality; anything about answer
quality, refusals included.

### The GLM-5.3-Flash presets

Purpose: record what `glm-5.3-flash-q2` and `glm-5.3-flash-q2-uncensored`
rest on while no llama.cpp release loads them, and one load attempt.
Environment for the attempt: the GPU host on llama.cpp build b10920, with
the orcarouter file (116.9 GB) downloaded; the build gate was opened by a
temporary edit of the model set on the host (`llama_build = ""`),
restored afterwards. Measured on a GPU: nothing that ran. Checked:

- The first parts of Unsloth's UD-Q2_K_XL and of orcarouter's Q2_K both
  name the architecture `glm5next`. Part 4 of the Unsloth file carries
  the MTP layer as four `blk.45.nextn` tensors (the headers of all parts
  read in the virtual machine); orcarouter's card says its GGUFs drop
  that head, so its set is `mtp = false` and its preset does not draft.
- No `glm5next` exists in `src/llama-arch.cpp` on llama.cpp master;
  pull requests 27752 (draft) and 27754 are open with no maintainer
  review, and issue 28282 (the Blackwell prefill crash at a 2048
  micro-batch) is open, reported against a build of 27754. The pull
  request text names `NVIDIA_TF32_OVERRIDE=0` and `-fa off` as required
  for correct output and measures MTP at 58.6 to 86.5 tokens per second
  with two draft tokens on a B200. The pinned image's `libllama.so`
  (`tokencrate/llama:server-cuda13-b11028`) names `glm5` (`grep -c`
  finds 18) and no `glm5next` (0), so both GLM presets stay behind their
  gate.
- The memory splits are arithmetic from the file sizes and layer counts,
  for a host that reports 93.35 GiB and a 32 GB card. UD-Q2_K_XL
  (108.7 GB): about 78 GiB in system memory (38 of 45 layers) and about
  25 GB on the card; the 120.4 GB UD-IQ3_XXS quant would need 89.8 GiB
  and was not chosen. The orcarouter file (116.9 GB, a plain Q2_K):
  87.2 GiB (39 of 45 layers), which leaves about 6 GiB for the rest of
  the host, so its first run decides whether it stays.
- The gate: the engine-free gate passes in strict mode with every preset
  and model set present; the two GLM presets validate,
  list as waiting with the pinned build, and stay out of `models.ini`
  and the agent model lists, and `LLM_DEFAULT_PRESET` naming one is
  refused by `up` before any download. On the host, `up` lists both as
  `waits for an unreleased llama.cpp build (pinned: b11028)` in every
  run.
- The load attempt with the gate open: `up` rendered
  `glm-5.3-flash-q2-uncensored` and the router listed 10 models
  including it; every request failed with HTTP 500 `model
  name=glm-5.3-flash-q2-uncensored failed to load`, and the model server
  logged `llama_model_load: error loading model: unknown model
  architecture: 'glm5next'` and exited with status 1 at each of the
  three loads the `smoke` requests triggered, 0.12 seconds after its
  start; the router retried at every request. The card held nothing
  afterwards (728 MiB, the desktop). The gate's claim holds: the set
  needs a build with `glm5next`.

Not covered: everything a build that carries the architecture would
show, listed under [Still unverified](#still-unverified).

### Request size of the coding set

Purpose: measure what the `coding` set adds to every request before
the first word of a task, in characters of the request body pi sends
(tokens depend on the model's tokenizer; [pi and the agent
sets](#pi-and-the-agent-sets) has the token counts on the 27B).
Environment: the virtual machine, the `agent-pi` image with pi 0.85.1,
started through the entrypoint with a stub model endpoint inside the
container (`--add-host llama:127.0.0.1`, no network) that records each
chat-completion request and answers `hi`. Command in the container:
`pi -p 'say hi' --no-session`, once with `--no-extensions` and once as
shipped.

| Configuration | Tools | Tool schemas (characters) | System prompt (characters) | Request body (characters) |
| --- | --- | --- | --- | --- |
| pi without extensions | 4 (`read`, `bash`, `edit`, `write`) | 2,901 | 5,289 | 8,487 |
| pi with the `coding` set | 17 | 20,261 | 8,104 | 28,685 |
| pi with the `coding`, `debug`, and `browser` sets | 24 | 26,145 | 8,722 | 35,192 |

The largest schemas of the `coding` set are `lens_diagnostics` (2,166
characters), `module_report` (1,901), and `subagent` (1,819); in the
image with the `debug` and `browser` sets, `debug` adds 3,177 and the six
`chrome_devtools_*` tools 2,700 together. The system prompt grows by
the hashline edit instructions and pi-lens's four skill descriptions. With
the browser extension listed in every image and pi-lens's
`effective_config` tool on, the `coding` set would send 24 tools and 32,474
characters, which is why the `browser` set is separate and the `coding`
set turns that tool off. Every extension loaded: each tool of each listed
package appeared in the request.

### Docker Engine

Purpose: the Docker path without a GPU: `doctor`, `tests/integration.py`
to completion with a first build of the agent images on Docker's store,
the gateway mode of the internal networks, the containment lines, the
agent checks of both UI sets, both UIs, the cross-project check, and the
home lifecycles. Environment: the virtual machine of [The CPU
integration check](#the-cpu-integration-check) (kernel 7.2.4, 12 CPUs of
an AMD Ryzen 9 7950X, 31.3 GiB of system memory, Python 3.14.7) with
Docker Engine 29.7.2 (build `a7dcaa6fdb`) and Compose 5.5.1, the rootful
daemon started for the session and stopped afterwards,
`CONTAINER_ENGINE=docker`, the Docker CLI's `default` context, and
`LLM_GPU=false`. The integration run used the fixture model sets and
presets of the script with the model files already under
`LLM_MODELS_DIR`; the UI checks used the `ci-small` fixture (Qwen3-0.6B
Q4_K_M) alone, and the cross-project check two scratch projects A and B
below the home directory.

- `doctor` passed with 0 failures and the `LLM_GPU=false` warning, and
  printed `Docker version 29.7.2, build a7dcaa6fdb`, `Docker Compose
  version 5.5.1`, and `Docker Engine 29.7.2 keeps host services off the
  agents network (gateway mode isolated needs 28 or newer)`.
- `CONTAINER_ENGINE=docker LLM_GPU=false python3 tests/integration.py -v
  --durations 0` ran for 11 minutes. The setup fetched
  the skill sets, `doctor` passed as above, the llama image came from the
  build cache, and `up` rendered 3 of 14 presets and reported `ci-small`
  loaded; `Ran 9 tests in 662.268s`, `OK`. `down` removed the llama
  container and the three networks; `docker ps -a` and `docker network
  ls` afterwards listed no container and only Docker's `bridge`, `host`,
  and `none` networks.

| Test | Duration | Result |
| --- | ---: | --- |
| `test_agent_checks_pass` | 183.4 s | four checks with 0 failures; three first builds |
| `test_omp_answers` | 132.0 s | `hello` |
| `test_thinking_level_reaches_the_template` | 130.2 s | both agents' `low` reached the `ci-think` template |
| `test_pi_answers_with_a_tool_call` | 122.4 s | the three selections exited 0 with output and without a load error; no file added to the project |
| `test_home_lifecycle_paseo` | 34.8 s | the saved session reopened with text and image data; home 608 KiB |
| `test_home_lifecycle_pi_web` | 30.6 s | the saved session reopened with text and image data; home 56 KiB |
| `test_probes_swap_the_loaded_model` | 7.5 s | `smoke` on `ci-small`, the basic probe on `ci-tiny`, `bench` |
| `test_home_lifecycle_omp` | 5.0 s | the saved session reopened with text and image data; home 20 KiB |
| `test_home_lifecycle_pi` | 4.0 s | the saved session reopened with text and image data; home 32 KiB |

- Docker's store held no pi image of the pinned Node tag, so the run
  measured a first build. `test_agent_checks_pass` pulled
  `node:26.9.0-bookworm-slim` (two layers, 55 MB and 28 MB) and built the
  `coding` image with no cached step, then the
  `coding,debug,dotnet,web,browser` and `coding,debug,odin` images over
  the cached `pi` stage; the `paseo` and `pi-web` images followed in their
  lifecycle checks. The step times BuildKit printed sum to 39 s, 66 s,
  73 s, 21 s, and 7 s for the five images; the longest steps were the apt
  install of the Odin toolchain (49.4 s, 161 MB fetched in 33 s), the
  image exports (13 to 22 s each), and the apt install of Chromium
  (20.8 s). The builds are why `test_agent_checks_pass` took 183.4 s
  against 29.0 s with a warm cache on Podman. The oh-my-pi image's apt
  layer came from the cache, and every later build of the run was cached.
- The agent checks of the three pi selections and of oh-my-pi passed
  with 0 failures, with the toolchain probes of [The CPU integration
  check](#the-cpu-integration-check) (the .NET SDK 10.0.401, js-debug,
  Chromium 153.0.8010.52, and Odin `dev-2026-08-nightly:902106f`) and, in
  every check, the model endpoint reachable, no default route, no route
  to `1.1.1.1`, no name resolution, `agent-ui` and `ui-forward` not
  resolving, `the agents network has no gateway address; no host address
  is reachable`, a read-only root, and the seeded tools note and pi
  packages.
- On the CPU, `smoke` on `ci-small` generated at 108.1 tokens/s with the
  streamed tool call and the mid-conversation system message passing,
  the basic probe on `ci-tiny` generated at 5148.1 tokens/s, and `bench`
  on `ci-small` measured 912.8 prompt and 87.1 generation tokens/s over
  two iterations of the short prompt (223 prompt tokens, 128 generated).
- The three pi prompts exited 0 without a load error and added no file
  to the project. Each printed four characters and the first line of
  the seeded tools note, so the check proves that pi ran to completion
  on each image, not that the 0.6B model read the file. oh-my-pi
  answered `hello`, and both agents' `low` reached the `ci-think`
  template.
- The four home lifecycles passed as under Podman: every home tmpfs
  owned by the host user with mode `0750`, each session manager
  reopening its saved session with text and image data in the first
  container, in the peer, and after stop/start and recreation, and the
  retained directories keeping their markers while planted files and
  settings changes disappeared.
- After the integration run, `up --model-set ci-small` rendered 1 of 12
  presets and reported `ci-small` loaded; `smoke --agent pi --sets
  coding,pi-web` and `smoke --agent pi --sets coding,paseo` each passed
  with 0 failures in about three seconds from the cached images, with
  `pi-web 1.202609.0 resolves the image's pi and node-pty` and `paseo
  0.8.0 starts` next to the containment lines above. `docker images`
  reports the disk usage of the images the run built as 1.25 GB
  (`coding`), 3.51 GB (`coding,debug,dotnet,web,browser`), 2.53 GB
  (`coding,debug,odin`), 1.36 GB (`coding,pi-web`), 1.92 GB
  (`coding,paseo`), and 1.9 GB (oh-my-pi), with content sizes of 291 MB,
  920 MB, 591 MB, 309 MB, 451 MB, and 423 MB; the llama image is 5.26 GB
  (1.88 GB of content).
- `up` created `tokencrate_agents` and `tokencrate_ui` as internal
  networks with `com.docker.network.bridge.gateway_mode_ipv4: isolated`
  (and the IPv6 twin) and no gateway address. Container names on
  Docker's isolated networks still resolved (`llama` answered `/health`),
  and the agent checks passed with the same lines before and while a UI
  ran. On the host the retained directories of the agent home belonged
  to the calling user.
- `ui pi-web --dir A` was ready in 13 to 15 seconds with no published
  port on `agent-ui` and `ui-forward` on `tokencrate_ui` and
  `tokencrate_ui-publish` publishing `127.0.0.1:4224`, nothing listening
  on another address. Through the forwarder, `Origin:
  http://evil.example.com`, `Host: ui.example.com:4224`, and
  `Sec-Fetch-Site: cross-site` got `403`; `Sec-Fetch-Site: same-origin`,
  `none`, and a request without the header got `200`; a prompt through
  `POST /api/sessions/<id>/prompt` produced `assistant -> hello` in pi's
  session file under the project's agent home, and nothing was written
  into the project directory.
- `ui paseo --dir A` was ready in 22 seconds and answered `/api/health`;
  `paseo run --provider pi` reached `completed`; neither DNS nor speech
  models existed in the container. Paseo's `paseo.pid` in the retained
  `.paseo` directory can name a process id from a container of the other
  engine that exists in the new one (`Another Paseo daemon is already
  running (PID 80)` when the file was left in place), which is why the
  launcher removes the file before the daemon starts.
- The cross-project check for project B: without egress the agent check
  passed with 0 failures; with the egress overlay `agent-ui` and
  `ui-forward` did not resolve, and the route checks failed, as they
  must.
- `agent pi --dir A -- -p ...` started while the UI ran for A, on the same
  project, and answered; `agent pi` and `agent omp` each answered a
  prompt in a scratch project.
- The agent `/tmp` is mounted with `exec` because the two engines differ
  on it: Docker mounts a tmpfs `noexec` unless the options say otherwise,
  Podman honours the options as written, and a toolchain that builds a
  program and runs it under `/tmp` fails on the first and works on the
  second. Measured in the odin image: the same probe prints `ok` with
  `exec` and `Could not spawn subprocess: Permission denied` with
  `noexec`.
- `ui stop` removed the UI containers and `down` removed the llama
  container and all four networks (Docker printed that `tokencrate_ui`
  was still in use at `ui stop`, which is expected while llama runs).
  The strict engine-free gate's agent-check test drives every branch of
  the gateway probe with stub commands.

Not covered: a real browser; the GPU; Docker Engine versions other than
29.7.2; a rootful Podman or a Podman without netavark; the Docker
integration workflow in CI.

### The CPU integration check

Purpose: `tests/integration.py` on the CPU with the fixture models, with
the engine-free checks and the UI-set agent checks on the same machine.
Environment: the virtual machine with rootless Podman 6.1.1,
podman-compose 1.6.0, `crun` 1.29.1, and netavark 2.1.0, kernel 7.2.4,
12 CPUs of an AMD Ryzen 9 7950X (6 cores, 2 threads each), 31.3 GiB of
system memory (MemTotal 32851940 kB), Python 3.14.7, Node.js 24.20.0, and
Ruff 0.16.6. The run was `CONTAINER_ENGINE=podman LLM_GPU=false python3
tests/integration.py -v --durations 0`, with the files of both fixture
model sets already under `LLM_MODELS_DIR` and every image layer in the
Podman build cache, so the run downloaded no model and measured no build
time.

The setup fetched the skill sets, `doctor` passed with 0 failures and
the `LLM_GPU=false` warning, and `up` rendered 3 of 14 presets and
reported `ci-small` loaded; `Ran 9 tests in 605.592s`, `OK`. The run
removed its fixture copies, containers, networks, reports, and scratch
directories, and `git status --short` printed nothing it created.

| Test | Duration | Result |
| --- | ---: | --- |
| `test_omp_answers` | 148.9 s | `hello` |
| `test_pi_answers_with_a_tool_call` | 146.2 s | the three selections exited 0 with output and without a load error; no file added to the project |
| `test_thinking_level_reaches_the_template` | 145.9 s | both agents' `low` reached the `ci-think` template |
| `test_home_lifecycle_pi_web` | 44.1 s | passed; home 56 KiB |
| `test_home_lifecycle_paseo` | 30.0 s | passed; home 608 KiB |
| `test_agent_checks_pass` | 29.0 s | four checks with 0 failures |
| `test_home_lifecycle_omp` | 15.8 s | passed; home 20 KiB |
| `test_home_lifecycle_pi` | 14.9 s | passed; home 32 KiB |
| `test_probes_swap_the_loaded_model` | 13.4 s | `smoke` on `ci-small`, the basic probe on `ci-tiny`, `bench` |

- The agent checks of the three pi selections passed with the toolchain
  probes: the .NET SDK 10.0.401 builds the xunit template from the
  image's NuGet cache without a route out, js-debug answers a DAP
  `initialize` request over stdio, Chromium 153.0.8010.52 runs headless,
  and Odin `dev-2026-08-nightly:902106f` builds and runs a program. Every
  check found the model endpoint, no default route, no name resolution,
  a read-only root, and the seeded tools note and pi packages.
- On the CPU, `smoke` on `ci-small` generated at 99.7 tokens/s with the
  streamed tool call and the mid-conversation system message passing,
  the basic probe on `ci-tiny` generated at 5545.7 tokens/s, and `bench`
  on `ci-small` measured 952.4 prompt and 80.5 generation tokens/s over
  two iterations of the short prompt (223 prompt tokens, 128 generated).
- The agent prompts dominate the run: oh-my-pi's one prompt took 148.9 s
  (its first request is about 19,000 tokens), and each of pi's three
  prompts about 50 s. The check accepts any answer without a load
  error; with the 0.6B model, pi's three answers said that README.md was
  not found. A separate prompt with the same model and the `coding`
  selection showed pi calling `read` on the seeded `AGENTS.md` path and
  returning that file's first line, so the tool machinery runs and the
  model chooses the wrong path.
- The engine-free gate passed in strict mode
  (`TOKENCRATE_STATIC_STRICT=1 bash tests/static.sh`): `Ran 227 tests in
  35.296s`, 44 s in all. `doctor` with the machine's `.env` passed with 0
  failures and the `LLM_GPU=false` warning, and `presets render`
  validated every preset against its model set, all loadable except the
  two GLM presets waiting for a build.
- The pi images for `coding,pi-web` (980 MB) and `coding,paseo`
  (1.38 GB) built from the rendered Dockerfiles, and `smoke --agent pi
  --sets` passed for both against `ci-small` with the UI probes: the
  `pi-web` set resolves the image's pi (its scope directory links to
  the global install, not a second copy), pi-ai, and node-pty (PI WEB
  1.202609.0), and Paseo 0.8.0 starts. Inside the Paseo container
  `relay.enabled` is `false`, the speech providers are logged as
  `enabled:false`, no model directory is created, and `relay.paseo.sh`
  does not resolve.

Not covered: a session that uses `lens_diagnostics`, the `debug` tool,
a subagent, or the browser tools, because the fixture model does not
call tools reliably; a first build of the agent images; Docker Engine,
whose CPU runs are in [Docker Engine](#docker-engine).

### HTTP authorities and label discovery

Purpose: verify HTTP port-80 authorization, UI-set label discovery,
and direct UI stop/log dispatch. Date: 2026-09-20.
Environment: the pins in [Environment](#environment), Arch Linux VM,
kernel 7.2.4, 12 CPUs, 31.3 GiB RAM, Python 3.14.7, and Node.js 24.20.0
for the engine-free forwarder harness. The pi and forwarder images use
the pinned Node 26.9.0. Rootless Podman 6.1.1 used podman-compose 1.6.0; Docker
Engine 29.7.2 used Compose 5.5.1 and a temporary daemon with a separate
store, socket, and bridge. Each engine had an isolated source copy,
Compose project, copied fixture models, scratch clients, and fresh
retained state; `LLM_GPU=false`.

- The 54 focused forwarder, UI lifecycle, CLI, and settings tests passed.
  The strict engine-free gate passed 253 tests, Ruff, ShellCheck,
  podman-compose compatibility checks, and both Compose renders with
  the repository virtual environment active.
- The forwarder harness exercised HTTP and WebSocket upgrades with all
  three loopback names, implicit and explicit port 80, and a non-default
  port. Foreign hosts, sibling ports, non-HTTP and malformed Origins,
  and disallowed Fetch Metadata were rejected. The harness used
  unprivileged listeners independently of the published authority.
- Both full `python3 tests/integration.py -v` runs passed all 10 tests,
  including agent/toolchain checks, prompts, model swaps, thinking-level
  forwarding, and all four home lifecycles. Podman took 887.427 seconds;
  Docker took 1068.978 seconds with a fresh image store. The runs
  overlapped on the same CPU host, so these are not benchmark comparisons.

- Both engines' independent-client checks passed: pi, omp, PI WEB, and
  Paseo answered on `ci-small`, and a repeat pi request answered with the
  same router/model process identities. Targeted restarts, saved state,
  project/image/port changes, close starts, failed launches, port
  collisions, and stop-all passed. Both terminal agents could not reach
  either UI or forwarder by name or effective address, with or without
  egress. Both forwarders rejected foreign and sibling UI origins.
- The manual cross-project procedure passed on both engines with both
  UIs alive: `smoke --agent pi` and project B without egress had zero
  failures; B with egress had exactly the three expected route failures
  and could not reach any UI peer. These checks used only the repository
  skill (`LLM_SKILL_SETS=`). Whole-stack `down` with both UI pairs alive
  removed every test-project container and network on both engines.

Not covered: GPU or MTP inference, real browser rendering, interactive
terminal screens, a host listener on privileged port 80, or the default
host-port combination `4207`, `4224`, `4250`. The port-80 result covers
HTTP authorization; the container runs used allocated free host ports.

### Local services and agent builds

Purpose: verify direct local HTTP requests, rendered build scripts,
read-only model-list mounts, and UI lifecycle with temporary launch
files, over the JSON-form Bash build steps, the label-based lifecycle
discovery, and the shared model and UI lifecycle lock. Date: 2026-09-20.

Environment: the pins in [Environment](#environment), Arch Linux VM
without a GPU, Python 3.14.7, Node.js 24.20.0 for the forwarder harness,
rootless Podman 6.1.1 with podman-compose 1.6.0, and Docker Engine 29.7.2
with Compose 5.5.1. Docker used a temporary local daemon. Each engine had
separate source and retained-state directories, test image tags, a
Compose project, and allocated loopback ports; `LLM_GPU=false`.

- The strict static gate passed all 271 tests, Ruff, ShellCheck,
  podman-compose compatibility checks, and both Compose renders.
- Rendered build scripts preserved inline comments, literal hashes, and
  variables across lines, and stopped on command and pipeline failures.
  Compose contract checks verified that agents mount only their generated
  model-list file, read-only. Preset validation refused `rpc` and retained
  the fixture's `override-kv` setting.
- Local API calls bypassed a configured HTTP proxy while ordinary urllib
  calls retained it. The forwarder harness checked HTTP and WebSocket
  authorities, duplicate Host normalization, and interrupted streams.
  UI manifest checks rejected names that collide with `stop` and `logs`.
- Temporary UI files were removed after success and failure. Both Compose
  providers preserved paths, literal dollars, networks, and the engine's
  user mapping. Lifecycle tests covered interrupted builds, disappearing
  containers, bounded waits for automatic removal, and recovery commands.
- The full Podman CPU integration suite passed all 10 tests: the three
  pi selections and oh-my-pi, prompts, model switching, smoke and benchmark
  probes, reasoning-level forwarding, concurrent clients, and all four
  home lifecycles. Docker passed all four home lifecycles and the targeted
  independent-client check.
- On both engines, pi, omp, PI WEB, and Paseo answered with one unchanged
  router and loaded model process. Containment, independent restarts,
  saved state, project/image/port changes, close starts, failed launches,
  and port collisions passed without persistent UI launch records.
  Whole-stack shutdown removed live terminal clients and project networks,
  then startup succeeded. The final removal code also passed a separate
  Podman check with three live auto-remove containers and their network.
- Cleanup left no test-project containers or networks. Test image tags,
  the temporary Docker daemon, and its bridge were removed.

Not covered: GPU or MTP inference, real browser rendering, interactive
terminal screens, privileged host-port binding, the default host-port
combination, or a full Docker integration run beside these checks.
