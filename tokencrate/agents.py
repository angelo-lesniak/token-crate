"""Coding-agent sessions: the project directory, the per-project agent home,
the pre-flight checks, and the Compose invocation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from . import TokenCrateError, agentsets, presets, runtime, skills, uis, warn
from .engine import Engine
from .env import SERVICE_HOST, Settings
from .names import preset_file

AGENTS = ("pi", "omp")
# Refused in cli.dispatch before the pre-flight and again at the render,
# so the two cannot word it differently.
SETS_ARE_PI_ONLY = "--sets applies to pi only; oh-my-pi has no agent sets"
HOME_IN_CONTAINER = "/home/agent"
# The home is a per-container tmpfs; these are the only home paths bound
# from the host, read-write. OMP externalizes transcript images to blobs;
# its other two directories retain --continue selection and references to
# custom transcript files for storage GC. Paths are relative to the home.
PERSISTENT_DIRECTORIES = {
    "pi": (".pi/agent/sessions",),
    "omp": tuple(f".omp/agent/{name}" for name in ("sessions", "blobs", "terminal-sessions", "custom-session-files")),
}
UI_DIRECTORIES = agentsets.UI_DIRECTORIES
# How long `ui` waits for the UI to answer on the published port.
UI_START_TIMEOUT = 90
UNSAFE_PATH_CHARACTERS = set(" \t\n,:$\"'")


def resolve_project_directory(settings: Settings, requested: str) -> Path:
    """The project directory is mounted at the same absolute path inside the
    container, so file paths in agent output match the host. It must be a real
    directory below the user's home or an explicitly allowed root."""
    if not os.path.isdir(requested):
        raise TokenCrateError(
            f"project directory does not exist: {requested} (create it first; --dir mounts an existing directory)"
        )
    resolved = Path(os.path.realpath(requested))
    home_value = settings.environ.get("HOME", "")
    home = Path(os.path.realpath(home_value)) if home_value else None
    if resolved == Path("/"):
        raise TokenCrateError("refusing to mount the root filesystem as a project")
    if home is not None and resolved == home:
        raise TokenCrateError(
            "refusing to mount your whole home directory as a project; choose a project directory below it"
        )
    if UNSAFE_PATH_CHARACTERS & set(str(resolved)):
        raise TokenCrateError(f"project path contains characters that Compose mounts cannot express safely: {resolved}")
    # The checkout (with .env) and the storage directories are what the next
    # start trusts; a project must not contain them or lie inside them.
    for label, path in (
        ("the TokenCrate checkout", settings.root),
        ("the models directory", settings.models_dir),
        ("the agents directory", settings.agents_dir),
        ("the skills directory", settings.skills_dir),
        ("the private skills directory", settings.local_skills_dir),
    ):
        protected = Path(os.path.realpath(path))
        if resolved.is_relative_to(protected) or protected.is_relative_to(resolved):
            raise TokenCrateError(
                f"refusing a project that contains or lies inside {label}: {protected} "
                "(the project is the working directory unless --dir names one)"
            )
    roots: list[Path] = [home] if home is not None else []
    for entry in settings.get("LLM_PROJECT_ROOTS").split(":"):
        if not entry:
            continue
        if not entry.startswith("/"):
            raise TokenCrateError(f"LLM_PROJECT_ROOTS entries must be absolute paths: {entry}")
        if os.path.isdir(entry):
            roots.append(Path(os.path.realpath(entry)))
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise TokenCrateError(f"project directory is outside your home directory and LLM_PROJECT_ROOTS: {resolved}")
    # Linked worktrees, selected submodules and repository subdirectories
    # can depend on Git metadata outside the one project mount.
    for directory in (resolved, *resolved.parents):
        git_dir = directory / ".git"
        if git_dir.is_file():
            text = git_dir.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir: "):
                raise TokenCrateError(f"invalid Git directory reference: {git_dir}")
            git_dir = directory / text.removeprefix("gitdir: ")
        elif not (git_dir / "HEAD").is_file():
            continue
        git_dir = git_dir.resolve()
        common = git_dir / "commondir"
        common_dir = (git_dir / common.read_text(encoding="utf-8").strip()).resolve() if common.is_file() else git_dir
        if not all(path.is_relative_to(resolved) for path in (git_dir, common_dir)):
            raise TokenCrateError(
                "Git metadata lies outside the project mount; choose the repository root "
                "or a standalone clone instead of a linked worktree or submodule"
            )
        break
    parts = resolved.parts
    if len(parts) > 3 and parts[1] == "mnt" and len(parts[2]) == 1 and parts[2].isalpha():
        warn(
            f"{resolved} is on a Windows drive mount; expect slow file access, foreign ownership, and CRLF line endings"
        )
    return resolved


def agent_home_directory(settings: Settings, agent: str, project_dir: Path) -> Path:
    """One host state directory per agent and project; only the selected
    transcript and UI subdirectories are mounted into containers."""
    digest = hashlib.sha256(str(project_dir).encode()).hexdigest()[:12]
    return settings.agents_dir / agent / f"{project_dir.name}-{digest}"


def require_skill_sets(settings: Settings) -> None:
    """Every set named in LLM_SKILL_SETS must be known, fetched, and complete."""
    names = [name for name in settings.get("LLM_SKILL_SETS").split(",") if name]
    if not names:
        return
    hosts = skills.load_allowed_hosts(settings.config_dir / "skill-sets" / "allowed-git-hosts.txt")
    catalog = skills.available_sets(settings.config_dir / "skill-sets", hosts)
    for name in names:
        if name not in catalog:
            raise TokenCrateError(f"unknown skill-set: {name} (run: bash bin/tokencrate skills list)")
        if not (settings.skills_dir / name).is_dir():
            raise TokenCrateError(f"skill set {name} is not fetched; run: bash bin/tokencrate skills fetch {name}")
        missing = skills.missing_skills(catalog[name], settings.skills_dir)
        if missing:
            raise TokenCrateError(
                f"skill set {name} is incomplete (missing: {', '.join(missing)}); "
                f"run: bash bin/tokencrate skills fetch {name}"
            )


def require_session_ready(
    settings: Settings, engine: Engine, configuration: presets.Configuration, preset: str
) -> None:
    """What every agent container needs before it starts: a preset the running
    llama service knows, every set in LLM_SKILL_SETS fetched (the entrypoint
    refuses to start otherwise), the llama service itself, and internal
    networks that carry no host address."""
    preset_file(settings.config_dir, preset)
    if preset not in presets.rendered_model_ids(settings.build_dir):
        wait = configuration.wait(preset)
        if wait:
            raise presets.wait_error(preset, wait)
        raise TokenCrateError(
            f"preset {preset} is not rendered as loadable; fetch its model set "
            f"(bash bin/tokencrate models fetch {configuration.find(preset).model_set}) "
            "and run: bash bin/tokencrate up"
        )
    require_skill_sets(settings)
    container_id = engine.running_llama_id()
    digest = engine.command(
        "inspect", "--format", '{{index .Config.Labels "io.tokencrate.config-sha256"}}', container_id, capture=True
    ).stdout.strip()
    if digest != runtime.config_digest(settings):
        raise TokenCrateError(
            "the running llama configuration differs from the rendered files; run: bash bin/tokencrate up"
        )
    runtime.require_isolated_networks(engine)


def chosen_preset(settings: Settings, preset: str, hint: str) -> str:
    preset = preset or settings.default_preset
    if not preset:
        raise TokenCrateError(hint)
    return preset


def _symlink_in_path(path: Path) -> Path | None:
    return next((part for part in (*reversed(path.parents), path) if part.is_symlink()), None)


def persistent_directories(agent: str, *, ui: bool = False) -> tuple[str, ...]:
    return PERSISTENT_DIRECTORIES[agent] + (UI_DIRECTORIES if ui else ())


def home_tmpfs_directories(agent: str) -> set[str]:
    """Every ancestor of a retained bind needs a writable, owned tmpfs of
    its own (the home root among them, as "."). The engines otherwise
    create root-owned ancestors for nested mounts."""
    return {str(parent) for relative in PERSISTENT_DIRECTORIES[agent] for parent in Path(relative).parents}


def prepare_mountpoints(home: Path, agent: str, *, ui: bool = False) -> None:
    """Create the retained bind sources as the caller, without following
    links; nothing else in the host home is mounted or touched."""
    for relative in persistent_directories(agent, ui=ui):
        path = home / relative
        if link := _symlink_in_path(path):
            raise TokenCrateError(f"{link} is a symbolic link; the agent home must contain real paths (move it aside)")
        if path.exists() and not path.is_dir():
            raise TokenCrateError(f"{path} is not a directory; move it aside")
        path.mkdir(parents=True, exist_ok=True)


def prepare_session(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    project: Path,
    home: Path,
    *,
    ui: bool = False,
) -> dict[str, str]:
    """The pre-flight every session shares (a preset the running service
    knows, the skill sets, the llama service), the directories the mounts
    need, and the Compose variables of the session."""
    require_session_ready(settings, engine, configuration, preset)
    prepare_mountpoints(home, agent, ui=ui)
    settings.local_skills_dir.mkdir(parents=True, exist_ok=True)
    return {"LLM_AGENT_PROJECT_DIR": str(project), "TOKENCRATE_AGENT_HOME": str(home), "TOKENCRATE_PRESET": preset}


def selected_sets(settings: Settings, sets: str | None) -> list[agentsets.AgentSet]:
    return agentsets.select(settings.root, settings.get("LLM_AGENT_SETS") if sets is None else sets)


def render_image(settings: Settings, agent: str, sets: str | None) -> dict[str, str]:
    """The pi image is rendered from the selected agent sets; its tag names
    the selection. oh-my-pi has no sets."""
    if agent != "pi":
        if sets is not None:
            raise TokenCrateError(SETS_ARE_PI_ONLY)
        return {}
    selected = selected_sets(settings, sets)
    tag = agentsets.render(settings.root, settings.build_dir, selected)
    names = ", ".join(entry.name for entry in selected) or "none"
    print(f"Agent sets: {names} (image tag suffix {tag}).")
    return {"TOKENCRATE_AGENT_SETS_TAG": tag}


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
) -> int:
    resolved = resolve_project_directory(settings, project_dir)
    preset = chosen_preset(settings, preset, "no preset selected; set LLM_DEFAULT_PRESET in .env or pass --preset")
    home = agent_home_directory(settings, agent, resolved)
    extra = prepare_session(settings, engine, configuration, agent, preset, resolved, home)
    extra.update(render_image(settings, agent, sets))
    if egress:
        warn("this agent session has internet access (egress enabled).")
    service = f"agent-{agent}"
    engine.compose("build", service, profiles=(service,), egress=egress, **extra)
    # Compose `run` replaces the image command, so name the agent binary
    # explicitly and append the user's arguments to it.
    result = engine.compose(
        "run", "--rm", service, agent, *arguments, profiles=(service,), egress=egress, check=False, **extra
    )
    return result.returncode


def agent_check(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    sets: str | None = None,
) -> int:
    """Prove from inside an agent container that the model is reachable and
    that there is no route out, no browser-UI peer, and no host address on
    the bridge. The scratch project and agent home live in a temporary
    directory. The engine name and the gateway of the agents network go in
    from here, because the container cannot tell a gateway from a peer."""
    preset = chosen_preset(settings, preset, "smoke --agent needs --preset or LLM_DEFAULT_PRESET")
    scratch = Path(tempfile.mkdtemp(prefix="tokencrate-agent-check-"))
    try:
        (scratch / "project").mkdir()
        extra = prepare_session(settings, engine, configuration, agent, preset, scratch / "project", scratch / "home")
        extra.update(render_image(settings, agent, sets))
        service = f"agent-{agent}"
        engine.compose("build", service, profiles=(service,), **extra)
        result = engine.compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-e",
            f"TOKENCRATE_ENGINE={engine.name}",
            "-e",
            f"TOKENCRATE_AGENTS_GATEWAY={engine.network_gateway('agents')}",
            "-e",
            f"TOKENCRATE_UI_TARGETS={uis.peer_targets(engine)}",
            service,
            "/usr/local/bin/tokencrate-agent-check",
            profiles=(service,),
            check=False,
            **extra,
        )
        return result.returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# --- Browser UIs -------------------------------------------------------------


IDENTITY_FILE_LIMIT = 64 * 1024


def ui_identity_store(settings: Settings, ui_set: str) -> Path:
    """Where one identity per UI set is kept, next to the agent homes."""
    return settings.agents_dir / "pi" / f"{ui_set}-identity"


def _plain_file_path(root: Path, relative: str) -> Path | None:
    """`root/relative` when no symbolic link takes part in it; None otherwise.
    The agent writes its home, so a link there could point the copy at a
    file of the host or of another project."""
    path = root / relative
    if _symlink_in_path(path) is not None:
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


def wait_for_ui(engine: Engine, ui_set: str, port: str, timeout: int, **poll_options) -> None:
    """Readiness needs both owned containers alive and a forwarded response."""
    url = f"http://{SERVICE_HOST}:{port}"

    def state() -> str:
        for service in uis.services(ui_set):
            ids = engine.container_ids(service, all_states=True)
            state = engine.container_state(ids[0]) if ids else "removed"
            if state in runtime.STOPPED_STATES:
                return state
        return "running"

    for _ in runtime.poll(
        state,
        timeout,
        stopped=f"the {ui_set} container is {{state}} before it answered. Check: bash bin/tokencrate ui logs {ui_set}",
        timed_out=f"{ui_set} did not answer at {url}/ within {timeout}s. Check: bash bin/tokencrate ui logs {ui_set}",
        **poll_options,
    ):
        if runtime.http_get(f"{url}/") is not None:
            return


def run_ui(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    ui_set: str,
    preset: str,
    project_dir: str,
    sets: str | None = None,
    port: str = "",
    **wait_options,
) -> int:
    """Start or replace only the named UI; keep the model and sibling UIs."""
    resolved = resolve_project_directory(settings, project_dir)
    preset = chosen_preset(settings, preset, "no preset selected; set LLM_DEFAULT_PRESET in .env or pass --preset")
    selected, entry = ui_selection(settings, sets, ui_set)
    port = settings.ui_port(ui_set, port)
    home = agent_home_directory(settings, "pi", resolved)
    with engine.lock():
        engine.require_port(uis.services(ui_set)[1], port)
        extra = prepare_session(settings, engine, configuration, "pi", preset, resolved, home, ui=True)
        tag = agentsets.render(settings.root, settings.build_dir, selected)
        print(f"Agent sets: {', '.join(item.name for item in selected)} (image tag suffix {tag}).", flush=True)
        extra.update(
            TOKENCRATE_AGENT_SETS_TAG=tag,
            TOKENCRATE_UI_COMMAND=entry.ui["command"],
            TOKENCRATE_UI_PORT=str(entry.ui["port"]),
            TOKENCRATE_UI_HOST_PORT=port,
            TOKENCRATE_UI_SERVICE=uis.services(ui_set)[0],
        )
        with uis.snapshot(engine, ui_set, extra) as candidate:
            # A build failure leaves the running pair untouched.
            engine.compose("build", uis.services(ui_set)[0], profiles=("ui",), files_extra=(candidate,))
            engine.require_port(uis.services(ui_set)[1], port)
            seed_ui_identity(settings, home, entry)
            # --no-deps prevents Compose from touching llama or another UI.
            # Keep a failed target for logs/retry/stop; never clean sibling resources.
            engine.compose(
                "up",
                "--no-build",
                "--detach",
                "--no-deps",
                *uis.services(ui_set),
                profiles=("ui",),
                files_extra=(candidate,),
            )
            wait_for_ui(engine, ui_set, port, UI_START_TIMEOUT, **wait_options)
            harvest_ui_identity(settings, home, entry)
    print(f"{ui_set} is ready at http://{SERVICE_HOST}:{port}/ for {resolved}")
    print(
        f"Follow its output with: bash bin/tokencrate ui logs {ui_set}; "
        f"stop it with: bash bin/tokencrate ui stop {ui_set}"
    )
    return 0
