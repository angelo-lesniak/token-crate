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
| `agents`, `agentsets`, `uis`, `skills` | Agent sessions, image selections, browser UIs, and skill sets |
| `doctor`, `probe`, `checkpins` | Host checks, API probes and benchmarks, and upstream pin lookups |

Usage and error text in `cli.py` are part of the documented interface.
`docs/cli.md` must show every usage line verbatim.

## Tests

```bash
bash tests/static.sh
```

`tests/static.sh` is the engine-free gate. It runs:

- `bash -n` and ShellCheck over the shell files it lists;
- `node --check` over the two JavaScript files;
- the unit tests (`python3 -m unittest discover -s tests -t .`, every
  `tests/test_*.py`; the entrypoint and forwarder tests run Node.js). The
  CLI tests run the package against the fake engine under
  `tests/fixtures/engine-bin` in a temporary copy of the checkout;
  `tests/test_project_contracts.py` holds the parsed repository contracts
  (the Compose files, the Dockerfiles, the agent settings) and the
  documentation checks, and refuses to run without PyYAML;
- Ruff (`ruff check` and `ruff format --check` over `tokencrate` and
  `tests`);
- `tests/podman-compose.sh`;
- a scan of the tracked files for machine-specific host paths;
- a Compose render with every installed engine.

Missing optional tools produce a `SKIPPED:` line. Set
`TOKENCRATE_STATIC_STRICT=1`, as CI does, to make any skip a failure.
CI uses only tracked files, so checks must not depend on local build
artifacts. After committing a change to the gate's inputs, extract a clean
copy with `git archive HEAD | tar -x -C "$(mktemp -d)"` and run the gate
there. CI also lints both Dockerfiles with hadolint.

Run integration checks after changing the package, images, chat template,
agents, or Compose files. They require a container engine, PyYAML, and
network access for images, fixture models (0.4 GB on the first run), and
GitHub skill sets. Allow several minutes.

The run takes over this checkout's Compose project: `up` replaces a
running stack, and cleanup stops it with `down`. Use a separate checkout
and Compose project to keep an existing stack running.

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

This unittest module is outside the static gate's `test_*` discovery.
Use `-k <pattern>` to select checks by name; setup and `down` still run
around them. CI runs integration weekly and for pull requests touching
the paths in `.github/workflows/integration.yml`.

## Documentation changes

Write and review documentation with the `documentation-guidelines` skill
from [SkillCrate](https://github.com/angelo-lesniak/skill-crate): TokenCrate
agents load it from the `skill-crate` skill set; for another agent, copy
`skills/documentation-guidelines` from that repository into its skills
directory. `AGENTS.md` lists the pages of this repository and which page
owns which facts.

Prefer the existing canonical page over a duplicated explanation. The
README's "Choose what to do next" table is the documentation index; a new
page needs a row there. Keep a section in `docs/cli.md` for every command
listed by `bin/tokencrate help`. `tests/test_project_contracts.py` checks
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
3. The `args:` block of the service in `compose.yaml`, without a fallback
   default; `pins.env` is the single source of pins.
4. The Dockerfile `ARG` (no `=default`).
5. For a pin that `pins check` resolves: `COMPONENTS` and
   `resolve_component` in `tokencrate/checkpins.py`, plus
   `tests/test_checkpins.py`.

## Adding an agent set

An agent set is a directory under `config/agent-sets/` with a `set.toml`
([Agent sets](docs/agent-sets.md) documents the keys and how to write
one). Before pinning a pi extension, read its source at that version:
it runs with pi's permissions inside the container. A shipped set also needs:

- a row in the table of [Agent sets](docs/agent-sets.md#shipped-sets);
- a row in `THIRD_PARTY_NOTICES.md` for what it installs beyond Debian
  packages;
- a passing `bash tests/static.sh` (`tests/test_agentsets.py` validates
  and renders every shipped set);
- `bash bin/tokencrate smoke --agent pi --sets <selection>` for the
  changed selection, recorded as `docs/validation.md` describes.

## Model sets, presets, and skill sets

Model-set entries must use immutable Hugging Face repository commits and
include the exact remote filename, byte size, SHA-256 checksum, an immutable
model-card link, and license links. Start a manifest with
`bash bin/tokencrate models draft hf:<owner>/<repo>:<file.gguf>`, review the
`TODO` lines, and run the model-set unit tests before changing a shipped
pin; a wrong pin fails loudly at `models fetch`. Do not add tokens or
downloaded weights to the repository.

A preset change must state what it was measured with: attach a `bench` report
from `reports/` and the `smoke` result for the affected preset. A model set
whose architecture the pinned llama.cpp build lacks declares the build it
waits for
([Adding a model](docs/models.md#adding-a-model)).

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

These decisions include their reasons and conditions for reconsideration.
Challenge them with evidence against the stated reason.

- **Agent sets:** pi's tools are selected and installed at build time.
  The image is the reviewed artifact, and the container has no route out.
  A new toolchain therefore belongs in a manifest using the existing step
  vocabulary. Reconsider if pi drops local-directory packages or a set
  needs a new kind of step; extend the vocabulary before adding an image
  stage.
- **Shared pi configuration:** sets add to `PATH`, the
  tools note, pi-lens's configuration, and the package list; pi settings
  and skills stay the same across selections, so the model uses a
  consistent tool vocabulary. Reconsider if a set needs different pi
  settings.
- **Browser UI containers:** a UI runs as an agent set inside the pi
  container because it spawns or embeds pi. A separate forwarder publishes
  its port and joins `ui-publish`; Docker cannot publish a container
  attached only to internal networks. This gives both engines the same
  containment: no UI egress, no access from terminal containers, and no
  cross-site access to the unauthenticated UI.
  [Privacy and containment](docs/privacy.md#defaults-and-their-limits)
  states which network each container joins, why a published port needs
  the forwarder on Docker, and the three conditions it refuses on.
  Reconsider if Docker publishes ports from internal networks or a UI
  authenticates and checks origins itself.
- **Two agents:** pi with the `coding` set includes the oh-my-pi features
  expected to justify their cost on a local model. oh-my-pi remains an
  alternative, but its first request costs more than twice pi's
  ([request sizes](docs/agents.md)). Its `bun install --global` has no
  lockfile, so the version pin does not pin all dependencies. It also
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
- **Print-only pin checks:** `pins check` automates version and image-digest
  lookups for five components and leaves `pins.env` edits to the maintainer.
  The resulting diff is the review. Driver requirements, the CUDA family,
  and agent-set versions remain manual. Remove the command if upgrades
  prove no faster with it than with a fully manual lookup.
- **Compose settings:** `.env.example` documents each Compose setting
  and its default; Compose reads these values without wrapper logic for
  each one. Reconsider if a setting gains a second reader that can disagree
  with Compose about its default.
- **llama-server router mode:** the router loads presets, routes requests
  by `model`, loads the default at startup, and serves the built-in chat
  UI. It covers TokenCrate's model-switching needs. A separate proxy such
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
  There is no fork image, second llama image, or `.env` build switch.
  When a release supports the architecture, record its build number in
  both GLM model sets and raise the pin. Remove GLM if its first measured
  tasks show no benefit over the 27B or 4-bit Flash-Next. Reconsider the
  tier when a comparable open model fits with better results.
