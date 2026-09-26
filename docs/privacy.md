# Privacy and containment

TokenCrate runs models and agents locally. By default, agent containers
have no route to the internet, so their settings cannot enable outbound
requests. This requires a
[local container engine](configuration.md#configuration); remote engine
connections are unsupported.

`agent pi --cloud` and `ui <set> --cloud` are the exception: they mount
your cloud keys file into that one session or UI and give it a route
out. Nothing restricts the route out to the providers you keyed. [Cloud
providers](agents.md#cloud-providers) says how to set the file up, who
can use the keys while a session or a UI runs, and why oh-my-pi is not
offered them.

## What leaves the machine

| Activity | Destination | When |
| --- | --- | --- |
| `models fetch` and `models draft` | huggingface.co and, for `fetch`, the Hugging Face CDN hosts it redirects to (`*.cdn.hf.co` and similar) | Only when you run them |
| `skills fetch` | The allowlisted Git hosts in `config/skill-sets/allowed-git-hosts.txt` | Only when you run it |
| `pins check` | ghcr.io, registry.npmjs.org, hub.docker.com | Only when you run it |
| The runtime image build | ghcr.io (the llama.cpp server image) | At `up`, when the image is missing or its inputs changed |
| An agent image build | docker.io (the Node or Bun base image), the Debian and npm mirrors, and the `url` of every asset and Git checkout in the selected [agent sets](agent-sets.md): github.com with the asset hosts it redirects to (`objects.githubusercontent.com` and similar) for `debug`, `dotnet`, `web`, and `odin`, and builds.dotnet.microsoft.com and nuget.org for `dotnet` | At the first `agent`, `smoke --agent`, or `ui <set>` with that selection |
| The forwarder's base image pull | docker.io (the Node image) | At the first `ui <set>` |
| `--egress` and `--cloud` sessions and browser UIs | Whatever the agent, the UI, or your commands contact | Only when you ask for it |
| The conversation so far: every prompt, file content, and tool output of the session, the turns the local model answered included | The provider whose model you picked in the agent, over its own endpoint | Only in a `--cloud` session or browser UI, with each request to that model |

Commands run on the host as your user. Those not listed above reach only
loopback ports or use no network. Requests to local model and UI APIs
bypass host HTTP proxy settings.

The llama container joins the default network to publish its loopback
port; UI forwarders join `ui-publish`. Both have outbound routes.
Forwarders send requests only to their UI backend. With the shipped
text-only presets, llama-server and the built-in chat UI make no outbound
requests of their own. The built-in chat UI stores conversations in the
browser.

llama.cpp runs in offline mode (`LLAMA_ARG_OFFLINE=1` in `compose.yaml`),
which stops model downloads from URLs or Hugging Face at startup. The
preset renderer passes only a short list of `[server.extra]` options
through, so a preset cannot enable the server's tools, MCP proxy, file
serving, or remote compute; the list is code, reviewed as such
([Adding a model](models.md#adding-a-model)).

## Telemetry switches

TokenCrate disables known telemetry and update checks in its bundled
components. Browser UI containers and terminal agents have no internet
route without `--egress` or `--cloud`. With one of them the switches
below still hold, but what they do not switch off can reach the
internet: PI WEB's user-started package installs and updates, Paseo's
"What's new" changelog, and the browser tool of the `browser` set.

| Component | Default upstream behavior | TokenCrate setting |
| --- | --- | --- |
| pi | Anonymous install ping and update check; a model-catalogue refresh for every configured provider | `PI_TELEMETRY=0` before the package install and at runtime, `PI_SKIP_VERSION_CHECK=1`, `PI_OFFLINE=1`, `enableInstallTelemetry: false`, `enableAnalytics: false`. The offline switch also stops the catalogue refresh, so a cloud provider offers the model list bundled with the pinned package |
| pi extensions (`coding` set) | pi-lens installs language servers and tools on demand; the package list in pi's settings can name registry packages | `PI_LENS_DISABLE_LSP_INSTALL=1` and `PI_LENS_DISABLE_TOOL_INSTALL=1`; the entrypoint sets the package list to the image's local directories at every start |
| .NET SDK (`dotnet` set) | Usage telemetry, first-run banner, workload update check | `DOTNET_CLI_TELEMETRY_OPTOUT=1`, `DOTNET_NOLOGO=1`, `DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1`; NuGet sources cleared to the image cache |
| Chromium (`browser` set) | Update and safe-browsing requests of a desktop browser | Runs headless inside the container; the browser tool reaches only what the container reaches |
| oh-my-pi | Inherits pi's switches; optional OpenTelemetry export | Same variables; automatic skill learning disabled |
| PI WEB (`pi-web` set) | No telemetry; a release check against the npm registry and an hourly model-catalog refresh through pi; user-started package installs and updates | `PI_WEB_OFFLINE=1` and `PI_WEB_SKIP_VERSION_CHECK=1` in the launcher. Not switchable: it asks the session's model (the local llama service) for a title after the first message |
| Paseo (`paseo` set) | No telemetry; a rendezvous relay, a hub, speech-model downloads at daemon start, push notifications for paired phones, provider quota lookups | `PASEO_RELAY_ENABLED=false`, `PASEO_DICTATION_ENABLED=false`, and `PASEO_VOICE_MODE_ENABLED=false` in the launcher; the hub and push features are never set up. The bundled web UI loads nothing from other sites except a changelog when you open "What's new" |
| Model downloader | None: standard-library HTTPS, no client library | No telemetry; reaches huggingface.co and the CDN hosts it redirects to, and sends the token to huggingface.co only |
| llama.cpp | None known | Offline mode; nothing leaves the machine |

## Defaults and their limits

- The host ports are published on `127.0.0.1` only, and no setting exposes
  them on another address. A reverse proxy with authentication and TLS on
  the same host reaches the loopback ports; TokenCrate provides neither.
- A browser UI (`ui <set>`) has no password: PI WEB has no
  authentication, and Paseo's is not turned on. Every process on the host
  can use the UI port, and with it the agent's access to the project.
- The forwarder blocks other websites from using the UI. It returns `403`
  for a foreign `Host` or `Origin`, or, without an `Origin`, a
  `Sec-Fetch-Site` value other than `same-origin` or `none`. These checks
  cover cross-site requests and DNS rebinding. Allowed authorities are
  exactly `127.0.0.1`, `localhost`, and `[::1]` with the UI's own port
  (on port `80`, also without a port), and an `Origin` must use `http://`.
  The UI's own `Origin` passes even if the browser marks the request
  cross-site, as it does between `127.0.0.1` and `localhost`; one UI's
  origin does not authorize another. On Docker, the host reaches a UI
  started with `--egress` or `--cloud` at its address on the default
  network as well, past the forwarder's `Host` check ([the
  record](validation.md#browser-uis-with---egress-and---cloud)), so a
  page that rebinds a name to that address is expected to reach it.
  Rootless Podman keeps its bridges in the user's network namespace,
  which the host does not reach.
- The llama API on `LLM_PORT` answers a browser page only from a loopback
  origin (`LLAMA_ARG_CORS_ORIGINS=localhost` in `compose.yaml`). A page
  of another site, a DNS-rebinding page included, cannot read its
  responses. The API has no `Host` check, so such a page can still send
  a request the server acts on without reading the answer, for example a
  form post that loads or unloads a model. Host-side clients send no
  `Origin` and are unaffected.
- Terminal agents share the internal `agents` network with each other
  and the model. All browser UIs, their forwarders, and the model share
  the internal `ui` network; each forwarder also joins `ui-publish` to
  publish its loopback port. Terminal sessions cannot resolve a UI
  started without `--egress` or `--cloud`, and a session without a
  route out cannot reach any UI. A UI started with `--egress` or
  `--cloud` joins the default network as well. An `--egress` or
  `--cloud` terminal session of any project can then resolve and reach
  that UI, and through it the UI's project and keys; it cannot reach
  any other UI. Browser UIs are not isolated from each other: they share
  a network and, on the same project, the retained pi and UI
  directories. Treat them as trusted peers with access to their mounted
  projects.
- Every service runs with a read-only root filesystem, no Linux
  capabilities, `no-new-privileges`, a PID limit, and a size-limited
  tmpfs `/tmp`; no service has a memory limit.
- The internal `agents` and `ui` networks have no internet route or
  gateway through which agents can reach host services. Compose keeps an
  existing network's options, so `up` and every agent start refuse a
  network of that name that is not internal or that this Compose project
  did not create, on both engines.

  `internal` guarantees no route out of such a network. An `--egress` or
  `--cloud` session is on the default network instead of the `agents`
  network, so it shares no network with offline sessions and cannot relay
  for them. Whether such a session can reach a UI peer is engine
  behavior that neither Podman nor Docker documents. On rootless Podman
  it depends on the order in which the networks were set up: an internal bridge
  created before IPv4 forwarding was switched on in the engine's network
  namespace forwards, one created after it does not ([the VM
  record](validation.md#the-internal-bridges-of-the-virtual-machine)).
  Run `smoke --agent pi --egress` while a browser UI runs to check it,
  and again after an engine upgrade; a UI started with `--egress` or
  `--cloud` is reported as reached by design on its name and its
  default-network address, and its `ui` address must still be
  unreachable. If a UI is reachable, run `down` and
  `up` to recreate the networks and check again; that remedy is expected
  to work, because the recreated bridges come after forwarding is on, and
  has no recorded run.

  On Docker, `compose.docker.yaml` uses gateway mode `isolated`. An
  ordinary internal bridge retains a host gateway through which agents
  could reach services bound to all interfaces. This requires Engine 28
  or newer; `doctor` rejects older versions. Compose preserves existing
  network settings, so `up` and agent starts refuse either network if it
  has a gateway. Run `down` to remove those networks before recreating them.

  On rootless Podman, the gateway belongs to the user's network namespace
  and does not expose host services. `doctor` warns about Podman older
  than 6, the oldest version TokenCrate is tested on.
- The model runs third-party weights and a third-party chat template; agents
  run third-party skills. Pinning makes them repeatable, not trustworthy;
  [Coding agents and skills](agents.md#what-the-container-can-and-cannot-do)
  says what the container limits a bad skill or a confused model to.
- An agent with `--egress` can exfiltrate the mounted project. Use it only
  for projects you would share with the internet anyway, or pair it with a
  host firewall. `--cloud` gives the same route, and nothing restricts it
  to the providers you keyed. Such a session also reaches host services
  bound to non-loopback addresses, on both engines: the default network's
  gateway is the host on Docker, and rootless Podman adds
  `host.containers.internal` to a non-internal network.
- An agent home is a tmpfs; [Storage
  layout](configuration.md#storage-layout) lists the transcript and UI
  directories that persist, and [Agent
  configuration](agents.md#agent-configuration) says what one session can
  change for a later one.
- Agent and browser UI containers reach the router's whole API, including
  its management endpoints: an agent can load, unload, or switch models
  (`POST /models/load`, `POST /models/unload`, or a request that names
  another preset).

## Checking yourself

```bash
bash bin/tokencrate smoke --agent pi            # no route out of the agent container
bash bin/tokencrate smoke --agent pi --egress   # a route out, no UI peer but an egress UI (run it while a UI runs)
podman network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
```

On Docker, the internal networks must also carry no gateway address:

```bash
docker network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
docker network inspect tokencrate_agents --format '{{json .IPAM.Config}}'   # no Gateway
```
