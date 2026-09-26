"""Terminal coding-agent sessions and the containment check.

Both start the container `session.prepare` sets up; what differs is the
lifetime. `agent` runs one agent process in the foreground and the
container goes when it exits, while `smoke --agent` runs the check script
instead of the agent and reports what the container can reach. Browser
UIs, whose container outlives any one agent session, are in `uis`.
"""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from . import presets, uis
from .engine import Engine
from .env import Settings
from .session import (
    agent_home_directory,
    chosen_preset,
    cloud_keys_file,
    prepare,
    resolve_project_directory,
    run_arguments,
    selected_sets,
    warn_about,
)


def stop_session(engine: Engine, name: str) -> None:
    """Stop the named session container; `--rm` then removes it. The Compose
    client is gone with the wrapper's exception, but the provider it started
    may still be creating the container, so the name is tried again for a
    few seconds."""
    deadline = time.monotonic() + 5
    while engine.command("stop", "--time", "5", name, capture=True, check=False).returncode:
        if time.monotonic() >= deadline:
            return
        time.sleep(0.5)


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
    use_cloud: bool = False,
) -> int:
    """With `use_cloud` the session also gets the cloud keys file, which
    needs the route out, so it implies `egress`; `egress` alone mounts no
    keys. The CLI has refused `use_cloud` for oh-my-pi before this."""
    resolved = resolve_project_directory(settings, project_dir)
    # The keys file is checked before the preset and the pre-flight, which
    # all cost something.
    keys = cloud_keys_file(settings, resolved) if use_cloud else None
    egress = egress or use_cloud
    preset = chosen_preset(settings, preset)
    home = agent_home_directory(settings, agent, resolved)
    service = f"agent-{agent}"
    selected = selected_sets(settings, sets) if agent == "pi" else None
    variables = prepare(settings, engine, configuration, agent, preset, resolved, home, selected=selected)
    warn_about(egress, keys)
    # The overlay only changes networks, so a build never needs it.
    engine.compose("build", service, profiles=(service,), **variables)
    # Compose `run` replaces the image command, so name the agent binary
    # explicitly and append the user's arguments to it. The container is
    # named, because a hang-up or termination of the wrapper ends the
    # Compose client and not the session.
    name = f"tokencrate-agent-{secrets.token_hex(6)}"
    try:
        result = engine.compose(
            "run",
            "--rm",
            "--name",
            name,
            *run_arguments(keys),
            service,
            agent,
            *arguments,
            profiles=(service,),
            egress=egress,
            check=False,
            **variables,
        )
    except BaseException:
        stop_session(engine, name)
        raise
    return result.returncode


def agent_check(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    sets: str | None = None,
    egress: bool = False,
) -> int:
    """Prove from inside an agent container that the model is reachable and
    that there is no route out, no browser-UI peer, and on Docker no gateway
    address on the agents network. The scratch project and agent home live
    in a temporary directory. The engine name and the gateway of the agents
    network go in from here, because the container cannot tell a gateway
    from a peer.

    With `egress` the same container runs under the overlay, on the default
    network instead of the agents network: a route out is then the expected
    finding, the gateway probe does not apply, and what still must not be
    reachable is a browser UI, except one started with --egress or --cloud,
    which the report marks as reached by design. No provider key is passed
    either way, so the check never carries a credential."""
    preset = chosen_preset(settings, preset)
    # A real path: the retained mounts below it refuse a linked ancestor.
    scratch = Path(os.path.realpath(tempfile.mkdtemp(prefix="tokencrate-agent-check-")))
    service = f"agent-{agent}"
    try:
        (scratch / "project").mkdir()
        selected = selected_sets(settings, sets) if agent == "pi" else None
        variables = prepare(
            settings, engine, configuration, agent, preset, scratch / "project", scratch / "home", selected=selected
        )
        engine.compose("build", service, profiles=(service,), **variables)
        gateway = "" if egress else engine.network_gateway("agents")
        result = engine.compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-e",
            f"TOKENCRATE_ENGINE={engine.name}",
            "-e",
            f"TOKENCRATE_AGENTS_GATEWAY={gateway}",
            "-e",
            f"TOKENCRATE_UI_TARGETS={uis.peer_targets(engine)}",
            "-e",
            f"TOKENCRATE_EGRESS={'1' if egress else ''}",
            service,
            "/usr/local/bin/tokencrate-agent-check",
            profiles=(service,),
            egress=egress,
            check=False,
            **variables,
        )
        return result.returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
