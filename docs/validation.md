# Validation

This page lists the validation procedures, when each last passed on
which host and engine, and what no procedure covers. A result applies
only to the versions and environment of its run. After changing a pinned
component, Compose file, entrypoint, renderer, or package code, repeat
the relevant procedure before relying on an earlier date.

Validated behavior is stated as plain fact on the page that owns it;
this page says when the run behind it passed. The logs, reports, and
transcripts of each run stay in the run's own directory outside the
repository ([Recording a run](#recording-a-run)).

## Status

| Procedure | GPU host, rootless Podman | Virtual machine, rootless Podman | Virtual machine, Docker Engine |
| --- | --- | --- | --- |
| [Static gate](#static-gate-and-cpu-integration-check) | not run: the host has no Node.js | 2026-10-21 in strict mode | does not apply |
| [CPU integration check](#static-gate-and-cpu-integration-check) | 2026-09-20, `LLM_GPU=true`, without `test_concurrent_clients` | 2026-09-20 | 2026-10-18, Engine 29.9.0 with Docker Compose 5.6.0 |
| [NVIDIA host baseline](#nvidia-host-baseline) | 2026-09-20 for every preset the pinned build loads (driver 610.57.04 and 615.71.09); `smoke` and `bench` on the default preset again 2026-10-18 (driver 615.78.08, Podman 6.1.3) | does not apply | does not apply |
| [Agent check](#nvidia-host-baseline) (`smoke --agent`) | 2026-09-20 for `coding`, `coding,debug,dotnet,web,browser`, `coding,debug,odin`, `coding,pi-web`, `coding,paseo`, and oh-my-pi; `coding,metrics` 2026-09-27 and, with and without `--egress`, 2026-10-18 | 2026-09-20 for the same selections; `coding,metrics` 2026-09-27 | 2026-09-20 for the same selections, Engine 29.7.2 |
| [Agent home check](#agent-home-check) | 2026-09-20 | 2026-09-20 | 2026-10-18 |
| [Cross-project containment check](#cross-project-containment-check) | 2026-09-20 with both UIs running; the checks without a UI again 2026-10-18 | 2026-09-20, with a `--cloud` UI as well | 2026-09-20, Engine 29.7.2; with a `--cloud` UI on 29.8.1 |
| [Independent-client check](#independent-client-check) | 2026-09-20, scripted and by hand in browser windows and terminal screens | 2026-09-20 | 2026-10-18 |
| [Cloud check](#cloud-check) | 2026-09-20 with an OpenRouter key: a free model answered through `agent pi --cloud` and through `ui paseo --cloud` | 2026-09-20, placeholder key | 2026-09-20, `ui pi-web --cloud` with a placeholder key only, Engine 29.8.1 |
| [Dashboard and stats check](#dashboard-and-stats-check) | 2026-09-29, with the GPU exporter | 2026-09-27, on the CPU fixture preset | not run |

The engines of these runs: rootless Podman 6.1.1 to 6.1.3 with
podman-compose 1.6.0 and `crun`, and Docker Engine 29.7.2, 29.8.1, and
29.9.0 with Docker Compose 5.5.1 and 5.6.0. Each run used the pins of its date
as `bash bin/tokencrate pins` prints them; the measured figures on
[Models](models.md#included-presets) name their build.

### Known gaps

No run covers:

- Windows 11 with WSL2 (`doctor` treats it as Linux on x86-64);
- Docker Engine with a GPU; the GPU host has no Docker Engine. Gateway
  mode `isolated` is documented from Engine 28 on and `doctor` checks
  for 28, but only 29.7.2 and newer have a run;
- on Docker Engine: the UI daemon's bind address (that its
  default-network address refuses connections), a `--cloud` terminal
  session and the removal of its container on `SIGTERM`, the llama API's
  CORS setting, and the dashboard profile; each has a rootless Podman
  run only;
- the GLM presets: no llama.cpp release carries `glm5next`. On a release
  that does, run `glm-5.3-flash-q2`, then `glm-5.3-flash-q2-uncensored`,
  each with `smoke` and `bench`, and record the build number with the
  results;
- a 16 GB card: `gpt-oss-20b-small` and `qwen3.8-27b-q3-small` were
  measured on a 32 GB card, where they held 12.7 and 13.5 GiB;
- the forwarding refusal of `up` and the agent and UI starts: no
  recorded start met an internal bridge that forwards, and whether `up`
  sets up the model's non-internal network before the internal ones on
  every host ([Rootless Podman](privacy.md#rootless-podman) names the
  per-host check);
- an `--egress` session reaching host services through
  `host.containers.internal` on rootless Podman;
- the lock's wait notice, which needs two CLI processes contending for
  the lock at once;
- pi's `defaultProjectTrust: ask` prompt and oh-my-pi's ungated
  `bunfig.toml` preload, and that Paseo's RPC-mode pi shows no project
  trust prompt, so `.pi/` resources do not load;
- the effort pi sends on gpt-oss while its seeded `xhigh` is a hidden
  level;
- a task that the `debug` tool carries through to the end: the recorded
  session ran the adapter for 74 assistant messages without finishing;
- oh-my-pi's language-server, subagent, and MCP features;
- whether the `[requires]` values of the presets that no session has
  filled leave the right headroom (the 128K presets were measured with
  an empty and a nearly full slot);
- the UI launchers' readiness timeouts for a daemon that never answers;
- the structured assistant-answer check for pi's toolchain selections,
  the default `coding,metrics` included;
- the live panel's token rates while the dashboard profile runs beside
  an agent turn on the GPU host, and the profile over weeks (the 90-day
  retention, Grafana's growth on its tmpfs);
- Grafana's exemption of `/api/health` from its `Host` check;
- the provider in pi's interactive model picker, a cloud answer through
  PI WEB's browser session or Paseo's create-agent form, a paid provider,
  and the reported cost: every recorded cloud answer came from a scripted
  prompt on a free model;
- `fetch` and `up --model-sets` against a present stamped model file;
  they share `file_state` with `models status`, whose trust in the stamp
  has a run;
- the [router observations](../CONTRIBUTING.md#router-behavior-the-wrapper-relies-on)
  on the pinned build: they were made on the b10920 image; repeat them
  after a `LLAMA_CPP_TAG` change;
- answer quality, refusals included: what three bits cost the 27B on
  agent work, and plain pi against the `coding` bundle on the same tasks
  (the [settled decision](../CONTRIBUTING.md#settled-decisions) names
  that comparison).

## Hosts

**The GPU host** is Linux x86-64 with an NVIDIA GeForce RTX 5090
(32607 MiB), 93.35 GiB of system memory and 46 GiB of swap, rootless
Podman with `crun`, Python 3.14, and host UID:GID `1000:1000` with
`keep-id`; it has no Node.js, so the static gate cannot run there.
**The virtual machine** is Arch Linux with no GPU, 12 virtual CPUs and
31.3 GiB of RAM, rootless Podman with `crun`, Docker Engine for the
Docker runs (the rootful daemon started for a session and stopped
afterwards), Python 3.14, Node.js, and Ruff. Unless a procedure names
another, runs used `LLM_AGENT_SETS=coding`,
`LLM_SKILL_SETS=pocock-core,skill-crate`, and on the GPU the model set
`qwen3.8-27b-ud-q4-k-xl` with the preset `qwen3.8-27b-q4-mtp`.

## Procedure

### Static gate and CPU integration check

[Contributing](../CONTRIBUTING.md#tests) gives the automated-check commands,
prerequisites, coverage, and CI behavior. Neither check establishes GPU
behavior or the answer quality of the shipped presets.

### NVIDIA host baseline

On the NVIDIA host under test, with the pins under test in `pins.env`:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate status
bash bin/tokencrate smoke
bash bin/tokencrate bench --presets qwen3.8-27b-q4,qwen3.8-27b-q4-mtp
```

Then `smoke --preset` and `bench --presets` for every other shipped preset
the host can load, and these hands-on checks:

- Open the built-in UI at the root address, select the default preset,
  send a message, and confirm the answer arrives and the reasoning block is
  shown; select another preset and confirm the model swap in `status`.
- Confirm in `nvidia-smi` that llama-server holds GPU memory and that the
  bench report's generation speed is within a few percent of the
  [preset table](models.md#included-presets).
- Start `bash bin/tokencrate agent pi --dir <project>` in a small project,
  ask for a one-line change, and confirm the file changes and a commit
  succeeds.
- Run `bash bin/tokencrate smoke --agent pi` for each `--sets` selection
  you ship or use, and `bash bin/tokencrate smoke --agent omp`.
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
The checks use the built images in a disposable Compose project with
scratch retained directories, networking disabled, and no model. They
verify:

- the home tmpfs ownership;
- that nothing outside the retained directories enters or outlives the
  home;
- that a transcript saved in one container reopens in a peer and after
  stop/start and recreation;
- that Paseo keeps its identity.

Repeat with `CONTAINER_ENGINE=docker`. These checks do not test the
production network, forwarder, or model.

### Cross-project containment check

Run on both engines after a change to the Compose networks, the forwarder,
or the agent check. Copy `tests/fixtures/model-sets/ci-small.toml` into
`config/model-sets/` and `tests/fixtures/presets/ci-small.toml` into
`config/presets/`. Set `LLM_DEFAULT_PRESET=ci-small` (and `LLM_GPU=false`
on a host without a GPU) and create a scratch project A below the home
directory. On a host with the shipped model set, name the loaded preset
with `--preset` instead. `smoke --agent` runs its check in a scratch
project of its own, which stands for the other project. Then:

1. `bash bin/tokencrate up --model-sets ci-small`, then `ui pi-web --dir A`
   and `ui paseo --dir A`.
2. `bash bin/tokencrate smoke --agent pi`: every UI container and
   forwarder unreachable by name and address; on Docker, no gateway
   address on the agents network.
3. `bash bin/tokencrate smoke --agent pi --egress`: a default route, and
   every UI peer still unreachable.
4. `bash bin/tokencrate ui pi-web --egress --dir A`, then both checks
   again: the egress check reports name resolution as `[info]`, every UI
   address and forwarder stay `not reachable`, and the check without
   `--egress` reports 0 failures.
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

`tests/concurrent_clients.py` says what it checks: four clients kept
alive on one router and model process, containment from both terminal
agents with and without egress, and the forwarders' `Host` and `Origin`
checks among them. `TOKENCRATE_CONCURRENT_AGENTS` selects the terminal
clients kept alive in RPC mode (`pi,omp` by default). CI sets `pi`,
because omp's first prompt is a cold prompt that takes six to eleven
minutes on the runner's CPU. `RPC_TIMEOUT` (default 1200 seconds)
bounds each RPC answer.

For browser and terminal-screen acceptance, follow the
[four-client workflow](agents.md#use-four-clients-with-one-model) with
separate conversations: confirm the effective preset in each client,
especially Paseo's retained profile, and record the assistant responses
and the router and model-process identities before and after. A banner,
health response, or live process does not prove a prompt response; a GPU
or browser claim needs such a run.

### Cloud check

Run after a change to the keys file handling, the session container, or
the UI launchers. Write `local/cloud-keys.env` with one placeholder key
(`ANTHROPIC_API_KEY=sk-ant-placeholder-not-a-key`), then:

1. `bash bin/tokencrate agent pi --cloud -- --list-models anthropic`: the
   two warnings of `--cloud`, the provider's bundled catalogue, and no
   key value in the output; the same command with `--egress` instead
   lists no Anthropic model.
2. `agent pi --cloud` with no keys file, with a directory at its path,
   and with the file below the project, and `agent omp --cloud`: a
   one-sentence refusal each, before the pre-flight.
3. `bash bin/tokencrate ui pi-web --cloud --dir A`, then inspect the UI
   container with the engine: the keys file mounted read-only,
   `TOKENCRATE_CLOUD=1`, addresses on the `default` and `ui` networks,
   and no key value in the document. `smoke --agent pi --egress` reports
   name resolution as `[info]` and every UI address and forwarder as
   `not reachable`, with 0 failures.
4. With a real key for a provider that offers a free model, one prompt
   through `agent pi --cloud` and one through `paseo run --provider pi`
   inside a `--cloud` Paseo container; afterwards search the agent homes
   under `LLM_AGENTS_DIR` for the key value and find nothing.
5. `bash bin/tokencrate ui stop`, `bash bin/tokencrate down`, and remove
   the keys file.

### Dashboard and stats check

Run after a change to the dashboard profile, the exporter, or the `stats`
modules, with `LLM_DASHBOARD=true` (and `LLM_GPU=true` on the NVIDIA
host):

1. `bash bin/tokencrate up`: the profile's containers start after the
   model, and `status` lists them beside llama.
2. Open the Grafana address `up` printed: the provisioned dashboard
   renders, a `POST /api/dashboards/db` as the anonymous viewer answers
   403, and a request with a foreign `Host` is redirected to
   `127.0.0.1`.
3. After `smoke` and `bench`, Grafana's query API answers
   `llamacpp:prompt_tokens_total` for the loaded preset and, with the
   GPU exporter, `DCGM_FI_DEV_FB_USED`.
4. `bash bin/tokencrate stats --serve` beside an agent turn: the live
   panel fills its tiles, and `/live` answers 403 for a foreign `Host`.
5. `bash bin/tokencrate down` removes the profile's containers and
   networks with the rest.

### Recording a run

A run writes its logs, reports, and transcripts to a directory of its
own outside the repository, named by purpose and UTC time; nothing of it
is copied here. Afterwards:

- Put the run's date in the [Status](#status) table for each procedure
  that passed, with the engine or driver version when it changed, and
  keep the old date for a procedure the run did not repeat or that
  failed.
- Refresh the measured columns of the
  [preset table](models.md#included-presets) for every preset the run
  re-measured.
- Remove the [known gaps](#known-gaps) the run closed and add the ones
  it opened.
- Put what the run found on the page that owns it: a failure that will
  recur on [Troubleshooting](troubleshooting.md), a measurement that
  explains a setting on the page of that setting, a choice in the
  [settled decisions](../CONTRIBUTING.md#settled-decisions).
