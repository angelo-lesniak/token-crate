# Contributing

A change to TokenCrate passes `tests/static.sh` and keeps the decisions
below; this page says how to set up, where code lives, and what a
reviewer holds a change to. Every change keeps the shared Compose core
for Docker and Podman, host-mounted data, the single pin file `pins.env`,
and the privacy defaults (loopback ports, agents without internet access,
telemetry switches off).

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
| `cli` | The command table, from which `USAGE` and the misplaced-flag refusals are generated, and dispatch |
| `env`, `names` | Settings, pins, the storage list, and name validation |
| `agenthome`, `files` | Leaves: the agent-home constants every module shares, and atomic file writes |
| `engine`, `runtime`, `localhttp` | Engine commands, stack lifecycle, and direct local HTTP requests |
| `models`: `manifest`, `library`, `hub`, `download`, `drafts` | Manifests, the library, the Hub, downloads, drafts |
| `presets`, `agentmodels` | Preset validation and rendering, and agent model lists |
| `session` | One agent container start: the pre-flight and the `Launch` |
| `agents`, `uis`, `agentsets`, `skills` | Terminal sessions and their check, browser UIs, set selections, skill sets |
| `doctor`, `probe`, `checkpins` | Host checks, API probes and benchmarks with their history, upstream pin lookups |
| `stats`: `transcripts`, `tables`, `report` | Transcript reading, the one aggregation, the Markdown report |
| `stats`: `page`, `live`, `server` | The HTML page (assets under `stats/pages/`), the live sampler, `--serve` |

`session.plan` is the one pre-flight of every agent container start
(terminal session, browser UI, `smoke --agent`). It checks the keys file,
resolves the preset and the home, prepares the mounts, and renders the
image. It returns a `Launch` whose `build` and `run` are the only way a
start reaches Compose. Every `run` names its container, stops it on any
unwind, and carries the plan's profiles, egress, and keys mount; a caller
chooses only the command, whether to detach, and the terminal. Add a new
way to start a container as a caller of `plan`, never beside it.
`session.cloud_keys_file` is the one check of the cloud keys file, and
the wrapper never reads that file. `Settings.storage` in `env.py` is the
one list of host paths; `doctor` and `runtime` iterate it instead of
naming directories.

## Tests

```bash
bash tests/static.sh
```

`tests/static.sh` is the static gate: it needs no container engine and
no model, so it runs on any machine with the language tools. CI runs it
in strict mode on every pull request; running it locally first gives
the result in about a minute instead of a push and a wait. It runs:

- shell syntax and ShellCheck;
- `node --check`;
- an import of each `tokencrate` module on its own, subpackages included;
- every `tests/test_*.py` (the CLI tests use the fake engine under
  `tests/fixtures/engine-bin`; `tests/test_project_contracts.py` holds the
  repository contracts and the documentation checks and needs PyYAML);
- Ruff;
- `tests/podman-compose.sh`, which renders every Compose file combination
  and checks each service's network placement;
- a scan for machine-specific host paths;
- a Compose render with every installed engine.

A missing optional tool, Node.js included, prints a `SKIPPED:` line
and the gate still passes; `TOKENCRATE_STATIC_STRICT=1`, as in CI, makes
any skip a failure. The
gate runs on the tracked files alone, so a check must not depend on local
build artifacts. CI also lints both Dockerfiles with hadolint.

```bash
python3 tests/integration.py
```

Run the integration checks after changing the package, images, chat
template, agents, or Compose files. They need a container engine, PyYAML,
and network access (images, 0.4 GB of fixture models on the first run,
GitHub skill sets), and take several minutes. They take over this
checkout's Compose project: `up` replaces a running stack and cleanup
stops it with `down`. The docstring of `tests/integration.py` lists the checks;
`-k <pattern>` selects by name. CI runs them weekly and for pull requests
that touch the paths in `.github/workflows/integration.yml`, one job per
`CI_JOBS` entry.

## Documentation changes

Write and review documentation with the `documentation-guidelines` skill
from [SkillCrate](https://github.com/angelo-lesniak/skill-crate). TokenCrate
agents load it from the `skill-crate` skill set; for another agent, copy
`skills/documentation-guidelines` from that repository into its skills
directory. `AGENTS.md` lists which page owns which facts.

Update the existing canonical page instead of duplicating an explanation.
A new page needs a row in the README's "Choose what to do next" table.
Usage and error text in `cli.py` are part of the documented interface:
keep a section in `docs/cli.md` for every command listed by
`bin/tokencrate help`, with every usage line verbatim.
`tests/test_project_contracts.py` checks that relative links and heading
anchors resolve, that the README table links every page, and that every
usage line appears in `docs/cli.md`. Check the facts in the prose by
hand.

## Adding a pin

`pins.env` is self-describing: a pin is `<NAME>_TAG` with `<NAME>_DIGEST`
beside it (the tag names the image, the manifest digest is what the build
pulls), `<NAME>_VERSION`, or `CUDA_MIN_DRIVER_MAJOR`. `env.load_pins`
refuses any other key name, and a tag or digest without its partner. To
add a pin:

1. Write it in `pins.env` as a plain value (no quotes, no whitespace);
   [Upgrading](docs/configuration.md#upgrading) shows the digest lookup.
2. For a pin an image build uses, add it to the service's `args:` block in
   `compose.yaml` without a fallback and as a Dockerfile `ARG` without a
   default. `pins.env` stays the only place the value lives; a contract
   test checks this.
3. For a pin `pins check` should resolve, add one `RESOLVERS` entry keyed
   by the pin in `tokencrate/checkpins.py` and a case in
   `tests/test_checkpins.py`. A pin without a resolver prints
   `<name>: <value> (no resolver; look it up by hand)`.

## Adding an agent set

An agent set is a directory under `config/agent-sets/` with a `set.toml`
([Agent sets](docs/agent-sets.md) documents the keys and how to write
one). Before pinning a pi extension, read its source at that version: it
runs with pi's permissions inside the container. A shipped set also needs:

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

`models draft` writes a model-set entry with the immutable Hugging Face
commit, exact filename, size, checksum, and links that
[Adding a model](docs/models.md#adding-a-model) requires; run
`python3 -m unittest tests.test_model_sets` before changing a shipped
entry. A preset change attaches the `bench` report from `reports/` and
the `smoke` result for the affected preset.

Skill-set entries must use a public credential-free HTTPS repository on an
allowlisted host, a full commit, and the tree digest that
`skills.digest_command` in `tokencrate/skills.py` computes for the pinned
directory. From the repository root:

```bash
python3 - <<'PY'
from pathlib import Path
from tokencrate import skills
hosts = skills.load_allowed_hosts(Path("config/skill-sets/allowed-git-hosts.txt"))
print(skills.digest_command("https://github.com/<owner>/<repo>", "<commit>", "<path>", hosts))
PY
```

Read each `SKILL.md` and every file under its `scripts/` directory before
pinning it. Commit pinning is not a code review.

Do not commit models, tokens, `.env`, `build/`, `data/`, `local/`, or
`reports/`.

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
- **A browser UI is an agent set inside the pi container.** It spawns or
  embeds pi. A separate forwarder publishes its port because Docker
  cannot publish a container attached only to internal networks; both
  engines get the same containment
  ([Privacy and containment](docs/privacy.md#defaults-and-their-limits)).
  Reconsider if Docker publishes ports from internal networks or a UI
  authenticates and checks origins itself.
- **Shared networks and targeted hardening, not per-session networks.**
  Sessions share `agents`, UIs share `ui`, and `--egress` or `--cloud`
  adds the default network with no gate. The consequences are stated in
  [Cloud providers](docs/agents.md#cloud-providers) and guarded only
  where a check is cheap. Reconsider when a per-session gate is proven on
  both engines for less than the stated consequences cost.
- **Sessions and UIs start with `compose run`, under fixed names.** One
  Compose core carries the hardening, the mounts, the keys file, and the
  egress overlay for every container. Reconsider if a provider stops
  honoring `run --name` or `--service-ports`.
- **Two agents.** pi with the `coding` set includes the oh-my-pi features
  expected to pay for themselves on a local model. oh-my-pi stays as an
  alternative although its first request costs more than twice pi's
  ([Coding agents and skills](docs/agents.md)) and needs a second image,
  base pin, model-list dialect, entrypoint branch, overlay, Compose
  service, and validation coverage. Reconsider if GPU results show no
  benefit over pi with `coding`, or if oh-my-pi still cannot be
  lockfile-pinned.
- **`coding` and `metrics` are the default agent sets.** `coding` adds
  four times the tools and more than three times the request body before
  a task starts (17 tools and a 28,685-character body against 4 and
  8,487 for pi without extensions, measured against a stub endpoint);
  its value on a local model is a hypothesis. `metrics` changes no request
  and fills the stats Timings table. Reconsider after comparing plain pi
  and the bundle on the same coding tasks with a shipped 27B preset:
  completion, wrong edits, tokens, turns, and wall time.
- **`pocock-core,skill-crate` are the default skill sets.** They keep
  eighteen skill descriptions available (seventeen and one). An empty
  default would remove `skills fetch` from initial setup. Reconsider if
  those descriptions cost more context on a 27B model than their skills
  return.
- **Cloud sessions are egress sessions, not filtered ones.** A `--cloud`
  session has the full route out of `--egress`. A Node client honors
  proxy variables only when it opts in, so a filter must work at the
  network level; a filter that does not filter is worse than stating
  what the session can reach
  ([Privacy and containment](docs/privacy.md#defaults-and-their-limits)).
  Reconsider when a network-level allowlist is proven on both engines.
- **Cloud keys in a file the wrapper never reads.** The wrapper checks
  the file, never its contents, and keeps no provider table itself,
  because pi's variable names change with `PI_VERSION`;
  `cloud-keys.env.example` lists the names as of the pinned version
  ([Cloud providers](docs/agents.md#cloud-providers)). Reconsider when a
  sidecar that injects the credential is proven on both engines with a
  real key.
- **Cloud models through pi only.** `agent omp --cloud` is refused:
  oh-my-pi reads provider settings from project `.env` files
  ([Cloud providers](docs/agents.md#cloud-providers) says what that
  exposes); pi reads no such file. Reconsider when the credential is
  injected inside the container, out of the agent's environment.
- **No repository skills.** Every skill an agent sees is a pinned skill
  set or a private skill below `LLM_LOCAL_SKILLS_DIR`. Generic advice
  belongs to a skill set; a claim about what leaves the machine
  belongs to the documentation, where `--cloud` qualifies it. Reconsider
  for a set-specific instruction that no manifest `note` can carry.
- **No renderer entry for a cloud provider.** Both pinned agents ship
  each provider's endpoint, dialect, and model catalogue, and offer a
  provider when its key variable is set. An entry would duplicate the
  bundle plus a base URL the wrapper would then have to pin. Reconsider
  if an agent version drops its bundled catalogues.
- **Print-only pin checks.** `pins check` prints and never edits, so the
  `pins.env` diff is the review ([`pins`](docs/cli.md#pins)). Remove the
  command if upgrades prove no faster with it than with a manual lookup.
- **Every Compose setting is required.** Every `.env` setting and the
  four derived values (`HOST_UID`, `HOST_GID`, `TOKENCRATE_ROOT`,
  `TOKENCRATE_HOME_OWNER`) are `${VAR:?}` in the Compose files (`?` for
  `LLM_SKILL_SETS`, which may be empty), so an empty value fails the
  Compose call naming the variable instead of taking a silent fallback.
  Reconsider if a setting gains a second reader that can disagree with
  Compose about its default.
- **The dashboard is an opt-in profile, and two scrapers carry one
  rule.** The profile is off by default because it adds four containers;
  the exporter and the live panel share the two-poll rule
  ([Dashboard](docs/configuration.md#dashboard)) and
  `tests/test_statspage.py` pins that line in both copies. Reconsider the
  exporter when the router serves counters without loading a model, and
  the second copy when the page can read the exporter instead.
- **llama-server router mode.** The router loads presets, routes by
  `model`, loads the default at startup, and serves the built-in chat
  UI. A separate proxy would add a pinned component, a configuration
  format, and per-effort aliases, and clients already send
  `reasoning_effort` per request. Reconsider if router mode loses a
  required feature.
- **Table-driven CLI.** `COMMANDS` in `cli.py` is the one description of
  the interface ([Layout](#layout)). Add a flag as a `Flag` of its
  command, never as a check inside a handler. Reconsider if a command
  needs an option grammar the table cannot express.
- **Paseo's identity travels through the per-set state mount.** One
  pairing serves every project through the per-set state mount
  ([Browser UIs](docs/agents.md#browser-uis)); the manifest has no
  identity key, and the quirk stays in the one launcher that has it.
  Reconsider if a second UI needs cross-project state the mount cannot
  carry.
- **Filesystem hardening covers the user's own storage.** The symlink
  refusals, owner checks, and per-directory modes stay wherever an agent
  can write and in the model library, although only the host writes
  `data/models`. The checks are correct, and their cost is code size, not
  behavior. Reconsider when the threat model in `SECURITY.md` changes or
  a check refuses a layout a user needs.
- **The 96 GB RAM tier is Flash-Next and GLM-5.3-Flash.** UD-Q4_K_XL
  and UD-Q2_K_XL behind a build gate, on one 32 GB card with 96 GB of
  system memory ([The 96 GB RAM tier](docs/models.md#the-96-gb-ram-tier)).
  GLM ships because the full model is expected to beat the 27B on
  knowledge (Artificial Analysis, checked 2026-09-20: Intelligence Index
  42 against 34, Omniscience +7 against −10, HLE 40 against 34 percent).
  The 2-bit quant keeps 78 percent top-1 agreement, so the edge is
  expected, not measured; 3 bits would leave no memory margin. The sets
  wait behind the build gate for upstream `glm5next` support; no fork
  image. Remove GLM if its first measured tasks show no benefit over the
  27B or Flash-Next; reconsider the tier when a comparable open model
  fits with better results.
