# Validation

This page records what has been checked, on which versions and hosts,
and what remains unverified.

Every record carries its date. A record uses
the shipped tree and the pins in [Environment](#environment) unless it
names a difference. Results apply only to their tested versions and
environments. After changing a pinned component, Compose file,
entrypoint, renderer, or package code, repeat the relevant procedure
before reusing a result.

## Status

- **Validated**: a defined procedure passed, with a record in
  [Records](#records).
- **Expected**: technical evidence supports the claim, but no recorded
  validation run confirms it.
- **Unverified**: no recorded evidence supports the claim.

| Claim | Term | Engine and host | Record |
| --- | --- | --- | --- |
| A terminal agent of another project, with or without `--egress`, cannot resolve or reach a running UI started without `--egress` or `--cloud`, or its forwarder, by name or container address. On rootless Podman that holds while the internal bridges keep IPv4 forwarding off; on Docker the internal networks have no gateway address | Validated | RTX 5090, rootless Podman 6.1.1 and 6.1.2; Docker Engine 29.7.2 without a GPU | [Egress sessions and the UI networks](#egress-sessions-and-the-ui-networks), [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools), [Docker Engine](#docker-engine), [The internal bridges of the virtual machine](#the-internal-bridges-of-the-virtual-machine) |
| `up` and every agent or UI start read the IPv4 forwarding flag of each internal bridge on rootless Podman and refuse with one sentence while a bridge forwards; the refusal has no recorded run | Expected | rootless Podman | [The internal bridges of the virtual machine](#the-internal-bridges-of-the-virtual-machine) for the boundary the check reads; the agent and UI starts of [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) passed the check with no refusal and no warning (at `up` after `down` no bridge existed yet) |
| `agent pi --cloud`: the four refusals before the pre-flight; the keys file mounted read-only into the named session container with no key value in `inspect` or on the command line; the keyed provider's bundled catalogue (none with `--egress` alone); the session container gone after `SIGTERM`, `SIGHUP`, or `Ctrl-C` to the wrapper; the llama API echoing a loopback `Origin` only; `doctor`'s warning for an `LLM_AGENT_SETS` name no catalogue has | Validated | Arch Linux VM, rootless Podman 6.1.2, placeholder key, llama.cpp b11028 on the CPU; RTX 5090, rootless Podman 6.1.2, an OpenRouter key with a free model answering | [The cloud keys file and the session container](#the-cloud-keys-file-and-the-session-container) |
| The pinned router, rendered with `metrics = true` in `[*]`, serves llamacpp counters at `GET /metrics?model=` across a model swap and, on the GPU preset with real traffic, the spec-decode counters; `bench` writes its measurements as JSON next to the report; `stats` summarizes real transcripts with no message content, session name, or project path | Validated | Arch Linux VM, rootless Podman 6.1.2, llama.cpp b11028 on the CPU; RTX 5090 on `qwen3.8-27b-q4-mtp` | [Metrics counters and the stats report](#metrics-counters-and-the-stats-report), [The metrics run on the GPU](#the-metrics-run-on-the-gpu) |
| The router answers `501` at `/slots` (`no-slots = true` in the rendered `[*]`); nothing in TokenCrate reads that endpoint | Validated | llama.cpp b11028 on the GPU host | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| The `metrics` agent set times pi's requests through a first-party extension that writes `ttft` and `duration` on the assistant message in oh-my-pi's fields, so `stats` fills a pi row of its Timings table; the request pi sends is byte-identical with and without the set | Validated | Arch Linux VM, rootless Podman 6.1.2, the `coding,metrics` image against a stub model endpoint inside the container; RTX 5090 on `qwen3.8-27b-q4-mtp` with tool calls | [The metrics set and its timings extension](#the-metrics-set-and-its-timings-extension) |
| The served stats page shows a live panel of the model server from `/live`, polled from the loopback API at most every 2 seconds while a page is open and only for a preset two consecutive polls reported loaded; `/live` answers only the server's own loopback `Host` names; the saved page carries no panel | Validated | Arch Linux VM, rootless Podman 6.1.2, llama.cpp b11028 on the CPU with the `ci-small` fixture preset, and the RTX 5090 on `qwen3.8-27b-q4-mtp` during an agent session; the page rendered in Chromium 153.0.8010.52 | [The live panel of the served stats page](#the-live-panel-of-the-served-stats-page) |
| `stats --since` and `--agent` keep whole sessions, the Sessions table carries turns and duration, the Thinking levels table keys requests by the last level change before them; `bench --history` lists every saved bench JSON's runs and skips what is not a measurement; the live panel's draft-acceptance tile follows the spec-decode counters and its GPU tiles the host's `nvidia-smi` | Validated | the engine-free harness on Python 3.14.7; RTX 5090, rootless Podman 6.1.2, on `qwen3.8-27b-q4-mtp` after a nine-request tool-calling session, the GPU and acceptance tiles read from the running preset | [The usage command, the filters, and the bench history](#the-usage-command-the-filters-and-the-bench-history) |
| `stats --serve` serves on 127.0.0.1 in the foreground (started with `setsid ... &`, it answered 200 and 403 through the look-around); the wrapper keeps no server process of its own, so `down` has nothing to stop | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| With `LLM_DASHBOARD=true`, `up` starts the exporter, VictoriaMetrics, and Grafana on the internal `dashboard` network beside the model, the exporter reads the router's counters for the loaded preset only (the two-poll rule), VictoriaMetrics keeps them, Grafana serves the provisioned dashboard on loopback to an anonymous viewer who cannot write, with its plugin install, update checks, usage reports, and news feed switched off; `down` removes all three | Validated | Arch Linux VM, rootless Podman 6.1.2, llama.cpp b11028 on the CPU with the `ci-small` fixture preset; RTX 5090, rootless Podman 6.1.2, on `qwen3.8-27b-q4-mtp` with smoke, bench, and an agent session behind it | [The dashboard profile](#the-dashboard-profile) |
| Grafana answers a request whose `Host` is not `127.0.0.1` with a `301` to the same path at `http://127.0.0.1:<LLM_DASHBOARD_PORT>` (`GF_SERVER_ENFORCE_DOMAIN`), `localhost` included | Validated | Grafana 13.2.2, RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| Grafana exempts `/api/health` from the `Host` check (it reports the version only), and its external snapshot publishing and Gravatar lookups are off | Expected | Grafana 13.2.2 | none; `compose.yaml` sets `GF_SNAPSHOTS_EXTERNAL_ENABLED` and `GF_SECURITY_DISABLE_GRAVATAR`, and Grafana's documentation names the exemption |
| NVIDIA's dcgm-exporter serves the GPU's utilization, memory, power, temperature, and clocks as the host user with a read-only root, no capabilities, `no-new-privileges`, and the CDI device as the only device source, which is how the `gpu-exporter` service runs it; through `up` with `LLM_GPU=true` the service starts with the profile, VictoriaMetrics scrapes it, and Grafana answers the GPU's utilization, memory, and power | Validated | RTX 5090, driver 615.71.09, rootless Podman 6.1.2, `podman run` outside Compose and the Compose service through `up` | [The GPU exporter probe](#the-gpu-exporter-probe), [The dashboard profile](#the-dashboard-profile) |
| `stats` writes its report as a self-contained HTML page whose chart (the inlined, hash-pinned uPlot) and tables (the Preset fit table first) match the Markdown and carry no transcript content; the served page leads with a verdict on the loaded preset and answers on 127.0.0.1 only: 200 for its own loopback `Host` names, 403 for others, 404 off `/`, 503 without transcripts | Validated | Arch Linux VM, Python 3.14.7 engine-free harness; the page rendered in Chromium 153.0.8010.52; the GPU host on `qwen3.8-27b-q4-mtp` for the verdict, the live tiles, and the Grafana dashboard | [The stats page and its loopback server](#the-stats-page-and-its-loopback-server), [The stats page's verdict, marks, and tables](#the-stats-pages-verdict-marks-and-tables) |
| An `--egress` session is on the default network alone: it keeps the model, cannot resolve or reach an offline session by name or by its address on the agents network, and its check reports the route out, `[info]` for the gateway probe, and `[warn]` when no browser UI runs | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.7.2 | [The egress network on the virtual machine](#the-egress-network-on-the-virtual-machine) |
| An oh-my-pi session sends the Anthropic key to the address a project's `.env` or `.env.local` names (8 requests to a listener inside the container with the file, 0 without), so `agent omp --cloud` is refused | Validated | Arch Linux VM, rootless Podman 6.1.2, pinned oh-my-pi image offline | [oh-my-pi and project env files](#oh-my-pi-and-project-env-files) |
| The forwarder accepts implicit and explicit port 80 for the exact loopback authorities over HTTP and WebSocket and rejects foreign hosts, origins, sibling ports, and disallowed Fetch Metadata; local model and UI API requests bypass host HTTP proxies; whole-stack shutdown removes live terminal agents, the model, and all project networks, and startup succeeds afterwards | Validated | Node.js 24.20.0 and Python 3.14.7 engine-free harnesses; rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines) |
| Terminal pi and omp in RPC mode, PI WEB through its HTTP API, and Paseo through its daemon CLI answer sequentially while all clients stay alive, with one unchanged router and loaded model process | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2, CPU fixture; RTX 5090 on the shipped preset | [The harnesses and the CPU runs on both engines](#the-harnesses-and-the-cpu-runs-on-both-engines), [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The nine loadable presets in the linked record run through CDI, pass every `smoke` check (including streamed tool calls and mid-conversation system messages), and hold 3 to 7 GiB less than `[requires]`. `bench` measures the MTP preset at about twice the generation speed of the two-slot preset using the same file | Validated | RTX 5090, rootless Podman 6.1.1, driver 610.57.04; the `qwen3.8-flash-next-q4` row on driver 615.71.09 and the `qwen3.8-flash-next-q4-uncensored` row on llama.cpp b10920 | [The llama API and the presets](#the-llama-api-and-the-presets) |
| `qwen3.8-27b-q4-mtp-long` and `qwen3.8-27b-q4-uncensored-mtp-long` pass every `smoke` check, report a 128K context, hold 22.5 GiB against 28 GiB declared with the slot empty and with 119,009 prompt tokens in it, find a code near the start of that prompt, reuse all but the new tokens on the next turn, and generate at the speed of their 64K MTP siblings, twice `qwen3.8-27b-q4-long` | Validated | RTX 5090, driver 615.71.09, rootless Podman 6.1.2 | [The 128K MTP presets](#the-128k-mtp-presets) |
| `gpt-oss-20b-small` and `qwen3.8-27b-q3-small` pass every `smoke` check and hold 12.7 and 13.5 GiB, 2.3 and 1.5 GiB less than the 15 GiB they declare | Validated | RTX 5090, driver 610.57.04, rootless Podman 6.1.1 | [The 16 GB presets](#the-16-gb-presets) |
| The 96 GB tier and the 27B variants hold less than `[requires]` and pass every `smoke` check; Flash-Next reuses a session's growing prompt, and the settings behind `n_cpu_moe`, the 2048 micro-batch, and the unset `load-mode` are measured | Validated | RTX 5090 with 96 GB of RAM, llama.cpp b10920; the `load-mode` session on b11028 | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| `models status` trusts the `<file>.tokencrate-verified` stamp a download wrote (no `verifying:` notice) and `status --verify` re-reads the file; `fetch` and `up --model-set` share `file_state` and are expected to trust it the same way (no run with a present stamped file) | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| The pi image renders and builds for `coding`, `coding,debug,dotnet,web,browser`, and `coding,debug,odin` from the pinned Node base image; each passes the agent check, whose per-set lines come from the sets' `check` scripts; prompts complete on CPU and GPU, with answers checked in the GPU record | Validated | Rootless Podman, with and without a GPU; Docker Engine 29.7.2 without one | [pi and the agent sets](#pi-and-the-agent-sets), [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Both agents run on the GPU with one scripted prompt each: pi edits and commits a file, every agent check passes for the default and the toolchain selections and for oh-my-pi, and both resume a transcript with `--continue` in a new container | Validated | RTX 5090, rootless Podman 6.1.1 | [pi and the agent sets](#pi-and-the-agent-sets), [oh-my-pi](#oh-my-pi) |
| The thinking levels reach the Qwen template; on a task that needs reasoning the 27B generated monotonically more tokens at each level, and on a one-line answer the level made no difference (the effort is an instruction, not a budget) | Validated | RTX 5090 | [pi and the agent sets](#pi-and-the-agent-sets) |
| `ui pi-web` and `ui paseo` start from their sets, answer through the forwarder on loopback, refuse a foreign origin, and run one prompt through pi | Validated | Rootless Podman 6.1.1 with the GPU and 6.1.2 without one; Docker Engine 29.8.1 without one | [PI WEB](#pi-web), [Paseo](#paseo), [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| `ui <set>` starts the UI and its forwarder with `compose run` as `tokencrate-ui-<set>` and `tokencrate-ui-forward-<set>`, a relaunch replaces only that set, and `ui stop` and `down` remove both | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1; RTX 5090, rootless Podman 6.1.2 | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| A UI daemon listens only on its address on the `ui` network, so a `--egress` or `--cloud` UI has no listener on its default-network address: neither the host on Docker nor an egress session reaches the daemon past the forwarder | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host), [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| With `ui <set> --cloud` the keys file is mounted read-only with `TOKENCRATE_CLOUD=1` and no key value in `inspect`; the UI sits on `ui` and `default`, the forwarder on `ui` and `ui-publish` alone; `status` ends the line with `cloud`; a relaunch without the flag drops the mount and the network; on the GPU host `ui paseo --cloud` answered `CLOUD_OK` from a free OpenRouter model | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1, placeholder key; RTX 5090, rootless Podman 6.1.2, an OpenRouter key | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| With a `--cloud` UI running, `smoke --agent pi --egress` reports `[info]` for the UI's name and `not reachable` for its `ui` address and its forwarder, with 0 failures; `smoke --agent pi` reports every UI target `not reachable` with 0 failures | Validated | Arch Linux VM, rootless Podman 6.1.2 and Docker Engine 29.8.1; RTX 5090, rootless Podman 6.1.2 | [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| PI WEB answers successive sessions, reopens its transcript after a restart, runs browser terminal panels, and shares a project with a terminal agent; Paseo answers after recreation and keeps its identity through `ui stop` and a new `ui paseo` | Validated | RTX 5090, rootless Podman 6.1.1 | [PI WEB](#pi-web), [Paseo](#paseo) |
| Paseo's identity (keypair and server id) travels through `LLM_AGENTS_DIR/pi/paseo-state/`, which `ui` mounts read-write at `/run/tokencrate/ui-state` in every Paseo container, so a second project's daemon pairs with the browser without a new pairing | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| `tests/integration.py` passes on the GPU, every test except `test_concurrent_clients`: the fixture presets through the router, the full and basic probes with the swap between them, `bench`, the three pi selections answering, the four agent checks, each agent's thinking level reaching the template, and the four home lifecycles | Validated | RTX 5090, rootless Podman 6.1.1 | [The integration run and the home lifecycles](#the-integration-run-and-the-home-lifecycles) |
| Agent homes keep transcripts, oh-my-pi blobs, and browser-UI state and identity through stop/start and recreation; live settings and other home files do not persist, and a terminal and a UI container on one project share transcripts only | Validated | Rootless Podman 6.1.1 and Docker Engine 29.7.2 | [The integration run and the home lifecycles](#the-integration-run-and-the-home-lifecycles) |
| `tests/integration.py` passes on the CPU with the fixture models | Validated | Rootless Podman 6.1.1 and 6.1.2 and Docker Engine 29.7.2, Arch Linux VM, no GPU | [The CPU integration check](#the-cpu-integration-check), [Docker Engine](#docker-engine) |
| Four clients answer in turn on the shipped MTP preset with one unchanged router and model process, each forwarder refuses foreign and sibling authorities, and a second client queues behind the first: one request takes 7.5 seconds alone and two issued together 14.6 seconds, at unchanged generation speed | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The default preset serves a coding session of a dozen turns in its 64K slot: pi compacts the prompt when it fills and continues, a session whose turns read 20 KB files refills the slot within two turns, and one overflow compaction at 63,312 tokens failed because its summary hit the token cap; long sessions stay far inside the 256 MiB home tmpfs (424 KiB after twelve pi turns; oh-my-pi grows in its retained directories on disk, 8.6 MiB after six turns) | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| A GPU session calls `lens_diagnostics`, the `debug` tool over js-debug, the subagent tool, and the browser tools; the `coding` set seeds its subagent definitions without a `model:` line, so a subagent runs on the session's own model (the scout returned a delegated result in 24 seconds), and the image build and the agent check refuse a definition that names a model of its own; oh-my-pi starts on the selected preset at `xhigh` without its onboarding wizard and its model picker saves a choice for the session | Validated | RTX 5090, rootless Podman 6.1.1 | [Four clients, long sessions, and the tools](#four-clients-long-sessions-and-the-tools) |
| The abliterated 27B does not loop in longer runs: five of six long completions ended on their own, exactly as on the shipped preset, and a six-turn session ended every turn | Validated | RTX 5090 | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| `load-mode = "none"` on Flash-Next doubles prompt processing, also measured after a six-turn agent session, and leaves the host 5 GiB of available memory with 32 GiB of swap in use; the presets keep the memory map | Validated | RTX 5090 with 96 GB of RAM | [The settings of the 96 GB RAM tier](#the-settings-of-the-96-gb-ram-tier) |
| `up` records the engine in `build/stack.json` and `down` removes the record; while a stack runs, every command uses the recorded engine and refuses a disagreeing `CONTAINER_ENGINE` with one sentence | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| `agent` under `timeout` with the terminal on standard input answers a `-p` prompt and exits: the wrapper passes `-T` and gives the engine `/dev/null` for a terminal it may not read from, and the same command with a non-terminal standard input prints the answer | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| A `bench` JSON (schema 2) carries each preset's own `n_ctx`, build, and model path, read after that preset's warm-up; `bench --history` shows them per row and reads schema-1 files with their document-level facts | Validated | RTX 5090, driver 615.78.08, rootless Podman 6.1.3 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| `pins check all` resolves the seven pins with a resolver (llama.cpp through the GitHub releases list and one GHCR manifest, pi and oh-my-pi through npm, the four images through Docker Hub newest first) and prints `no resolver` rows for the other two | Validated | Arch Linux VM with internet access; the GPU host (RTX 5090, rootless Podman 6.1.3), 2026-10-18 | [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host) |
| Either 16 GB preset runs on a 16 GB card: both were measured on a 32 GB one, and the fit follows from what they held | Expected | RTX 5090 | [The 16 GB presets](#the-16-gb-presets) |
| Loading and inference with `glm-5.3-flash-q2` and `glm-5.3-flash-q2-uncensored` on a build with `glm5next`; the pinned build lacks the architecture, and the preset settings await smoke and benchmark measurements | Unverified | RTX 5090 with 96 GB of RAM | [The GLM-5.3-Flash presets](#the-glm-53-flash-presets) |
| Windows 11 with WSL2 | Unverified | WSL2 | none |
| Docker Engine 29.7.2 and 29.8.1 with Compose 5.5.1 run every part of the procedure that needs no GPU: `doctor`, `tests/integration.py` to completion with a first build of the agent images on Docker's store, the agent checks of the `pi-web` and `paseo` sets, both UIs through the forwarder, the cross-project check, and the four home lifecycles; Docker Engine 29.9.0 with Compose 5.6.0 runs the CPU integration check end to end, both UIs through the forwarder and the stack record included | Validated | Docker Engine 29.7.2 and 29.8.1, Arch Linux VM, no GPU; Docker Engine 29.9.0 with Compose 5.6.0 (2026-10-18) | [Docker Engine](#docker-engine), [Browser UIs with --egress and --cloud](#browser-uis-with---egress-and---cloud) |
| Gateway mode `isolated` keeps host services off the agents network on Docker Engine versions between 28 and 29.6; only 29.7.2 has a record, where the agent check also found no default route and no external name resolution. The mode is documented from 28 on and `doctor` checks for 28 | Expected | Docker Engine 29.7.2 | [Docker Engine](#docker-engine) |

### Still unverified

The engine-free gate and the CPU integration check do not cover these:

- on Docker Engine, that a UI daemon's default-network address refuses
  connections (the 2026-10-18 integration run reached both UIs through
  the forwarder and exercised the stack record, and probed no address);
- the forwarding refusal itself: no recorded start met a bridge that
  forwards;
- a `--cloud` UI under the bind change;
- the lock's wait notice on a real contention;
- pi's `defaultProjectTrust: ask` prompt and oh-my-pi's ungated
  `bunfig.toml` preload;
- that Paseo's RPC-mode pi shows no project trust prompt, so `.pi/`
  resources do not load;
- the effort pi sends on gpt-oss while its seeded `xhigh` is a hidden
  level;
- an `--egress` session reaching host services through
  `host.containers.internal` on rootless Podman;
- the GLM presets on a llama.cpp release that carries `glm5next`: run
  `glm-5.3-flash-q2`, then `glm-5.3-flash-q2-uncensored`, each with
  `smoke` and `bench`, and record the build number with the results;
- Docker Engine with the GPU, and the Docker integration workflow in CI;
  the GPU host has no Docker Engine;
- a task that the `debug` tool carries through to the end: the [GPU
  record](#four-clients-long-sessions-and-the-tools) shows the tool
  running, but the model did not finish the task;
- whether the `[requires]` values of the presets that no session has
  filled leave the right headroom ([the 128K
  record](#the-128k-mtp-presets) measured empty and nearly full slots
  for four presets);
- the UI launchers' readiness timeouts for a daemon that never answers:
  no recorded run had a daemon fail to start;
- the live panel's token rates while the dashboard profile runs beside
  an agent turn on the GPU host; the rates during a session are recorded
  without the profile ([the live panel
  record](#the-live-panel-of-the-served-stats-page));
- the provider in pi's interactive model picker, a cloud answer through
  PI WEB's browser session or Paseo's create-agent form, and the
  reported cost: every recorded cloud answer came from a scripted prompt
  on a free model, which reports no cost;
- on Docker Engine, that a `SIGTERM` to the wrapper stops the named
  session container, and the llama API's CORS setting; both records are
  from rootless Podman;
- that `up` sets up the model's non-internal network before the internal
  ones on every host, which keeps IPv4 forwarding off on the internal
  bridges of rootless Podman ([the VM
  record](#the-internal-bridges-of-the-virtual-machine)); [Privacy and
  containment](privacy.md#defaults-and-their-limits) names the per-host
  check.

## Environment

The pins under test, as `bash bin/tokencrate pins` prints them:
`LLAMA_CPP_TAG=server-cuda13-b11028` (`llama-server --version` prints
`build 11028, commit 972d2313b`), `PI_VERSION=0.85.1`,
`OMP_VERSION=18.2.5`, `NODE_TAG=26.9.0-bookworm-slim`,
`BUN_TAG=1.4.2-slim`, `VICTORIAMETRICS_TAG=v1.152.0`,
`GRAFANA_TAG=13.2.2`, `DCGM_EXPORTER_TAG=4.6.1-4.8.4`,
`CUDA_MIN_DRIVER_MAJOR=580`, each image with the digest in `pins.env`.
The agent sets pin PI WEB 1.202609.0, Paseo 0.8.0, the .NET SDK
10.0.401, and Odin `dev-2026-08-nightly:902106f`; the runs used
Debian's Chromium 153.0.8010.52, which the `browser` set installs
unpinned. Unless a record states otherwise, agent sessions used
`LLM_AGENT_SETS=coding`, with `LLM_SKILL_SETS=pocock-core,skill-crate`,
and on the GPU with the model set `qwen3.8-27b-ud-q4-k-xl` and the
preset `qwen3.8-27b-q4-mtp` (`n_ctx` 65536).

Two machines appear in the records. **The GPU host** is Linux x86-64
with an NVIDIA GeForce RTX 5090 (32607 MiB, driver 610.57.04, CUDA
13.3, CDI device `nvidia.com/gpu=all`), 93.35 GiB of system memory
(MemTotal 97883376 kB) and 46 GiB of swap. It runs rootless Podman
6.1.1 or 6.1.2 with podman-compose 1.6.0 and `crun`, Python 3.14.7, and
host UID:GID `1000:1000` with `keep-id`; it has no Node.js, so the
engine-free gate cannot run there. **The virtual machine** is Arch Linux with no GPU,
12 virtual CPUs and 31.3 GiB of RAM, rootless Podman 6.1.1 or 6.1.2
with `crun` and podman-compose 1.6.0, Docker Engine 29.7.2 with Compose
5.5.1 for the Docker runs, Python 3.14.7, Node.js, and Ruff. Each record
names the versions of its run where they differ.

## Procedure

### Engine-free and CPU checks

Run on any Linux machine with a container engine:

```bash
bash tests/static.sh
python3 tests/integration.py
```

[CONTRIBUTING.md](../CONTRIBUTING.md#tests) says what each runs. The
gate's Compose render (`tests/podman-compose.sh`) exports the settings
of `.env.example` and a scratch UI set with a scratch host port. It
checks the rendered networks, mounts, labels, and published ports
against those exported values rather than against literal port numbers.
Neither check proves anything about the GPU or about the quality of the
shipped presets.

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

1. `bash bin/tokencrate up --model-set ci-small`, then `ui pi-web --dir A`
   and `ui paseo --dir A`.
2. `bash bin/tokencrate smoke --agent pi`: every UI container and
   forwarder unreachable by name and address; on Docker, no gateway
   address on the agents network.
3. `bash bin/tokencrate smoke --agent pi --egress`: a default route, and
   every UI peer still unreachable.
4. `bash bin/tokencrate ui pi-web --egress --dir A`, then both checks
   again: the egress check reports the UI's name as `[info]`, its `ui`
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
because omp's first prompt of about 16,000 tokens takes six to eleven
minutes on the runner's CPU. `RPC_TIMEOUT` (default 1200 seconds)
bounds each RPC answer.

For browser and terminal-screen acceptance, follow the
[four-client workflow](agents.md#use-four-clients-with-one-model) with
separate conversations: confirm the effective preset in each client,
especially Paseo's retained profile, and record the assistant responses
and the router and model-process identities before and after. A banner,
health response, or live process does not prove a prompt response; a GPU
or browser claim needs such a run.

### Recording a result

Add a section under [Records](#records), headed by the subject, with:

- Purpose and a `Date:` line;
- Environment: the pins the run measured, from `bash bin/tokencrate
  pins`, the engine and version, GPU and driver; name differences from
  [Environment](#environment) instead of repeating it. A record names
  its own pins, so a run needs no edit of that section first;
- results, including the smoke and benchmark reports;
- a closing "Not covered" paragraph.

Replace records for subjects the run repeated, using the new run's date.
Update the affected [Status](#status) rows and measured columns in the
[preset table](models.md#included-presets). Keep dates and evidence for
subjects the run did not repeat.

## Router behavior the wrapper relies on

The observations were read on llama.cpp build b10920's official image
in router mode (`--models-preset`, `--models-max 1`) with CPU fixture
models. On the pinned b11028 the CPU integration check confirms
readiness polling, preset switching, and preset-file behavior, not the
failure codes.
Repeat these observations after a `LLAMA_CPP_TAG` change.

- Readiness: `GET /health` answers `{"status":"ok"}` while the default
  preset is still `loading` in `GET /models`, so `up` polls `/models` for
  `loaded` (`runtime.wait_until_ready`).
- Swap: a request whose `model` names another preset waits until the
  running request has finished; then the router unloads the loaded model
  and loads the other one. `POST /models/load` answers 400 for the model
  that is loading or loaded and 500 `model limit reached` for another
  model while one is loaded, so `up` asks for a load only when nothing is
  loaded.
- Failure: a preset whose model server exits leaves the router running,
  `/models` reports it `unloaded`, and a request for it answers 500; `up`
  fails when the default preset turns `unloaded` after `loading`.
- Requests without `model` answer 400 `model name is missing from the
  request`; `GET /props`, `POST /tokenize`, and `GET /metrics` need
  `?model=` or a `model` field, which the probe sends. A request routes
  to its preset, so asking `/metrics` for an unloaded preset is expected
  to load it first (the swap above; not observed for `/metrics`): scrape
  only presets `GET /models` reports loaded.
- Preset file: keys are llama-server option names without dashes
  (`jinja = true` becomes `--jinja`, `ui-config-file`
  `--webui-config-file`, `gpu-layers` `--n-gpu-layers`); a key given twice
  keeps the last value silently; keys in `[*]` reach every child; an
  unknown key stops the router at start with `option '<key>' not
  recognized in preset '<name>'`. The renderer therefore keeps a typed
  vocabulary and passes only `override-kv`, `load-mode`,
  `log-prompts-dir`, and `verbose` through `[server.extra]`, refusing
  every other key there.

## Records

### The stats page's verdict, marks, and tables

Purpose: prove the usability pass over the stats page, the live
panel, the Grafana dashboard, and the two terminal outputs. Date:
2026-09-29. Environment: the virtual machine's engine-free harness on
Python 3.14.7 and the pinned pi image's Chromium 153.0.8010.52, over
the GPU host's 47 retained transcripts and its rendered agent model
list (13 presets); and the GPU host (RTX 5090, driver 615.71.09,
rootless Podman 6.1.2, `LLM_AGENT_SETS=coding,metrics,browser`, the
dashboard profile on `qwen3.8-27b-q4-mtp`; runs `ux-20260929T050915Z`
and `ux2-20260929T182936Z` in the validate directory). On the host,
`up`, `smoke`, and `bench` passed, a scripted turn made nine requests,
and the `browser` set's Chromium screenshotted the served page and
Grafana over the host's loopback.

- Preset fit: `presets.rendered_slots` reads each rendered preset's
  slot from the pi model list (`build/agents/pi/models.json`); the
  table judged the host's 13 presets
  the same in the Markdown and the page (the three 32K presets `too
  small` with 93 of 321 requests and 5 sessions over, the 48K one with
  29 and 2, every 64K and 128K preset `fits`), and `--since 1d` the
  day's 17 requests as fitting everywhere.
- The served page led with `qwen3.8-27b-q4-mtp (slot 65,536 tokens,
  loaded): every request fit` on the good status from the sampler's
  last sample; with a 32K preset loaded in the harness, `93 of 321
  requests (29%) would not fit` on the critical one; the chart marked
  the compaction p50 (60,378) and the loaded slot, the saved page the
  most-used preset's slot, legibly over the step lines.
- The summary line of both renderers ended with `4 sessions and 17
  requests in the last 24 h` on the host (`none in the last 24 h` over
  the harness fixture).
- The live panel on the host, two minutes after the turn: the state
  dot with the preset and the sample's time, `54.5` prompt and `9.7`
  generated tokens/s left by the turn's last request, `58%`
  acceptance, `20,943 / 32,607` MiB with the reason `in use / in all`
  (`memory.total` joins the `nvidia-smi` query; 150 samples carried
  the three GPU numbers, power from 335 W after the bench to 43 W
  idle), the two charts side by side at 1280 pixels and stacked at 420;
  without a GPU query the page has no GPU tiles, and a tile without a
  number names its reason (`first sample`, `needs two scrapes`, `no
  draft model`).
- The tables scroll inside their own regions on a phone with the first
  column kept, the column headers sort, the Definitions list stands
  below the tables in both renderers, and the chart carries axis
  titles and a tooltip with both shares.
- `/usage` over RPC after the turn answered one `notify` event: `usage:
  context 9,976 (peak 9,976) · 8,663 in / 1,541 out · cache-read 89% ·
  ttft p50 120 ms, duration p50 1.1 s · 9 requests, 8 tools, 3 errors`.
- `bench --history` printed the host's four rows grouped by preset and
  run, `+12.2` on the newest short row against the previous run at the
  same 65,536 `n_ctx` (137.2 after 125.0 generation tokens/s) and no
  change
  where the context size differs or is unknown.
- Grafana 13.2.2 rendered the provisioned dashboard
  (its API listed the ten panels in order and a 15-minute range,
  answered the stat panel's rate query with 200, and refused an
  anonymous dashboard write with 403): the stat row, Occupancy with
  the turn's `processing` step and Throughput with its burst (about
  145 prompt and 25 generated tokens/s over one minute) in the page's
  blue and orange, the busy-slots and loaded-preset timelines, and the
  GPU panels.
- The strict gate pins the slot reader, the fit verdict and table, the
  chart's marks, the page's scroll regions and sort buttons, the
  last-day clause, the history's grouping and delta, and the
  dashboard's panel order and datasource.

Not covered: the sticky strip, sorting, the tooltip, and the
empty-window overlay in a driven browser (headless screenshots do not
scroll or click; the overlay counts a nonzero rate as a seen request);
the turn's occupancy in the page's own ring (the
sampling loop ended before the turn); print and forced-colors output.

### The usage command, the filters, and the bench history

Purpose: prove the last items of the metrics work: the `metrics` set's
`/usage` command, the `stats` filters and the two new tables, `bench
--history`, and the live panel's new tiles. Date: 2026-09-27.
Environment: the virtual machine, rootless Podman 6.1.2; the
`coding,metrics` image built from the pinned Node base image with the
extension as shipped, pi started through the entrypoint with the stub
model endpoint of [The metrics set and its timings
extension](#the-metrics-set-and-its-timings-extension); the engine-free
harness on Python 3.14.7; `stats` read over the GPU host's 43 retained
transcripts through the share.

- `pi -p 'say hi'` and `pi --continue -p 'say hi again'` sent two
  requests in the image without the command and two in the image with
  it: both request bodies are
  byte-identical between the images (28,362 and 28,471 bytes, 17
  tools). A command is neither a tool nor prompt text.
- `pi --continue --mode rpc` with the prompt `/usage` answered one
  `extension_ui_request` of method `notify`: `usage: 2 requests, 200 in
  / 6 out, cache-read 0%, context 103 (peak 103), ttft p50 167 ms,
  duration p50 0.2 s, 0 tools, 0 errors`, the stub's usage and the
  extension's own timings; the transcript gained no entry from it.
- `stats --since 7d --agent pi` over the share's transcripts reported
  26 of the 34 pi sessions (the summary line names both filters); the
  Sessions table carries turns p50 and duration p50/p90 (pi 10 s and
  5 m 06 s, oh-my-pi 8 s and 3 m 46 s), and the Thinking levels table
  keys the 260 pi requests as `xhigh` 246, `high` 8, `low` 5, `off` 1
  and every oh-my-pi request as `xhigh`; `--since 2027-01-01` is
  refused with "no agent transcripts match since ...", distinct from an
  empty directory, and `--since yesterday` with the syntax sentence.
- `bench --history` over the share's `reports/` printed the two rows of
  the one JSON there (`b11028-972d2313b`, `n_ctx` `?` for a file without
  the field, 1,854.1 and 3,321.9 prompt and 138.8 and 156.1
  generation tokens/s); in this checkout, with no JSON, the note.
- The engine-free gate pins the filters' whole-session rule over
  fixtures with level changes and malformed entries, `bench_history`'s
  skipping and ordering, and the sampler's acceptance and GPU readings.

- On the GPU host (RTX 5090, driver 615.71.09, rootless Podman 6.1.2,
  `LLM_AGENT_SETS=coding,metrics` on `qwen3.8-27b-q4-mtp`, the run
  `metrics-final-20260928T172953Z` in the validate directory, dated
  2026-09-28): a scripted turn made nine requests with eight tool
  calls, two of them errors; `/usage` over RPC answered one `notify`
  event whose every number was the transcript's own (the input sum
  7,847 over the nine usage objects, the nearest-rank p50 of the nine
  `ttft` values 116 ms); `stats --since 1d` reported that session and
  two like it; `bench --history` printed three rows, the new one with
  `n_ctx` 65,536 (125.0 generation tokens/s thirty seconds after `up`
  with the dashboard profile running; not isolated); `stats --serve`
  with `LLM_GPU=true` produced 45 samples in ninety seconds with the
  GPU tiles filled from the host's `nvidia-smi` (21,219 to 21,362 MiB
  in use, 42 to 112 W) and the acceptance tile at 60.4 percent of
  drafted tokens; the window ended before the turn, so the rates in
  it are zero.

Not covered: the live rates while a turn runs on the host with the
dashboard up (the sample window missed the turn); the reasoning-token
item of the plan, closed because the
local router fills `usage.reasoning` with 0 (40 host transcripts
checked).

### The GPU exporter probe

Purpose: decide whether the dashboard profile can carry a GPU exporter
under the shared hardening, by running the image
directly with `podman run` the way the profile runs its services: the
host user with keep-id, a read-only root, no capabilities,
`no-new-privileges`, a tmpfs `/tmp`, the CDI device with
`NVIDIA_VISIBLE_DEVICES=void`, a loopback port; and once more
with the image's own default user. Date: 2026-09-28. Environment: the
GPU host, RTX 5090, driver 615.71.09, rootless Podman 6.1.2; the runs
`gpu-exporter-20260928T181508Z` (started without a network, so no
metrics could be read) and `gpu-exporter-2-20260928T183007Z` in the
validate directory.

- `nvcr.io/nvidia/k8s/dcgm-exporter:4.6.1-4.8.4` (exporter 4.8.4 on
  DCGM 4.6.1) under the hardening: the process runs as uid 1000,
  DCGM and NVML initialize, the RTX 5090 is found, the registry is
  built from the default counters, and `/metrics` served 15 lines with
  `DCGM_FI_DEV_GPU_UTIL`, `FB_USED`, `FB_FREE`, `POWER_USAGE`,
  `GPU_TEMP`, and `SM_CLOCK` for the card. The image declares root and
  `NVIDIA_VISIBLE_DEVICES=all`; neither was needed, and the run with
  its default user served the same 15 lines. The labels carry the
  GPU's UUID, PCI address, model name, driver version, and the
  container's hostname; no host name or path.
- It starts in about a second and holds no writable path but `/tmp`.

Not covered: Docker Engine; a second GPU.

### The dashboard profile

Purpose: prove the opt-in Compose profile behind `LLM_DASHBOARD=true`:
the exporter, VictoriaMetrics, and Grafana start with `up`, the
exporter reads the router's counters for the loaded preset only,
VictoriaMetrics stores them, Grafana shows the provisioned dashboard
to an anonymous viewer on loopback, and `down` removes all three.
Date: 2026-09-27. Environment: the virtual machine, rootless Podman
6.1.2, the pinned router (llama.cpp b11028) on the CPU with the
`ci-small` fixture preset, the images `victoriametrics/victoria-metrics:v1.152.0`
and `grafana/grafana:13.2.2` by their pinned digests and the pinned Node
image for the exporter; the dashboard rendered by the pinned pi image's
Chromium 153.0.8010.52 over the host's loopback.

- `up` with `LLM_DASHBOARD=true` loaded the preset, then started the
  three containers by name under the profile and printed the Grafana
  address; `status` lists them beside llama, and `down` removed them
  with the networks.
- The exporter's `/metrics`, read from inside the `dashboard` network,
  carried `tokencrate_router_up 1`, `tokencrate_preset_loaded{preset="ci-small"} 1`,
  and after a `smoke --basic` the router's numeric `llamacpp:` lines
  (96 prompt tokens, 17 predicted, the spec-decode counters at 0);
  VictoriaMetrics answered `llamacpp:prompt_tokens_total` with 96 for
  the job `llama`, and Grafana's query API returned the same series.
- Grafana: `/api/health` ok, the dashboard `tokencrate-model-server`
  provisioned read-only (`canSave`, `canEdit`, and `canAdmin` false), a
  `POST /api/dashboards/db` as the anonymous viewer answered 403, and
  a login attempt 400 with the form off. Through both of Grafana's
  datasource proxy paths, open to the anonymous viewer, a `POST
  api/v1/query` answered 200 and `api/v1/import` and
  `api/v1/admin/tsdb/delete_series` answered 403 at the exporter's
  query gate, which refused `api/v1/import` from inside the network
  too. The rendered dashboard shows
  the request gauges, the token rates of the smoke traffic, busy slots,
  the loaded preset, and "No data" for draft acceptance on a preset
  without a draft model.
- With `GF_PLUGINS_PREINSTALL_DISABLED=true` Grafana skips its start-up
  plugin re-install from grafana.com, which fails on the read-only root
  ("Plugin not registered" on every query), and the bundled plugin
  answers.
- The exporter's node-driven test pins the two-poll rule: a preset is
  scraped only after two polls reported it loaded, and only
  `/metrics?model=<validated name>` is ever asked; the Compose renders
  and the contract tests cover the profile's services, networks,
  hardening, digests, and the one published port.

- On the GPU host (RTX 5090, rootless Podman 6.1.2, the run
  `metrics-final-20260928T172953Z`, dated 2026-09-28): `up` with
  `LLM_DASHBOARD=true` loaded `qwen3.8-27b-q4-mtp` in the usual time,
  then started the three containers, and `status` listed them beside
  llama with Grafana on `127.0.0.1:4211`. After `smoke`, `bench`, and
  the nine-request agent session, Grafana's query API answered through
  the gate with `llamacpp:prompt_tokens_total` at 9,186 and the
  acceptance ratio at 0.627 for the loaded preset; `/api/health` was
  ok, the anonymous `POST /api/dashboards/db` answered 403, and the
  exporter's log showed both listeners. `down` removed the three
  containers and the `dashboard` and `dashboard-publish` networks with
  the rest.
- On the GPU host again with the `gpu-exporter` service (run
  `dashboard-gpu-20260928T193744Z`, dated 2026-09-28): `up` with
  `LLM_DASHBOARD=true` and `LLM_GPU=true` started the four containers,
  the exporter's log reached "ready to serve metrics" as the host user,
  and after `smoke` Grafana answered through the gate for the `gpu`
  job: `up` 1, `DCGM_FI_DEV_GPU_UTIL` 1, `DCGM_FI_DEV_FB_USED` 21,143
  MiB, `DCGM_FI_DEV_POWER_USAGE` 103.7 W with the 27B preset loaded,
  each series labelled with the card's UUID, PCI address, model name,
  and driver version.

Not covered: the profile on Docker Engine; a `/metrics` read that waits
on a decode step of a busy slot set (the exporter allows 15 s and
keeps the last lines; the host session ran one client); a preset swap
seen by the exporter against the real router (the fake router covers
it); the 90-day retention over real time; Grafana's own database growth
on its tmpfs over weeks.

### The live panel of the served stats page

Purpose: prove that `stats --serve` shows the running model server's
occupancy and throughput from its own counters, that the server polls
only a loaded preset, that `/live` keeps the page's loopback rules, and
that the saved page stays static. Date: 2026-09-27. Environment: the
virtual machine of [The CPU integration check](#the-cpu-integration-check),
rootless Podman 6.1.2, the pinned router (llama.cpp b11028) on the CPU
with the `ci-small` fixture preset (Qwen3-0.6B, `parallel = 1`) started
with `up`; `stats --serve` over a copy of the stub transcripts of [The
metrics set and its timings extension](#the-metrics-set-and-its-timings-extension);
pairs of streaming chat completions (300 tokens each) sent every six
seconds while `/live` was fetched every two; the served page
screenshotted light and dark by the pinned pi image's Chromium
153.0.8010.52 over the host's loopback.

- Fourteen fetches of `/live` returned one more sample each. The first
  named the preset without counters (seen loaded once); from the second
  on the gauges followed the pairs of requests: `processing 1, queued
  1` while both waited, `processing 1, queued 0` once the first had
  finished, `processing 0, queued 0` between pairs. Rates from the
  third sample on: about 9.3 prompt tokens/s and 147 generated tokens/s
  while a request streamed (a 104-token prompt and 300 generated tokens
  per request on the CPU), 0 between pairs.
- Every sample named `ci-small`, the one preset rendered for the run
  (the router's log was not kept; which presets the server asks for is
  pinned by the fake-router audit below).
- `/live` answered 200 for the server's own loopback names and 403 for
  a foreign `Host`; the JSON carries the API address, and per sample the
  time, reachability, the preset's name, whether it was scraped, the
  two gauges, and the two rates, and nothing else.
- Both screenshots show the panel above the report: the state line
  `ci-small loaded`, the four tiles with the last sample, the
  throughput chart with the generated-tokens line stepping between 0
  and about 147 per request pair and the prompt line near 9, the
  occupancy chart with processing and queued as stepped lines between 0
  and 1, time-of-day labels on both x axes, legends under each chart,
  the dark palette applied, and no label collisions.
- The saved page (`stats` without `--serve`) carries no live script and
  no `/live` reference; the strict gate pins that, the `/live` Host
  matrix, and the sampler against a fake router: a preset is scraped
  only after two polls report it loaded (an audit of every `/metrics`
  path asked), a counter going backwards yields no rate for that tick,
  a swap names the new preset a tick before scraping it, a hostile
  preset name and a text label never enter a sample, the ring is
  bounded, and an unreachable API gives unreachable samples.
- SIGTERM stopped the server cleanly (exit 143 through the wrapper's
  signal handler).

- On the GPU host (RTX 5090, `qwen3.8-27b-q4-mtp`, run
  `metrics-set-20260927T203216Z`), `stats --serve` ran beside the
  scripted pi session of [The metrics set and its timings
  extension](#the-metrics-set-and-its-timings-extension) while a loop
  fetched `/live` every two seconds: 64 samples, the first naming the
  preset without counters and every later one scraped, `processing 1`
  in 48 of them and `queued 0` throughout (one client), prompt rates up
  to 513 tokens/s and generation rates mostly between 27 and 492
  tokens/s while the agent worked, 0 between turns. One tick reported
  4,340 generated tokens/s: llama.cpp b11028 adds a request's generated
  tokens to `llamacpp:tokens_predicted_total` when the slot is released
  at the request's end, so a long answer (8,824 tokens after 78 s)
  arrives as one burst; the samples integrate to about 10,960
  generated tokens over the session against 11,070 in the transcript.
  [`stats`](cli.md#stats) states that rule for the panel's rates.
  `down` ended the run; SIGTERM stopped the server.

Not covered: a preset swap and a stack restart seen by a running page
(covered by the fake-router tests only), `--models-max` above 1, and a
wall clock that steps backwards while the page is open (samples out
of order are skipped).

### The metrics set and its timings extension

Purpose: prove that the `metrics` agent set's pi extension writes each
request's time to first token and duration into the transcript, that
`stats` reports them, and that the set leaves the request pi sends to
the model unchanged. Date: 2026-09-27. Environment: the virtual machine
of [The CPU integration check](#the-cpu-integration-check), rootless
Podman 6.1.2, the `agent-pi` images for the `coding` and the
`coding,metrics` selections built from the pinned Node base image; pi
started through the entrypoint as `agent pi` starts it, with a stub
model endpoint inside the container (`--network none`, `--add-host
llama:127.0.0.1`) that records each chat-completion request body and
streams `hi there.` with a delay before its first token, the method of
[Request size of the coding set](#request-size-of-the-coding-set); then
the GPU host (RTX 5090, driver 615.71.09, rootless Podman 6.1.2) with
`LLM_AGENT_SETS=coding,metrics` on `qwen3.8-27b-q4-mtp`, the scripted
run `metrics-set-20260927T203216Z` in the validate directory.

- `pi -p 'say hi'` and then `pi --continue -p 'say hi again'` sent two
  requests in each image. Both request bodies are byte-identical
  between the images (28,369 and 28,478 bytes, 17 tools), the second
  one with the timed assistant message of the first turn in its
  history: the extension registers no tool, command, or prompt text,
  the set has no note, and pi builds the request's assistant messages
  from role and content only.
- With the `coding,metrics` image, the transcript's assistant messages
  carry `ttft: 168` and `duration: 226`, then `ttft: 172` and
  `duration: 232` (milliseconds) against a stub that delays the first
  token by 150 ms; a run against a 400 ms delay carried `ttft: 419` and
  `duration: 475`. Each message keeps its usage and stop reason; the
  `coding` image's transcript carries no timing fields.
- `stats` over the transcripts of the 150 ms and 400 ms runs prints
  the Timings row `| pi | tokencrate | stub | 2 | 169 | 419 | 228 | 475 |`,
  and the Timings table names the agent in its first column, so pi's
  rows and oh-my-pi's rows never merge (both name provider `tokencrate`
  and the same model, and each measures by its own definition).
- `smoke --agent pi --sets coding,metrics` on the CPU stack with the
  `ci-small` fixture preset: `Agent check completed with 0 failure(s).`,
  every containment line `[ok]`, `agent sets seeded: 6 pi package(s)
  and the tools note`, and the set's line `metrics: the timings
  extension parses`.
- The strict gate pins the extension: `node --check`, the rendered
  manifest of every shipped set, and a replay of pi's hook sequence (a
  completed answer gains the two fields; errored, empty, user, and
  tool-result messages are returned untouched).

- On the GPU host, `smoke --agent pi --sets coding,metrics` built the
  image and passed with 0 failures, `6 pi package(s)` seeded and the
  set's line `metrics: the timings extension parses`. A scripted
  two-turn session (write a script, run it, fix it; then list the
  files, the second turn through `--continue` in a new container) made
  eight assistant requests, six with tool calls (`write`, `bash`), all
  eight timed in one transcript: TTFT 126 to 412 ms, durations 536 ms to
  78.4 s (the turn that ran and fixed the script), contexts 7,524 to
  19,050 tokens. `stats` over the host's transcripts, which held that
  session and one like it, printed the pi
  Timings row `| pi | tokencrate | qwen3.8-27b-q4-mtp | 16 | 183 | 412 |
  1748 | 8634 |` next to an oh-my-pi row on another preset, and
  carried no message content, session name, or project path.

Not covered: browser-UI sessions (`pi-web`, `paseo`), and an errored or
aborted request against a real model server (the extension's
stop-reason filter is exercised by the hook replay only).

### The metrics run on the GPU

Purpose: prove the `/metrics` counters on a shipped GPU preset with
real traffic behind them, including the spec-decode counters of the
MTP preset, and the bench JSON and stats outputs on the GPU host.
Date: 2026-09-27. Environment: the GPU host, rootless Podman 6.1.2,
driver 615.71.09, `LLM_AGENT_SETS=coding`, preset
`qwen3.8-27b-q4-mtp`; the scripted run in the validate directory's
`metrics-20260927T125938Z`.

- `up` rebuilt the runtime image from the pinned digest and loaded the
  default preset in 42 seconds, holding 20,697 MiB against the
  declared 24 GiB.
- `smoke` passed all nine checks on the GPU preset, `metrics counters`
  included (16 llamacpp metric names); generation ran at 134 tokens/s
  in the completion check.
- `bench --long` wrote the Markdown report and the JSON samples
  (build `b11028-972d2313b`, three `timings` samples per run):
  1,854/3,322 prompt tokens/s and 138.8/156.1 generation tokens/s for
  the 262- and 6,052-token prompts; the long run's `prompt_ms` of
  1,819 is the first-token wait on a cold 6K prompt.
- A scrape of the loaded preset after that traffic returned 18
  `llamacpp:` series, among them the spec-decode counters:
  951 drafted and 613 accepted tokens over 320 drafts (64.5 percent
  of drafted tokens accepted; by draft position 276/193/144 of 320,
  so 86/60/45 percent), the number MTP tuning needs.
- `stats` on the host reported its own 41 transcripts (288 requests)
  and saved the HTML page with no message content, session names, or
  host paths.

Not covered: a scrape of an unloaded preset (the run scrapes only the
loaded one by design); counter content beyond smoke and bench traffic,
such as a long agent session; every preset other than the default.

### The stats page and its loopback server

Purpose: prove that `stats` writes its report as a self-contained HTML
page whose chart and tables match the Markdown, that the chart's
vendored library is the pinned artifact, and that `stats --serve`
answers only its own loopback `Host` names. Date: 2026-09-27.
Environment: the virtual machine; the engine-free harness
(`tests/test_statspage.py`) on Python 3.14.7, and the page rendered
headless and offline (`--network none`) with Debian Chromium
153.0.8010.52 from the pinned pi image over the GPU host's 41 retained
transcripts.

- Over the synthetic transcripts, the page carries the two inlined
  uPlot 1.6.32 files (SHA-256 asserted against the published npm
  artifact; the gate runs `node --check` over the vendored source),
  the chart mount, the legend, and every table cell of the Markdown
  report. The data island holds one aligned series per agent - leading
  zeros, monotone shares, the flat tail at the axis end - and only
  agent labels and numbers; a `<script>` in a transcript-supplied
  model name arrives escaped, and none of the fixture's content
  markers, session names, or paths appear. The saved page has no
  refresh; the served one reloads every 60 seconds.
- The server, bound to an ephemeral loopback port, answered 200 with
  the page for its own `127.0.0.1:<port>` and `localhost:<port>` Host
  names, 403 for a foreign name, a portless name, and a wrong port,
  404 off `/`, and 503 with its one-sentence explanation for an agents
  directory without transcripts; binding an occupied port is a
  one-sentence refusal.
- Rendered over the GPU host's transcripts (288 requests), the canvas
  chart drew one step line per agent with the distribution its tables
  state - pi crossing 50 percent near 22K tokens, oh-my-pi's first
  step at 19K - with no label collisions in light or dark mode.

Not covered: the crosshair, tooltip, and keyboard readout in a driven
browser (the chart script is syntax-checked and reads only the data
island); the chart's redraw on a color-scheme change or before
printing; a served page under concurrent readers.

### Metrics counters and the stats report

Purpose: prove that the router rendered with `metrics = true` in `[*]`
answers with counters at `GET /metrics?model=` for a loaded and a
swapped preset (the `smoke` check `metrics counters`), that
`bench` writes its JSON measurements next to the Markdown report, and
that `stats` reports over real transcripts without carrying content.
Date: 2026-09-26. Environment: the virtual machine, rootless Podman
6.1.2 with podman-compose 1.6.0 and `crun`, kernel 7.2.6,
`LLM_GPU=false` with the CPU fixture models.

- `python3 tests/integration.py -k probes_swap` passed: the router
  started with `metrics = true` in the rendered `[*]` section, the full
  probe on `ci-small` and the basic probe on `ci-tiny` passed every
  check including `metrics counters`, and the swap between the presets
  held.
- `bench --preset ci-small --iterations 2` saved
  `bench-<timestamp>.json` next to the Markdown report, with build
  `b11028-972d2313b` and one `timings` sample per iteration
  (`prompt_ms` 287 for the 223-token prompt).
- `stats` over the GPU host's 41 retained transcripts, read over the
  VM's share mount, reported 288 requests with first-request p50s
  matching the [pi](#pi-and-the-agent-sets) and [oh-my-pi](#oh-my-pi)
  records, and carried no message content, session names, or project
  paths.

Not covered: the counters' content on the GPU presets over a real
workload and the spec-decode counters of the MTP presets; a scrape of
an unloaded preset, which by the routing rule of
[Router behavior](#router-behavior-the-wrapper-relies-on) loads it
first, was not repeated for `/metrics`.

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
  | `qwen3.8-27b-q4-uncensored-mtp` | 19.7 GiB | 24 GiB |
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
  | `qwen3.8-27b-q4-uncensored-mtp` | 151, 143 | 1,803, 3,221 |
  | `qwen3.8-27b-q6-quality` | 113, 100 | 1,000, 2,707 |
  | `qwen3.8-flash-next-q4` | 32, 31 | 98, 660 |
  | `qwen3.8-flash-next-q4-uncensored` | 37, 36 | 118, 776 |
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

- `doctor`: 19 `[ok]` lines, 0 failures and 0 warnings. `up` downloaded
  the 13.1 GB UD-Q3_K_XL file and rendered 11 of the 13 presets.
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

  The shorter slot costs gpt-oss nothing but context (both presets of
  that file within two percent), and the three-bit 27B generates faster
  than `qwen3.8-27b-q4` (75, 74) because less of a smaller file is read
  per token; drafting would take it to about 14.5 GiB, so it leaves MTP
  off.

Not covered: a 16 GB card, which no run here has; an agent session on
either preset; what three bits cost the 27B on agent work.

### The 128K MTP presets

Purpose: the GPU measurement of `qwen3.8-27b-q4-mtp-long` and
`qwen3.8-27b-q4-uncensored-mtp-long`, the 128K slot with MTP drafting,
next to `qwen3.8-27b-q4-long` and `qwen3.8-27b-q4-uncensored-mtp`, with
an empty and a nearly full slot. Environment: the GPU host on the shipped
pins, driver 615.71.09, rootless Podman 6.1.2, the model files in the
page cache. "Held" is `nvidia-smi` after `smoke` minus what the desktop
held before `up` (960 MiB). Date: 2026-09-20.

- `up` rendered 13 of 15 presets, the four under test among them, and
  loaded the default preset in 7 to 8 seconds.
- `smoke`: every check `pass` on all four presets, three times on
  `qwen3.8-27b-q4-uncensored-mtp-long` and twice on
  `qwen3.8-27b-q4-uncensored-mtp`. Every run ended both completions with
  `stop`, so nothing looped in its reasoning, and the long presets report
  `n_ctx` 131072.
- Held against `[requires]`, with the slot empty and while a prompt of
  119,009 tokens filled it:

  | Preset | Held, empty | Held, 119,009 tokens | `[requires]` |
  | --- | ---: | ---: | ---: |
  | `qwen3.8-27b-q4-mtp` | 19.8 GiB | refused | 24 GiB |
  | `qwen3.8-27b-q4-long` | 21.0 GiB | 21.0 GiB | 28 GiB |
  | `qwen3.8-27b-q4-mtp-long` | 22.5 GiB | 22.5 GiB | 28 GiB |
  | `qwen3.8-27b-q4-uncensored-mtp-long` | 22.4 GiB | 22.4 GiB | 28 GiB |

  The cache is allocated when the preset loads, so a full slot adds
  nothing; drafting costs the 128K slot 1.5 GiB, and the 128K MTP
  presets hold 5.5 GiB less than they declare.
- `bench`, three iterations with a 262-token and a 6,052-token prompt,
  prompt caching off, each pair in one report:

  | Preset | Generation (short, long) | Prompt (short, long) |
  | --- | --- | --- |
  | `qwen3.8-27b-q4-long` | 76, 75 | 2,098, 3,499 |
  | `qwen3.8-27b-q4-mtp-long` | 138, 154 | 1,804, 3,277 |
  | `qwen3.8-27b-q4-uncensored-mtp` | 151, 141 | 1,778, 3,261 |
  | `qwen3.8-27b-q4-uncensored-mtp-long` | 147, 142 | 1,714, 3,258 |

  The 128K slot costs MTP nothing measurable: `qwen3.8-27b-q4-mtp-long`
  generates at the default preset's 138 and 154 tokens per second, twice
  `qwen3.8-27b-q4-long`, and the abliterated pair is within three
  percent of each other.
- The nearly full slot: 5,049 numbered lines with an access code at line
  151, 119,009 prompt tokens (91 percent of the slot), thinking off, and
  a second turn on the same conversation:

  | Preset | Turn 1 | Prompt tokens/s | Generation tokens/s | Code found | Turn 2 processed, reused |
  | --- | ---: | ---: | ---: | --- | --- |
  | `qwen3.8-27b-q4-long` | 63 s | 1,898 | 49 | yes | 32, 119,016 |
  | `qwen3.8-27b-q4-mtp-long` | 68 s | 1,766 | 85 | yes | 31, 119,017 |
  | `qwen3.8-27b-q4-uncensored-mtp-long` | 68 s | 1,756 | 88 | yes | 31, 119,017 |

  Each answered `AZURE-7431` and ended with `stop`. On the second turn
  the context checkpoints left only the new tokens to process. Drafting
  kept its lead with the slot full, at 8 generated tokens per answer.
  The second question asked for the line after line 100: the two MTP
  presets answered `101`, `qwen3.8-27b-q4-long` answered `151`, one
  sample each at temperature 1.0. The default refused the same prompt
  with `400 ... exceeds the available context size (65536 tokens)`.

Not covered: an agent session on either preset; answer quality over a
full slot beyond one retrieval question.

### pi and the agent sets

Purpose: the pi image for the three shipped selections, its agent check,
a scripted task, the thinking levels, and terminal resume, all on the
default 27B preset. Date: 2026-09-20. Environment: the GPU host; the
pi images built from
the pinned Node base image, pulled by its digest, `coding` from scratch
and the other selections reusing its cached layers.

- `smoke --agent pi` for `coding`, `coding,debug,dotnet,web,browser`,
  and `coding,debug,odin`: `Agent check completed with 0 failure(s).`
  each time, with every containment line `[ok]`, the gateway `10.89.1.1`
  answering from the user's network namespace, 5, 7, and 6 pi packages
  seeded, and the sets' own check lines as in [The CPU integration
  check](#the-cpu-integration-check); for the `coding,pi-web` and
  `coding,paseo` selections `pi-web: pi-web 1.202609.0 resolves the
  image's pi and node-pty` and `paseo: paseo 0.8.0 answers --version`.
  The oh-my-pi check passed with the same containment lines.
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

Not covered: a task a subagent carries out end to end; the `odin` set's
debug adapter in a session.

### oh-my-pi

Purpose: the oh-my-pi image, its agent check, a prompt, and terminal
resume on the default 27B preset. Date: 2026-09-20. Environment: the
GPU host; the image `agent-omp:18.2.5-bun1.4.2-slim` from the pinned
Bun base image.

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

### PI WEB

Purpose: the `pi-web` set through `ui pi-web`: readiness through the
forwarder, the retained binds, successive sessions, a restart, and a
terminal agent on the same project. Date: 2026-09-20. Environment: the
GPU host; the image for `coding,pi-web`; the forwarder on the set's
default port,
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
  in the retained `sessions` directory, and `.pi-web/` holds the UI's
  own state files.
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
stop` and a new `ui paseo`. Date: 2026-09-20. Environment: the GPU
host; the image for `coding,paseo`; Paseo reports `daemonVersion
0.8.0`, listens on port 6767 inside the container with `authRequired
false`, and logs its speech providers as unavailable.

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
  after and equal to the copies in the shared store
  `LLM_AGENTS_DIR/pi/paseo-state/`; a file planted in the home before
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
  another project could neither resolve (`getent hosts agent-ui
  ui-forward` printed nothing) nor reach any UI peer, with and without
  `--egress`.
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
- The `coding` set strips the `model:` line from the subagent
  definitions it seeds (the pi package's name cloud models), so each
  subagent runs on the session's own model and thinking level; the image
  build and the agent check refuse a definition that names a model of
  its own. One `subagent` call had the scout report all three TODO
  comments of a scratch project with file and line in 24 seconds.
- oh-my-pi's two settings of its own ([Agent
  configuration](agents.md#agent-configuration)): the onboarding wizard
  stayed off with `startup.setupWizard: false`, and in an interactive
  session the model picker saved a choice with no `EBUSY`, because the
  entrypoint writes the settings into the home and keeps the repository
  file as the overlay above it.

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
  stop/start and recreation. Two concurrent containers shared a
  transcript without sharing live settings or other home files; host
  files outside the retained directories stayed invisible; stop/start
  and recreation removed planted
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
- The first completion after a load took 23 and 38 seconds, the page
  faults of the memory map.
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
check. bf16 holds as much as f16 and buys nothing for prompt processing
on this build.

Checked from the file headers at the pinned commits: the abliterated
27B (huihui-ai) and Unsloth's 27B are both `qwen35` with 866 tensors,
the `blk.64.nextn.*` MTP tensors, and identical embedded chat templates
(9,993 characters, the same SHA-256), so the shipped patched template
applies to the abliterated file. Unsloth's Flash-Next names the
architecture `qwen4exp` and embeds the same template; orcarouter's
Q4_K_S names `qwen4exp` too and embeds a different one (8,952
characters).

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
Date: 2026-09-20. Environment for the attempt: the GPU host on
llama.cpp build b10920, with the orcarouter file (116.9 GB) downloaded;
the build gate was opened by a temporary edit of the model set on the
host (`llama_build = ""`), restored afterwards. No GLM preset ran on
the GPU. Checked:

- The first parts of Unsloth's UD-Q2_K_XL and of orcarouter's Q2_K both
  name the architecture `glm5next`. Part 4 of the Unsloth file carries
  the MTP layer as four `blk.45.nextn` tensors (the headers of all parts
  read in the virtual machine); orcarouter's card says its GGUFs drop
  that head, so its set is `mtp = false` and its preset does not draft.
- The pinned image's `libllama.so`
  (`tokencrate/llama:server-cuda13-b11028`) names `glm5` (`grep -c`
  finds 18) and no `glm5next` (0), so both GLM presets stay behind their
  gate.
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
Date: 2026-09-20. Environment: the virtual machine, the `agent-pi`
image with pi 0.85.1, started through the entrypoint with a stub model
endpoint inside the container (`--add-host llama:127.0.0.1`, no
network) that records each chat-completion request and answers `hi`.
Command in the container:
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

Not covered: oh-my-pi's request; the `dotnet`, `odin`, and `web` sets;
the tokens these characters become, which depend on the model's
tokenizer.

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
  on another address. Through the forwarder, a foreign `Origin`, `Host`,
  or `Sec-Fetch-Site` got `403` and a same-origin request `200`; a
  prompt through
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

Date: 2026-10-18 (Arch Linux VM, Docker Engine 29.9.0 with Compose
5.6.0, no GPU). `tests/integration.py` passed all nine tests in 851
seconds: the fixture presets through the router, the smoke and basic
probes with the swap, `bench`, the three pi selections and oh-my-pi
answering, the four agent checks, both thinking levels, the four home
lifecycles, and the concurrent clients with both UIs through their
forwarders. `build/stack.json` named `docker` while the stack ran and
was gone after `down`.

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
  (`TOKENCRATE_STATIC_STRICT=1 bash tests/static.sh`), and `presets
  render` validated every preset, all loadable except the two GLM ones.

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

- The forwarder harness accepted the loopback authorities over HTTP and
  WebSocket, with implicit and explicit port 80, and rejected foreign
  hosts, sibling ports, malformed Origins, duplicate `Host` headers, and
  disallowed Fetch Metadata.
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
every host ([Still unverified](#still-unverified)).

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
  forwarder's checks, from a daemon that listened on every container
  address; the shipped launchers bind the daemon to its `ui`-network
  address alone, validated on rootless Podman in
  [Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host](#stamps-stack-record-bind-address-paseo-state-and-pin-checks-on-the-gpu-host);
  no Docker run covers it. Its `ui` address did not answer
  (gateway mode `isolated`), and
  rootless Podman's bridges are inside the user's network namespace,
  where the host does not reach them.
- On the GPU host (RTX 5090, driver 615.71.09, rootless Podman 6.1.2,
  `qwen3.8-27b-q4-mtp` loaded, the `coding` selection, the keys file
  holding an OpenRouter key): `ui paseo --cloud --dir /tmp/...` was
  ready in 458 seconds, image build included, with the same mounts,
  labels, and networks as on the VM; the egress check printed `[info]`
  for the UI's name and default-network address and `not reachable`
  for its `ui` address and the forwarder, 0 failures; `paseo run
  --provider pi --model
  openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
  --thinking off` inside the UI container reached `completed` in 8
  seconds, and the pi transcript in the retained sessions directory
  holds the assistant turn `CLOUD_OK` with `provider: openrouter`, cost
  0. The relaunch without the flag, `ui stop`, the key grep of the agent
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
  27B preset), the same steps: `agent pi --cloud --
  --list-models openrouter` with a keys file holding an OpenRouter key
  printed both warnings and OpenRouter's bundled catalogue, and the same
  command with `--egress` alone printed `No models matching
  "openrouter"`. A turn on
  `openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
  answered `CLOUD_OK` in 11 seconds including the container start, so a
  cloud model answered a prompt through the mounted file, and a turn on
  the local model in the same `--cloud` session answered too. Afterwards
  no key value was in any file under the agent homes. With a placeholder
  key, a turn on `anthropic/claude-haiku-4-5` ended in Anthropic's `401`
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
  read (engine-free gate, `tests/test_agents.py`).

Not covered: `~/.env` and oh-my-pi's own configuration directories, which
the agent home tmpfs and the read-only configuration mount keep empty.

### Stamps, stack record, bind address, Paseo state, and pin checks on the GPU host

Purpose: run the model-file stamps, the stack record, `no-slots`,
Grafana's `Host` check, the forwarding pre-flight, a scripted `agent`
without a terminal, the UI daemons' bind address, Paseo's state mount,
the per-preset bench facts, the foreground stats server, and `pins
check` on a running stack. Date: 2026-10-17 and 2026-10-18 (three host
runs, `validate/review-20261017T181728Z`, `review-20261017T192253Z`,
and `refactor-20261019T090646Z`, the last one on the tree whose `stats`
and `models` modules are packages, and the virtual machine's
`validate/pins-check-vm-20261018.log`).

Environment: the GPU host with driver 615.78.08 and rootless Podman
6.1.3 (podman-compose 1.6.0); the pins of [Environment](#environment);
`LLM_AGENT_SETS=coding,metrics`, `LLM_DASHBOARD=true`, the preset
`qwen3.8-27b-q4-mtp` of the model set `qwen3.8-27b-ud-q4-k-xl`.

- Stamps. On the first run `up --model-set qwen3.8-27b-ud-q4-k-xl`
  fetched the 17.6 GB file and wrote `Qwen3.8-27B-UD-Q4_K_XL.gguf.tokencrate-verified`
  (161 bytes, mode 0600) when the download's checksum matched, with no
  `verifying:` notice. `models status` afterwards printed `ready` with no
  notice; `models status --verify` printed `verifying: 1 file(s) (17.6
  GB) by checksum; later runs trust the record written beside each
  verified file` and `ready`. The later runs' plain `up` rendered the
  preset from the present file (no `--model-set`, so no verification
  ran) and printed no notice.
- Stack record and lock. `build/stack.json` held `{"engine": "podman",
  "project": "tokencrate"}` after every `up`; `CONTAINER_ENGINE=docker
  bash bin/tokencrate status` was refused with `the stack runs on podman,
  not docker (build/stack.json); run: CONTAINER_ENGINE=podman bash
  bin/tokencrate down` (exit 1); `build/locks/` held `tokencrate.lock`
  alone. `down` ran at the start of each run (the record's removal was
  not inspected; `runtime.stop_stack` unlinks it).
- The model server. `GET /slots?model=qwen3.8-27b-q4-mtp` answered `501
  Not Implemented`; `/metrics?model=` answered `200`. `smoke` passed all
  nine checks on every run (118 and 137 tokens/s generation on the short
  completion).
- Grafana. `/api/search` with `Host: attacker.example` answered `301
  Moved Permanently` with `Location: http://127.0.0.1:4211/api/search`;
  with its own `Host` it answered `200`; `http://localhost:4211/` was
  redirected to `127.0.0.1` the same way.
- Containment. `smoke --agent pi` (two runs) and `smoke --agent pi
  --egress` (two runs) completed with 0 failures (the egress check: one
  interface, a default route, `example.com` resolves, `[warn] no browser
  UI running`); the agent and UI starts passed the forwarding check with
  no refusal and no warning (at `up` after `down` no bridge existed
  yet).
- The scripted agent. `timeout 600 bash bin/tokencrate agent pi ... --
  -p '...' < /dev/tty` printed `ready` and exited on both runs that
  tried it, as did the run whose standard input was not a terminal; the
  wrapper gave the engine `/dev/null` for the terminal it may not read.
- Browser UIs. `ui pi-web --egress` logged `PI WEB listens on
  10.89.2.3:8504 inside the container`; the container's addresses were
  `tokencrate_default=10.89.0.4` and `tokencrate_ui=10.89.2.3`; a Node
  `fetch` from a peer on `tokencrate_default` to `10.89.0.4:8504` got
  `ECONNREFUSED`; `ui pi-web` without the flag logged the same `ui`
  address; the forwarder answered `200` on `127.0.0.1:4224` and `403`
  for `Host: attacker.example` on every run. `ui paseo` logged `Paseo
  listens on 10.89.2.5:6767` with no copy error;
  `data/agents/pi/paseo-state/` held `daemon-keypair.json` (0600) and
  `server-id`; a second project's `ui paseo` ended with a
  `.paseo/server-id` identical to the store's (`cmp` printed nothing)
  on both runs that tried it.
- Bench. `bench --iterations 1` wrote a schema-2 JSON whose report header
  reads `qwen3.8-27b-q4-mtp: n_ctx 65536, build b11028-972d2313b,
  /models/unsloth/...Q4_K_XL.gguf` (1843.0 prompt and 139.8 generation
  tokens/s); `bench --history` listed the four earlier rows (three
  files) with their document-level facts (`?` for the two rows of the
  oldest file, which has no `n_ctx`) and the new row with its own, on
  both runs that printed it.
- Stats. `stats --since 7d` and, on the last run, `stats --since 14d`
  wrote the report and page; the server started with `setsid bash
  bin/tokencrate stats --serve </dev/null >... &` answered `200` on
  `127.0.0.1:4210` and `403` for `Host: attacker.example`, and kept
  serving through the look-arounds.
- `pins check all`. From the virtual machine and from the host it
  resolved all seven pins, each image with its digest: llama.cpp
  `server-cuda13-b11028 -> server-cuda13-b11718` (the VM) and `->
  server-cuda13-b11723` (the host, a day later) through the releases
  list and one GHCR manifest, pi `0.85.1 -> 1.3.0`, oh-my-pi `18.2.5 ->
  18.12.1` and `18.12.2`, Node `26.9.0 -> 26.12.0`, Bun `1.4.2 ->
  1.4.3`, VictoriaMetrics `v1.152.0 -> v1.154.0`, Grafana `13.2.2 ->
  13.2.4`. It printed `(no resolver; look it up by hand)` for
  `dcgm-exporter` and `cuda-min-driver-major` and exited 0. The listed
  newer pins were not applied.

Not covered: Docker Engine for the bind address's refusal on the
default network; the forwarding refusal itself; a `--cloud` UI under
the bind address; the lock's wait notice (no two commands contended);
`fetch` and `up --model-set` against a present stamped file; the stack
record's removal by `down`; `down` while the stats server runs (it has
no hook to run); the served stats page of the tree with the packages
(the engine-free gate covers it); Grafana's `/api/health` exemption.
