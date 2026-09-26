"""Browser UIs: the launch, the identity a daemon keeps, and container
ownership.

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

import os
import stat
from pathlib import Path

from . import TokenCrateError, agentsets, presets, runtime
from .engine import SERVICE_LABEL, Engine
from .env import SERVICE_HOST, Settings
from .localhttp import http_get
from .session import (
    agent_home_directory,
    chosen_preset,
    cloud_keys_file,
    prepare,
    resolve_project_directory,
    run_arguments,
    selected_sets,
    symlink_in_path,
    warn_about,
)

# The set a UI container belongs to, and on the UI container of a set
# started with --egress or --cloud, the mark the egress overlay sets.
UI_LABEL = "io.tokencrate.ui-set"
EGRESS_LABEL = "io.tokencrate.ui-egress"
# How long `ui` waits for the UI to answer on the published port.
UI_START_TIMEOUT = 90
IDENTITY_FILE_LIMIT = 64 * 1024


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
    with engine.lock():
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
    reaching those is the documented consequence of the flag, while its
    address on the `ui` network and its forwarder must stay unreachable."""
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


def ui_identity_store(settings: Settings, ui_set: str) -> Path:
    """Where one identity per UI set is kept, next to the agent homes."""
    return settings.agents_dir / "pi" / f"{ui_set}-identity"


def _plain_file_path(root: Path, relative: str) -> Path | None:
    """`root/relative` when no symbolic link takes part in it; None otherwise.
    The agent writes its home, so a link there could point the copy at a
    file of the host or of another project."""
    path = root / relative
    if symlink_in_path(path) is not None:
        return None
    return path


def _copy_identity_file(source: Path, target: Path) -> None:
    """Copy through one descriptor. The UI container writes its retained
    directory while the harvest runs, so the file is checked and read as
    the same object: a link or a pipe put in its place is refused rather
    than resolved on the host, and no more than the limit is read."""
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise TokenCrateError(f"identity file is not a regular file: {source}")
        data = handle.read(IDENTITY_FILE_LIMIT + 1)
    if len(data) > IDENTITY_FILE_LIMIT:
        raise TokenCrateError(f"identity file is larger than expected: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _copy_ui_identity(source_root: Path, target_root: Path, entry: agentsets.AgentSet) -> None:
    """Copy the set's identity files that the target does not have yet."""
    for relative in entry.ui["identity"] if entry.ui else ():
        source = _plain_file_path(source_root, relative)
        target = _plain_file_path(target_root, relative)
        if source is not None and source.is_file() and target is not None and not target.exists():
            _copy_identity_file(source, target)


def seed_ui_identity(settings: Settings, home: Path, entry: agentsets.AgentSet) -> None:
    """Copy the UI set's stored identity into a project's agent home that
    has none yet. Paseo's web client tells daemons apart by the identity
    (keypair and server id) a daemon keeps in its home and treats another
    identity at the address it knows as a host it cannot reach: it
    reconnects forever. Every project has its own agent home, so the
    wrapper keeps one identity per UI set and hands it to every project;
    the browser then sees one host whose project changes."""
    _copy_ui_identity(ui_identity_store(settings, entry.name), home, entry)


def harvest_ui_identity(settings: Settings, home: Path, entry: agentsets.AgentSet) -> None:
    """After the first start of a UI set, keep the identity its daemon
    created so later projects start with the same one."""
    _copy_ui_identity(home, ui_identity_store(settings, entry.name), entry)


def ui_selection(
    settings: Settings, sets: str | None, ui_set: str
) -> tuple[list[agentsets.AgentSet], agentsets.AgentSet]:
    """The selection of a UI session: LLM_AGENT_SETS (or --sets) plus the
    named UI set, which must declare a `[ui]` table."""
    selected = selected_sets(settings, sets)
    entry = next((item for item in selected if item.name == ui_set), None) or agentsets.load_set(settings.root, ui_set)
    if entry.ui is None:
        raise TokenCrateError(f"agent set {ui_set} is not a UI set (no [ui] table in its manifest)")
    if all(item.name != ui_set for item in selected):
        selected.append(entry)
    return selected, entry


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
    use_cloud: bool = False,
) -> int:
    """Start or replace only the named UI; keep the model and sibling UIs.
    `egress` and `use_cloud` mean what they mean for a terminal session
    (`agents.run_agent`), for the UI container alone: the forwarder gets
    neither the route out nor the keys."""
    selected, entry = ui_selection(settings, sets, ui_set)
    port = settings.ui_port(ui_set, port, entry.ui["host_port"])
    resolved = resolve_project_directory(settings, project_dir)
    keys = cloud_keys_file(settings, resolved) if use_cloud else None
    egress = egress or use_cloud
    preset = chosen_preset(settings, preset)
    home = agent_home_directory(settings, "pi", resolved)
    ui_name, forward_name = container_names(ui_set)
    with engine.lock():
        engine.require_port(forward_name, port)
        variables = prepare(settings, engine, configuration, "pi", preset, resolved, home, selected=selected, ui=entry)
        # The launcher's variables: the set's name (the label of both
        # containers and the forwarder's target), command, container port,
        # and state directory, and the forwarder's host port.
        variables.update(
            TOKENCRATE_UI_SET=ui_set,
            TOKENCRATE_UI_COMMAND=entry.ui["command"],
            TOKENCRATE_UI_PORT=str(entry.ui["port"]),
            TOKENCRATE_UI_STATE=entry.ui["state"],
            TOKENCRATE_UI_HOST_PORT=port,
        )
        warn_about(egress, keys)
        # A build failure leaves the running pair untouched.
        engine.compose("build", "agent-ui", profiles=("ui",), **variables)
        engine.require_port(forward_name, port)
        seed_ui_identity(settings, home, entry)
        # A replace: the set's own pair goes, nothing else. --no-deps keeps
        # Compose from touching llama or another UI. A failed target stays
        # for logs/retry/stop.
        engine.remove_containers([item for item in containers(engine) if set_name(item) == ui_set])
        engine.compose(
            "run",
            "--detach",
            "--no-deps",
            "-T",
            "--name",
            ui_name,
            *run_arguments(keys),
            "agent-ui",
            profiles=("ui",),
            egress=egress,
            **variables,
        )
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
            **variables,
        )
        wait_for_ui(engine, ui_set, port, UI_START_TIMEOUT)
        harvest_ui_identity(settings, home, entry)
    print(f"{ui_set} is ready at http://{SERVICE_HOST}:{port}/ for {resolved}")
    print(
        f"Follow its output with: bash bin/tokencrate ui logs {ui_set}; "
        f"stop it with: bash bin/tokencrate ui stop {ui_set}"
    )
    return 0
