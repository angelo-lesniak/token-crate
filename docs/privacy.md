# Privacy and containment

TokenCrate runs models and agents locally. A route out is a network
path that leaves this machine; by default, agent containers have none,
and no setting grants one. The container engine must run on this
machine.

`--cloud` is the exception: it mounts your cloud keys file into one pi
session or browser UI and gives it a route out, which nothing restricts
to the providers you keyed. [Cloud providers](agents.md#cloud-providers)
says what such a session exposes.

## What leaves the machine

| Activity | Destination | When |
| --- | --- | --- |
| `models fetch` and `models draft` | huggingface.co and, for `fetch`, the Hugging Face CDN hosts it redirects to (`*.cdn.hf.co` and similar) | Only when you run them |
| `skills fetch` | The allowlisted Git hosts in `config/skill-sets/allowed-git-hosts.txt` | Only when you run it |
| `pins check` | api.github.com and ghcr.io (llama.cpp releases and images), registry.npmjs.org, hub.docker.com | Only when you run it |
| The runtime image build | ghcr.io (the llama.cpp server image) | At `up`, when the image is missing or its inputs changed |
| An agent image build | docker.io (the Node or Bun base image), the Debian and npm mirrors, and the `url` of every asset and Git checkout in the selected [agent sets](agent-sets.md), with the hosts those URLs redirect to | At the first `agent`, `smoke --agent`, or `ui <set>` with that selection |
| The forwarder's base image pull | docker.io (the Node image) | At the first `ui <set>` |
| The [dashboard](configuration.md#dashboard) image pulls | docker.io (the VictoriaMetrics, Grafana, and Node images) and, with `LLM_GPU=true`, nvcr.io (the DCGM exporter image) | At the first `up` with `LLM_DASHBOARD=true` |
| `--egress` and `--cloud` sessions and browser UIs | Whatever the agent, the UI, or your commands contact | Only when you ask for it |
| The conversation so far: every prompt, file content, and tool output of the session, the turns the local model answered included | The provider whose model you picked in the agent, over its own endpoint | Only in a `--cloud` session or browser UI, with each request to that model |

Commands not listed above reach only loopback ports or use no network;
requests to local APIs bypass host HTTP proxy settings.

The llama container and the UI forwarders have a route out through the
networks that publish their loopback ports; forwarders send requests
only to their UI backend. With the shipped text-only presets, the model
server and its built-in chat UI make no outbound requests of their own;
the chat UI keeps conversations in the browser. llama.cpp runs in
offline mode (`LLAMA_ARG_OFFLINE=1` in `compose.yaml`), which stops
model downloads at startup, and the preset renderer passes only a short
list of `[server.extra]` options through, so a preset cannot enable the
server's tools, MCP proxy, file serving, or remote compute. The
[dashboard](configuration.md#dashboard) stores the server's numeric
counters, never prompt text, under `data/dashboard`; of its containers,
Grafana alone has a route out.

## Telemetry switches

TokenCrate switches off the known telemetry and update checks of its
bundled components, so they stay off even with a route out. The agent
`Dockerfile`, the entrypoint, `config/agents/`, the set manifests and UI
launchers in `config/agent-sets/`, and the `grafana` service in
`compose.yaml` set the switches. Not switched off, and able to reach
the internet with a route out: PI WEB's user-started package installs
and updates, Paseo's "What's new" changelog, and the `browser` set's
browser tool.

| Component | Switched off |
| --- | --- |
| pi and oh-my-pi | The install ping, the update checks, package installs, and the model-catalogue refresh, so a cloud provider offers the model list bundled with the pinned package; oh-my-pi's automatic skill learning |
| pi-lens (`coding` set) | On-demand installs of language servers and tools |
| .NET SDK (`dotnet` set) | Usage telemetry and the workload update check; NuGet sources point at the image cache |
| PI WEB (`pi-web` set) | The release check and the model-catalogue refresh |
| Paseo (`paseo` set) | The rendezvous relay, the speech-model downloads, and the usage sources, which read other agents' credential files and call their providers; the hub and push features are never set up |
| Grafana (dashboard profile) | Usage reporting, update checks, the news feed, plugin preinstalls and key retrieval, external snapshot publishing, Gravatar lookups |

## Defaults and their limits

### Ports

Every host port listens on `127.0.0.1` only, and no setting exposes it
on another address ([Ports](configuration.md#ports) lists them). Access
from another machine needs a reverse proxy with authentication and TLS
on this host; TokenCrate ships none, and no run covers one. The
forwarder, the stats server, and Grafana check the `Host` header; the
llama API does not ([llama API](#llama-api)).

### Browser UIs

A browser UI (`ui <set>`) has no password: PI WEB has no
authentication, and Paseo's is not turned on. Every process on the host
can use the UI port, and with it the agent's access to the project.

### Forwarder

The forwarder returns `403` for a foreign `Host` or `Origin`, or,
without an `Origin`, a `Sec-Fetch-Site` value other than `same-origin`
or `none`; these checks cover cross-site requests and DNS rebinding.
Allowed authorities are `127.0.0.1`, `localhost`, and `[::1]`
with the UI's own port (on port `80`, also without a port), and an
`Origin` must use `http://`. An allowed `Origin` takes precedence over
`Sec-Fetch-Site`; one UI's origin does not authorize another. The UI
daemon listens only on the container's `ui`-network address, so on
rootless Podman an `--egress` session does not reach it past the
forwarder; on Docker Engine no run covers this ([Known
gaps](validation.md#known-gaps)).

### llama API

The llama API on `LLM_PORT` has no `Host` check; its CORS setting
(`LLAMA_ARG_CORS_ORIGINS=localhost` in `compose.yaml`) governs only the
response header, not which requests the server accepts. A page of
another site that rebinds its name to `127.0.0.1` can therefore send
requests the server acts on and read the answers: a model load (`POST
/models/load`), a completion, the counters. The slot endpoint, whose
JSON can carry an in-flight prompt, is off (`no-slots = true` in the
rendered `[*]` section).

### Networks

Terminal agents share the internal `agents` network with each other
and the model, so offline sessions of different projects reach each
other's listeners. All browser UIs, their forwarders, and the model
share the internal `ui` network. The dashboard profile's containers
share the internal `dashboard` network with the model; no agent or UI
container is on it. A session without a route out
cannot reach any UI; an `--egress` or `--cloud` session can resolve the
name of a UI started with either flag, but the daemon's bind address
prevents a connection ([Forwarder](#forwarder)). A UI started with
`--egress` or `--cloud` joins the default network as well, so while it
runs every other running UI, of any project, has a transitive route out
through the shared `ui` network (a [settled
decision](../CONTRIBUTING.md#settled-decisions)). Browser UIs are not
isolated from each other: treat them as trusted peers with access to
their mounted projects.

### Services

Every service runs with a read-only root filesystem, no Linux
capabilities, `no-new-privileges`, a PID limit, and a size-limited tmpfs
`/tmp`; no service has a memory limit.

### Internal networks

The internal `agents`, `ui`, and `dashboard` networks have no route out
and no gateway through which agents reach host services. Compose keeps an existing network's options, so `up` and
every agent or UI start refuse a network of that name that is not
internal, that this Compose project did not create, or that fails the
engine check below; each refusal names its fix.

### Rootless Podman

The engine keeps its bridges and gateways in the user's network
namespace, which exposes no host service. Whether an `--egress` or
`--cloud` session can reach a UI peer depends on each internal bridge's
IPv4 `forwarding` flag: the first non-internal network turns it on for
every bridge that already exists. `up` and every agent or UI start
refuse an internal bridge that forwards. [`smoke --agent pi
--egress`](cli.md#smoke), run while a browser UI runs and again after
an engine upgrade, proves that an egress session cannot reach the UI.

### Docker

An ordinary internal bridge keeps a host gateway through which agents
could reach services bound to all interfaces. `compose.docker.yaml`
therefore creates the internal networks with gateway mode `isolated`
(Engine 28 or newer).

### Third-party content

The model runs third-party weights and a chat template; agents run
third-party skills. Pinning makes them repeatable, not trustworthy;
[What the container can and cannot
do](agents.md#what-the-container-can-and-cannot-do) states the limits.

### Egress

An agent with `--egress` or `--cloud` can exfiltrate the mounted
project; use the flags only for projects you would share with the
internet anyway, or pair them with a host firewall. Such a session
also reaches host services bound to non-loopback addresses: on Docker
the default network's gateway is the host, and on rootless Podman the
same is expected through `host.containers.internal`.

### Router API

Agent and browser UI containers reach the router's whole API, its
management endpoints included: an agent can load another preset
(`POST /models/load`, or a request that names it), which unloads the one
in use.

## Check the boundaries

```bash
bash bin/tokencrate smoke --agent pi            # no route out of the agent container
bash bin/tokencrate smoke --agent pi --egress   # a route out, no UI peer (run it while a UI runs)
podman network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
podman network inspect tokencrate_dashboard --format '{{.Internal}}'              # true (with the dashboard)
docker network inspect tokencrate_agents --format '{{json .IPAM.Config}}'         # Docker only: no Gateway
```

The lines use the default `COMPOSE_PROJECT_NAME`, `tokencrate`. On
Docker, run the `network inspect` lines with `docker`.
