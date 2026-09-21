# Privacy and containment

TokenCrate runs models and agents locally. By default, agent containers
have no route to the internet, so their settings cannot enable outbound
requests. This requires a [local container engine](configuration.md#configuration);
remote engine connections are unsupported.

## What leaves the machine

| Activity | Destination | When |
| --- | --- | --- |
| `models fetch` and `models draft` | huggingface.co and, for `fetch`, the Hugging Face CDN hosts it redirects to (`*.cdn.hf.co` and similar) | Only when you run them |
| `skills fetch` | The allowlisted Git hosts in `config/skill-sets/allowed-git-hosts.txt` | Only when you run it |
| `pins check` | ghcr.io, registry.npmjs.org, hub.docker.com | Only when you run it |
| The runtime image build | ghcr.io (the llama.cpp server image) | At `up`, when the image is missing or its inputs changed |
| An agent image build | docker.io (the Node or Bun base image), the Debian and npm mirrors, and the `url` of every asset and Git checkout in the selected [agent sets](agent-sets.md): github.com with the asset hosts it redirects to (`objects.githubusercontent.com` and similar) for `debug`, `dotnet`, `web`, and `odin`, and builds.dotnet.microsoft.com and nuget.org for `dotnet` | At the first `agent`, `smoke --agent`, or `ui <set>` with that selection |
| The forwarder's base image pull | docker.io (the Node image) | At the first `ui <set>` |
| `agent --egress` sessions | Whatever the agent or your commands contact | Only when you ask for it |

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
preset renderer also rejects download options, including the Docker Hub
model option that offline mode does not cover, and remote compute through
`rpc`. Other `server.extra` options require review; the interface is not
a sandbox for untrusted presets. See [Models and presets](models.md#adding-a-model).

## Telemetry switches

TokenCrate disables known telemetry and update checks in its bundled
components. Terminal agents and browser UI containers also have no
internet route by default.

| Component | Default upstream behavior | TokenCrate setting |
| --- | --- | --- |
| pi | Anonymous install ping and update check | `PI_TELEMETRY=0` before the package install and at runtime, `PI_SKIP_VERSION_CHECK=1`, `PI_OFFLINE=1`, `enableInstallTelemetry: false`, `enableAnalytics: false` |
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
  cover cross-site requests and DNS rebinding. The UI's own `Origin`
  passes even if the browser marks the request cross-site, as it does
  between `127.0.0.1` and `localhost`. Each forwarder checks its own port;
  one UI's origin does not authorize another. The built-in chat UI on
  `LLM_PORT` has no such check.
  Allowed authorities are exactly `127.0.0.1`, `localhost`, and `[::1]`
  with that port, and Origins require `http://`. Port `80` accepts both
  explicit `:80` and an omitted port for HTTP and WebSocket upgrades.
- Terminal agents sit on `agents`; all browser UIs, their forwarders,
  and the model share the internal `ui` network. Each forwarder also
  joins `ui-publish` to publish its loopback port. Terminal sessions of
  any project, with or without `--egress`, cannot resolve or reach these
  UI peers. Terminal sessions share `agents` with each other and the
  model. Browser UIs are not isolated from each other: they share a
  network, and when launched on the same project they also share the
  retained pi and UI directories. Treat both browser UIs as trusted
  peers with access to their mounted projects.
- Every service runs with a read-only root filesystem, no Linux
  capabilities, `no-new-privileges`, a PID limit, and a size-limited
  tmpfs `/tmp`.
- The internal `agents` and `ui` networks have no internet route or
  gateway through which agents can reach host services.

  On Docker, `compose.docker.yaml` uses gateway mode `isolated`. An
  ordinary internal bridge retains a host gateway through which agents
  could reach services bound to all interfaces. This requires Engine 28
  or newer; `doctor` rejects older versions. Compose preserves existing
  network settings, so `up` and agent starts refuse either network if it
  has a gateway. Run `down` to remove those networks before recreating them.

  On rootless Podman, the gateway belongs to the user's network namespace
  and does not expose host services. Podman 6 with netavark 2 also keeps
  bridges apart, which protects `ui-publish` from sessions with
  `--egress`. `doctor` rejects older Podman versions.
- The model runs third-party weights and a third-party chat template; agents
  run third-party skills. Pinning makes them repeatable, not trustworthy;
  [Coding agents and skills](agents.md#what-the-container-can-and-cannot-do)
  says what the container limits a bad skill or a confused model to.
- An agent with `--egress` can exfiltrate the mounted project. Use it only
  for projects you would share with the internet anyway, or pair it with a
  host firewall.
- An agent home is a tmpfs; [Storage
  layout](configuration.md#storage-layout) lists the transcript and UI
  directories that persist, and [Agent
  configuration](agents.md#agent-configuration) says what one session can
  change for a later one.
- Agent containers reach the router's whole API, including its management
  endpoints: an agent can load, unload, or switch models (`POST /models/load`,
  `POST /models/unload`, or a request that names another preset).

## Checking yourself

```bash
bash bin/tokencrate smoke --agent pi     # no route out of the agent container
podman network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
```

On Docker, the internal networks must also carry no gateway address:

```bash
docker network inspect tokencrate_agents tokencrate_ui --format '{{.Internal}}'   # true, true
docker network inspect tokencrate_agents --format '{{json .IPAM.Config}}'   # no Gateway
```
