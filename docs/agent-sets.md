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
bash bin/tokencrate agent pi --dir ~/src/my-project          # the sets in LLM_AGENT_SETS
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

## Common selections

Each example starts where [Start here](../README.md#start-here) ends,
with the stack up and the skill sets fetched. `--sets` applies to one
launch; put a selection in `LLM_AGENT_SETS` to make it the default for
`agent pi` and `ui`. [Validation](validation.md#status) states which
selections are validated.

**A .NET backend with a Vue frontend in PI WEB.** The first launch builds
the image, which downloads the .NET SDK and the npm packages:

```bash
bash bin/tokencrate ui pi-web --sets coding,debug,dotnet,web,browser --dir ~/src/my-project
```

Open <http://127.0.0.1:4224/>. The container has no route out, so
`npm install` fails and NuGet restores only the packages of the warmed
templates. Relaunch with `--egress` for new packages; NuGet also needs an
explicit source and `NUGET_PACKAGES` set to a writable directory in the
project. `ui stop pi-web` stops the UI and keeps its sessions.

**Odin with Claude beside the local model.** With `--cloud`, the whole
conversation, including file contents and tool output, goes to Anthropic
once you pick a Claude model, and every process in the session can read
the key. Use it only in a project you trust ([Cloud
providers](agents.md#cloud-providers)). Copy the keys template, set
`ANTHROPIC_API_KEY` in `local/cloud-keys.env`, and start pi:

```bash
cp cloud-keys.env.example local/cloud-keys.env && chmod 600 local/cloud-keys.env
bash bin/tokencrate agent pi --sets coding,debug,odin --cloud --dir ~/src/my-project
```

pi starts on the local preset; `/model` switches to a Claude model and
back. The container has no display; SDL uses its dummy drivers, and code
that opens a window cannot run there.

## Writing a set

Create a directory containing `set.toml` under `config/agent-sets/<name>/`
for a shipped set, or `local/agent-sets/<name>/` for a private one. Private
sets are not committed, but are included in the build context. Containers
cannot write to the host's `local/` directory.

The directory name is the set name. The wrapper rejects duplicate names
across the two locations, unknown manifest keys, and paths that leave the
set directory or carry characters other than letters, digits, and
`._+@-` (the rule every manifest kind shares).

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
| `build` (list) | Lines of one Bash script, run with `errexit` and `pipefail` in the set directory as one layer after its files are copied into the image. Shell variables carry across lines; a line can end with a comment but cannot be one. Files of the set directory are installed from here (`install -m 0755 wrapper /usr/local/bin/wrapper`), and so is a Git checkout at a commit (see the `debug` set) |
| `check` (list) | Lines of one Bash script, in the shape of `build`, that `smoke --agent` runs inside the container as the container user, with no route out (an `--egress` check skips them), in a scratch directory (`$CHECK_DIR`, also the working directory); the last line it prints is the report line. The gate requires the key of every shipped set, an empty list when nothing of it can be probed |
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

A UI set's name ends the names of its containers, `tokencrate-ui-<set>`
and `tokencrate-ui-forward-<set>`, so it holds lowercase letters,
digits, and hyphens, at most 41 characters, starts with a letter or a
digit, and does not start with `forward-`; `stop` and `logs` are
reserved for UI commands.

| Key | Meaning |
| --- | --- |
| `command` | A program name on the image's `PATH` that the entrypoint runs instead of `pi`; install it with a `build` line. It must bind all interfaces of the container and keep running in the foreground |
| `port` | The container port it listens on (`1024` to `65535`), which the wrapper forwards the loopback port to |
| `state` | One directory below the agent home (such as `.paseo`) that holds the UI's configuration, sessions, and identity. It is the UI's only home path bound from the host, so it persists per project ([storage layout](configuration.md#storage-layout)); it cannot be one of the agent's own directories (`.pi`, `.config`, and the like) |
| `host_port` (optional) | The loopback port (`1024` to `65535`) the forwarder publishes unless `LLM_UI_PORT_<SET>` or `--port` names another ([`ui`](cli.md#ui)) |
| `identity` (optional list) | Files directly below the `state` directory, written as `<state>/<file>` (`".paseo/server-id"`), that the wrapper keeps once per UI set under `LLM_AGENTS_DIR/pi/<set>-identity/` and copies into a project's home that lacks them before the start, such as a daemon's keypair |

A UI's persistent files, including its identity paths, must live under
its `state` directory; nothing else in the home outlives the container.
A set without `host_port` needs `LLM_UI_PORT_<SET>` or `--port`; the
manifest `port` remains internal. See [`ui`](cli.md#ui) for all options.

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
the image and check containment; each set's `check` lines run without
internet access and report one line per set. Record the result as
[Validation](validation.md#recording-a-result) describes.
