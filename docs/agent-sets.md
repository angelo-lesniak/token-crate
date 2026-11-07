# Agent sets

An agent set adds toolchains, language servers, debug adapters, or
extensions to the pi image through a reviewed manifest. Agent sets apply
to pi only; oh-my-pi keeps its built-in tools. The wrapper includes the
selected sets in the image at the next pi start, and nothing is
installed at runtime. The first start of a selection builds its image
and downloads its toolchains; images for different selections coexist.

```bash
bash bin/tokencrate agent-sets list        # the shipped and private sets
bash bin/tokencrate agent pi --dir ~/src/my-project          # the sets in LLM_AGENT_SETS
```

`LLM_AGENT_SETS` selects the sets for `agent pi` and `ui`
([Configuration](configuration.md#when-a-change-takes-effect) says when a change takes effect);
`--sets` overrides it for one launch ([`agent`](cli.md#agent)).

## Shipped sets

`agent-sets list` prints what each set installs, and the manifests hold
the pinned versions. What decides a selection:

| Set | Select it for |
| --- | --- |
| `coding` | Code intelligence, anchored edits, `/plan`, `/advisor`, and subagents that run on the session's own model |
| `debug` | A `debug` tool over the debug adapters of `dotnet`, `web`, or `odin`, so select one of them too |
| `dotnet` | .NET; NuGet restores from a read-only cache warmed with four project templates, and other packages need `--egress`, an explicit source, and a writable `NUGET_PACKAGES` |
| `web` | TypeScript and Vue; `npm install` needs `--egress` |
| `browser` | Chrome DevTools tools against headless Chromium, which runs without its own sandbox (the container is the sandbox) |
| `metrics` | The [`stats`](cli.md#stats) Timings table; it adds no tool |
| `odin` | Odin with SDL2 and Vulkan; there is no display, so SDL uses its dummy drivers |
| `pi-web` | The PI WEB browser UI (`ui pi-web`) |
| `paseo` | The Paseo browser UI (`ui paseo`); about 0.5 GB more image |

Every tool schema is sent with every request, so select `debug` and
`browser` only for projects that need them. The `dotnet` set pins its
SDK tarball by SHA-512; csharp-ls and the cached NuGet packages come
from nuget.org by version only, without a hash.

## Common selections

```bash
# A .NET backend and Vue frontend in PI WEB
bash bin/tokencrate ui pi-web --sets coding,debug,dotnet,web,browser --dir ~/src/my-project
# Odin in terminal pi
bash bin/tokencrate agent pi --sets coding,debug,odin --dir ~/src/my-project
```

## Write a set

Create a directory containing `set.toml` under `config/agent-sets/<name>/`
for a shipped set, or `local/agent-sets/<name>/` for a private one, which
is not committed but is part of the build context. The directory name is
the set name (letters, digits, and `._-`, starting with a letter or
digit). The wrapper also refuses a name used in both locations, an
unknown key, an invalid value, and a path that leaves the set
directory.

A manifest runs as root during the image build, with the build's network
access. Its `env` and `into` keys can affect any image path; the manifest
format is not a sandbox. Review extensions at their pinned versions before
adding them.

```toml
schema = 1
description = "Shell and Python linters"
apt = ["shellcheck", "pyflakes3"]
note = "shellcheck and pyflakes3 are installed."
```

Build and check the set, replacing `<name>` with its directory name:

```bash
bash bin/tokencrate smoke --agent pi --sets <name>
```

[`smoke`](cli.md#smoke) explains the checks;
[CONTRIBUTING.md](../CONTRIBUTING.md#add-an-agent-set) says what a
shipped set needs beyond that. Manifest keys:

| Key | Meaning |
| --- | --- |
| `schema` | Required; `1` |
| `description` | Required; one line, which `agent-sets list` prints |
| `env` | Variables set in the image; `PATH` is appended to the image's `PATH`, so a set's tools never shadow `node`, `pi`, or `git` |
| `apt` | Debian packages from the base image's release at build time, without per-package pins |
| `asset` | Release assets, each with `url`, `sha256` or `sha512`, and an absolute `into`; a `.tar.gz`, `.tgz`, or `.zip` is extracted into `into` (`strip`, for a tarball only, drops leading path components), any other file is installed at `into` with `mode` (default `0644`) |
| `npm` | Installs the set directory's `package.json` and `package-lock.json` with `npm ci --ignore-scripts` and `npm audit signatures`; `omit_peer = true` for pi extensions, whose peers pi provides |
| `build` | Lines of one Bash script, run with `errexit` and `pipefail` in the set directory after its files are copied into the image; it installs the set's own files and Git checkouts (see the `debug` set) |
| `check` | Lines of one Bash script that `smoke --agent` runs as the container user without a route out (an `--egress` check skips it), in `$CHECK_DIR`; the last line it prints is the report line. Every shipped set needs the key, an empty list when nothing can be probed |
| `pi_packages` | Directories below the set directory that pi loads as packages |
| `pi_lens` | Merged into pi-lens's configuration, for example a language server under `lsp.servers` |
| `note` | Lines for the tools note pi loads as global context |
| `ui` | Makes the set a browser UI ([UI sets](#ui-sets)) |

`env`, `apt`, and `asset` run before the set directory is copied, so
editing a note or lockfile does not repeat those downloads. The whole
directory is copied to `/opt/tokencrate/sets/<name>` in the image: keep
only required files there, and never credentials such as a private
`.npmrc`.

### UI sets

A `[ui]` table makes the set a browser UI that `ui <set>` adds to the
selection and runs instead of `pi` ([Browser UIs](agents.md#browser-uis)).
The set name goes into container names, so a UI set's name is stricter;
the refusal states the rule.

| Key | Meaning |
| --- | --- |
| `command` | A program name on the image's `PATH`, installed by a `build` line, that the entrypoint runs instead of `pi`. It must stay in the foreground and listen on the container's `ui`-network address or on all interfaces; the shipped launchers read that address from `/proc/net/route` and bind it alone |
| `port` | The container port it listens on, which the forwarder publishes on a loopback port |
| `state` | One directory below the agent home, such as `.paseo`, that holds the UI's configuration and sessions and persists per project |
| `host_port` (optional) | The loopback port the forwarder publishes unless `--port` names another; a set without it needs `--port` |

What a UI keeps once for all projects goes in the per-set state
directory that [Storage layout](configuration.md#storage-layout) names.

## Upgrade a set

Update the source pin and its verification data together:

- For a release asset, download the new file, run `sha256sum` (or
  `sha512sum` for the .NET SDK), and update `url` and checksum. Keep Odin
  and OLS on the same monthly tag.
- For npm packages, set the exact version in `package.json` and run
  `npm install --package-lock-only --ignore-scripts` in the set directory.
  Add `--omit=peer` for pi extensions.
- For the `debug` set's Git checkout, review the upstream diff of
  `extensions/dap` between the two commits before changing the pin.

Run `bash bin/tokencrate smoke --agent pi --sets <selection>` to build
the image and run each set's `check` lines, and record the result as
[Validation](validation.md#record-a-run) describes.
