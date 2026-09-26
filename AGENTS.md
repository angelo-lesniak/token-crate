# Agent guidance

## Guiding principle

**Code is a liability; less is more.** Prefer the smallest coherent
solution that satisfies the task and preserves the project's invariants.
Remove obsolete complexity when it is in scope and verified. Do not turn a
local task into an unrelated rewrite.

Documentation is maintained surface area too. Add information only when it
helps a named reader decide, act, verify, or recover.

## Know this repository

- The implementation is one Python package, `tokencrate/`, behind the shim
  `bin/tokencrate`; `CONTRIBUTING.md` lists its modules, the rules for
  changing it, the pin locations, and the metadata for model-set,
  agent-set, and skill-set entries.
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
    limits, and the first-request token costs.
  - `docs/privacy.md`: what leaves the machine, the telemetry switches, and
    the network layout with its limits (the forwarder rules and the Docker
    gateway mode).
  - `docs/configuration.md`: the storage layout with the retained
    agent-home directories and their tmpfs limits, the pins in `pins.env`
    with the image names, the built-in chat UI defaults, when a setting
    takes effect, and the upgrade procedure. `.env.example` is the settings
    reference.
  - `docs/validation.md`: the validation procedures, the only status text
    (the claims table with its evidence terms expected, validated, and
    unverified, and the "Still unverified" list), the router
    behavior the wrapper relies on, and the dated records. Other pages link
    to `docs/validation.md#status` instead of restating status.
  - `docs/troubleshooting.md`: observed failures.
  - `SECURITY.md`: the scope statement, the reporting channel, and the
    credentials rule.
- The project has no glossary, no terminology register, and no changelog
  before the first tagged release; Git history records changes.
- Verification: `bash tests/static.sh` is the engine-free gate for code,
  configuration, Compose, and documentation changes;
  `python3 tests/integration.py` runs the package against real containers.
  `CONTRIBUTING.md` says what each runs and which changes need which. The
  gate checks links, anchors, the README index, and the usage lines; check
  the facts in the prose by hand against the implementation.

## Documentation review gate

Before you write, restructure, or review documentation, or change anything
user-visible (behavior, commands, configuration, defaults, setup,
compatibility, security, privacy, or validation claims), load the
`documentation-guidelines` skill from
[SkillCrate](https://github.com/angelo-lesniak/skill-crate);
`CONTRIBUTING.md` says how to obtain it. Its `SKILL.md` is the workflow and
its `references/documentation-guidelines.md` the policy; the section above
gives the repository facts the workflow asks for.

When changes are authorized, update the existing canonical page. During
review-only tasks, report missing, stale, conflicting, or misplaced
documentation instead of editing it. Do not require optional pages, generic
tutorials, speculative failure cases, or documentation added solely for
completeness. Do not present planned behavior as available or make
validation claims without a dated record.
