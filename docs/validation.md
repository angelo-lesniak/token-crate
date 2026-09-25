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

The table summarizes the [records](#records).

- **Validated**: a defined procedure passed, with a record in
  [Records](#records).
- **Expected**: technical evidence supports the claim, but no recorded
  validation run confirms it.
- **Unverified**: no recorded evidence supports the claim.

| Claim | Term | Engine and host | Record |
| --- | --- | --- | --- |
| The CLI refuses a malformed `LLM_PORT`, `--sets` with oh-my-pi, a repeated single-valued flag, a benched preset named twice, an unknown default preset, and `ui stop` of an unknown set, each with one sentence and before the pre-flight | Validated | RTX 5090, rootless Podman 6.1.1 | [CLI refusals](#cli-refusals) |
| A terminal agent of another project, with or without `--egress`, cannot resolve or reach a running UI started without `--egress` or `--cloud`, or its forwarder, by name or effective container address, and its check finds nothing but the routes out it asked for. On rootless Podman that holds while the internal bridges keep IPv4 forwarding off, which is the case for bridges created after forwarding was switched on in the engine's network namespace; on Docker the internal networks have no gateway address | Validated | RTX 5090, rootless Podman 6.1.1 and 6.1.2; Docker Engine 29.7.2 without a GPU | [Egress sessions and the UI networks](#egress-sessions-and-the-ui-networks), [Cross-project containment](#cross-project-containment), [Docker Engine](#docker-engine), [The internal bridges of the virtual machine](#the-internal-bridges-of-the-virtual-machine) |
| `agent pi --cloud` refuses a missing keys file, a directory, a file inside the project, and oh-my-pi, each with one sentence before the pre-flight; the file reaches the named session container through the `run`'s own `-v`, read-only, with no key value in `inspect` or on the command line; the entrypoint exports its lines, refuses a malformed one, and pi offers the keyed provider's bundled catalogue; `--egress` alone offers no cloud model | Validated | Arch Linux VM, rootless Podman 6.1.2, placeholder key; RTX 5090, rootless Podman 6.1.2, an OpenRouter key with a free model answering | [The cloud keys file and the session container](#the-cloud-keys-file-and-the-session-container) |
| A `SIGTERM` or `SIGHUP` to the wrapper of a running `agent` session stops the session container and leaves no Compose provider process; `Ctrl-C` ends the session with status 130 | Validated | Arch Linux VM, rootless Podman 6.1.2 | [The cloud keys file and the session container](#the-cloud-keys-file-and-the-session-container) |
| The llama API echoes a loopback `Origin` and no other; a cross-site simple request is still acted on | Validated | Arch Linux VM, rootless Podman 6.1.2, llama.cpp b11028 on the CPU | [The cloud keys file and the session container](#the-cloud-keys-file-and-the-session-container) |
| `doctor` warns about an `LLM_AGENT_SETS` name no catalogue has; the agent check reports one interface, no default or gateway route, and no name resolution offline, and a default route with `--egress`, where the set checks are skipped | Validated | Arch Linux VM, rootless Podman 6.1.2 | [The cloud keys file and the session container](#the-cloud-keys-file-and-the-session-container) |
| An `--egress` session is on the default network alone: it keeps the model, cannot resolve or reach an offline session by name or by its address on the agents network, and its check reports the route out, `[info]` for the gateway probe, and `[warn]` when no browser UI runs; a UI started with `--egress` or `--cloud` is the exception the UI rows below state | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.7.2 | [The egress network on the virtual machine](#the-egress-network-on-the-virtual-machine) |
| An oh-my-pi session sends the Anthropic key to the address a project's `.env` or `.env.local` names (8 requests to a listener inside the container with the file, 0 without), so `agent omp --cloud` is refused | Validated | Arch Linux VM, rootless Podman 6.1.2, pinned oh-my-pi image offline | [oh-my-pi and project env files](#oh-my-pi-and-project-env-files) |
| Local model and UI API requests bypass host HTTP proxies; the ordinary urllib transport retains proxy handling | Validated | Python 3.14.7, engine-free harness with loopback listeners | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines) |
| Whole-stack shutdown removes live terminal agents, the model, and all project networks; startup succeeds afterwards | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines) |
| HTTP and WebSocket authorization accepts implicit and explicit port 80 for the exact loopback authorities and rejects foreign hosts, origins, sibling ports, and disallowed Fetch Metadata | Validated | Node.js 24.20.0, engine-free harness with unprivileged listeners | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines) |
| Terminal pi and omp in RPC mode, PI WEB through its HTTP API, and Paseo through its daemon CLI answer sequentially while all clients stay alive, with one unchanged router and loaded model process | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture; RTX 5090 on the shipped preset | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines), [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The nine loadable presets in the linked record run through CDI, pass every `smoke` check (including streamed tool calls and mid-conversation system messages), and hold 3 to 7 GiB less than `[requires]`. `bench` measures the MTP preset at about twice the generation speed of the two-slot preset using the same file | Validated | RTX 5090, driver 610.57.04, rootless Podman 6.1.1 | [The llama API and the presets](#the-llama-api-and-the-presets) |
| `gpt-oss-20b-small` and `qwen3.8-27b-q3-small` pass every `smoke` check and hold 12.7 and 13.5 GiB, 2.3 and 1.5 GiB less than the 15 GiB they declare | Validated | RTX 5090, driver 610.57.04, rootless Podman 6.1.1 | [The 16 GB presets](#the-16-gb-presets) |
| The 96 GB tier and the 27B variants hold less than `[requires]` and pass every `smoke` check; Flash-Next reuses a session's growing prompt, and the settings behind `n_cpu_moe`, the 2048 micro-batch, and the unset `load-mode` are measured | Validated | RTX 5090 with 96 GB of RAM | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| The pi image renders and builds for `coding`, `coding,debug,dotnet,web,browser`, and `coding,debug,odin` from the pinned Node base image; each passes the agent check, whose per-set lines come from the sets' `check` scripts; prompts complete on CPU and GPU, with answers checked in the GPU record | Validated | Rootless Podman, with and without a GPU; Docker Engine 29.7.2 without one | [pi and the agent sets](#pi-and-the-agent-sets), [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Both agents run on the GPU with one scripted prompt each: pi edits and commits a file, every agent check passes for the default and the toolchain selections and for oh-my-pi, and both resume a transcript with `--continue` in a new container | Validated | RTX 5090, rootless Podman 6.1.1 | [pi and the agent sets](#pi-and-the-agent-sets), [oh-my-pi](#oh-my-pi) |
| The thinking levels reach the Qwen template; on a task that needs reasoning the 27B generated monotonically more tokens at each level, and on a one-line answer the level made no difference (the effort is an instruction, not a budget) | Validated | RTX 5090 | [pi and the agent sets](#pi-and-the-agent-sets) |
| `ui pi-web` and `ui paseo` start from their sets, answer through the forwarder on loopback, refuse a foreign origin, and run one prompt through pi | Validated | Rootless Podman 6.1.1 with the GPU and 6.1.2 without one; Docker Engine 29.8.1 without one | [PI WEB](#pi-web), [Paseo](#paseo), [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| `ui <set>` starts the UI and its forwarder with `compose run` as `tokencrate-ui-<set>` and `tokencrate-ui-forward-<set>`, a relaunch replaces only that set, and `ui stop` and `down` remove both | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1; RTX 5090, rootless Podman 6.1.2 | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud), [The CPU integration check](#the-cpu-integration-check) |
| With `ui <set> --cloud` the keys file is mounted read-only through the `run`'s `-v` with `TOKENCRATE_CLOUD=1` and no key value in `inspect`; the UI sits on `ui` and `default` with the forwarder on `ui` and `ui-publish` alone; `status` ends the line with `cloud`; the launcher and the UI daemons hold the key and offer the keyed provider; an offline sibling UI reaches the cloud UI over `ui`; a relaunch without the flag drops the mount and the network; on Docker the host reaches the cloud UI's default-network address past the forwarder's `Host` check; on the GPU host `ui paseo --cloud` with an OpenRouter key answers `CLOUD_OK` from a free model through Paseo's daemon | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1, placeholder key; RTX 5090, rootless Podman 6.1.2, an OpenRouter key | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| With a `--cloud` UI running, `smoke --agent pi --egress` reports `[info]` for the UI's name and its default-network address and `not reachable` for its `ui` address and its forwarder, with 0 failures; `smoke --agent pi` reports every UI target `not reachable` with 0 failures | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1; RTX 5090, rootless Podman 6.1.2 | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| PI WEB answers successive sessions, reopens its transcript after a restart, runs browser terminal panels, and shares a project with a terminal agent; Paseo answers after recreation and keeps its identity | Validated | RTX 5090, rootless Podman 6.1.1 | [PI WEB](#pi-web), [Paseo](#paseo) |
| `tests/integration.py` passes on the GPU, every test except `test_concurrent_clients`: the fixture presets through the router, the full and basic probes with the swap between them, `bench`, the three pi selections and oh-my-pi contained and answering, each agent's thinking level reaching the template, and the four home lifecycles | Validated | RTX 5090, rootless Podman 6.1.1 | [The integration run and the home lifecycles](#the-integration-run-and-the-home-lifecycles) |
| Agent homes keep transcripts, oh-my-pi blobs, and browser-UI state and identity through stop/start and recreation; live settings and other home files do not persist, and a terminal and a UI container on one project share transcripts only | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2 | [The integration run and the home lifecycles](#the-integration-run-and-the-home-lifecycles) |
| `tests/integration.py` passes on the CPU with the fixture models | Validated | Rootless Podman 6.1.1 and 6.1.2 and Docker Engine 29.7.2, Arch Linux VM, no GPU | [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Four clients answer in turn on the shipped MTP preset with one unchanged router and model process, each forwarder refuses foreign and sibling authorities, and a second client queues behind the first: one request takes 7.5 seconds alone and two issued together 14.6 seconds, at unchanged generation speed | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The default preset serves a coding session of a dozen turns in its 64K slot: pi compacts the prompt when it fills and continues, and a session whose turns read 20 KB files refills the slot within two turns; one overflow compaction at 63,312 tokens failed because its summary hit the token cap | Validated | RTX 5090 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| A GPU session calls `lens_diagnostics`, the `debug` tool over js-debug, the subagent tool, and the browser tools | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The `coding` set seeds its subagent definitions without a `model:` line, so a subagent runs on the session's own model: the scout returned a delegated result on the GPU in 24 seconds. The image build and the agent check refuse a definition that names a model of its own | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| Long sessions stay far inside the 256 MiB home tmpfs: 424 KiB after twelve pi turns, and oh-my-pi keeps its growth in the retained directories on disk (8.6 MiB after six turns) | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| oh-my-pi starts on the selected preset at `xhigh` without its onboarding wizard, and its model picker saves a choice for the session: the entrypoint writes its settings into the home, where the picker's rewrite lands, and keeps the repository file as the overlay above it | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The abliterated 27B does not loop in longer runs: five of six long completions ended on their own, exactly as on the shipped preset, and a six-turn session ended every turn | Validated | RTX 5090 | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| `load-mode = "none"` on Flash-Next doubles prompt processing, also measured after a six-turn agent session, and leaves the host 5 GiB of available memory with 32 GiB of swap in use; the presets keep the memory map | Validated | RTX 5090 with 96 GB of RAM | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| Either 16 GB preset runs on a 16 GB card: both were measured on a 32 GB one, and the fit follows from what they held | Expected | RTX 5090 | [The 16 GB presets](#the-16-gb-presets) |
| Loading and inference with `glm-5.3-flash-q2` and `glm-5.3-flash-q2-uncensored` on a build with `glm5next`; the pinned build lacks the architecture, and the preset settings await smoke and benchmark measurements | Unverified | RTX 5090 with 96 GB of RAM | [The GLM-5.3-Flash presets](#the-glm-53-flash-presets) |
| Docker Engine 29.7.2 and 29.8.1 with Compose 5.5.1 run every part of the procedure that needs no GPU: `doctor`, `tests/integration.py` to completion with a first build of the agent images on Docker's store, the agent checks of the `pi-web` and `paseo` sets, both UIs through the forwarder, the cross-project check, and the four home lifecycles; the Compose files render with the Docker CLI in the static gate | Validated | Docker Engine 29.7.2 and 29.8.1, Arch Linux VM, no GPU | [Docker Engine](#docker-engine), [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| Gateway mode `isolated` keeps host services off the agents network on Docker Engine versions between 28 and 29.6; only 29.7.2 has a record, where the agent check also found no default route and no external name resolution. The mode is documented from 28 on and `doctor` checks for 28 | Expected | Docker Engine 29.7.2 | [Docker Engine](#docker-engine) |

### Still unverified

The engine-free gate and the CPU integration check do not cover these:

- the GLM presets on a llama.cpp release that carries `glm5next`: run
  `glm-5.3-flash-q2`, then `glm-5.3-flash-q2-uncensored`, each with
  `smoke` and `bench`, and record the build number with the results;
- Docker Engine with the GPU, and the Docker integration workflow in CI;
  the GPU host has no Docker Engine;
- a task that the `debug` tool carries through to the end: the [GPU
  record](#four-clients-long-sessions-and-the-tools) shows the tool
  running, but the model did not finish the task;
- whether the `[requires]` values of the presets that no session has
  filled leave the right headroom; the default preset held the same
  20.1 GiB with an empty and a full 64K slot;
- the UI launchers' readiness timeouts for a daemon that never answers:
  no recorded run had a daemon fail to start;
- the provider in pi's interactive model picker, a cloud answer through
  PI WEB's browser session or Paseo's create-agent form, and the
  reported cost: every recorded cloud answer came from a scripted prompt
  on a free model, which reports no cost;
- on Docker Engine, that a `SIGTERM` to the wrapper stops the named
  session container, and the llama API's CORS setting; both records are
  from rootless Podman;
- the router observations that the wrapper relies on
  ([Router behavior](#router-behavior-the-wrapper-relies-on)) were read
  on build b10920; the pinned b11028 confirms readiness, swapping, and
  the preset file through the CPU integration check, not the failure
  codes, the offline behavior, or the image details;
- that `up` sets up the model's non-internal network before the internal
  ones on every host, which is what keeps IPv4 forwarding off on the
  internal bridges of rootless Podman ([the VM
  record](#the-internal-bridges-of-the-virtual-machine)); `smoke --agent
  pi --egress` with a browser UI running is the per-host check.

## Environment

The pins under test, as `bash bin/tokencrate pins` prints them:
`LLAMA_CPP_TAG=server-cuda13-b11028` (`llama-server --version` prints
`build 11028, commit 972d2313b`), `PI_VERSION=0.85.1`,
`OMP_VERSION=18.2.5`, `NODE_TAG=26.9.0-bookworm-slim`,
`BUN_TAG=1.4.2-slim`, `CUDA_MIN_DRIVER_MAJOR=580`, each image with the
digest in `pins.env`. The agent sets pin PI WEB 1.202609.0, Paseo 0.8.0,
the .NET SDK 10.0.401, and Odin `dev-2026-08-nightly:902106f`; the runs
used Debian's Chromium 153.0.8010.52, which the `browser` set installs
unpinned. Unless a record states otherwise, agent
sessions used `LLM_AGENT_SETS=coding`, with
`LLM_SKILL_SETS=pocock-core,skill-crate`, and on the GPU with the model
set `qwen3.8-27b-ud-q4-k-xl` and the preset `qwen3.8-27b-q4-mtp`
(`n_ctx` 65536).

Two machines appear in the records. **The GPU host** is Linux x86-64
(kernel 7.2.4 or 7.2.6) with an NVIDIA GeForce RTX 5090 (32607 MiB,
driver 610.57.04, CUDA 13.3, CDI device `nvidia.com/gpu=all`), 93.35 GiB
of system memory (MemTotal 97883376 kB) and 46 GiB of swap, rootless
Podman 6.1.1 or 6.1.2 with podman-compose 1.6.0, `crun`, and netavark
2.1.0, Python 3.14.7, host UID:GID `1000:1000` with `keep-id`, and no
Node.js, so the engine-free gate cannot run there. **The virtual
machine** is Arch Linux (kernel 7.2.4 or 7.2.6) with no GPU, rootless
Podman 6.1.1 or 6.1.2 with `crun`, netavark 2.1.0, and podman-compose
1.6.0, Docker Engine 29.7.2 with Compose 5.5.1 for the Docker runs,
Python 3.14.7, Node.js, and Ruff. Each record names the versions of its
run where they differ.
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
integration setup and `down` around them;
[CONTRIBUTING.md](../CONTRIBUTING.md#tests) lists what the setup needs.
The checks themselves use no model.

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
on a host without a GPU), and create a scratch project A below the home
directory. On a host with a GPU and the shipped model set, name the
loaded preset with `--preset` instead of copying the fixture.
`smoke --agent` runs its check in a scratch project of its own, which
stands for the other project. Then:

1. `bash bin/tokencrate up --model-set ci-small`, then
   `bash bin/tokencrate ui pi-web --dir A` and
   `bash bin/tokencrate ui paseo --dir A`.
2. `bash bin/tokencrate smoke --agent pi`: the check must report that
   every active UI container and forwarder is unreachable by name and
   current container address and, on Docker, that the agents network has
   no gateway address.
3. `bash bin/tokencrate smoke --agent pi --egress`: the check starts the
   container with the egress overlay, as `agent --egress` does. A default
   route must exist, and every UI peer must still be unreachable.
4. `bash bin/tokencrate ui pi-web --egress --dir A`, then the check with
   `--egress` again: the UI's name and its address on the default
   network are reported as `[info] ... that UI was started with
   --egress`, its address on the `ui` network and its forwarder stay
   `not reachable`, and the check without `--egress` reports 0 failures.
5. `bash bin/tokencrate ui stop`, `bash bin/tokencrate down`, and remove
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
creates a PI WEB session through its published API, and drives a Paseo
session through the daemon. It checks the assistant messages and the
effective `ci-small` model, including Paseo's saved provider model and
transcript, repeats the pi prompt, and compares router and model PIDs
and kernel start times within an unchanged router container. It also
exercises targeted stops, retained state, project and image changes,
near-simultaneous starts, occupied ports, failed custom-set launches,
both forwarders' Host and Origin checks, and name and address
containment from both terminal agents with and without egress.

For browser and terminal-screen acceptance, follow the
[four-client workflow](agents.md#use-four-clients-with-one-model) with
separate conversations. Confirm the effective preset in each client,
especially Paseo's retained profile, and wait for PI WEB's title request
before the next prompt. Record the assistant responses, router and
model-process identities, UI IDs, and listener addresses before and
after. Test the default ports separately from free-port integration
runs. A banner, health response, or live process does not prove a
prompt response; a GPU or browser claim needs such a run.

### Recording a result

Add a section under [Records](#records), headed by the subject, with:

- Purpose and the run date;
- Environment: pins from `bash bin/tokencrate pins`, the tree under
  test, engine and version, GPU and driver; name differences from
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
  CDI device, the Podman version, and 32 GiB against
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
  | `qwen3.8-flash-next-q4` | 32, 31 | 98, 660 |
  | `qwen3.8-flash-next-q4-uncensored` | 34, 35 | 111, 774 |
  | `gpt-oss-20b-fast` | 264, 246 | 7,601, 22,449 |

  The MTP preset generated about twice as fast as the two-slot preset of
  the same file. A second run of both repeated the generation numbers
  within one percent; its prompt speeds differed by up to half, which is
  cache state, not the preset. The `qwen3.8-flash-next-q4` row is a
  warmed measurement on driver 615.71.09: `smoke` loaded the preset
  first, so the page faults of the memory map are not in the average;
  the same short prompt directly after the load measured 79 prompt and
  30 generation tokens per second. The `qwen3.8-flash-next-q4-uncensored`
  row is from the runs of [the 96 GB tier
  record](#the-settings-of-the-96-gb-ram-tier) on llama.cpp build
  b10920; every other row is from the pinned build.

Not covered: the two GLM presets, which the pinned build does not load
([The GLM-5.3-Flash presets](#the-glm-53-flash-presets)); the two
[16 GB presets](#the-16-gb-presets), measured separately.

### The 16 GB presets

Purpose: the GPU measurement of `gpt-oss-20b-small` and
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
  reachable, no route out (the route probes of the check as run there:
  no default route, no route to an address literal, no name resolution),
  `agent-ui` and `ui-forward` not resolving, the gateway `10.89.1.1`
  answering from the user's network namespace, the root filesystem
  read-only, the project mounted, and 5, 7, and 6 pi packages seeded. The
  sets' own check lines: `dotnet: dotnet 10.0.401 builds the xunit
  template from the cached packages`, `web: js-debug answers a DAP
  initialize request over stdio`, `browser: Chromium 153.0.8010.52 built
  on Debian GNU/Linux 12 (bookworm) answers --version`, `odin: odin
  version dev-2026-08-nightly:902106f builds and runs a program`, and for
  the `coding,pi-web` and `coding,paseo` selections `pi-web: pi-web
  1.202609.0 resolves the image's pi and node-pty` and `paseo: paseo
  0.8.0 answers --version`; the oh-my-pi check passed with the same
  containment lines. Every check without a browser UI printed `[warn] no
  browser UI running; UI isolation not tested`.
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
- The check's scratch project stands for the other project: without
  egress, `getent hosts agent-ui ui-forward` printed nothing and the check
  passed with 0 failures, every containment line `[ok]`. With `--egress`
  the check found the route out (a default route, an address literal and
  a public name reached) and the two UI names still did not resolve.

Not covered: the same check with `agent omp`. Connection attempts to the
UI's and the forwarder's addresses are in [Egress sessions and the UI
networks](#egress-sessions-and-the-ui-networks).

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

Purpose: four clients on the shipped MTP preset, whether a second client
queues on it, multi-turn sessions for pi, oh-my-pi, and PI WEB, home
capacity in a long session, and sessions that call `lens_diagnostics`,
the `debug` tool, the subagent tool, and the browser tools. Date:
2026-09-20. Environment: the GPU host, the default preset unless a line
names another, both browser UIs on their default host ports (`4224` and
`4250`); the desktop held 683 MiB before the run, which "held" subtracts.

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
  finished after 7.4 and 14.6 seconds. Generation stayed at 110 to 114
  tokens per second in all three and the drafting numbers matched, so
  the second request waited for the slot instead of sharing it, as the
  preset's one slot implies.
- A pi session of 12 turns in one container, reading and editing files of
  8 to 21 KB: turns took 3.7 to 141 seconds and used `read`, `write`,
  `replace`, `insert`, `bash`, and `lens_diagnostics`. The prompt grew
  from 8,013 to 51,822 tokens by turn 10; pi compacted there and continued
  at 28,292; turn 12 reached 63,312 tokens of the 64K slot, ended with
  `length`, and its overflow compaction failed (`Summarization failed:
  generation hit the token cap and the summary is incomplete`), after
  which the agent stayed busy and refused the next prompt. The card held
  21,238 MiB before the first turn and after the last, 20.1 GiB against
  the preset's 24 GiB `[requires]`: a full slot holds no more than an
  empty one, because llama.cpp allocates the cache when the model loads.
- An oh-my-pi session of 6 turns in one container, on
  `qwen3.8-flash-next-q4`: every turn ended on its own, the prompt grew
  from 26,845 to 39,298 tokens, and the home tmpfs stayed empty while its
  retained `.omp` directories grew to 8.6 MiB on disk.
- Home capacity in a long session: pi's home tmpfs held 96 KiB before the
  first turn and 424 KiB after the twelfth, of the 256 MiB the tmpfs
  offers, and its `/tmp` 10.5 MiB of 1 GiB. Nothing approached a limit.
- PI WEB in a browser, resuming the 12-turn conversation: a reply ended
  with `length` at 63,359 tokens, PI WEB compacted (a 12,275-character
  summary), and the session continued at 15,076 tokens, read four files,
  and reached 63,729 two turns later. Compaction recovers the slot, and a
  session whose turns read 20 KB files refills it within two turns. Two
  other conversations in the same project answered normally.
- The tool families, one scripted session each on the
  `coding,debug,dotnet,web,browser` image, with the tools the transcripts
  record:

  | Objective | Session | Tools called | Result |
  | --- | ---: | --- | --- |
  | `lens_diagnostics` on a type error | 77 s | `lens_diagnostics`, `read`, `anchor_grep`, `replace` | reported the diagnostic, fixed the file, and confirmed it clean |
  | the `debug` tool over js-debug | stopped at the run's 1,200 s limit | `debug`, `bash`, `read` | the adapter answered and the model kept debugging for 74 assistant messages, compacting once, without finishing the task |
  | the subagent tool | 51 s | `subagent`, `read`, `bash`, `replace` | the scout, its definition naming the loaded preset, returned all three TODO comments with file and line |
  | the browser tools | 20 s | `chrome_devtools_navigate`, `chrome_devtools_evaluate` | returned the title, the `h1`, and the text the page's script wrote |

- The four clients by hand, in real browser windows and terminal screens:
  every client answered its own conversation, nothing hung, and the model
  stayed loaded. Paseo's browser form created an agent that ran on
  `tokencrate/qwen3.8-27b-q4-mtp` at `xhigh` and closed normally; PI WEB
  served its terminal panel and an extension dialog.
- The subagent definitions the pi package ships name models no container
  here can reach (`claude-haiku-4-5` in `scout.md`, `claude-sonnet-4-5` in
  `planner.md`, `reviewer.md`, and `worker.md`). The `coding` set strips
  the `model:` line from the definitions it seeds, so each subagent runs
  on the session's own model and thinking level; the image build and the
  agent check refuse a definition that names a model of its own. A
  session delegated with one `subagent` call and the scout reported all
  three TODO comments of a scratch project with file and line in 24
  seconds, ending on its own.
- oh-my-pi's two settings of its own ([Agent
  configuration](agents.md#agent-configuration)): its onboarding wizard
  opens whenever the stored setup version is older than the binary's,
  which a fresh tmpfs home makes every session, and
  `startup.setupWizard: false` in the repository settings turns it off;
  its model picker saves by renaming a temporary file over
  `~/.omp/agent/config.yml`, which fails with `EBUSY` unless that path is
  writable, so the entrypoint writes the settings into the home and keeps
  the repository file as the overlay above it (the agent check performs
  that write). oh-my-pi answered a prompt in 10 seconds with
  `model_change tokencrate/qwen3.8-27b-q4-mtp` and `thinking_level_change
  xhigh` in its transcript, and in an interactive session the picker
  saved a choice with no `EBUSY`.

Not covered: Docker Engine with a GPU; a `debug` task the model
finishes; the GLM presets.

### The integration run and the home lifecycles

Purpose: `tests/integration.py` on the GPU, whose four
`test_home_lifecycle_*` checks are the [agent home
check](#agent-home-check), and the same four checks on both engines of
the virtual machine. Date: 2026-09-20. Environment: the GPU host with
`CONTAINER_ENGINE=podman LLM_GPU=true`, run as `python3
tests/integration.py -v --durations 0` on the fixture models (`ci-small`,
Qwen3-0.6B Q4_K_M; `ci-tiny`, stories260K; the preset `ci-think`); the
virtual machine with rootless Podman 6.1.1 and with Docker Engine 29.7.2,
no model, for the lifecycle checks alone.

- The GPU run: the setup fetched the skill sets, `doctor` passed with 0
  failures and 0 warnings, `up` rendered every shipped and fixture preset
  except the two GLM ones and reported `ci-small` loaded; the nine tests
  (every test except `test_concurrent_clients`) passed in 180 seconds:
  the three pi selections and oh-my-pi answered, the four agent checks
  had 0 failures, `smoke` on `ci-small`, the basic probe on `ci-tiny`,
  and `bench` swapped the loaded model, both agents' `low` reached the
  `ci-think` template, and the four home lifecycles passed with homes of
  28 to 616 KiB. `git status --short` printed nothing afterwards.
- The lifecycle checks on the virtual machine ran for five selections on
  each engine, ten runs, and every run passed: pi with the `dotnet`,
  `web`, and `browser` sets; pi with the `odin` set; oh-my-pi; PI WEB;
  Paseo. Every home mount ancestor was writable as `1000:1000` with mode
  `0750`, which needs the tmpfs option `U` on Podman and `uid=,gid=` on
  Docker and an owned tmpfs on every ancestor of a retained bind: a
  tmpfs on the home alone leaves the nested mount points root-owned.
- The session managers saved and reopened text and image messages;
  oh-my-pi restored image bytes from its retained blob store after
  stop/start and recreation, and its pinned sources name the terminal
  breadcrumbs and the custom session-file registry as its other resume
  and cleanup inputs, which is why those directories are retained too.
  Two concurrent containers shared a transcript without sharing live
  settings or other home files; host files outside the retained
  directories stayed invisible; stop/start and recreation removed planted
  home files, kept every retained-directory marker, and recreated the
  generated model list and the skills link. Both UI launchers reached
  HTTP readiness after the first start, after stop/start, and after
  recreation; Paseo kept the exact keypair and server id; Odin built and
  ran a program under `/tmp`.
- Home usage, retained binds included, stayed below 0.7 MiB (464 KiB
  after the .NET first run, 656 KiB for Paseo) and `/tmp` below 8 MiB,
  which supports the 256 MiB limit of each home tmpfs for these
  workloads, not an aggregate memory bound.

Not covered: the production network and the forwarder (the lifecycle
checks run with networking disabled) and a real browser. Home capacity
in a long session is in [Four clients, long sessions, and the
tools](#four-clients-long-sessions-and-the-tools).

### The settings of the 96 GB RAM tier

Purpose: the measurements behind the settings of the 96 GB tier: the
expert split, the micro-batch, the memory map, and the alternatives that
were tried and dropped. The presets' own results are in [The llama API
and the presets](#the-llama-api-and-the-presets). Date: 2026-09-20.
Environment: the GPU host on llama.cpp build b10920; the [baseline
procedure](#nvidia-host-baseline) for the shipped settings and hand-run
`smoke` and `bench` commands for the alternatives, each alternative a
temporary edit of a preset on the host, reverted afterwards. `bench` ran
three iterations with a 262-token and a 6,052-token prompt, prompt
caching off. "Held" is `nvidia-smi` after `smoke` minus what the desktop
held before the run (739 to 1041 MiB).

The shipped settings:

- `smoke`: every check passed on every run of the four presets (the
  abliterated 27B, the f16 preset, and the two Flash-Next presets after
  each change of their settings); the `reply terminates` check found
  `stop` on all six completions of the abliterated 27B. On the
  orcarouter Flash-Next file, whose embedded template differs (see the
  source checks below), the patched template replaced it and every check
  passed.
- GPU memory held while loaded, generation and prompt speed in tokens
  per second for the short and the long prompt, against `[requires]`:

  | Preset | Held | `[requires]` | Generation | Prompt |
  | --- | ---: | ---: | --- | --- |
  | `qwen3.8-flash-next-q4` | 26.2 GiB | 30 GiB | 34, 33 | 119, 740 |
  | `qwen3.8-flash-next-q4-uncensored` | 26.1 GiB | 30 GiB | 37, 36 | 118, 776 |

  The card had 4.1 and 4.2 GiB free with the two presets loaded.
- Flash-Next at the 2048 micro-batch: two uncached 12,052-token prompts
  on `qwen3.8-flash-next-q4` processed at 729 and 788 tokens per second
  with no error in the log, so llama.cpp issue 28282 (a CUDA illegal
  memory access at this micro-batch on this card class, reported on a
  GLM model) did not show.
- The loader's own lines (`verbosity = 4` in `[server.extra]`) are where
  the memory split in the preset's comment comes from; they also report
  `load_mode = mmap` with the warning that CPU tensor overrides are
  slower than `--load-mode none`, and the server re-processes a full
  prompt between requests that share no prefix.
- Flash-Next in system memory: `free` showed 7 GiB used and 86 GiB of
  page cache while the Unsloth file was loaded, because llama.cpp
  memory-maps the weights and the kernel counts mapped file pages as
  cache; a desktop monitor showed under 8 GiB in use throughout. The
  first completion after a load took 23 and 38 seconds, the page faults
  of the memory map.
- Prefix reuse with prompt caching on: a 6,052-token request processed
  at 606 tokens per second; the same conversation with one more turn
  appended reported `cache_n` 6048 and `prompt_n` 39, processed in 0.5
  seconds. A session's growing prompt is reused, so a turn pays for its
  new tokens.
- An agent on Flash-Next: `agent pi --preset qwen3.8-flash-next-q4` in a
  fresh Git project created `hello.txt`, committed, and answered `done`
  in six requests; the first request's 8,011 prompt tokens processed at
  187 tokens per second at the default micro-batch (43 seconds before
  the first word), generation at 34 to 35 tokens per second.

The alternatives measured on Flash-Next, none adopted; every `smoke`
run passed:

| Preset and setting | Held | Prompt (short, long) | Generation | Verdict |
| --- | ---: | --- | --- | --- |
| `qwen3.8-flash-next-q4`, default micro-batch (512), 36 layers in system memory | 27.1 GiB | 119, 324 | 35, 34 | Less than half the long-prompt speed of the 2048 micro-batch |
| `qwen3.8-flash-next-q4`, 2048 micro-batch, 36 layers | 29.3 GiB (1.0 GiB free) | 102, 720 | 33, 32 | Too little headroom for a session; the shipped 38 layers cost about 1 token per second of generation |
| `qwen3.8-flash-next-q4-uncensored`, default micro-batch, 36 layers | 23.8 GiB | 107, 328 | 37, 36 | The orcarouter file holds 3 GiB less at the same layer count, so its preset keeps 36 |
| `qwen3.8-flash-next-q4-uncensored`, default micro-batch, 34 layers | 26.6 GiB (3.8 GiB free) | 115, 346 | 38, 31 | No gain from two more expert layers on the card |
| `qwen3.8-flash-next-q4`, `load-mode = "none"`, default micro-batch, 36 layers | 27.2 GiB | 272, 689 | 34, 34 | `smoke` took 61 seconds including the load |
| `qwen3.8-flash-next-q4`, `load-mode = "none"` at the shipped settings | 26.2 GiB | 242, 1,315 | 33, 33 | Prompt processing doubles, but `free` afterwards showed 69 GiB used and 24 GiB available, swap 9 to 10 GiB, and `vmstat` up to 2,953 pages swapped in per second: the experts sit in memory the kernel cannot reclaim. Not set; the preset comment gives the two lines that turn it on |

The KV-cache types on the 27B Q4 file with MTP, two runs that agree
within 1 percent: prompt speed the same for all three types; generation
for the short and the long prompt 135 and 152 (`q8_0`), 139 and 141
(`f16`), 142 and 136 (`bf16`). `nvidia-smi` right after `smoke` showed
22871 MiB in use with `qwen3.8-27b-q4-mtp-f16kv` (21.3 GiB held) and
23073 MiB with a bf16 copy of it (21.5 GiB held); both passed every
check. bf16 holds as much as f16, as the same element size predicts, and
buys nothing for prompt processing on this build: the flash-attention
kernel that processes prompts (`fattn-mma-f16.cuh` at b10920) has no
bf16 path and converts K and V to f16.

Checked from the file headers at the pinned commits: the abliterated
27B (huihui-ai) and Unsloth's 27B are both `qwen35` with 866 tensors,
the `blk.64.nextn.*` MTP tensors, and identical embedded chat templates
(9,993 characters, the same SHA-256), so the shipped patched template
applies to the abliterated file. Unsloth's Flash-Next names the
architecture `qwen4exp` and embeds the same template; orcarouter's
Q4_K_S names `qwen4exp` too and embeds a different one (8,952
characters). The memory split of Flash-Next is arithmetic from the file
sizes and layer counts: about 60 GiB of experts in system memory (38 of
48 layers) plus up to 27 GiB of memory-mapped n-gram table, against the
93.35 GiB the host reports.

`load-mode = "none"` in an agent session of six turns on
`qwen3.8-flash-next-q4`, on the pinned build with the shipped settings
and the setting added for the run: the load cost 132 seconds including
`smoke`, whose every check passed; the host went from 44 GiB in use, 48
GiB available, and no swap before the load to 88 GiB in use, 5 GiB
available, and 32 GiB of swap after the session, with up to 27,397 pages
per second swapped in during its busiest interval; the six turns took 23
to 161 seconds and grew the prompt to 40,996 tokens; `bench` on the same
loaded model measured 260 and 1,352 prompt tokens per second and 34.5
and 33.2 of generation, so the doubled prompt speed reproduces and
generation is unchanged. The setting stays off: it buys prompt speed
with the host's last reclaimable memory.

The abliterated 27B in longer runs, against `qwen3.8-27b-q4-mtp`
measured the same way: six prompts at `xhigh` with a 4,096-token budget,
five of which ended on their own on both presets. The sixth, a 600-word
story, spent the whole budget on reasoning and returned no answer on
both, so that is what `xhigh` does with a creative prompt, not what
abliteration does. No answer repeated itself beyond a LaTeX delimiter,
and a six-turn agent session on the abliterated preset ended every turn
on its own, grew the prompt from 8,208 to 25,768 tokens, and left the
files it was asked to write.

Not covered: what the f16 cache buys in quality; anything about answer
quality, refusals included.

### The GLM-5.3-Flash presets

Purpose: record what `glm-5.3-flash-q2` and `glm-5.3-flash-q2-uncensored`
rest on while no llama.cpp release loads them, and one load attempt.
Environment for the attempt: the GPU host on llama.cpp build b10920, with
the orcarouter file (116.9 GB) downloaded; the build gate was opened by a
temporary edit of the model set on the host (`llama_build = ""`),
restored afterwards. No GLM preset ran on the GPU. Checked:

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
home lifecycles. Date: 2026-09-20. Environment: the virtual machine of
[The CPU integration check](#the-cpu-integration-check) with Docker
Engine 29.7.2 (build `a7dcaa6fdb`) and Compose 5.5.1, the rootful daemon
started for the session and stopped afterwards, `CONTAINER_ENGINE=docker`,
the Docker CLI's `default` context, and `LLM_GPU=false`. The integration
run used the fixture model sets and presets of the script with the model
files already under `LLM_MODELS_DIR`; the UI checks used the `ci-small`
fixture (Qwen3-0.6B Q4_K_M) alone, and the cross-project check a scratch
project A below the home directory.

- `doctor` passed with 0 failures and the `LLM_GPU=false` warning, and
  printed `Docker version 29.7.2, build a7dcaa6fdb`, `Docker Compose
  version 5.5.1`, and `Docker Engine 29.7.2 keeps host services off the
  agents network (gateway mode isolated needs 28 or newer)`.
- `CONTAINER_ENGINE=docker LLM_GPU=false python3 tests/integration.py -v
  --durations 0`: the setup fetched the skill sets, the llama image came
  from the build cache, `up` rendered the three fixture presets and
  reported `ci-small` loaded, and all ten tests passed in 950 seconds,
  the pi images built from the shipped manifests over Docker's cached
  base layers. `down` removed the llama container and the three
  networks; `docker ps -a` and `docker network ls` afterwards listed no
  container and only Docker's own networks.
- The agent checks of the three pi selections and of oh-my-pi passed
  with 0 failures, with the sets' check lines of [The CPU integration
  check](#the-cpu-integration-check) (`dotnet`, `web`, `browser`,
  `odin`, and `coding`) and, in every check, the model endpoint
  reachable, no route out, `the agents network has no gateway address`,
  a read-only
  root, the seeded tools note and pi packages, and `[warn] no browser UI
  running; UI isolation not tested`.
- On the CPU, `smoke` on `ci-small` passed with the streamed tool call and
  the mid-conversation system message, the basic probe on `ci-tiny`
  passed, and `bench` on `ci-small` measured over two iterations of the
  short prompt. The three pi prompts exited 0 without a load error and
  added no file to the project; oh-my-pi answered `hello`, and both
  agents' `low` reached the `ci-think` template. The four home
  lifecycles passed as under Podman.
- The independent-client check passed as under Podman: four clients on
  `ci-small`, containment from both terminal agents with and without
  egress, targeted stops, retained state, and a failed custom UI launch.
  The UI containers mount one UI path from the host, the set's `state`
  directory, beside the pi transcripts.
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
  `paseo run --provider pi` reached `completed`. Paseo's `paseo.pid` in
  the retained `.paseo` directory can name a process id from a container
  of the other engine that exists in the new one (`Another Paseo daemon
  is already running (PID 80)` when the file was left in place), which
  is why the launcher removes the file before the daemon starts.
- The cross-project check, whose scratch project stands for the other
  project: without egress the agent check passed with 0 failures; with
  `--egress` the check found the route out, and `agent-ui` and
  `ui-forward` did not resolve. `agent pi --dir A -- -p ...` answered
  while the UI ran for project A; `agent pi` and `agent omp` each
  answered a prompt in a scratch project.
- `ui stop` removed the UI containers and `down` removed the llama
  container and all four networks (Docker printed that `tokencrate_ui`
  was still in use at `ui stop`, which is expected while llama runs).

Not covered: a real browser; the GPU; Docker Engine versions other than
29.7.2; a rootful Podman or a Podman without netavark; the Docker
integration workflow in CI.

### The CPU integration check

Purpose: `tests/integration.py` on the CPU with the fixture models, with
the engine-free checks and the UI-set agent checks on the same machine.
Date: 2026-09-20. Environment: the virtual machine with rootless Podman
6.1.2, podman-compose 1.6.0, `crun`, and netavark 2.1.0, kernel 7.2.6,
12 CPUs of an AMD Ryzen 9 7950X, 31.3 GiB of system memory, Python
3.14.7, Node.js 24.20.0, and Ruff 0.16.6. The run was
`CONTAINER_ENGINE=podman LLM_GPU=false python3 tests/integration.py -v`,
with the files of both fixture model sets already under
`LLM_MODELS_DIR` and the base layers of the pi images in the store.

- The setup fetched the skill sets, `doctor` passed with 0 failures and
  the `LLM_GPU=false` warning, and `up` rendered the three fixture
  presets and reported `ci-small` loaded; all ten tests passed in 4,653
  seconds, the pi images of every selection built from the shipped
  manifests over the cached base layers. The run removed its fixture
  copies, containers, networks, reports, and scratch directories, and
  `git status --short` printed nothing it created.
- The agent checks of the three pi selections and of oh-my-pi passed
  with 0 failures. The sets' own check scripts reported, one line each:
  `dotnet: dotnet 10.0.401 builds the xunit template from the cached
  packages`, `web: js-debug answers a DAP initialize request over
  stdio`, `browser: Chromium 153.0.8010.52 built on Debian GNU/Linux 12
  (bookworm) answers --version`, `odin: odin version
  dev-2026-08-nightly:902106f builds and runs a program`, and `coding: 4
  subagent definitions seeded, none pinned to another model`. Every
  check found the model endpoint, no route out, a read-only root, and
  the seeded tools note and pi packages, and printed `[warn] no browser
  UI running; UI isolation not tested`, because the checks run before
  any UI.
- On the CPU, `smoke` on `ci-small` passed with the streamed tool call and
  the mid-conversation system message (115 tokens per second of
  generation), the basic probe on `ci-tiny` passed, and `bench` on
  `ci-small` measured over two iterations of the short prompt.
- The agent prompts dominate the run: oh-my-pi's one prompt and each of
  pi's three take one to two minutes on the 0.6B model. The check accepts
  any answer without a load error; with that model, pi's answers say that
  README.md was not found. A separate prompt with the same model and the
  `coding` selection showed pi calling `read` on the seeded `AGENTS.md`
  path and returning that file's first line, so the tool machinery runs
  and the model chooses the wrong path.
- The independent-client check: four clients answered on `ci-small` with
  one unchanged router and model process; both terminal agents could not
  reach either UI or forwarder by name or effective address, with and
  without egress; targeted stops, retained state, project and image
  changes, near-simultaneous starts, an occupied port, and a failed
  custom UI launch (a private set with a `[ui]` table) behaved as the
  check demands.
- The four home lifecycles passed: every home tmpfs owned by the host
  user with mode `0750`, each session manager reopening its saved
  session in the first container, in the peer, and after stop/start and
  recreation, and the retained directories keeping their markers while
  planted files and settings changes disappeared. The UI containers
  mount one UI path from the host, the set's `state` directory
  (`.pi-web` or `.paseo`), beside the pi transcripts.
- The engine-free gate passed in strict mode
  (`TOKENCRATE_STATIC_STRICT=1 bash tests/static.sh`). `doctor` with the
  machine's `.env` passed with 0 failures and the `LLM_GPU=false`
  warning, and `presets render` validated every preset against its model
  set, all loadable except the two GLM presets waiting for a build.

Not covered: a session that uses `lens_diagnostics`, the `debug` tool,
a subagent, or the browser tools, because the fixture model does not
call tools reliably; Docker Engine, whose CPU runs are in [Docker
Engine](#docker-engine).

### The harnesses and the CPU runs on both engines

Purpose: the engine-free forwarder and local-HTTP harnesses, and the
CPU integration and independent-client checks on both engines with
scratch checkouts. Date: 2026-09-20. Environment: the virtual machine,
Node.js 24.20.0, rootless Podman 6.1.1, and Docker Engine 29.7.2 on a
temporary daemon with a separate store, socket, and bridge; each engine
with an isolated source copy, Compose project, copied fixture models,
scratch clients, fresh retained state, allocated loopback ports, and
`LLM_GPU=false`.

- The forwarder harness exercised HTTP and WebSocket upgrades with all
  three loopback names, implicit and explicit port 80, and a non-default
  port, with unprivileged listeners. Foreign hosts, sibling ports,
  non-HTTP and malformed Origins, duplicate `Host` headers, interrupted
  streams, and disallowed Fetch Metadata were rejected.
- Local API calls bypassed a configured HTTP proxy while ordinary urllib
  calls retained it.
- Both full `python3 tests/integration.py -v` runs passed all 10 tests
  in 887 seconds on Podman and 1,069 seconds on Docker with a fresh image
  store; the runs overlapped on one CPU host, so the times do not compare
  the engines. Both independent-client checks passed: terminal pi and omp
  in RPC mode, PI WEB through its HTTP API, and Paseo through its daemon
  CLI answered on `ci-small` while all clients stayed alive, a repeat pi
  request answered with the same router and model process identities,
  and targeted restarts, saved
  state, project, image, and port changes, close starts, failed launches,
  port collisions, and stop-all passed.
- Whole-stack `down` with both UI pairs and live terminal clients removed
  every test-project container and network on both engines, and startup
  succeeded afterwards; a separate Podman check removed three live
  auto-remove containers and their network.
- Cleanup left no test-project containers or networks; the test image
  tags, the temporary Docker daemon, and its bridge were removed.

Not covered: GPU or MTP inference, real browser rendering, interactive
terminal screens, a host listener on privileged port 80, or the default
host-port combination `4207`, `4224`, `4250`.

### CLI refusals

Purpose: that a wrong command gets one sentence rather than a traceback
or a silent last-value-wins, before the pre-flight. Date: 2026-09-20.
Environment: the GPU host, both browser UIs running.

- Twelve refusals each printed one sentence and exited non-zero, with no
  traceback: `LLM_PORT` of `99999`, `abc` and `0` gave `LLM_PORT requires a
  port from 1 to 65535`; `agent omp --sets` and `smoke --agent omp --sets`
  gave `--sets applies to pi only; oh-my-pi has no agent sets`; a repeated
  `--dir`, `--sets` and `--iterations` gave `<flag> may be given once with
  <command>`; `bench` with the same preset twice gave `--preset names
  qwen3.8-27b-q4-mtp twice`; `smoke` and `bench` with an unknown
  `LLM_DEFAULT_PRESET` gave `unknown preset: nope (run: bash bin/tokencrate
  presets list)`; `ui stop no-such-set` gave `no UI container found:
  no-such-set`.
- The refusals returned before the pre-flight: the block of twelve took
  4 seconds with no stack running, too little for a pre-flight and engine
  detection.
- The closing `podman ps -a` and `podman network ls` were empty after
  `ui stop` and `down`.

Not covered: the same refusals on Docker.

### Egress sessions and the UI networks

Purpose: what a terminal session started with `--egress` can and cannot
reach while a browser UI runs. Date: 2026-09-20. Environment: the GPU
host, rootless Podman 6.1.2 (kernel 7.2.6), netavark 2.1.0-3 and
aardvark-dns 2.1.0-3 on the nftables backend with no `firewall_driver`
set, and PI WEB and Paseo serving a scratch project on their manifests'
host ports (`127.0.0.1:4224` and `127.0.0.1:4250`).

- `smoke --agent pi` and `smoke --agent pi --egress` with both UIs
  running: 0 failures. With `--egress` the route findings read
  `(expected with --egress)`, the gateway probe printed `[info] the
  session is on the default network, not the agents network`, and every
  browser-UI target `is not reachable`: each UI's name and address on the
  `ui` network (`10.89.2.3:8504`, `10.89.2.5:6767`) and each forwarder's
  name and addresses on `ui` and `ui-publish`. Without a UI the same
  checks printed `[warn] no browser UI running; UI isolation not tested`
  and 0 failures. Each UI container bound one UI directory from the
  host (`/home/agent/.pi-web` or `/home/agent/.paseo`) beside the pi
  sessions directory. An `agent pi --egress` prompt answered `OK` on the
  model through the default network.
- A container started by hand on `tokencrate_agents` and the model's
  non-internal `tokencrate_default` got `curl failed (not reachable)`
  from `10.89.2.3:8504`. In the engine's network namespace the bridges
  of the internal `tokencrate_agents` and `tokencrate_ui` carried
  `forwarding = 0`, those of `tokencrate_default` and
  `tokencrate_ui-publish` `1`; the netavark `FORWARD` chain carried
  `policy accept`, and its isolation chains named only the two bridges
  that are not internal.
- `ui stop` and `down` removed both UI pairs, the model, and all four
  networks and left no container.

Not covered: the egress session's network list and the no-relay probe on
this host, recorded on the virtual machine ([The egress network on the
virtual machine](#the-egress-network-on-the-virtual-machine));
Docker Engine, and whether the order in which the network namespace sets
up its bridges holds on every host ([Still
unverified](#still-unverified)).

### The internal bridges of the virtual machine

Purpose: why an internal bridge on rootless Podman sometimes forwards,
which decides whether an `--egress` session can reach a browser UI.
Date: 2026-09-20. Environment: the virtual machine, rootless Podman
6.1.2 with netavark, the interfaces of the engine's rootless network
namespace read directly.

- netavark creates an internal bridge with `forwarding = 0`. When
  `net.ipv4.ip_forward` first changes from 0 to 1 in that namespace,
  which the first non-internal network's setup does, Linux sets
  `forwarding = 1` on every interface that exists at that moment.
- An internal bridge created before that change therefore forwards: a
  container on it and on a non-internal network reached a peer on the
  internal bridge (HTTP status 200). An internal bridge created after
  the change keeps `forwarding = 0`, and the same peer was unreachable.
- On the GPU host ([Egress sessions and the UI
  networks](#egress-sessions-and-the-ui-networks)) the `agents` and `ui`
  bridges carried `forwarding = 0` and the UI was unreachable; the
  netavark firewall is not the boundary there: its `FORWARD` chain had
  `policy accept` and its isolation chains named only the two bridges
  that are not internal.

Not covered: whether `up` orders the network setup the same way on
every host; `smoke --agent pi --egress` with a browser UI running is the
per-host check ([Still unverified](#still-unverified)).

### The egress network on the virtual machine

Purpose: the `--egress` session's network placement and the containment
check's report with and without a browser UI. Date: 2026-09-20.
Environment: the virtual machine, once with rootless Podman 6.1.2 and
once with Docker Engine 29.7.2 and Compose 5.5.1 (the rootful daemon
started for the session and stopped afterwards, the Docker CLI's
`default` context), `LLM_GPU=false` with the `ci-small` fixture loaded,
`LLM_SKILL_SETS=` and the `coding` selection. The sessions that ran a
shell instead of the agent used the wrapper's own `session.prepare` and
Compose `run`, as the integration script does. Every result below holds
on both engines; the addresses are the Podman run's, Docker's differ in
the subnets only.

- `smoke --agent pi --egress` with no UI running: 0 failures, the route
  findings `(expected with --egress)`, `[warn] no browser UI running; UI
  isolation not tested`, and `[info] the session is on the default
  network, not the agents network; the gateway probe does not apply`.
- `ui pi-web` started; its container's home binds were exactly
  `/home/agent/.pi/agent/sessions` and `/home/agent/.pi-web`. The same
  check with the UI running: 0 failures, every UI target `is not
  reachable` (the UI's name and address on the `ui` network, the
  forwarder's name and its addresses on `ui` and `ui-publish`).
- No relay: an offline session held `tokencrate_agents` alone
  (`10.89.2.3`); an egress session started beside it held
  `tokencrate_default` alone. From the egress session the offline
  container's name did not resolve and a connection to its `agents`
  address failed. On Docker, `tokencrate_default` carries a gateway
  (`172.20.0.1`), the host address an egress session reaches, as
  [Privacy and containment](privacy.md#defaults-and-their-limits)
  states.

Not covered: the cloud keys file, recorded below on Podman.

### Browser UIs with --egress and --cloud

Purpose: the UI launch through `compose run`, and what `ui <set>
--cloud` mounts, joins, shows, and exposes. Date: 2026-09-20.
Environment: the virtual machine, once with rootless Podman 6.1.2 and
podman-compose 1.6.0 and once with Docker Engine 29.8.1 and Compose
5.5.1 (the rootful daemon started for the session and stopped
afterwards, the Docker CLI's `default` context), `LLM_GPU=false` with
the `ci-small` fixture loaded, `LLM_SKILL_SETS=`, the `coding`
selection, a scratch project below `/tmp` (`LLM_PROJECT_ROOTS=/tmp`),
and the keys file `local/cloud-keys.env` with the placeholder key
`sk-ant-placeholder-not-a-key`. Every result holds on both engines
unless it names one; the addresses are the Podman run's (Docker's are
`172.19.0.3` on the default network and `172.20.0.2` on `ui`).

- `tests/integration.py` passed all ten tests, in 4,706 seconds on
  Podman and 936 on Docker, the pi images built for the `coding`,
  `coding,pi-web`, `coding,paseo`, and toolchain selections included. Its four-client
  check started both UIs as `tokencrate-ui-pi-web`,
  `tokencrate-ui-forward-pi-web`, `tokencrate-ui-paseo`, and
  `tokencrate-ui-forward-paseo`; PI WEB answered `hello` and Paseo
  `Welcome!` on `ci-small`; the containment probes from both terminal
  agents, with and without egress, listed those four names and their
  addresses on `ui` and `ui-publish` and reached none; the failed
  custom UI launch left both siblings running, `ui stop pi-web` removed
  one pair, the relaunch found the retained transcript, and `down`
  removed the live terminal clients, both UI pairs, and the networks.
- `ui pi-web --cloud --dir P --port 4311` printed the two warnings of
  `agent --cloud` and was ready in 25 seconds. `inspect` of
  `tokencrate-ui-pi-web`: the keys file at `/etc/tokencrate/cloud-keys`
  with `rw=false` beside the project, sessions, and `.pi-web` binds;
  `TOKENCRATE_CLOUD=1` in the environment; the labels
  `io.tokencrate.ui-set=pi-web` and `io.tokencrate.ui-egress=1`;
  addresses on `tokencrate_default` (`10.89.1.3`) and `tokencrate_ui`
  (`10.89.3.3`); no key value anywhere in the document. The forwarder
  sat on `tokencrate_ui` and `tokencrate_ui-publish` only, published
  `127.0.0.1:4311`, and had no `TOKENCRATE_CLOUD`. Inside the UI
  container the launcher shell, `pi-web-sessiond`, and `pi-web-server`
  each held `ANTHROPIC_API_KEY` in their environment, and PI WEB's
  session model list offered the providers `anthropic` and
  `tokencrate`. `status` printed `UI pi-web: forwarder running
  http://127.0.0.1:4311/ project=/tmp/... cloud`.
- `smoke --agent pi --egress` with that UI running: 0 failures, `[info]
  the container resolves tokencrate-ui-pi-web; a browser UI is
  reachable by name; that UI was started with --egress or --cloud`, `[info] the
  container reached browser UI tokencrate-ui-pi-web:8504; ...` and the
  same for `10.89.1.3:8504`, and `is not reachable` for `10.89.3.3:8504`
  and for the forwarder's name and its two addresses. `smoke --agent pi`
  without egress: 0 failures, every one of the six UI targets `is not
  reachable`.
- `ui paseo --dir P --port 4312` (no flag) beside it: from the Paseo
  container `curl http://tokencrate-ui-pi-web:8504/` answered `200`
  and `example.com` did not answer; from the cloud UI `example.com`
  answered `200`. `ui logs pi-web` showed the request from the Paseo
  container's address.
- `ui pi-web --dir P --port 4311` without the flag replaced the pair:
  the UI then sat on `tokencrate_ui` alone with no keys mount, and its
  `status` line ended without `cloud`. `ui stop` removed both pairs;
  the retained agent homes under `data/agents/pi/` held no copy of the
  placeholder key; `down` removed llama and the four networks.
- On Docker, from the host, `curl` with `Host: evil.example:8504` to
  the cloud UI's default-network address answered `200`, past the
  forwarder's checks; its `ui` address did not answer (gateway mode
  `isolated`). Rootless Podman's bridges are inside the user's network
  namespace, and the host does not reach them.
- The `StopTimeout` the engine records for a UI container is 20 seconds
  on Docker and 10 on Podman: podman-compose passes `stop_grace_period`
  to its own `stop` and `down` only, and `ui stop` calls the engine's
  `stop` directly.
- On the GPU host (RTX 5090, driver 615.71.09, rootless Podman 6.1.2,
  `qwen3.8-27b-q4-mtp` loaded, the `coding` selection, the keys file
  holding an OpenRouter key): `ui paseo --cloud --dir /tmp/...` was
  ready in 458 seconds, image build included, with the same mounts,
  labels, and networks as on the VM (`10.89.0.3` on the default network,
  `10.89.2.3` on `ui`); the Paseo daemon, its supervisor, the launcher
  shell, and three node processes held `OPENROUTER_API_KEY`; `status`
  ended the line with `cloud`; the egress check printed the three
  `[info]` lines for the UI's name and default-network address and
  `not reachable` for its `ui` address and the forwarder, 0 failures;
  the offline check 0 failures. `paseo run --provider pi --model
  openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
  --thinking off` inside the UI container reached `completed` in 8
  seconds; the saved agent record names that model, and the pi
  transcript in the retained sessions directory holds the assistant
  turn `CLOUD_OK` with `provider: openrouter`, 8,715 tokens, cost 0.
  The relaunch without the flag, `ui stop`, the key grep of the agent
  homes (nothing), and `down` behaved as on the VM.

Not covered: a cloud model through PI WEB; Paseo's create-agent form
in a browser; a paid provider.

### The cloud keys file and the session container

Purpose: what `agent pi --cloud` refuses, how the keys file reaches pi,
what the engine records of it, what a signal to the wrapper does to the
session container, the llama API's CORS setting, the agent check's route
lines, and `doctor`'s set-name warning. Date: 2026-09-20. Environment:
the virtual machine, rootless Podman 6.1.2 with podman-compose 1.6.0 and
`crun`, kernel 7.2.6, `LLM_GPU=false` with the `ci-small` fixture
loaded, `LLM_SKILL_SETS=` and the `coding` selection, a scratch project
below the home directory, and the keys file `local/cloud-keys.env` with
the placeholder key `sk-ant-placeholder-not-a-key`.

- Four refusals, one sentence each, exit status 1, before the pre-flight:
  no file gave `no cloud keys file at .../local/cloud-keys.env; write one
  NAME=value line per provider key there (.env.example describes it), or
  set LLM_CLOUD_KEYS_FILE`; a directory at that path `the cloud keys
  file is not a regular file`; a file below the project `the cloud keys
  file lies inside the project (...), which agent containers read; move
  it`; `agent omp --cloud` gave `--cloud applies to pi only; oh-my-pi
  reads provider settings from the project's .env files, which could
  redirect a key`.
- `agent pi --cloud -- --list-models anthropic` with the file holding a
  comment line, a blank line, a double-quoted Anthropic key, and an
  OpenAI key whose value carries `=`: the wrapper printed both warnings,
  the second naming the file, and pi listed the 14 Anthropic models of
  its bundled catalogue; the key value appeared nowhere in the output.
  The same command with `--egress` instead of `--cloud` printed `No
  models matching "anthropic"`. A file whose first line is `not a line`
  stopped the container with `cloud keys file line 1 is not NAME=value`.
- A shell started the way the session is: `env` held the exported key,
  `/proc/self/mounts` showed the file at `/etc/tokencrate/cloud-keys`
  mounted `ro`, and `inspect` of the container listed the mount with the
  host path and `RW false`, `TOKENCRATE_CLOUD=1` in its environment,
  `tokencrate_default` as its only network, and the key value nowhere.
  The project's agent home directory had mode `0700`.
- `agent pi --cloud -- -p ...` runs in a container named
  `tokencrate-agent-<12 hex digits>`. With the prompt in progress, a
  `SIGTERM` to the wrapper ended it with status 143 and a `SIGHUP` with
  status 129; in both cases the container was gone within seconds and
  no `podman-compose` process remained. `Ctrl-C` through a
  pseudo-terminal ended the wrapper with status 130 and left no session
  container.
- On the GPU host (rootless Podman 6.1.2, driver 615.71.09, the default
  27B preset), the same steps: `smoke --agent pi` and `smoke --agent pi
  --egress` passed with the lines above and the gateway `10.89.1.1`
  answering from the user's network namespace; `agent pi --cloud --
  --list-models openrouter` with a keys file holding an OpenRouter key
  printed both warnings and OpenRouter's bundled catalogue, and the same
  command with `--egress` alone printed `No models matching
  "openrouter"`. A turn on `openrouter/google/gemma-4-31b-it:free` ended
  in OpenRouter's `429` naming the upstream provider's shared free pool
  (`is_byok: false`, no authentication error), so the file's key reached
  OpenRouter and was accepted; a turn on the local model in the same
  `--cloud` session answered. A second run tried free models in turn:
  `minimax/minimax-m3:free` got OpenRouter's `404` (the model is no
  longer free), and
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` answered
  `CLOUD_OK` in 11 seconds including the container start, so a cloud
  model answered a prompt through the mounted file. Afterwards no key
  value was in any file under the agent homes. With a placeholder key, a turn on
  `anthropic/claude-haiku-4-5` ended in Anthropic's `401`
  `authentication_error`, `API key is invalid.`
- The llama API (`LLAMA_ARG_CORS_ORIGINS=localhost`): `GET /health` with
  `Origin: http://evil.example` answered without an
  `Access-Control-Allow-Origin` header; with `Origin:
  http://127.0.0.1:4300` and `http://localhost:4300` the header echoed
  the origin. A `text/plain` `POST /models/load` with the foreign origin
  answered `404` for the unknown model name: the request was acted on,
  not refused.
- `smoke --agent pi`: 0 failures, with `the container has one network
  interface`, `no default route and no route through a gateway (IPv4 or
  IPv6)`, `no name resolution (example.com does not resolve)`, and the
  gateway `10.89.2.1` answering from the user's network namespace. With
  `--egress`: 0 failures, `the routing table has a default route
  (expected with --egress)`, `example.com resolves (expected with
  --egress)`, and no `coding:` line, the set checks being skipped.
- `doctor` with `LLM_AGENT_SETS=preset` printed `[warn] LLM_AGENT_SETS
  names no known set: preset (run: bash bin/tokencrate agent-sets list)`
  and 0 failures.

Not covered: the interactive model picker and the reported cost; a paid
provider; Docker Engine.

### oh-my-pi and project env files

Purpose: whether an oh-my-pi session with a route out can be made to send
a provider key to an address a project chooses, which decides whether
`--cloud` can be offered through oh-my-pi. Date: 2026-09-20. Environment:
the virtual machine, rootless Podman 6.1.2, the pinned `agent-omp` image
(oh-my-pi 18.2.5) run offline (`--network none`) with the sentinel key
`sk-SENTINEL-not-a-key` in its environment and an HTTP listener inside
the container on port 9999.

- With `ANTHROPIC_BASE_URL=http://127.0.0.1:9999` in the project's
  `.env`, `omp -p hi --model anthropic/claude-sonnet-4-5` sent 8 `POST
  /v1/messages` requests to the listener, each carrying the sentinel in
  `x-api-key`; the same line in `.env.local` gave the same 8. Without the
  file (the control) the listener received no request.
- The mechanism, read in the image: oh-my-pi's CLI merges `<cwd>/.env`,
  `.env.local`, `.env.development`, and `.env.development.local` into its
  environment for every unset variable, and its Anthropic provider uses
  `ANTHROPIC_BASE_URL` when set. pi has no such loader; its bundled SDK
  reads `ANTHROPIC_BASE_URL` from the environment alone, which the
  container's Compose service does not set. `enabledProviders` in
  oh-my-pi's settings opts foreign configuration directories in and gates
  no provider, so it is no remedy.
- `agent omp --cloud` is refused with one sentence before the keys are
  read (engine-free gate, `tests/test_cloud.py`).

Not covered: `~/.env` and oh-my-pi's own configuration directories, which
the agent home tmpfs and the read-only configuration mount keep empty.
