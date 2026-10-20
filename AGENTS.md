# Agent guidance

## Guiding principle

Less is more. Prefer the smallest coherent solution that satisfies the
task and preserves the project's invariants. Remove obsolete complexity
when it is in scope and verified. Do not turn a local task into an
unrelated rewrite. Documentation is maintained surface area too: add
information only when it helps a named reader decide, act, verify, or
recover.

## Know this repository

- The implementation is the Python package `tokencrate/` behind the shim
  `bin/tokencrate`, with the shell and JavaScript of the images under
  `services/` (entrypoint, containment check, forwarder, dashboard
  exporter) and `config/agent-sets/` (UI launchers, the metrics
  extension). `CONTRIBUTING.md` lists the modules, the rules for changing
  them, the pin locations, and the metadata for model-set, agent-set, and
  skill-set entries.
- `README.md` carries the product scope, the host requirements, and the
  shortest user path. Its "Choose what to do next" table is the only
  documentation index and must link every page under `docs/`,
  `CONTRIBUTING.md`, and `SECURITY.md`.
- Pages are flat kebab-case Markdown files under `docs/`, hard-wrapped near
  80 columns, with one main purpose each. Page ownership:
  - `docs/cli.md`: every `bin/tokencrate` command and flag, one section per
    command in `bin/tokencrate help`, with every usage line verbatim; other
    pages link to it instead of restating flags.
  - `docs/models.md`: model sets, presets, reasoning effort, and the chat
    template.
  - `docs/agent-sets.md`: the shipped agent sets, the manifest keys, and
    upgrading a set.
  - `docs/agents.md`: agents, skills, the container's filesystem and mount
    limits, the first-request token costs, the cloud providers
    (`#cloud-providers`), and the browser UIs (`#browser-uis`).
  - `docs/privacy.md`: what leaves the machine, the telemetry switches, and
    the network layout with its limits (the forwarder rules and the Docker
    gateway mode).
  - `docs/configuration.md`: the storage layout and the retained
    agent-home directories, the pins in `pins.env` and the image names,
    the built-in chat UI defaults, when a setting takes effect, the
    upgrade procedure, and the dashboard (`#dashboard`). `.env.example` is
    the settings reference. `cloud-keys.env.example` is the keys-file
    template; its rules live on `docs/agents.md#cloud-providers`.
  - `docs/validation.md`: the validation procedures, the status (the
    claims table and the "Still unverified" list), the router behavior the
    wrapper relies on, and the dated records. Other pages link to
    `docs/validation.md#status` instead of restating status.
  - `docs/troubleshooting.md`: observed failures.
  - `SECURITY.md`: the scope statement, the reporting channel, and the
    credentials rule.
- The project has no glossary, no terminology register, and no changelog
  before the first tagged release; Git history records changes.
- Verification: `bash tests/static.sh` is the engine-free gate and
  `python3 tests/integration.py` runs the package against real containers;
  [Tests](CONTRIBUTING.md#tests) says what each covers. The gate checks
  links, anchors, the README index, and the usage lines; check the facts
  in the prose by hand against the implementation.

## Documentation review gate

Before you write, restructure, or review documentation, or change anything
user-visible, load the `documentation-guidelines` skill from
[SkillCrate](https://github.com/angelo-lesniak/skill-crate);
`CONTRIBUTING.md` says how to obtain it. Its `SKILL.md` is the workflow,
its `references/documentation-guidelines.md` the policy, and the section
above gives the repository facts the workflow asks for. A validation claim
needs a dated record in `docs/validation.md`.
