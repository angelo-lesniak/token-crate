# Agent sets

An agent set adds toolchains, language servers, debug adapters, or
extensions to the pi image through a reviewed manifest. Choose sets in
`.env`; the wrapper includes them in the image at the next pi start.
Nothing is installed at runtime.

The first start of a selection builds its image and downloads its
toolchains (a few hundred megabytes for `dotnet` or `odin`). Images for
different selections coexist.

```bash
bash bin/tokencrate agent-sets list        # the shipped and private sets
bash bin/tokencrate agent pi --dir ~/src/my-project          # LLM_AGENT_SETS
bash bin/tokencrate agent pi --sets coding,debug,odin --dir ~/src/my-project
```

`LLM_AGENT_SETS` in `.env` selects the default sets (`coding`). Use
`--sets` to override the selection for one session, or `--sets ''` for
plain pi. See [`agent`](cli.md#agent), [`smoke`](cli.md#smoke), and
[`ui`](cli.md#ui) for command options.

## Shipped sets

| Set | Adds | Pair with |
| --- | --- | --- |
| `coding` | The pi coding extensions: pi-lens code intelligence (`lens_diagnostics` after edits; `lsp_navigation` and `ast_grep_*` on demand), anchored edits, `/plan`, `/advisor`, and the subagent tool with the `scout`, `planner`, `reviewer`, and `worker` definitions, each running on the session's own model | Any |
| `debug` | One `debug` tool over whatever debug adapters the other sets ship | `dotnet`, `web`, or `odin` |
| `dotnet` | The .NET SDK, csharp-ls, netcoredbg, a read-only NuGet cache warmed with the `console`, `classlib`, `xunit`, and `web` templates; uncached packages need `--egress`, an explicit source, and a writable project cache (`NUGET_PACKAGES`) | `debug` |
| `web` | TypeScript, typescript-language-server, the Vue language tools and `vue-tsc`, js-debug behind a stdio bridge; `npm install` needs `--egress` | `debug` |
| `browser` | The Chrome DevTools tools against Debian's Chromium, headless, without its own sandbox (the container is the sandbox) | `coding` |
| `odin` | The Odin compiler, OLS and `odinfmt` on the same monthly tag, clang as the linker, `lldb-dap`, SDL2, Vulkan, `glslc`; no display, so SDL uses its dummy drivers | `debug` |
| `pi-web` | PI WEB, a browser UI for pi, started with `ui pi-web` | Any |
| `paseo` | Paseo, a daemon with a browser UI that runs several pi sessions, started with `ui paseo`; about 0.5 GB | Any |

The manifests hold the pinned versions, and `agent-sets list` prints each
set's description.

Every set appends its note to the tools note pi loads as global context,
so the model knows what is installed and what needs `--egress`.

The `debug` and `browser` sets are separate from `coding` because every
tool schema is sent with every request; select them where an adapter or a
browser exists
([request-size record](validation.md#request-size-of-the-coding-set)).

## Writing a set

Create a directory containing `set.toml` under `config/agent-sets/<name>/`
for a shipped set, or `local/agent-sets/<name>/` for a private one. Private
sets are not committed, but are included in the build context. Containers
cannot write to the host's `local/` directory.

The directory name is the set name. The wrapper rejects duplicate names
across the two locations, unknown manifest keys, and paths that leave the
set directory.

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

This is a complete set. Add its name to `LLM_AGENT_SETS` for the next
`agent pi` start, or run
`bash bin/tokencrate smoke --agent pi --sets <name>` to build it and check
containment.
[CONTRIBUTING.md](../CONTRIBUTING.md#adding-an-agent-set) says what a
shipped set needs beyond that. Manifest keys:

| Key | Meaning |
| --- | --- |
| `env` (table) | Variables set in the image. `PATH` is appended to the image's `PATH`, so a set's tools never shadow `node`, `pi`, or `git` |
| `apt` (list) | Debian packages, installed with `--no-install-recommends`. Versions come from the base image's Debian release at build time, without per-package pins |
| `asset` (array of tables) | A release asset: `url` (https, without credentials), exactly one of `sha256` or `sha512`, `into` (absolute). A `.tar.gz` or `.tgz` is extracted into `into` (`strip` drops leading path components), a `.zip` is unzipped into it, any other file is installed at `into` with `mode` (default `0644`) |
| `npm` (table) | Install `package.json` and `package-lock.json` of the set directory with `npm ci --ignore-scripts` and `npm audit signatures`; `omit_peer = true` for pi extensions (pi provides their peers) |
| `build` (list) | Lines of one Bash script run with `errexit` and `pipefail` in the set directory, as one layer, after its files are copied into the image. Inline comments and shell variables work across lines. Files of the set directory are installed from here (`install -m 0755 wrapper /usr/local/bin/wrapper`), and so is a Git checkout at a commit (see the `debug` set) |
| `pi_packages` (list) | Directories below the set directory that pi loads as packages (an extension with its `package.json`) |
| `pi_lens` (table) | Merged into pi-lens's configuration, for example a language server under `lsp.servers` |
| `note` (string) | Lines for the tools note |
| `ui` (table) | Makes the set a browser UI for `ui <set>`; see [UI sets](#ui-sets) |

`env`, `apt`, and `asset` depend only on the manifest and run before the
set directory is copied. Editing a note or lockfile therefore does not
repeat those downloads. The whole directory is copied to
`/opt/tokencrate/sets/<name>` in the image. Keep only required files there,
and never credentials such as a private `.npmrc`.

### UI sets

A `[ui]` table makes the set a browser UI that `ui <set>` adds to the
selection and runs instead of `pi` ([Browser UIs](agents.md#browser-uis)).

The names `stop` and `logs` are reserved for UI commands and cannot name
a set with a `[ui]` table.

| Key | Meaning |
| --- | --- |
| `command` | A program name on the image's `PATH` that the entrypoint runs instead of `pi`; install it with a `build` line. It must bind all interfaces of the container and keep running in the foreground |
| `port` | The container port it listens on (1024 to 65535), which the wrapper forwards the loopback port to |
| `identity` (optional list) | Files directly below `.pi-web/` or `.paseo/` in the agent home that the wrapper keeps once per UI set under `LLM_AGENTS_DIR/pi/<set>-identity/` and copies into every project's home before the start, such as a daemon's keypair |

A UI's persistent files, including its identity paths, must live under
one of the [retained home directories](configuration.md#storage-layout).
The manifest does not add mounts. Supporting another state directory
requires a reviewed Compose mount and host-path preparation change.

Custom UI sets require an explicit host port with `--port`; the manifest
port remains internal. See [`ui`](cli.md#ui) for the complete command contract.

## Upgrading a set

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
the image and check containment. For `dotnet`, `web`, `browser`, and
`odin`, it also checks the toolchain without internet access. Record the
result as [Validation](validation.md#recording-a-result) describes.
