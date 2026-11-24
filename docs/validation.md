# Validation

This page lists the validation procedures, when each last passed, and
what no run covers. A date applies only to the versions and environment
of its run; after a change a procedure covers, repeat it before relying
on the date.

## Status

| Procedure | GPU host, rootless Podman | Virtual machine, rootless Podman | Virtual machine, Docker Engine |
| --- | --- | --- | --- |
| [Static gate](#static-gate-and-cpu-integration-check) | not run (no Node.js) | 2026-11-22 in strict mode | does not apply |
| [CPU integration check](#static-gate-and-cpu-integration-check) | 2026-11-09, `LLM_GPU=true` | 2026-11-22 | 2026-11-09, Engine 29.9.2 with Docker Compose 5.6.1 |
| [NVIDIA host baseline](#nvidia-host-baseline) | 2026-11-13 and 2026-11-14, scripted part, for every preset the pinned build loads except the Qwen3.8-27B ones with several slots, and 2026-11-22 `smoke` and `bench` for those (driver 615.78.08, Podman 6.1.4); 2026-11-09 for its hands-on checks | does not apply | does not apply |
| [Agent check](#nvidia-host-baseline) (`smoke --agent`) | 2026-11-19 for `coding`, `coding,debug,dotnet,web,browser`, `coding,debug,odin`, `coding,guard,judge,todo,mcp,search`, `roles,guard,memory,hindsight,metrics`, and oh-my-pi, for `coding,guard,judge` with the judge service, with and without `--egress`, and for `coding` with pi-web running, with and without `--egress`; 2026-11-22 for `coding`, `coding,debug,dotnet,web,browser`, `coding,debug,odin`, `coding,guard,judge,todo,mcp,search`, `roles,guard,memory,hindsight,metrics`, and `coding,guard,judge` with the judge service, with and without `--egress`; 2026-11-14 for `coding,metrics` and `coding,web` | 2026-11-18 for `coding`, `coding,metrics`, `coding,debug,dotnet,web,browser`, `coding,debug,odin`, `coding,guard,judge,todo,mcp,search`, `roles,memory,hindsight,metrics`, `coding,pi-web`, and oh-my-pi, without the judge and memory services; 2026-11-22 for `coding,guard,judge,roles,todo`, and, with the memory server, for `roles,guard,memory,hindsight,metrics`, `hindsight,search` with and without `--egress`, and oh-my-pi with and without `--egress` | 2026-11-09 for `coding`, `coding,metrics`, `coding,debug,dotnet,web,browser`, `coding,debug,odin`, and oh-my-pi |
| [Agent home check](#agent-home-check) | 2026-11-09 | 2026-11-22 | 2026-11-09 |
| [Cross-project containment check](#cross-project-containment-check) | 2026-11-09, with a browser UI running and with an `--egress` UI | 2026-11-22, with an `--egress` and a `--cloud` UI and with online `--memory` sessions | 2026-09-20, with a `--cloud` UI, Engine 29.8.1 |
| [Independent-client check](#independent-client-check) | 2026-11-09 scripted; 2026-09-20 by hand | 2026-11-22 | 2026-11-09 |
| [Cloud check](#cloud-check) | 2026-11-09, a free OpenRouter model through `agent pi --cloud` | 2026-11-22, placeholder key | 2026-09-20, `ui --cloud` with a placeholder key only, Engine 29.8.1 |
| [Dashboard and stats check](#dashboard-and-stats-check) | 2026-11-09, with the GPU exporter, except Grafana's access checks (step 2) | 2026-11-22, on the CPU fixture preset, without an agent turn | not run |

Each run used the pins of its date.

### Known gaps

No run covers:

- Windows 11 with WSL2 (`doctor` treats it as Linux on x86-64);
- Docker Engine with a GPU, or Docker Engine 28, the oldest `doctor`
  accepts (the runs used 29.7.2 and newer);
- on Docker Engine: the UI daemon's bind address, a `--cloud` terminal
  session and the removal of its container on `SIGTERM`, the llama API's
  CORS setting, the dashboard profile, and the memory server;
- `glm-5.3-flash-q2-uncensored-64k`, which waits behind the
  [build gate](models.md#build-gate);
- a 16 GB card: `gpt-oss-20b-32k` and `qwen3.8-27b-q3-32k` were
  measured on a 32 GB card;
- an internal bridge that forwards: no recorded start met one, so the
  refusal of `up`, `agent`, and `ui` is untested, as is whether `up`
  creates the model's non-internal network first on every host
  ([Rootless Podman](privacy.md#rootless-podman) names the per-host
  check);
- an `--egress` session reaching host services through
  `host.containers.internal` on rootless Podman;
- the effort pi sends on gpt-oss, whose presets do not declare pi's
  seeded `xhigh`;
- oh-my-pi's language-server, subagent, and MCP features;
- pi's project trust: that `defaultProjectTrust: ask` keeps a project's
  `.pi/` resources from loading until the prompt is accepted;
- the dashboard profile over weeks (the 90-day retention, Grafana's
  growth on its tmpfs);
- a cloud answer through pi's interactive model picker or a pi-web
  session, a paid provider, and the reported cost: every
  recorded cloud answer came from a scripted prompt on a free model;
- these [router
  observations](../CONTRIBUTING.md#router-behavior-the-wrapper-relies-on)
  on the pinned build: readiness, `POST /tokenize` without a model, a
  `/metrics` request loading a preset, and the preset-file rules;
- a reverse proxy in front of the loopback ports;
- the loop guard's thresholds in real sessions, the `mcp` set with a
  server, and `roles` on a live cloud provider;
- pi-web started with `--egress` on the GPU host, and pi-web on Docker
  Engine and with `--cloud`;
- how well Kev-4B's verdicts fit agent work;
- a `--memory` session with `hindsight` and a route out on the GPU host
  and on Docker Engine;
- the memory server over real sessions: what it extracts, and its
  requests competing with the session for a one-slot preset;
- on the Qwen3.8-27B presets with several slots: agent sessions, and a
  long prompt's return from the cache in system memory after more or
  longer requests than two of 50K;
- pi's `edit` tool on agent work with the Qwen presets;
- answer quality, refusals included: what three bits cost the 27B on
  agent work, and plain pi against the `coding` bundle on the same
  tasks.

## Hosts

**The GPU host** is Linux x86-64 with an NVIDIA GeForce RTX 5090 (32 GB),
96 GB of system memory, rootless Podman with `crun`, and no Node.js.
**The virtual machine** is Arch Linux with no GPU, 32 GB of RAM,
rootless Podman with `crun`, Docker Engine, and Node.js. Unless a
procedure or Status cell names others, runs used
`LLM_AGENT_SETS=coding` and the default settings otherwise.

## Procedure

### Static gate and CPU integration check

[Contributing](../CONTRIBUTING.md#tests) gives the commands and when to
run them. Neither check establishes GPU behavior or answer quality.

### NVIDIA host baseline

On the NVIDIA host under test, with the pins under test in `pins.env`:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate status
bash bin/tokencrate smoke
bash bin/tokencrate bench --presets qwen3.8-27b-q4-mtp-2x128k,qwen3.8-27b-q4-mtp-128k
```

Then `smoke --preset` and `bench --presets` for every other shipped preset
the host can load, and these hands-on checks:

- In the built-in chat UI, send a message to the default preset and
  confirm the answer and its reasoning block; select another preset and
  confirm the swap in `status`.
- Confirm in `nvidia-smi` that llama-server holds GPU memory and that the
  bench report's generation speed rounds to the estimate in the
  [preset table](models.md#included-presets).
- With `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` set in `.env`, ask
  `bash bin/tokencrate agent pi --dir <project>` for a one-line change
  in a small project, and confirm the file changes and a commit
  succeeds.
- Run `bash bin/tokencrate smoke --agent pi` for each `--sets` selection
  you ship or use, and `bash bin/tokencrate smoke --agent omp`.
- Run `down` and `up`, and confirm the agent sessions under
  `LLM_AGENTS_DIR/pi/` are still present.

Repeat with `CONTAINER_ENGINE=docker` when the Docker path changed.

### Agent home check

Run on both engines after a change to the agent volumes in
`compose.yaml`, the entrypoint, or a UI launcher:

```bash
python3 tests/integration.py -k home_lifecycle
```

This runs the pi, oh-my-pi, and pi-web home checks, with the
integration setup and `down` around them. They verify the home tmpfs
ownership, that nothing outside the retained directories enters or
outlives the home, and that a transcript saved in one container reopens
in a peer and after stop/start and recreation. They run with networking
disabled and no model, so they do not test the production network,
forwarder, or model.

### Cross-project containment check

Run on both engines after a change to the Compose networks, the
forwarder, or the agent check. Create a scratch project `<project-a>`
below the home directory; `smoke --agent` uses a scratch project of its
own as the other project. Copy `tests/fixtures/model-sets/ci-small.toml`
into `config/model-sets/` and `tests/fixtures/presets/ci-small.toml`
into `config/presets/`, and set `LLM_DEFAULT_PRESET=ci-small` (and
`LLM_GPU=false` without a GPU); with a shipped model set loaded instead,
skip these fixture steps and pass `--preset <id>` to every `ui` and
`smoke --agent` command below.

1. `bash bin/tokencrate up --model-sets ci-small`, then
   `bash bin/tokencrate ui pi-web --dir <project-a>`.
2. `bash bin/tokencrate smoke --agent pi`: the UI container and its
   forwarder unreachable by name and address; on Docker, no gateway
   address on the agents network.
3. `bash bin/tokencrate smoke --agent pi --egress`: a default route, and
   every UI peer still unreachable.
4. `bash bin/tokencrate ui pi-web --egress --dir <project-a>`, then
   both checks again: the egress check reports name resolution as
   `[info]`, every UI address and forwarder stay `not reachable`, and the
   check without `--egress` reports 0 failures.
5. `bash bin/tokencrate ui stop`, `bash bin/tokencrate down`, and remove
   the fixture copies.

### Independent-client check

`tests/integration.py` takes over the configured Compose project, so
inspect existing containers first and run it from an isolated checkout
with its own Compose project and free host ports, on each engine:

```bash
python3 tests/integration.py -k concurrent_clients
```

It checks three live clients on one router and model process,
containment from both terminal agents with and without egress, the
forwarder's `Host` and `Origin` checks, and pi-web's transcript and
sidebar state across a stop and restart.

For browser and terminal-screen acceptance, follow the [three-client
workflow](agents.md#use-three-clients-with-one-model) with separate
conversations: confirm the effective preset in each client, and record
the assistant responses and the router and model-process identities
before and after.

### Cloud check

Run after a change to the keys file handling, the session container, or
the UI launchers. Create a scratch project `<project-a>` below the home
directory and write `local/cloud-keys.env` with one placeholder key
(`ANTHROPIC_API_KEY=sk-ant-placeholder-not-a-key`), then:

1. `bash bin/tokencrate agent pi --cloud --dir <project-a> -- --list-models anthropic`:
   the two warnings of `--cloud`, the provider's bundled catalogue, and
   no key value in the output; with `--egress` instead, no Anthropic
   model.
2. `bash bin/tokencrate agent pi --cloud --dir <project-a>` with no keys
   file, a directory at its path, or the file below the project, and
   `bash bin/tokencrate agent omp --cloud --dir <project-a>`: a
   one-sentence refusal each, before the pre-flight.
3. `bash bin/tokencrate ui pi-web --cloud --dir <project-a>`, then
   inspect the UI container with the engine: the keys file mounted
   read-only, `TOKENCRATE_CLOUD=1`, addresses on the `default` and `ui`
   networks, and no key value in the document.
   `bash bin/tokencrate smoke --agent pi --egress` reports name
   resolution as `[info]`, every UI address and forwarder as
   `not reachable`, and 0 failures.
4. With a real key for a provider that offers a free model, one prompt
   through `bash bin/tokencrate agent pi --cloud --dir <project-a>`;
   afterwards, search the agent homes under `LLM_AGENTS_DIR` for the key
   value and find nothing.
5. `bash bin/tokencrate ui stop`, `bash bin/tokencrate down`, and remove
   the keys file.

### Dashboard and stats check

Run after a change to the dashboard profile, the exporter, or the `stats`
modules, with `LLM_DASHBOARD=true` (and `LLM_GPU=true` on the NVIDIA
host):

1. `bash bin/tokencrate up`, then `status`: it lists the profile's
   containers.
2. In Grafana at the address `up` printed: the dashboard renders, an
   anonymous `POST /api/dashboards/db` answers 403, and a foreign `Host`
   is redirected to `127.0.0.1`.
3. After `smoke` and `bench`, Grafana's query API returns
   `llamacpp:prompt_tokens_total` and, with the GPU exporter,
   `DCGM_FI_DEV_FB_USED_BYTES`.
4. `bash bin/tokencrate stats --serve` during an agent turn: the live
   panel fills, and `/live` answers 403 for a foreign `Host`.
5. `bash bin/tokencrate down` also removes the profile's containers and
   networks.

### Record a run

A run keeps its logs, reports, and transcripts in a directory of its own
outside the repository, named by purpose and UTC time. Afterwards:

- Put the run's date in the [Status](#status) table for each procedure
  that passed, with the engine or driver version when it changed; a
  procedure the run failed or did not repeat keeps its old date.
- Change a generation estimate in the [preset
  table](models.md#included-presets) when the run's speed rounds to
  another value.
- Remove the [known gaps](#known-gaps) the run closed and add the ones
  it opened.
- Put each finding on the page that owns it: a recurring failure on
  [Troubleshooting](troubleshooting.md), a measurement that explains a
  setting on that setting's page, a choice in the [settled
  decisions](../CONTRIBUTING.md#settled-decisions).
