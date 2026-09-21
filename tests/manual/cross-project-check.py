#!/usr/bin/env python3
"""Cross-project containment: what a second project's agent session can
reach while a browser UI serves another project.

A terminal session cannot run a shell command through `agent`, so this
starts the agent container the way the wrapper does and runs the image's
own check inside it, once without and once with the egress overlay. It
proves nothing by itself: read the two reports against the conditions in
docs/validation.md, which is also where the surrounding procedure (the
fixture preset, the running UI, and the cleanup) lives.

Usage, from the checkout with a UI already serving another project:

    .venv/bin/python tests/manual/cross-project-check.py <project> [preset]

The preset defaults to `ci-small`, the CPU fixture that procedure uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tokencrate import PROJECT_ROOT, agents, agentsets, engine, env, uis  # noqa: E402


def run(project: Path, preset: str) -> None:
    settings = env.load(PROJECT_ROOT)
    selected_engine = engine.detect(settings)
    home = agents.agent_home_directory(settings, "pi", project)
    home.mkdir(parents=True, exist_ok=True)
    agents.prepare_mountpoints(home, "pi")
    tag = agentsets.render(settings.root, settings.build_dir, agentsets.select(settings.root, "coding"))
    extra = {
        "LLM_AGENT_PROJECT_DIR": str(project),
        "TOKENCRATE_AGENT_HOME": str(home),
        "TOKENCRATE_PRESET": preset,
        "TOKENCRATE_AGENT_SETS_TAG": tag,
    }
    for egress in (False, True):
        print(f"\n===== project {project.name}, egress={egress}", flush=True)
        selected_engine.compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-e",
            f"TOKENCRATE_ENGINE={selected_engine.name}",
            "-e",
            f"TOKENCRATE_AGENTS_GATEWAY={selected_engine.network_gateway('agents')}",
            "-e",
            f"TOKENCRATE_UI_TARGETS={uis.peer_targets(selected_engine)}",
            "agent-pi",
            "/usr/local/bin/tokencrate-agent-check",
            profiles=("agent-pi",),
            egress=egress,
            check=False,
            **extra,
        )


def main() -> None:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        raise SystemExit(__doc__)
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        raise SystemExit(f"cross-project check: not a directory: {project}")
    run(project, sys.argv[2] if len(sys.argv) > 2 else "ci-small")


if __name__ == "__main__":
    main()
