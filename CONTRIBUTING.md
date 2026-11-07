# Contributing

This page is for developers changing TokenCrate. Preserve the shared
Compose core for Docker and Podman, host-mounted data, the single pin
file `pins.env`, and the [privacy defaults](docs/privacy.md).

## Tools

Install Bash, Python 3.11 or newer, Git, Node.js, ShellCheck, and
ripgrep; the static gate runs Node.js. Install the Python test
dependencies in a virtual environment and activate it before running the
tests, because `tests/static.sh` runs the `python3` on `PATH`:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

## Layout

Keep behavior in the `tokencrate/` package, which uses only the Python
standard library and targets Python 3.11 (`ruff.toml`); `bin/tokencrate`
only launches it. The images' shell and JavaScript live under
`services/` and `config/agent-sets/`. Each module's docstring says what
it does.

`session.plan` prepares every agent container start: terminal sessions,
browser UIs, and the agent check. Add a new start as a caller of `plan`
and its `Launch.build` and `Launch.run`, so it inherits the mounts,
egress, keys-file checks, and cleanup. `Settings.storage` in `env.py` is
the shared list of host paths; `doctor` and `runtime` iterate it instead
of naming directories.

## Tests

```bash
bash tests/static.sh
```

Run the static gate after every change. It needs no container engine
and no model, takes about a minute, and
[`tests/static.sh`](tests/static.sh) lists its checks. A missing optional
tool prints a `SKIPPED:` line and the gate still passes;
`TOKENCRATE_STATIC_STRICT=1`, as in CI, makes any skip a failure. CI runs
the gate on a clean checkout, so a check must not depend on local build
artifacts. CI also lints the Dockerfiles with hadolint.

```bash
python3 tests/integration.py
```

Run the integration checks after changing the package, images, chat
template, agents, or Compose files;
[`tests/integration.py`](tests/integration.py) lists the checks and what
they need. They take over this checkout's Compose project: `up` replaces
a running stack and cleanup stops it with `down`. CI runs them weekly
and for changes to the paths in `.github/workflows/integration.yml`.

[Validation](docs/validation.md) holds the host acceptance procedures.

## Documentation changes

Write and review documentation with the `documentation-guidelines` skill
from [SkillCrate](https://github.com/angelo-lesniak/skill-crate):
TokenCrate agents get it from the `skill-crate` skill set, and another
agent needs a copy of its `skills/documentation-guidelines` directory.
This section is the checklist the skill asks for.

Each fact has one owner page; update it instead of restating the fact
elsewhere:

- `README.md#start-here`: the install and the quick start;
  `README.md#scope-and-support`: the supported platforms.
- `docs/cli.md`: every command and flag.
- `docs/configuration.md`: storage, pins, ports, and the dashboard;
  `.env.example` is the settings reference.
- `docs/models.md`: model sets, presets, their manifest keys, and the
  build gate.
- `docs/agent-sets.md`: agent sets, the manifest of a UI set included.
- `docs/agents.md`: how agents load skills, the use of browser UIs, the
  keys-file rules (`cloud-keys.env.example` is only the template), and
  the permission model of an agent container, except its network part.
- `docs/privacy.md`: the network layout, the forwarder, and their
  limits.
- `docs/validation.md#status`: the only statement of what is validated;
  a validated claim needs a date there. Findings go to the page that owns
  the fact.
- `docs/troubleshooting.md`: observed failures, one section each.

There is no glossary, word list, or changelog before the first tagged
release; Git history records changes.

`tests/test_project_contracts.py` checks that links and anchors
resolve, that the README's "Choose what to do next" table links every
page, that `docs/cli.md` shows every usage line verbatim, and that every
shipped agent set, model set, preset, and setting is named in code
formatting on its owner page. Usage and error text in `cli.py` are part
of the documented interface. Check the facts in the prose by hand.

## Add a pin

A pin in `pins.env` is `<NAME>_TAG` with `<NAME>_DIGEST` beside it (the
tag names the image, the manifest digest is what the build pulls),
`<NAME>_VERSION`, or `CUDA_MIN_DRIVER_MAJOR`; `env.load_pins` refuses any
other key name, and a tag or digest without its partner.

1. Write it in `pins.env` as a plain value (no quotes, no whitespace);
   [Upgrade a pin](docs/configuration.md#upgrade-a-pin) says where to
   look up a pin without a resolver.
2. For a pin an image build uses, add it to the service's `args:` block in
   `compose.yaml` without a fallback and as a Dockerfile `ARG` without a
   default, so that `pins.env` stays the only place the value lives; a
   contract test checks this.
3. For a pin `pins check` should resolve, add one `RESOLVERS` entry keyed
   by the pin in `tokencrate/checkpins.py` and a case in
   `tests/test_checkpins.py`.

## Add an agent set

[Write a set](docs/agent-sets.md#write-a-set) holds the manifest keys
and the procedure. Before pinning a pi extension, read its source at
that version: it runs with pi's permissions inside the container. A shipped set also needs:

- a row in the table of [Agent sets](docs/agent-sets.md#shipped-sets);
- a row in `THIRD_PARTY_NOTICES.md` for what it installs beyond Debian
  packages;
- `bash bin/tokencrate smoke --agent pi --sets <selection>` for the
  changed selection, recorded as `docs/validation.md` describes.

## Model sets, presets, and skill sets

Every manifest kind and every comma-separated list goes through
[`tokencrate/names.py`](tokencrate/names.py), which holds the rules they
share.

[Add a model](docs/models.md#add-a-model) holds the model-set and
preset procedure.

A skill-set entry pins a public credential-free HTTPS repository on a
host listed in `config/skill-sets/allowed-git-hosts.txt`, a full commit,
and the tree digest of the pinned directory. To obtain the digest, pin
64 zeros as `sha256` and run `bash bin/tokencrate skills fetch <set>`:
the refusal prints the tree digest to pin. Read each `SKILL.md` and
every file under its `scripts/` directory before pinning it; commit
pinning is not a code review.

Do not commit models, tokens, `.env`, `build/`, `data/`, `local/`, or
`reports/`.

## Router behavior the wrapper relies on

`runtime`, `probe`, and the preset renderer rest on these observations
of llama-server's router mode (`--models-preset`, `--models-max 1`),
made on b10920 ([Known gaps](docs/validation.md#known-gaps)); repeat
them after a `LLAMA_CPP_TAG` change.

- Readiness: `GET /health` answers `{"status":"ok"}` while the default
  preset is still `loading` in `GET /models`, so `up` polls `/models` for
  `loaded` (`runtime.wait_until_ready`).
- Swap: a request whose `model` names another preset waits for the
  running request, then the router unloads the loaded model and loads
  the other. `POST /models/load` answers 400 for the model that is
  loading or loaded and 500 `model limit reached` for another model
  while one is loaded, so `up` asks for a load only when nothing is
  loaded.
- Failure: a preset whose model server exits leaves the router running,
  `/models` reports it `unloaded`, and a request for it answers 500; `up`
  fails when the default preset turns `unloaded` after `loading`.
- Requests without `model` answer 400 `model name is missing from the
  request`; `GET /props`, `POST /tokenize`, and `GET /metrics` need
  `?model=` or a `model` field, which the probe sends. A `/metrics`
  request for an unloaded preset loads it, so scrape only presets
  `GET /models` reports loaded.
- Preset file: keys are llama-server option names without dashes
  (`ui-config-file` becomes `--webui-config-file`, `gpu-layers`
  `--n-gpu-layers`); a key given twice
  keeps the last value silently; keys in `[*]` reach every child; an
  unknown key stops the router at start with `option '<key>' not
  recognized in preset '<name>'`. The renderer therefore keeps a typed
  vocabulary and a short `[server.extra]` passthrough list ([Add a
  model](docs/models.md#add-a-model)).

## Settled decisions

Each entry gives the decision, its reason, and when to reconsider it;
the linked page holds the mechanism. Challenge one only with evidence
against its reason.

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
  adds the default network with no gate ([Cloud
  providers](docs/agents.md#cloud-providers) states the consequences).
  Reconsider when a per-session gate costs less than those consequences
  and is proven on both engines.
- **Sessions and UIs start with `compose run`, under fixed names.** One
  Compose core carries the hardening, mounts, keys file, and egress
  overlay for every container. Reconsider if a provider stops honoring
  `run --name` or `--service-ports`.
- **Two agents.** pi with `coding` includes the oh-my-pi features
  expected to pay off on a local model; oh-my-pi stays as an alternative
  although it needs its own image, pin, model-list dialect, entrypoint
  branch, overlay, Compose service, and validation. Reconsider if GPU results show no benefit over pi
  with `coding`, or if oh-my-pi still cannot be lockfile-pinned.
- **`coding` and `metrics` are the default agent sets.** `coding` gives
  a first session the tools a coding agent is expected to have without
  choosing sets, at the cost of more
  tools and a larger request body before a task starts; its value on a
  local model is a hypothesis. `metrics` changes no request and fills
  the stats Timings table. Reconsider after comparing plain pi and the
  bundle on the same coding tasks with a shipped 27B preset: completion,
  wrong edits, tokens, turns, and wall time.
- **`pocock-core,skill-crate` are the default skill sets.** An empty
  default would remove `skills fetch` from initial setup. Reconsider if
  the skill descriptions cost more context on a 27B model than their
  skills return.
- **Cloud sessions are egress sessions, not filtered ones.** A `--cloud`
  session has the full route out of `--egress`: Node clients honor proxy
  variables only by opt-in, so only a network-level filter would filter,
  and a leaky filter is worse than stating what the session can reach
  ([Egress](docs/privacy.md#egress)).
  Reconsider when a network-level allowlist is proven on both engines.
- **Cloud keys in a file the wrapper never reads.** The wrapper checks
  the file, never its contents, and keeps no provider table, because
  pi's variable names change with `PI_VERSION`
  ([Cloud providers](docs/agents.md#cloud-providers)). Reconsider when a
  sidecar that injects the credential is proven on both engines with a
  real key.
- **Cloud models through pi only.** `agent omp --cloud` is refused
  because oh-my-pi reads provider settings from project `.env` files
  ([Cloud providers](docs/agents.md#cloud-providers)); pi reads no such
  file. Reconsider when the credential is injected inside the container,
  out of the agent's environment.
- **No repository skills.** Every skill an agent sees is a pinned skill
  set or a private skill below `LLM_LOCAL_SKILLS_DIR`; generic advice
  belongs to a skill set, and a claim about what leaves the machine
  belongs to the documentation, where `--cloud` qualifies it. Reconsider
  for a set-specific instruction that no manifest `note` can carry.
- **No renderer entry for a cloud provider.** Both pinned agents bundle
  each provider's endpoint, dialect, and model catalogue and offer a
  provider when its key variable is set; an entry would duplicate the
  bundle and add a base URL to pin. Reconsider if an agent version drops
  its bundled catalogues.
- **Required Compose settings have no fallback.** Required settings and
  the derived values use `${VAR:?}` in the Compose files, so an empty
  value fails the Compose call naming the variable and no second default
  can disagree with `.env.example`. Reconsider if a setting gains a second reader that
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
  refusals, owner checks, and per-directory modes also cover the model
  library, which only the host writes; they cost code size, not
  behavior. Reconsider when the threat model in `SECURITY.md` changes or
  a check refuses a layout a user needs.
- **The 96 GB RAM tier is Flash-Next and GLM-5.3-Flash.** Both fit one
  32 GB card with 96 GB of system memory ([The 96 GB RAM
  tier](docs/models.md#the-96-gb-ram-tier)). GLM ships because
  Artificial Analysis (checked 2026-09-20) scores the full model above
  the 27B on knowledge; at 2 bits that edge is expected, not measured,
  and 3 bits would leave no memory margin. Remove GLM if its first
  measured tasks show no benefit over the 27B or Flash-Next; reconsider
  the tier when a comparable open model fits with better results.
