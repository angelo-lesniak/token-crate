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
  changing it, the synchronized pin locations, and the metadata for
  model-set, agent-set, and skill-set entries.
- `README.md` carries the product scope, the host requirements, and the
  shortest user path. Its "Choose what to do next" table is the
  documentation index: it must link every page under `docs/`,
  `CONTRIBUTING.md`, and `SECURITY.md`. There is no separate index page.
- Pages are flat kebab-case Markdown files under `docs/`, hard-wrapped near
  80 columns, with one main purpose each. `docs/cli.md` is the main source
  for every `bin/tokencrate` command and flag, with a section per command
  listed by `bin/tokencrate help` and every usage line of that help shown
  verbatim; other pages link to it instead of restating flags.
  `docs/models.md` owns model sets, presets, reasoning effort, and the chat
  template; `docs/agent-sets.md` owns the agent sets (the shipped ones,
  the manifest keys, upgrading one); `docs/agents.md` owns agents, skills,
  the filesystem and mount limits of the container, and the
  first-request token costs; `docs/privacy.md` owns what leaves the
  machine, the telemetry switches, and the network layout with its limits
  (the forwarder rules and the Docker gateway mode);
  `docs/troubleshooting.md` owns observed failures.
- `.env.example` is the settings reference. `docs/configuration.md` owns
  the storage layout with the retained agent-home directories and their
  tmpfs limits, the pins in `pins.env` with the image names, the built-in
  chat UI defaults, when a setting takes effect, and the one upgrade
  procedure.
- `docs/validation.md` holds the validation procedure, the only status text
  (a claims table with the evidence vocabulary: supported, expected,
  validated, unverified, and the list of what is still unverified), the
  router observations the wrapper relies on, and the dated records;
  other pages link to `docs/validation.md#status` instead of restating
  status.
- The project has no glossary and no terminology register.
- There is no changelog until the first tagged release; Git history is the
  record of changes.
- `SECURITY.md` holds the scope statement, the reporting channel, and the
  credentials rule.
- Verification: `bash tests/static.sh` is the engine-free gate for code,
  configuration, Compose, and documentation changes, and
  `python3 tests/integration.py` runs the package against real containers;
  `CONTRIBUTING.md` says what each runs and which changes need which. The
  gate checks links, anchors, the README index, and the usage lines; the
  facts in the prose are checked by hand against the implementation.

## Documentation review gate

Load the `documentation-guidelines` skill from
[SkillCrate](https://github.com/angelo-lesniak/skill-crate) from your own
skills directory before you write, restructure, or review documentation,
or change anything user-visible: behavior, commands, configuration,
defaults, setup, compatibility, security, privacy, or validation claims
(`CONTRIBUTING.md` says how each kind of agent obtains it). The skill's
`SKILL.md` is the workflow and its
`references/documentation-guidelines.md` the policy; the repository facts
the workflow asks for are the section above.

When changes are authorized, update the existing canonical page. During
review-only tasks, report missing, stale, conflicting, or misplaced
documentation instead of editing it. Do not require optional pages, generic
tutorials, speculative failure cases, or documentation added solely for
completeness. Do not present planned behavior as available or make
validation claims without a dated record.
