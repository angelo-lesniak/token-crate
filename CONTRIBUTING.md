# Contributing

Use this page to set up the development tools, find the code to change,
and choose the checks to run. Preserve the shared Compose core for Docker
and Podman, host-mounted data, the single pin file `pins.env`, and the
[privacy defaults](docs/privacy.md).

## Tools

Install Bash, Python 3.11 or newer, Git, Node.js, ShellCheck, and
ripgrep; the tests run Node.js for the entrypoint, forwarder, exporter,
and launcher checks. Install the Python test dependencies in a virtual
environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

`tests/static.sh` runs `python3` (or `python` when only that name exists)
from `PATH`, so activate the environment first.

## Layout

`bin/tokencrate` checks for Python 3.11 or newer and runs the package from
the repository. Keep behavior in `tokencrate/`; the shim only launches it.
Use only the Python standard library at runtime and target Python 3.11,
as set in `ruff.toml`. The images' shell and JavaScript live under
`services/` and `config/agent-sets/`.

| Modules | Responsibility |
| --- | --- |
| `cli` | The command table, from which `USAGE` and the misplaced-flag refusals are generated, dispatch, and the handlers that compose the modules |
| `env`, `names` | Settings, pins, the storage list, and name validation |
| `agenthome`, `files` | Leaves: the agent-home constants every module shares, and atomic file writes |
| `engine`, `runtime`, `localhttp` | Engine commands, stack lifecycle, and direct local HTTP requests |
| `models`: `manifest`, `library`, `hub`, `download`, `drafts` | Manifests, the library, the Hub, downloads, drafts |
| `presets`, `agentmodels` | Preset validation and rendering, and agent model lists |
| `session` | One agent container start: the pre-flight and the `Launch` |
| `agents`, `uis`, `agentsets`, `skills` | Terminal sessions and their check, browser UIs, set selections, skill sets |
| `doctor`, `probe`, `checkpins` | Host checks, API probes and benchmarks, upstream pin lookups |
| `stats`: `transcripts`, `tables`, `report` | Transcript reading, the one aggregation, the Markdown report |
| `stats`: `page`, `live`, `server` | The HTML page (assets under `stats/pages/`), the live sampler, `--serve` |

`session.plan` prepares every agent container start: terminal sessions,
browser UIs, and the agent check. Add a new start as a caller of `plan`
and its `Launch.build` and `Launch.run`, so it inherits the mounts,
egress, keys-file checks, and cleanup. The wrapper never reads the keys
file. `Settings.storage` in `env.py` is the shared list of host paths;
`doctor` and `runtime` iterate it instead of naming directories.

## Tests

```bash
bash tests/static.sh
```

The static gate needs no container engine and no model, and takes about
a minute. It runs shell syntax and ShellCheck, `node --check`, an import
of each `tokencrate` module on its own, every `tests/test_*.py` (the CLI
tests use the fake engine under `tests/fixtures/engine-bin`), Ruff,
`tests/podman-compose.sh` (every Compose file combination the wrapper
can pass, checked for network placement, mounts, labels, and published
ports), a scan for machine-specific host paths, and a Compose render with
Docker Compose when installed.

A missing optional tool prints a `SKIPPED:` line and the gate still
passes; `TOKENCRATE_STATIC_STRICT=1`, as in CI, makes any skip a
failure, a skipped unit test included. The gate runs on the tracked
files alone, so a check must not depend on local build artifacts. CI
also lints the Dockerfiles with hadolint.

```bash
python3 tests/integration.py
```

Run the integration checks after changing the package, images, chat
template, agents, or Compose files. They need a container engine, PyYAML,
and network access (images, 0.4 GB of fixture models on the first run,
GitHub skill sets), and take several minutes. They take over this
checkout's Compose project: `up` replaces a running stack and cleanup
stops it with `down`. The docstring of `tests/integration.py` lists the
checks; `-k <pattern>` selects by name. CI runs them weekly and for
changes to the paths in `.github/workflows/integration.yml`.

[Validation](docs/validation.md) holds the host acceptance procedures,
their last passed dates, and the known gaps.

## Documentation changes

Write and review documentation with the `documentation-guidelines` skill
from [SkillCrate](https://github.com/angelo-lesniak/skill-crate). TokenCrate
agents load it from the `skill-crate` skill set; for another agent, copy
`skills/documentation-guidelines` from that repository into its skills
directory. `AGENTS.md` lists which page owns which facts; update the
owner page instead of restating a fact elsewhere.

A new page needs a row in the README's "Choose what to do next" table.
Usage and error text in `cli.py` are part of the documented interface:
keep a section in `docs/cli.md` for every command listed by
`bin/tokencrate help`, with every usage line verbatim.
`tests/test_project_contracts.py` checks that relative links and heading
anchors resolve, that the README table links every page, and that every
usage line appears in `docs/cli.md`. Check the facts in the prose by
hand.

## Adding a pin

A pin in `pins.env` is `<NAME>_TAG` with `<NAME>_DIGEST` beside it (the
tag names the image, the manifest digest is what the build pulls),
`<NAME>_VERSION`, or `CUDA_MIN_DRIVER_MAJOR`; `env.load_pins` refuses any
other key name, and a tag or digest without its partner.

1. Write it in `pins.env` as a plain value (no quotes, no whitespace);
   [Upgrading](docs/configuration.md#upgrading) shows the digest lookup.
2. For a pin an image build uses, add it to the service's `args:` block in
   `compose.yaml` without a fallback and as a Dockerfile `ARG` without a
   default, so that `pins.env` stays the only place the value lives; a
   contract test checks this.
3. For a pin `pins check` should resolve, add one `RESOLVERS` entry keyed
   by the pin in `tokencrate/checkpins.py` and a case in
   `tests/test_checkpins.py`. A pin without a resolver prints
   `<name>: <value> (no resolver; look it up by hand)`.

## Adding an agent set

[Agent sets](docs/agent-sets.md#writing-a-set) documents the manifest
keys and how to write and upgrade a set. Before pinning a pi extension,
read its source at that version: it runs with pi's permissions inside
the container. A shipped set also needs:

- a row in the table of [Agent sets](docs/agent-sets.md#shipped-sets);
- a row in `THIRD_PARTY_NOTICES.md` for what it installs beyond Debian
  packages;
- a passing `bash tests/static.sh` (`tests/test_agentsets.py` validates
  and renders every shipped set);
- `bash bin/tokencrate smoke --agent pi --sets <selection>` for the
  changed selection, recorded as `docs/validation.md` describes.

## Model sets, presets, and skill sets

Every manifest kind (agent sets, model sets, presets, skill sets) goes
through the one reader in `tokencrate/names.py`: `schema = 1`, no unknown
keys, a one-line description, and paths below the manifest's own
directory made of letters, digits, and `._+@-`. Every comma-separated
list (`LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `--sets`) goes through its one
parser.

[Adding a model](docs/models.md#adding-a-model) holds the model-set and
preset procedure and what a change attaches; run `python3 -m unittest
tests.test_model_sets` before changing a shipped entry.

A skill-set entry pins a public credential-free HTTPS repository on a
host listed in `config/skill-sets/allowed-git-hosts.txt`, a full commit, and the tree
digest of the pinned directory. To obtain the digest: pin a placeholder
of 64 zeros as `sha256`, run `skills fetch <set>`, paste the digest the
refusal prints (`tree digest <digest> does not match the pinned ...`),
and run `skills fetch <set>` again. Read each `SKILL.md` and every file
under its `scripts/` directory before pinning it; commit pinning is not
a code review.

Do not commit models, tokens, `.env`, `build/`, `data/`, `local/`, or
`reports/`.

## Router behavior the wrapper relies on

`runtime`, `probe`, and the preset renderer rest on these observations
of llama-server's router mode (`--models-preset`, `--models-max 1`);
repeat them after a `LLAMA_CPP_TAG` change, as [Known
gaps](docs/validation.md#known-gaps) records.

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
  to its preset, so a `/metrics` request for an unloaded preset is
  expected to load it first: scrape only presets `GET /models` reports
  loaded.
- Preset file: keys are llama-server option names without dashes
  (`jinja = true` becomes `--jinja`, `ui-config-file`
  `--webui-config-file`, `gpu-layers` `--n-gpu-layers`); a key given twice
  keeps the last value silently; keys in `[*]` reach every child; an
  unknown key stops the router at start with `option '<key>' not
  recognized in preset '<name>'`. The renderer therefore keeps a typed
  vocabulary and passes only `override-kv`, `load-mode`,
  `log-prompts-dir`, and `verbose` through `[server.extra]`.

## Settled decisions

Each entry is the decision, its reason, and when to reconsider it; the
linked page holds the mechanism. Challenge a decision only with evidence
against its stated reason.

- **Agent sets select pi's tools at build time.** The image is the
  reviewed artifact and the container has no route out, so a new
  toolchain is a manifest in the existing step vocabulary
  ([Agent sets](docs/agent-sets.md)). Reconsider if pi drops
  local-directory packages or a set needs a new kind of step; extend the
  vocabulary before adding an image stage.
- **Shared pi configuration across sets.** Sets add to `PATH`, the tools
  note, pi-lens's configuration, and the package list; pi settings and
  skills stay the same, so the model sees one tool vocabulary. Reconsider
  if a set needs different pi settings.
- **A browser UI is an agent set inside the pi container.** A separate
  forwarder publishes its port because Docker cannot publish a container
  attached only to internal networks ([Forwarder](docs/privacy.md#forwarder)).
  Reconsider if Docker publishes ports from internal networks or a UI
  authenticates and checks origins itself.
- **Shared networks and targeted hardening, not per-session networks.**
  Sessions share `agents`, UIs share `ui`, and `--egress` or `--cloud`
  adds the default network with no gate; [Cloud
  providers](docs/agents.md#cloud-providers) states the consequences.
  Reconsider when a per-session gate is proven on both engines for less
  than those consequences cost.
- **Sessions and UIs start with `compose run`, under fixed names.** One
  Compose core carries the hardening, the mounts, the keys file, and the
  egress overlay for every container. Reconsider if a provider stops
  honoring `run --name` or `--service-ports`.
- **Two agents.** pi with the `coding` set includes the oh-my-pi
  features expected to pay for themselves on a local model; oh-my-pi
  stays as an alternative although its first request costs more than
  twice pi's ([Coding agents and skills](docs/agents.md)) and needs a
  second image, base pin, model-list dialect, entrypoint branch, overlay,
  Compose service, and validation coverage. Reconsider if GPU results
  show no benefit over pi with `coding`, or if oh-my-pi still cannot be
  lockfile-pinned.
- **`coding` and `metrics` are the default agent sets.** `coding`
  multiplies the tools and the request body pi sends before a task
  starts, and its value on a local model is a hypothesis; `metrics`
  changes no request and fills the stats Timings table. Reconsider after
  comparing plain pi and the bundle on the same coding tasks with a
  shipped 27B preset: completion, wrong edits, tokens, turns, and wall
  time.
- **`pocock-core,skill-crate` are the default skill sets.** An empty
  default would remove `skills fetch` from initial setup. Reconsider if
  the skill descriptions cost more context on a 27B model than their
  skills return.
- **Cloud sessions are egress sessions, not filtered ones.** A `--cloud`
  session has the full route out of `--egress`: a Node client honors
  proxy variables only when it opts in, so a filter must work at the
  network level, and a filter that does not filter is worse than stating
  what the session can reach ([Egress](docs/privacy.md#egress)).
  Reconsider when a network-level allowlist is proven on both engines.
- **Cloud keys in a file the wrapper never reads.** The wrapper checks
  the file, never its contents, and keeps no provider table, because
  pi's variable names change with `PI_VERSION`
  ([Cloud providers](docs/agents.md#cloud-providers)). Reconsider when a
  sidecar that injects the credential is proven on both engines with a
  real key.
- **Cloud models through pi only.** `agent omp --cloud` is refused
  because oh-my-pi reads provider settings from project `.env` files
  ([Cloud providers](docs/agents.md#cloud-providers) says what that
  exposes); pi reads no such file. Reconsider when the credential is
  injected inside the container, out of the agent's environment.
- **No repository skills.** Every skill an agent sees is a pinned skill
  set or a private skill below `LLM_LOCAL_SKILLS_DIR`; generic advice
  belongs to a skill set, and a claim about what leaves the machine
  belongs to the documentation, where `--cloud` qualifies it. Reconsider
  for a set-specific instruction that no manifest `note` can carry.
- **No renderer entry for a cloud provider.** Both pinned agents bundle
  each provider's endpoint, dialect, and model catalogue and offer a
  provider when its key variable is set; an entry would duplicate the
  bundle plus a base URL the wrapper would then have to pin. Reconsider
  if an agent version drops its bundled catalogues.
- **Required Compose settings have no fallback.** Required settings and
  the derived values use `${VAR:?}` in the Compose files (`?` for
  `LLM_SKILL_SETS`, which may be empty), so an empty value fails the
  Compose call naming the variable and no second default can disagree
  with `.env.example`. Reconsider if a setting gains a second reader that
  can disagree with Compose about its default.
- **The dashboard is an opt-in profile, and two scrapers carry one
  rule.** The profile is off by default because it adds three or four
  containers; the exporter and the live panel share the two-poll rule
  ([Dashboard](docs/configuration.md#dashboard)), which
  `tests/test_statspage.py` pins in both copies. Reconsider the exporter
  when the router serves counters without loading a model, and the second
  copy when the page can read the exporter instead.
- **llama-server router mode.** The router loads presets, routes by
  `model`, loads the default at startup, and serves the built-in chat UI;
  a separate proxy would add a pinned component, a configuration format,
  and per-effort aliases, and clients already send `reasoning_effort` per
  request. Reconsider if router mode loses a required feature.
- **Paseo's identity travels through the per-set state mount.** One
  pairing serves every project ([Browser UIs](docs/agents.md#browser-uis));
  the manifest has no identity key, and the quirk stays in the one
  launcher that has it. Reconsider if a second UI needs cross-project
  state the mount cannot carry.
- **Filesystem hardening covers the user's own storage.** The symlink
  refusals, owner checks, and per-directory modes stay wherever an agent
  can write and in the model library, although only the host writes
  `data/models`; their cost is code size, not behavior. Reconsider when
  the threat model in `SECURITY.md` changes or a check refuses a layout a
  user needs.
- **The 96 GB RAM tier is Flash-Next and GLM-5.3-Flash.** UD-Q4_K_XL
  and UD-Q2_K_XL behind a build gate, on one 32 GB card with 96 GB of
  system memory ([The 96 GB RAM tier](docs/models.md#the-96-gb-ram-tier)).
  GLM ships because Artificial Analysis (checked 2026-09-20) scores the
  full model above the 27B on knowledge; the 2-bit quant makes that edge
  expected, not measured, and 3 bits would leave no memory margin. Remove
  GLM if its first measured tasks show no benefit over the 27B or
  Flash-Next; reconsider the tier when a comparable open model fits with
  better results.
