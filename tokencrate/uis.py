"""Browser UIs: the launch and container ownership.

A UI container is not an agent. It runs a daemon that creates and destroys
agent sessions as the browser asks for them, so unlike a terminal session
it is detached, outlives any one conversation, is reachable on a published
loopback port through a forwarder, and has to be findable afterwards for
`ui stop` and `ui logs`. Both containers start with `compose run`, as a
terminal session does, under fixed names; the labels the Compose files
put on them, rather than launch-time shell variables, identify lifecycle
targets.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from . import TokenCrateError, agentsets, presets, runtime
from .engine import SERVICE_LABEL, Engine
from .env import SERVICE_HOST, Settings
from .localhttp import http_get
from .session import plan, resolve_project_directory, symlink_in_path

# The set a UI container belongs to, and on the UI container of a set
# started with --egress or --cloud, the mark the egress overlay sets.
UI_LABEL = "io.tokencrate.ui-set"
EGRESS_LABEL = "io.tokencrate.ui-egress"
# How long `ui` waits for the UI to answer on the published port.
UI_START_TIMEOUT = 90
# Where every UI container of a set finds the set's one shared directory.
UI_STATE_MOUNT = "/run/tokencrate/ui-state"


def container_names(name: str) -> tuple[str, str]:
    """The UI container and its forwarder; the first is the forwarder's
    target, so the name has to resolve on the `ui` network."""
    return f"tokencrate-ui-{name}", f"tokencrate-ui-forward-{name}"


def containers(engine: Engine, *, all_states: bool = True) -> list[dict]:
    return [item for item in engine.containers(all_states=all_states) if set_name(item)]


def set_name(container: dict) -> str:
    return (container.get("Config", {}).get("Labels") or {}).get(UI_LABEL, "")


def is_forwarder(container: dict) -> bool:
    return container["Config"]["Labels"].get(SERVICE_LABEL) == "ui-forward"


def environment(container: dict) -> dict[str, str]:
    return dict(value.split("=", 1) for value in container["Config"].get("Env") or [] if "=" in value)


def access(container: dict) -> str:
    """What a UI container was started with beyond the model: `cloud`,
    `egress`, or nothing."""
    if "TOKENCRATE_CLOUD" in environment(container):
        return "cloud"
    return "egress" if container["Config"]["Labels"].get(EGRESS_LABEL) else ""


def stop(engine: Engine, name: str = "") -> int:
    with engine.lock("ui stop"):
        owned = [item for item in containers(engine) if not name or set_name(item) == name]
        if name and not owned:
            raise TokenCrateError(f"no UI container found: {name}")
        engine.remove_containers(owned)
    if not owned:
        print("no browser UIs are running")
    else:
        for stopped in sorted({set_name(item) for item in owned}):
            print(f"Stopped UI {stopped}")
    return 0


def logs(engine: Engine, name: str = "") -> int:
    owned = containers(engine)
    if not name:
        names = sorted({set_name(item) for item in owned})
        if len(names) > 1:
            raise TokenCrateError("several UIs are present; name one: bash bin/tokencrate ui logs <set>")
        name = names[0] if names else ""
    matches = [item for item in owned if name and set_name(item) == name and not is_forwarder(item)]
    if not matches:
        raise TokenCrateError(f"no UI container found{': ' + name if name else ''}")
    return engine.command("logs", "--follow", matches[0]["Id"], check=False).returncode


def print_status(engine: Engine) -> None:
    """One line per UI set, from its UI container: a UI whose forwarder
    never started still holds its project, and with `--cloud` the keys."""
    owned = containers(engine)
    forwarders = {set_name(item): item for item in owned if is_forwarder(item)}
    for item in sorted(owned, key=set_name):
        if is_forwarder(item):
            continue
        forwarder = forwarders.get(set_name(item))
        if forwarder is None:
            listening = "forwarder missing"
        else:
            state = (forwarder.get("State") or {}).get("Status", "unknown")
            ports = (forwarder.get("NetworkSettings") or {}).get("Ports") or {}
            addresses = ", ".join(f"http://{e['HostIp']}:{e['HostPort']}/" for e in ports.get("8080/tcp") or [])
            listening = f"forwarder {state} {addresses}"
        project = environment(item).get("TOKENCRATE_PROJECT_DIR", "unknown")
        extra = access(item)
        print(f"UI {set_name(item)}: {listening} project={project}{' ' + extra if extra else ''}")


def peer_targets(engine: Engine) -> str:
    """Names and effective IP:port targets for terminal containment probes.
    The name of a UI started with --egress or --cloud, and its address on
    the default network, carry the prefix `egress:`: an egress session
    may resolve that name, but every TCP target must stay unreachable:
    the daemon binds only its `ui` address, and the forwarder is isolated."""
    targets = []
    default_network = f"{engine.settings.project_name}_default"
    for item in sorted(containers(engine, all_states=False), key=set_name):
        port = "8080" if is_forwarder(item) else environment(item).get("TOKENCRATE_UI_PORT", "")
        if not port:
            continue
        opted_in = EGRESS_LABEL in item["Config"]["Labels"]
        name = item["Name"].lstrip("/")
        targets.append(f"{'egress:' if opted_in else ''}{name}:{port}")
        for network, settings in (item.get("NetworkSettings", {}).get("Networks") or {}).items():
            if address := settings.get("IPAddress"):
                mark = "egress:" if opted_in and network == default_network else ""
                targets.append(f"{mark}{address}:{port}")
    return " ".join(targets)


# --- Launching a browser UI -------------------------------------------------


def ui_state_store(settings: Settings, ui_set: str) -> Path:
    """One directory per UI set, next to the agent homes, mounted read-write
    at UI_STATE_MOUNT into the set's UI container of every project: what a
    UI keeps once rather than per project. Paseo's launcher keeps its
    daemon identity there (the browser tells daemons apart by it); PI WEB
    ignores the directory. The copies run inside the container, where the
    agent owns both sides, so the host side only has to be a real path."""
    store = settings.agents_dir / "pi" / f"{ui_set}-state"
    if link := symlink_in_path(store):
        raise TokenCrateError(f"{link} is a symbolic link; the agent home must contain real paths (move it aside)")
    store.mkdir(parents=True, exist_ok=True)
    store.chmod(0o700)
    return store


def ui_entry(settings: Settings, ui_set: str) -> agentsets.AgentSet:
    """The named set, which must declare a `[ui]` table."""
    entry = agentsets.load_set(settings.root, ui_set)
    if entry.ui is None:
        raise TokenCrateError(f"agent set {ui_set} is not a UI set (no [ui] table in its manifest)")
    return entry


def host_port(entry: agentsets.AgentSet, requested: str) -> str:
    """The loopback port the forwarder publishes: `--port` for this launch
    (validated by the flag), else the `host_port` the manifest declares."""
    if requested:
        return requested
    if entry.ui.host_port is None:
        raise TokenCrateError(f"UI set {entry.name} declares no host_port; pass --port")
    return str(entry.ui.host_port)


def wait_for_ui(engine: Engine, ui_set: str, port: str, timeout: int) -> None:
    """Readiness needs both owned containers alive and a forwarded response."""
    url = f"http://{SERVICE_HOST}:{port}"
    hint = f"Check: bash bin/tokencrate ui logs {ui_set}"
    stopped: list[str] = []

    def state() -> str:
        for name in container_names(ui_set):
            state = engine.container_state(name)
            if state in runtime.STOPPED_STATES:
                stopped.append(name)
                return state
        return "running"

    try:
        for _ in runtime.poll(
            state,
            timeout,
            stopped=f"the container <name> is {{state}} before it answered. {hint}",
            timed_out=f"{ui_set} did not answer at {url}/ within {timeout}s. {hint}",
        ):
            if http_get(f"{url}/") is not None:
                return
    except TokenCrateError as error:
        # The message names the container that stopped, so the logs hint
        # points at the right one.
        raise TokenCrateError(str(error).replace("<name>", stopped[0] if stopped else ui_set)) from None


def start(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    ui_set: str,
    preset: str,
    project_dir: str,
    sets: str | None = None,
    port: str = "",
    egress: bool = False,
    cloud: bool = False,
) -> int:
    """Start or replace only the named UI; keep the model and sibling UIs.
    `egress` and `cloud` mean what they mean for a terminal session
    (`agents.run_agent`), for the UI container alone: the forwarder gets
    neither the route out nor the keys. The stack lock covers the
    replacement (the removal and both starts), not the image build or
    the readiness wait."""
    entry = ui_entry(settings, ui_set)
    port = host_port(entry, port)
    resolved = resolve_project_directory(settings, project_dir)
    ui_name, forward_name = container_names(ui_set)
    engine.require_port(forward_name, port)
    launch = plan(
        settings, engine, configuration, "pi", preset, resolved, sets=sets, ui=entry, egress=egress, cloud=cloud
    )
    # The launcher's variables: the set's name (the label of both
    # containers and the forwarder's target), command, container port,
    # and state directory, and the forwarder's host port.
    launch = dataclasses.replace(
        launch,
        variables={
            **launch.variables,
            "TOKENCRATE_UI_SET": ui_set,
            "TOKENCRATE_UI_COMMAND": entry.ui.command,
            "TOKENCRATE_UI_PORT": str(entry.ui.port),
            "TOKENCRATE_UI_STATE": entry.ui.state,
            "TOKENCRATE_UI_HOST_PORT": port,
        },
    )
    # A build failure leaves the running pair untouched.
    launch.build(engine)
    store = ui_state_store(settings, ui_set)
    with engine.lock("ui"):
        engine.require_port(forward_name, port)
        # A replace: the set's own pair goes, nothing else. --no-deps keeps
        # Compose from touching llama or another UI. A failed target stays
        # for logs/retry/stop.
        # The names are not project-scoped: one held by another checkout's
        # UI would fail the `run`, whose unwind would then stop that UI.
        for name in (ui_name, forward_name):
            if engine.foreign_container(name):
                raise TokenCrateError(
                    f"the container {name} belongs to another checkout's UI; "
                    f"free it there with: bash bin/tokencrate ui stop {ui_set}"
                )
        engine.remove_containers([item for item in containers(engine) if set_name(item) == ui_set])
        launch.run(engine, ui_name, "-v", f"{store}:{UI_STATE_MOUNT}", detach=True, no_deps=True)
        # The forwarder is not an agent container: no keys, no overlay.
        engine.compose(
            "run",
            "--detach",
            "--no-deps",
            "-T",
            "--service-ports",
            "--name",
            forward_name,
            "ui-forward",
            profiles=("ui",),
            **launch.variables,
        )
    wait_for_ui(engine, ui_set, port, UI_START_TIMEOUT)
    print(f"{ui_set} is ready at http://{SERVICE_HOST}:{port}/ for {resolved}")
    print(
        f"Follow its output with: bash bin/tokencrate ui logs {ui_set}; "
        f"stop it with: bash bin/tokencrate ui stop {ui_set}"
    )
    return 0
