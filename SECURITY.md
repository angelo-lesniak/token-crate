# Security policy

TokenCrate is intended for a trusted single-user environment. It is not a
hardened multi-user service. [Coding agents and skills](docs/agents.md)
describes what an agent container can and cannot touch;
[Privacy and containment](docs/privacy.md) describes the network defaults
and their limits.

Use the repository's **Security → Report a vulnerability** action to open a
private GitHub security advisory. If that action is temporarily unavailable,
open a public issue containing no vulnerability details and ask a maintainer to
establish a private channel.

Never place credentials in shared `.env` files, presets, model-set or
skill-set manifests, agent-set directories (they are copied into the
image), image build arguments, logs, or reports.
