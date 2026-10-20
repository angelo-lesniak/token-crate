"""Terminal coding-agent sessions and the containment check.

Both start the container `session.plan` prepares; what differs is the
lifetime. `agent` runs one agent process in the foreground and the
container goes when it exits, while `smoke --agent` runs the check script
instead of the agent and reports what the container can reach. Browser
UIs, whose container outlives any one agent session, are in `uis`.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from . import presets
from .engine import Engine
from .env import Settings
from .session import plan, resolve_project_directory


def terminal_is_ours() -> bool:
    """Whether Compose may attach the terminal: both standard streams are
    one and this process runs in its foreground process group. A command
    under `timeout`, in cron, or in a pipeline is not, and an attach
    would stop it with SIGTTIN, silently."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        return os.tcgetpgrp(sys.stdin.fileno()) == os.getpgrp()
    except OSError:
        return False


def run_agent(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    project_dir: str,
    egress: bool,
    arguments: list[str],
    sets: str | None = None,
    cloud: bool = False,
) -> int:
    """One foreground session; its status is the agent's. The CLI has
    refused `cloud` for oh-my-pi before this. The pre-flight runs
    under the stack lock, so it never reads a stack `up`, `down`, or `ui`
    is changing; the build is content-addressed and the session is the
    user's, so neither holds it."""
    project = resolve_project_directory(settings, project_dir)
    with engine.lock("agent"):
        launch = plan(settings, engine, configuration, agent, preset, project, sets=sets, egress=egress, cloud=cloud)
    launch.build(engine)
    # Compose `run` replaces the image command, so name the agent binary
    # explicitly and append the user's arguments to it.
    name = f"tokencrate-agent-{secrets.token_hex(6)}"
    return launch.run(engine, name, command=(agent, *arguments), tty=terminal_is_ours()).returncode


def agent_check(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    *,
    ui_targets: str,
    sets: str | None = None,
    egress: bool = False,
) -> int:
    """Prove from inside an agent container that the model is reachable and
    that there is no route out, no browser-UI peer, and on Docker no gateway
    address on the agents network. The scratch project and agent home live
    in a temporary directory, removed after the container is stopped. The
    engine name, the gateway of the agents network, and the UI peers
    (`uis.peer_targets`) go in from here, because the container cannot
    tell a gateway from a peer. The check holds the stack lock while it
    runs: it is short, and a `down` meanwhile would turn into a finding.

    With `egress` the same container runs under the overlay, on the default
    network instead of the agents network: a route out is then the expected
    finding, the gateway probe does not apply, and what still must not be
    reachable is a browser UI, except one started with --egress or --cloud,
    which the report marks as reached by design. No provider key is passed
    either way, so the check never carries a credential."""
    # A real path: the retained mounts below it refuse a linked ancestor.
    scratch = Path(os.path.realpath(tempfile.mkdtemp(prefix="tokencrate-agent-check-")))
    try:
        (scratch / "project").mkdir()
        launch = plan(
            settings,
            engine,
            configuration,
            agent,
            preset,
            scratch / "project",
            sets=sets,
            egress=egress,
            home=scratch / "home",
        )
        launch.build(engine)
        gateway = "" if egress else engine.network_gateway("agents")
        with engine.lock("smoke --agent"):
            result = launch.run(
                engine,
                f"tokencrate-agent-check-{secrets.token_hex(6)}",
                "-e",
                f"TOKENCRATE_ENGINE={engine.name}",
                "-e",
                f"TOKENCRATE_AGENTS_GATEWAY={gateway}",
                "-e",
                f"TOKENCRATE_UI_TARGETS={ui_targets}",
                "-e",
                f"TOKENCRATE_EGRESS={'1' if egress else ''}",
                command=("/usr/local/bin/tokencrate-agent-check",),
                no_deps=True,
            )
        return result.returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
