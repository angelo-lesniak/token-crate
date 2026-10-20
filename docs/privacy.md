# Privacy and containment

TokenCrate runs models and agents locally. By default, agent containers
have no route to the internet, so their settings cannot enable outbound
requests. The engine must run on this machine
([Configuration](configuration.md)).

`agent pi --cloud` and `ui <set> --cloud` are the exception: they mount
your cloud keys file into that one session or UI and give it a route
out. Nothing restricts the route out to the providers you keyed. [Cloud
providers](agents.md#cloud-providers) covers the keys file and what a
`--cloud` session exposes.

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

Commands not listed above reach only loopback ports or use no network.
Requests to local model and UI APIs
bypass host HTTP proxy settings. [`stats`](cli.md#stats) reads the
retained transcripts on the host and writes a report without message
content; `stats --serve` offers it on a loopback port to local readers
only and polls the model server's loopback port while a page is open.

The llama container joins the default network to publish its loopback
port; UI forwarders join `ui-publish`. Both have outbound routes.
Forwarders send requests only to their UI backend. With the shipped
text-only presets, llama-server and the built-in chat UI make no outbound
requests of their own; the chat UI stores conversations in the browser.
llama-server also serves aggregate Prometheus counters
(`GET /metrics?model=`) on the published loopback port: numeric token,
request, and KV-cache figures, never prompt text. The
[dashboard](configuration.md#dashboard) profile reads those counters
over the internal `dashboard` network and keeps them under
`data/dashboard`. Of its containers, Grafana alone has a route out,
through the network that publishes its port; [Telemetry
switches](#telemetry-switches) lists the outbound features it turns off.

llama.cpp runs in offline mode (`LLAMA_ARG_OFFLINE=1` in `compose.yaml`),
which stops model downloads from URLs or Hugging Face at startup. The
preset renderer passes only a short list of `[server.extra]` options
through, so a preset cannot enable the server's tools, MCP proxy, file
serving, or remote compute; the list is code, reviewed as such
([Adding a model](models.md#adding-a-model)).

## Telemetry switches

TokenCrate disables known telemetry and update checks in its bundled
components. A terminal agent has no internet route without `--egress` or
`--cloud`; a browser UI has none in the default case ([Defaults and
their limits](#defaults-and-their-limits)). With a route out the
switches below still hold. What they do not switch off can reach the
internet: PI WEB's user-started package installs and updates, Paseo's
"What's new" changelog, and the browser tool of the `browser` set.

| Component | Switched off | TokenCrate setting |
| --- | --- | --- |
| pi | The install ping, the update check, and the model-catalogue refresh for every configured provider | `PI_TELEMETRY=0` before the package install and at runtime, `PI_SKIP_VERSION_CHECK=1`, `PI_OFFLINE=1`, `enableInstallTelemetry: false`, `enableAnalytics: false`. Without the catalogue refresh, a cloud provider offers the model list bundled with the pinned package |
| pi extensions (`coding` set) | pi-lens's on-demand installs of language servers and tools; registry packages in pi's package list | `PI_LENS_DISABLE_LSP_INSTALL=1` and `PI_LENS_DISABLE_TOOL_INSTALL=1`; the entrypoint sets the package list to the image's local directories at every start |
| .NET SDK (`dotnet` set) | Usage telemetry, the first-run banner, the workload update check | `DOTNET_CLI_TELEMETRY_OPTOUT=1`, `DOTNET_NOLOGO=1`, `DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1`; NuGet sources cleared to the image cache |
| Chromium (`browser` set) | Nothing by setting: it runs headless inside the container and reaches only what the container reaches | None |
| oh-my-pi | pi's items above; automatic skill learning | Same variables; `config/agents/omp/config.yml` |
| PI WEB (`pi-web` set) | The release check against the npm registry and the hourly model-catalogue refresh | `PI_WEB_OFFLINE=1` and `PI_WEB_SKIP_VERSION_CHECK=1` in the launcher. Not switchable: it asks the session's model (the local llama service) for a title after the first message |
| Paseo (`paseo` set) | The rendezvous relay and the speech-model downloads at daemon start | `PASEO_RELAY_ENABLED=false`, `PASEO_DICTATION_ENABLED=false`, and `PASEO_VOICE_MODE_ENABLED=false` in the launcher; the hub and push features are never set up. The web UI loads nothing from other sites except a changelog when you open "What's new" |
| Grafana (dashboard profile) | Usage reporting, the update checks, feedback links, the news feed, plugin preinstalls and plugin-key retrieval, external snapshot publishing, Gravatar lookups | `GF_ANALYTICS_*=false`, `GF_ANALYTICS_CHECK_FOR_*=false`, `GF_NEWS_NEWS_FEED_ENABLED=false`, `GF_PLUGINS_PREINSTALL_DISABLED=true`, `GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED=true`, `GF_SNAPSHOTS_EXTERNAL_ENABLED=false`, `GF_SECURITY_DISABLE_GRAVATAR=true` in `compose.yaml` |
| Model downloader | Nothing to switch off: standard-library HTTPS, no client library | Reaches huggingface.co and the CDN hosts it redirects to, and sends the token to huggingface.co only |
| llama.cpp | Model downloads at startup | Offline mode (`LLAMA_ARG_OFFLINE=1`) |

## Defaults and their limits

**Ports.** The host ports are published on `127.0.0.1` only, and no
setting exposes them on another address. A reverse proxy with
authentication and TLS on the same host reaches the loopback ports;
TokenCrate provides neither.

**Browser UIs.** A browser UI (`ui <set>`) has no password: PI WEB has no
authentication, and Paseo's is not turned on. Every process on the host
can use the UI port, and with it the agent's access to the project.

**Forwarder.** The forwarder blocks other websites from using the UI. It
returns `403` for a foreign `Host` or `Origin`, or, without an `Origin`,
a `Sec-Fetch-Site` value other than `same-origin` or `none`. These
checks cover cross-site requests and DNS rebinding. Allowed authorities
are exactly `127.0.0.1`, `localhost`, and `[::1]` with the UI's own port
(on port `80`, also without a port), and an `Origin` must use `http://`.
The UI's own `Origin` passes even if the browser marks the request
cross-site, as it does between `127.0.0.1` and `localhost`; one UI's
origin does not authorize another. The UI daemon listens only on the
container's `ui`-network address, so a UI started with `--egress` or
`--cloud` has no listener on its default-network address, and neither
the host on Docker nor an `--egress` session reaches it past the
forwarder ([Validation](validation.md#status) says on which engine a
run has confirmed it). Rootless Podman keeps its bridges in the user's
network namespace, which the host does not reach.

**llama API.** The llama API on `LLM_PORT` has no `Host` check, and its
CORS setting (`LLAMA_ARG_CORS_ORIGINS=localhost` in `compose.yaml`)
governs only whether the server echoes a page's origin in the response
header. After a DNS rebind the page and the API share an origin. A page
of another site that rebinds its name to `127.0.0.1` can then send
requests the server acts on and read the answers: a model load (`POST
/models/load`), a completion, the counters. The slot endpoint, whose
JSON can carry an in-flight prompt, is off (`no-slots = true` in the
rendered `[*]` section; nothing in TokenCrate reads it). The forwarder
and the stats server check `Host`. Grafana answers a request with any
`Host` other than `127.0.0.1` with a `301` to the same path at
`http://127.0.0.1:<LLM_DASHBOARD_PORT>` (`GF_SERVER_ENFORCE_DOMAIN`);
Grafana documents `/api/health` as exempt, which no run has checked.
Host-side clients send no `Origin` and are unaffected.

**Networks.** Terminal agents share the internal `agents` network with
each other and the model, so offline sessions of different projects
reach each other's listeners. All browser UIs, their forwarders, and the
model share the internal `ui` network; each forwarder also joins
`ui-publish` to publish its loopback port. The dashboard profile's
containers share the internal `dashboard` network with the model, and no
agent or UI container is on it ([Dashboard](configuration.md#dashboard)
says what a viewer on this host can do). A session without a route out
cannot reach any UI. A UI started with `--egress` or `--cloud` joins the
default network as well; an `--egress` or `--cloud` terminal session of
any project can then reach that UI, and through it the UI's project and
keys, but no other UI. All UIs share the `ui` network, so while any UI
runs with `--cloud` or `--egress`, every other running UI, of any
project, has a transitive route out through it. A UI without the flag is
offline only when no such UI is running (a [settled
decision](../CONTRIBUTING.md#settled-decisions)). Browser UIs are not
isolated from each other: treat them as trusted peers with access to
their mounted projects.

**Services.** Every service runs with a read-only root filesystem, no
Linux capabilities, `no-new-privileges`, a PID limit, and a size-limited
tmpfs `/tmp`; no service has a memory limit.

**Internal networks.** The internal `agents`, `ui`, and `dashboard`
networks have no route out and no gateway through which agents reach
host services. Compose keeps an existing network's options, so `up` and
every agent or UI start refuse a network of that name that is not
internal, that this Compose project did not create, or that fails the
engine check below. `down`, then `up` recreates it.

**Rootless Podman:** the engine keeps its bridges and gateways in the
user's network namespace, which exposes no host service. Whether an
`--egress` or `--cloud` session can reach a UI peer depends on each
internal bridge's IPv4 `forwarding` flag, which the order of network
creation decides: netavark creates an internal bridge with the flag off,
and the first non-internal network switches IPv4 forwarding on in the
namespace, which turns the flag on for every bridge that already exists.
`up` and every agent or UI start read the flag of each
internal bridge (`podman unshare --rootless-netns`) and refuse a bridge
that forwards. No bridge exists before a container uses the network.
[`smoke --agent pi --egress`](cli.md#smoke), run while a browser UI runs
and again after an engine upgrade, is therefore the per-host proof that
the UI's `ui` address is unreachable from an egress session.

**Docker:** an ordinary internal bridge keeps a host gateway through which
agents could reach services bound to all interfaces.
`compose.docker.yaml` therefore creates the internal networks with
gateway mode `isolated` (Engine 28 or newer; `doctor` rejects older
versions), and a network of those names that has a gateway address is
refused.

**Third-party content.** The model runs third-party weights and a
third-party chat template; agents run third-party skills. Pinning makes
them repeatable, not trustworthy; [Coding agents and
skills](agents.md#what-the-container-can-and-cannot-do) says what the
container limits a bad skill or a confused model to.

**Egress.** An agent with `--egress` or `--cloud` can exfiltrate the
mounted project; use the flags only for projects you would share with
the internet anyway, or pair them with a host firewall. Such a session
also reaches host services bound to non-loopback addresses: on Docker
the default network's gateway is the host, and on rootless Podman the
same is expected through `host.containers.internal`.

**Router API.** Agent and browser UI containers reach the router's whole
API, its management endpoints included: an agent can load another preset
(`POST /models/load`, or a request that names it), which unloads the one
in use.

## Checking yourself

```bash
bash bin/tokencrate smoke --agent pi            # no route out of the agent container
bash bin/tokencrate smoke --agent pi --egress   # a route out, no UI peer (run it while a UI runs)
podman network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
podman network inspect tokencrate_dashboard --format '{{.Internal}}'              # true (with the dashboard)
docker network inspect tokencrate_agents --format '{{json .IPAM.Config}}'         # Docker only: no Gateway
```

On Docker, run the `network inspect` lines with `docker`; each internal
network must also show no `Gateway` in its `IPAM.Config`.
