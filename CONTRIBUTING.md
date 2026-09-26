# Contributing

Changes must preserve the shared Docker/Podman Compose core, host-mounted
data, the single pin file `pins.env`, and the privacy defaults: loopback
ports, agents without internet access, and disabled telemetry switches.

## Tools

Install Bash 4 or newer, Python 3.11 or newer, Git, Node.js, ShellCheck,
and ripgrep. Node.js runs the forwarder, debug bridge, and agent entrypoint
checks. Install the Python test dependencies in a virtual environment:

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
as set in `ruff.toml`.

| Modules | Responsibility |
| --- | --- |
| `cli` | Usage, option parsing, and dispatch |
| `env`, `names` | Settings, pins, and name validation |
| `engine`, `runtime`, `localhttp` | Engine commands, stack lifecycle, and direct local HTTP requests |
| `models`, `presets`, `agentmodels` | Model downloads, preset validation and rendering, and agent model lists |
| `session` | What one agent container start is made of |
| `agents`, `uis`, `agentsets`, `skills` | Terminal sessions and the containment check, browser UIs, image selections, and skill sets |
| `doctor`, `probe`, `checkpins` | Host checks, API probes and benchmarks, and upstream pin lookups |

Usage and error text in `cli.py` are part of the documented interface.
`docs/cli.md` must show every usage line verbatim.

`session.prepare` is the one pre-flight, mount, and render step: every
wrapper start of an agent container calls it and names its profiles and
`egress=` on each Compose call (a forgotten `egress=` fails closed: the
check reports "no default route although --egress was requested"). Add a
new way to start one there, so that no start can skip the mounts, the
pre-flight, or the image. `session.cloud_keys_file` is the one check of
the cloud keys file, `session.run_arguments` the one way it is mounted
(on the `run` of `agent --cloud` and `ui --cloud`), and the wrapper
never reads that file.

## Tests

```bash
bash tests/static.sh
```

`tests/static.sh` is the engine-free gate. It runs:

- `bash -n` and ShellCheck over the shell files it lists;
- `node --check` over the two JavaScript files;
- an import of each `tokencrate` module on its own, which catches import
  cycles;
- the unit tests, every `tests/test_*.py`. The entrypoint and forwarder
  tests run Node.js. The CLI tests run the package against the fake engine
  under `tests/fixtures/engine-bin` in a temporary copy of the checkout.
  `tests/test_project_contracts.py` holds the parsed repository contracts
  (the Compose files, the Dockerfiles, the agent settings) and the
  documentation checks, and needs PyYAML;
- Ruff (`ruff check` and `ruff format --check` over `tokencrate` and
  `tests`);
- `tests/podman-compose.sh`, which renders every file combination the
  wrapper passes and checks each service's network placement from the
  rendered `run` arguments;
- a scan of the tracked files for machine-specific host paths;
- a Compose render with every installed engine.

Missing optional tools produce a `SKIPPED:` line. Set
`TOKENCRATE_STATIC_STRICT=1`, as CI does, to make any skip a failure.
CI uses only tracked files, so checks must not depend on local build
artifacts. After committing a change to the gate's inputs, extract a clean
copy with `git archive HEAD | tar -x -C "$(mktemp -d)"` and run the gate
there. CI also lints both Dockerfiles with hadolint.

Run the integration checks after changing the package, images, chat
template, agents, or Compose files. They need a container engine, PyYAML,
and network access for images, fixture models (0.4 GB on the first run),
and GitHub skill sets, and take several minutes.

The run takes over this checkout's Compose project: `up` replaces a
running stack, and cleanup stops it with `down`. To keep an existing stack
running, use a separate checkout and Compose project.

```bash
python3 tests/integration.py
```

`tests/integration.py` runs the package against real containers: `skills
fetch` and `skills status`, `up` with the fixture model sets, `status`,
`smoke` (the full probe on a 0.4 GB instruct model, then the basic probe on
the 1.2 MB model, which swaps the loaded model), `bench`, `smoke --agent`
for both agents, a prompt through each agent, a check that each agent's
thinking level reaches the chat template, the [agent home
check](docs/validation.md#agent-home-check) for both agents and both
browser UIs, the
[independent-client check](docs/validation.md#independent-client-check),
and `down`.

The run calls `init` if `.env` is missing. It copies fixtures into
`config/` and refuses to start if a fixture copy already exists there.
Cleanup removes the resources created by the run.

Use `-k <pattern>` to select checks by name; setup and `down` still run
around them. CI runs the integration checks weekly and for pull requests
that touch the paths in `.github/workflows/integration.yml`, as parallel
jobs with a stack each. `CI_JOBS` in `tests/integration.py` assigns every
test to a job, and `TOKENCRATE_CI_JOB=<job>` runs one job's tests; a test
missing from `CI_JOBS`, or a name there without a test, stops the run.

## Documentation changes

Write and review documentation with the `documentation-guidelines` skill
from [SkillCrate](https://github.com/angelo-lesniak/skill-crate). TokenCrate
agents load it from the `skill-crate` skill set; for another agent, copy
`skills/documentation-guidelines` from that repository into its skills
directory. `AGENTS.md` lists which page owns which facts.

Update the existing canonical page instead of duplicating an explanation.
A new page needs a row in the README's "Choose what to do next" table.
Keep a section in `docs/cli.md` for every command listed by
`bin/tokencrate help`. `tests/test_project_contracts.py` checks
that relative links and heading anchors resolve, that the README table
links every page, and that every usage line of the help text appears in
`docs/cli.md`; the facts in the prose are checked by hand.

## Adding a pin

Add each new pin to these locations so builds and checks use the same
value:

1. `pins.env`, as a plain value (no quotes, no whitespace). A base image
   pins its tag and its manifest digest as two keys; the `FROM` line and
   the forwarder's image line use both
   ([Upgrading](docs/configuration.md#upgrading) shows the lookup).
2. `PIN_KEYS` in `tokencrate/env.py`: the wrapper reads exactly these keys
   and rejects any other, and `tests/test_project_contracts.py` imports
   the same tuple.
3. For a pin an image build uses: the `args:` block of the service in
   `compose.yaml` without a fallback default (`pins.env` is the single
   source of pins), and the Dockerfile `ARG` (no `=default`).
4. For a pin that `pins check` resolves: `COMPONENTS` and
   `resolve_component` in `tokencrate/checkpins.py`, plus
   `tests/test_checkpins.py`.

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
directory made of letters, digits, and `._+@-`. A comma-separated list
(`LLM_SKILL_SETS`, `LLM_AGENT_SETS`, `--sets`) goes
through its one parser, which ignores spaces, empty entries, and repeats.

Model-set entries must use immutable Hugging Face repository commits and
include the exact remote filename, byte size, SHA-256 checksum, an immutable
model-card link, and license links; `models draft` writes them
([Adding a model](docs/models.md#adding-a-model) is the procedure). Run
the model-set unit tests before changing a shipped pin; a wrong pin fails
loudly at `models fetch`. Do not add tokens or downloaded weights to the
repository.

A preset change must state what it was measured with: attach a `bench` report
from `reports/` and the `smoke` result for the affected preset. A model set
whose architecture the pinned llama.cpp build lacks declares the build it
waits for ([Adding a model](docs/models.md#adding-a-model)).

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

Do not commit models, `.env`, `build/`, `data/`, `local/`, or `reports/`.

## Settled decisions

Each decision states its reason and when to reconsider it. Challenge one
only with evidence against its stated reason.

- **Agent sets:** pi's tools are selected and installed at build time.
  The image is the reviewed artifact, and the container has no route out.
  A new toolchain therefore belongs in a manifest using the existing step
  vocabulary. Reconsider if pi drops local-directory packages or a set
  needs a new kind of step; extend the vocabulary before adding an image
  stage.
- **Shared pi configuration:** sets add to `PATH`, the tools note,
  pi-lens's configuration, and the package list; pi settings and skills
  stay the same across selections, so the model sees one tool
  vocabulary. Reconsider if a set needs different pi settings.
- **Browser UI containers:** a UI runs as an agent set inside the pi
  container because it spawns or embeds pi. A separate forwarder publishes
  its port and joins `ui-publish`; Docker cannot publish a container
  attached only to internal networks. Both engines get the same
  containment: no UI egress and no access from terminal containers
  unless the UI is started with `--egress` or `--cloud`, and no
  cross-site access to the unauthenticated UI
  ([Privacy and containment](docs/privacy.md#defaults-and-their-limits)
  gives the networks and the forwarder's checks). Reconsider if Docker
  publishes ports from internal networks or a UI authenticates and checks
  origins itself.
- **UI egress is the simple variant:** `ui --egress` and `ui --cloud`
  add the default network to the UI container, which stays on `ui` for
  its forwarder, and mount the keys file exactly as `agent pi --cloud`
  does; no per-UI network, no setting, no gate. The accepted
  consequences (who can reach the UI, its route, and its keys while it
  runs) are stated in [Cloud providers](docs/agents.md#cloud-providers)
  rather than guarded by code. Reconsider when a per-UI network with a
  guard is proven cheaper than those paragraphs.
- **UIs launch with `compose run`:** both containers of a UI start the
  way a terminal session does, under the fixed names
  `tokencrate-ui-<set>` and `tokencrate-ui-forward-<set>`, with the
  keys file, the egress overlay, and the labels delivered the same way.
  podman-compose ignores `run -l`, so the labels are interpolated in
  the Compose files (`TOKENCRATE_UI_SET`, and the overlay's own
  `io.tokencrate.ui-egress`). The fixed names mean two Compose projects
  cannot run one UI set at once. Reconsider if a provider stops
  honouring `run --name` or `--service-ports`.
- **Two agents:** pi with the `coding` set includes the oh-my-pi features
  expected to justify their cost on a local model. oh-my-pi remains an
  alternative, but its first request costs more than twice pi's
  ([Coding agents and skills](docs/agents.md)). Its `bun install
  --global` has no lockfile, so the version pin does not pin all
  dependencies. It also
  needs a second image, base pin, model-list dialect, entrypoint branch,
  configuration overlay, Compose service, and validation coverage.
  Reconsider if GPU results show no benefit over pi with `coding`, or if
  an upgrade still cannot provide a lockfile-pinned install.
- **Default coding extensions:** `LLM_AGENT_SETS=coding` adds four times
  the tools and more than three times the request body before a task
  starts; see the
  [request-size record](docs/validation.md#request-size-of-the-coding-set).
  Their value on a local model remains a hypothesis. Reconsider after
  comparing plain pi and the bundle on the same coding tasks with a shipped
  27B preset: completion, wrong edits, tokens, turns, and wall time.
- **Default skill sets:** `LLM_SKILL_SETS=pocock-core,skill-crate` keeps
  eleven skill descriptions available. An empty default would remove
  `skills fetch` and its startup requirement from initial setup.
  Reconsider if those descriptions cost more context on a 27B model than
  their skills return in value.
- **Cloud sessions are egress sessions, not filtered ones:** an
  `agent --cloud` session has the full route out of `--egress`; no
  per-provider allowlist narrows it. A Node client honours proxy variables
  only when it opts in, so a real filter must work at the network level,
  and a filter that does not filter is worse than stating what the
  session can reach
  ([Privacy and containment](docs/privacy.md#defaults-and-their-limits)).
  Reconsider when a network-level allowlist is proven on both engines.
- **Cloud keys in a file the wrapper never reads:** `agent --cloud`
  and `ui --cloud` mount the file `LLM_CLOUD_KEYS_FILE` names and the
  entrypoint exports its lines. The wrapper checks the file's place and
  shape, not its contents, and keeps no provider table: pi reads its
  provider variables from `pi-ai/dist/env-api-keys.js` in the pinned
  package, some in pairs,
  so a table drifts with every `PI_VERSION` and a filter would block what
  pi needs. A sidecar that injects the credential and keeps the keys out
  of the container would need a per-provider header dialect, rendered
  base URLs, and a network of its own, so that offline sessions cannot
  relay through it. Reconsider when such a sidecar is proven on both
  engines with a real key.
- **Cloud models through pi only:** `agent omp --cloud` is refused.
  oh-my-pi fills unset provider settings, base URLs included, from the
  project's `.env` files, so a cloned repository can send the key and
  every prompt to a server of its choosing
  ([record](docs/validation.md#oh-my-pi-and-project-env-files)); pi reads
  no such file. Reconsider when a forwarder inside the container injects
  the credential, so that no key is in the agent's environment for a
  `.env` file to redirect.
- **No repository skills:** every skill an agent sees is a pinned skill
  set or a private skill below `LLM_LOCAL_SKILLS_DIR`; the checkout
  ships none. Generic working advice belongs to a skill set, and a claim
  about what leaves the machine belongs to the documentation, where
  `--cloud` qualifies it. Reconsider for a set-specific instruction that
  no manifest `note` can carry.
- **No renderer entry for a cloud provider:** `tokencrate/agentmodels.py`
  renders the local provider alone. Both pinned agents ship each
  provider's endpoint, request dialect, and model catalogue, and offer a
  provider when its key variable is set. pi keeps its built-in models
  when a custom entry is added ("Merge semantics" in the pinned
  package's `docs/models.md`), so an entry would carry only what the
  bundle has, plus a base URL the wrapper would then have to pin.
  Reconsider if an agent version drops its bundled catalogues.
- **Print-only pin checks:** `pins check` automates version and image-digest
  lookups for five components and leaves `pins.env` edits to the maintainer.
  The resulting diff is the review. Driver requirements, the CUDA family,
  and agent-set versions remain manual. Remove the command if upgrades
  prove no faster with it than with a fully manual lookup.
- **Compose settings:** `.env.example` documents each Compose setting
  and its default; Compose reads these values with no per-setting wrapper
  logic, and the wrapper exports every documented key with its effective
  value, so a Compose fallback for one is never used. The variables the
  wrapper sets per call keep a fallback, because Compose interpolates
  every service on every call and `up` sets none of the agent ones. The
  two set on every call, `TOKENCRATE_ROOT` and `TOKENCRATE_HOME_OWNER`,
  are required. Reconsider if a
  setting gains a second reader that can disagree with Compose about its
  default.
- **llama-server router mode:** the router loads presets, routes requests
  by `model`, loads the default at startup, and serves the built-in chat
  UI, which covers TokenCrate's model switching. A separate proxy such
  as llama-swap would add a pinned component, configuration format, and
  per-effort aliases; clients already send `reasoning_effort` per request.
  Reconsider if router mode loses a required feature.
- **The 96 GB RAM tier:** Qwen3.8-Flash-Next uses a 4-bit quantization;
  GLM-5.3-Flash uses UD-Q2_K_XL behind a build gate. This tier assumes
  one 32 GB card and 96 GB of system memory. Flash-Next loads on the
  pinned build. GLM is included because it is expected to beat the 27B
  on knowledge; [The 96 GB RAM tier](docs/models.md#the-96-gb-ram-tier)
  gives the Artificial Analysis scores behind that expectation. A 3-bit
  GLM quantization would leave no memory margin on this split. The model
  sets use `[requires] llama_build` to wait for upstream `glm5next`
  support, keeping the pinned upstream image as the reviewed artifact.
  There is no fork image, second llama image, `.env` build switch, or
  image-name setting.
  When a release supports the architecture, record its build number in
  both GLM model sets and raise the pin. Remove GLM if its first measured
  tasks show no benefit over the 27B or 4-bit Flash-Next. Reconsider the
  tier when a comparable open model fits with better results.
