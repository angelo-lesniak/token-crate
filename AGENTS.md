# Agent guidance

## Guiding principle

Less is more. Prefer the smallest coherent solution that satisfies the
task and preserves the project's invariants. Remove obsolete complexity
when it is in scope and verified. Do not turn a local task into an
unrelated rewrite. Documentation is maintained surface area too: add
information only when it helps a named reader decide, act, verify, or
recover.

Every fact has one source of truth, and the code is the source for what
the code does: syntax lives in the usage text, settings and defaults in
`.env.example`, pins in `pins.env`, set contents in the manifests. A page
links to the source instead of restating it, with the owner map below as
the only exceptions, and never explains what a module does when reading
it shows that. A page holds the glue no single file shows: what a user
needs first, and where the deep dive is.

## Know this repository

- [Layout](CONTRIBUTING.md#layout) lists the modules and the rules for
  changing them; [Tests](CONTRIBUTING.md#tests) says what the static gate
  and the integration check cover; [Documentation
  changes](CONTRIBUTING.md#documentation-changes) says what the gate
  checks in the prose. Check every other fact by hand against the
  implementation.
- Page ownership, where an agent would otherwise put a fact twice:
  - `docs/cli.md` holds every command and flag; other pages link to it
    instead of restating flags.
  - `docs/privacy.md` holds the network layout and its limits, the
    forwarder rules and the Docker gateway mode included.
  - `docs/configuration.md` holds storage, pins, and the dashboard;
    `.env.example` is the settings reference.
  - `docs/agents.md#cloud-providers` holds the keys-file rules;
    `cloud-keys.env.example` is only the template.
  - `docs/validation.md#status` is the only statement of what is
    validated; a validated claim needs a date there. Findings go to the
    page that owns the fact.
  - `docs/troubleshooting.md` holds observed failures, one section each.
- The project has no glossary, no terminology register, and no changelog
  before the first tagged release; Git history records changes.

## Code

- Read the module you change before writing, and follow its names,
  error style, and structure, even where you would have chosen
  otherwise. New terms come from the page that owns the topic.
- A refusal is one sentence that names the cause and the remedy, like
  the existing ones.
- No abstraction for one caller, no option nobody asked for, no
  compatibility shim: the package has one consumer, this repository.
- A comment says why, or names the evidence behind a choice that is
  not obvious; it never restates the code.
- A change describes the new behavior only: no comment, docstring,
  test, or page says what the code did before. A choice a reviewer
  might overturn gets its reason once, in one sentence, where the
  choice is made.
- Delete what a change makes unused, tests and documentation included.
- A behavior change arrives with its test in the gate and its line on
  the owner page, in the same change.

## Documentation review gate

Before you write, restructure, or review documentation, or change anything
user-visible, load the `documentation-guidelines` skill from
[SkillCrate](https://github.com/angelo-lesniak/skill-crate);
`CONTRIBUTING.md` says how to obtain it. Its `SKILL.md` is the workflow,
its `references/documentation-guidelines.md` the policy, and the section
above gives the repository facts the workflow asks for.
