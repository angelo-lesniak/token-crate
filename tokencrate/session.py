"""What one agent container start is made of.

`agents` opens a terminal session, `uis` starts a browser UI, and
`smoke --agent` runs the containment check; all three mount the same
project, use the same per-project home, pass the same pre-flight, and run
the image the selected agent sets render. That shared part is `prepare`:
the one pre-flight, mount, and render step, whose result is the variables
every Compose call of the start carries. A caller names its profiles and
its egress on each call; a fourth start path cannot quietly skip a mount,
the pre-flight, or the image. The cloud keys file is delivered the same
way by every start that offers it: checked by `cloud_keys_file`, mounted
by the arguments of the `run` alone (`run_arguments`), announced by
`warn_about`.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from . import TokenCrateError, agentsets, presets, runtime, skills, warn
from .engine import Engine
from .env import Settings
from .names import parse_list

AGENTS = ("pi", "omp")
# Refused in cli.dispatch before the pre-flight.
SETS_ARE_PI_ONLY = "--sets applies to pi only; oh-my-pi has no agent sets"
# oh-my-pi fills unset variables from the project's `.env` files, base URLs
# included, so a project could send a key elsewhere; pi reads no such file.
CLOUD_IS_PI_ONLY = (
    "--cloud applies to pi only; oh-my-pi reads provider settings from the project's .env files, "
    "which could redirect a key"
)
HOME_IN_CONTAINER = "/home/agent"
# The home is a per-container tmpfs; these are the only home paths bound
# from the host, read-write. OMP externalizes transcript images to blobs;
# its other two directories retain --continue selection and references to
# custom transcript files for storage GC. Paths are relative to the home.
PERSISTENT_DIRECTORIES = {
    "pi": (".pi/agent/sessions",),
    "omp": tuple(f".omp/agent/{name}" for name in ("sessions", "blobs", "terminal-sessions", "custom-session-files")),
}
UNSAFE_PATH_CHARACTERS = set(" \t\n,:$\"'")
# Where `--cloud` mounts the keys file, read-only; the entrypoint exports
# its lines and refuses to start without it when the start asked for it
# (TOKENCRATE_CLOUD).
KEYS_MOUNT_TARGET = "/etc/tokencrate/cloud-keys"


def cloud_keys_file(settings: Settings, project: Path) -> Path:
    """The file `--cloud` mounts: a regular file whose path a `-v`
    argument can carry, outside every directory an agent container or an
    image build reads, since those would carry it into every session. The
    wrapper never opens it; the entrypoint reads it."""
    path = settings.cloud_keys_file
    try:
        regular = stat.S_ISREG(os.stat(path).st_mode)
    except FileNotFoundError:
        raise TokenCrateError(
            f"no cloud keys file at {path}; write one NAME=value line per provider key there "
            "(.env.example describes it), or set LLM_CLOUD_KEYS_FILE"
        ) from None
    if not regular:
        raise TokenCrateError(f"the cloud keys file is not a regular file: {path}")
    if ":" in str(path) or "," in str(path):
        raise TokenCrateError(f"the cloud keys file path contains ':' or ',', which a mount cannot carry: {path}")
    for label, directory in (
        ("the project", project),
        ("the models directory", settings.models_dir),
        ("the agents directory", settings.agents_dir),
        ("the skills directory", settings.skills_dir),
        ("the private skills directory", settings.local_skills_dir),
        ("the shipped configuration", settings.root / "config"),
        ("the private agent sets", settings.root / "local" / "agent-sets"),
    ):
        if path.is_relative_to(os.path.realpath(directory)):
            raise TokenCrateError(
                f"the cloud keys file lies inside {label} ({directory}), which agent containers read; move it"
            )
    return path


def run_arguments(keys: Path | None) -> tuple[str, ...]:
    """The arguments of the Compose `run` that mount the keys file: no
    Compose file and no variable carries it."""
    return ("-v", f"{keys}:{KEYS_MOUNT_TARGET}:ro", "-e", "TOKENCRATE_CLOUD=1") if keys else ()


def warn_about(egress: bool, keys: Path | None) -> None:
    """What a start with a route out, or with the keys file, gives away."""
    if egress:
        warn("this agent session has internet access (egress enabled).")
    if keys:
        warn(
            f"this session offers the cloud providers keyed in {keys}: prompts, file contents, and the "
            "conversation so far go to a cloud model you pick, and every process in the session can read the keys."
        )


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
    try:
        str(resolved).encode()
    except UnicodeEncodeError:
        shown = str(resolved).encode("utf-8", "backslashreplace").decode()
        raise TokenCrateError(f"project path is not valid UTF-8: {shown}") from None
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
    # A root is where projects live, not a project (the home directory was
    # refused above); a root below another root is still a root.
    if resolved in roots:
        raise TokenCrateError(
            f"refusing to mount an LLM_PROJECT_ROOTS entry as a project: {resolved} (choose a directory below it)"
        )
    if not any(resolved.is_relative_to(root) for root in roots):
        raise TokenCrateError(f"project directory is outside your home directory and LLM_PROJECT_ROOTS: {resolved}")
    # Git metadata outside the mount: a `.git` file (a linked worktree or a
    # submodule), a `commondir` (a worktree's main repository), or a
    # repository above the project. The file's contents are not parsed;
    # what it points at lies outside the mount by construction.
    for directory in (resolved, *resolved.parents):
        git_dir = directory / ".git"
        if git_dir.is_file() or (git_dir / "commondir").is_file() or (directory != resolved and git_dir.is_dir()):
            raise TokenCrateError(
                "Git metadata lies outside the project mount; choose the repository root "
                "or a standalone clone instead of a linked worktree or submodule"
            )
        if git_dir.is_dir():
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


def require_skill_sets(settings: Settings) -> list[str]:
    """Every set named in LLM_SKILL_SETS must be known, fetched, and complete;
    the names as parsed (each once) are what the container gets, so the
    entrypoint never links a set twice."""
    names = parse_list(settings.get("LLM_SKILL_SETS"), "skill set")
    if not names:
        return names
    catalog = skills.catalog(settings.config_dir)
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
    return names


def require_session_ready(
    settings: Settings, engine: Engine, configuration: presets.Configuration, preset: str
) -> list[str]:
    """What every agent container needs before it starts: a preset the running
    llama service knows, every set in LLM_SKILL_SETS fetched (the entrypoint
    refuses to start otherwise), the llama service itself, and internal
    networks that carry no host address."""
    configuration.require(preset)
    if preset not in presets.rendered_model_ids(settings.build_dir):
        raise TokenCrateError(
            f"preset {preset} is not rendered as loadable; fetch its model set "
            f"(bash bin/tokencrate models fetch {configuration.find(preset).model_set}) "
            "and run: bash bin/tokencrate up"
        )
    skill_sets = require_skill_sets(settings)
    container_id = engine.running_llama_id()
    digest = engine.command(
        "inspect", "--format", '{{index .Config.Labels "io.tokencrate.config-sha256"}}', container_id, capture=True
    ).stdout.strip()
    if digest != runtime.config_digest(settings):
        raise TokenCrateError(
            "the running llama configuration differs from the rendered files; run: bash bin/tokencrate up"
        )
    runtime.require_isolated_networks(engine)
    return skill_sets


def chosen_preset(settings: Settings, preset: str) -> str:
    """`--preset`, else LLM_DEFAULT_PRESET; a command that acts on a preset
    needs one of the two."""
    preset = preset or settings.default_preset
    if not preset:
        raise TokenCrateError("no preset selected; set LLM_DEFAULT_PRESET in .env or pass --preset")
    return preset


def symlink_in_path(path: Path) -> Path | None:
    return next((part for part in (*reversed(path.parents), path) if part.is_symlink()), None)


def persistent_directories(agent: str, state: str | None = None) -> tuple[str, ...]:
    """The home paths bound from the host: the transcript directories and,
    for a browser UI, the state directory its set declares."""
    return PERSISTENT_DIRECTORIES[agent] + ((state,) if state else ())


def prepare_mountpoints(home: Path, agent: str, state: str | None = None) -> None:
    """Create the retained bind sources as the caller, without following
    links; nothing else in the host home is mounted or touched. The home
    is readable by the calling user only: transcripts carry what the
    session saw, keys an `agent --cloud` session printed included."""
    for relative in persistent_directories(agent, state):
        path = home / relative
        if link := symlink_in_path(path):
            raise TokenCrateError(f"{link} is a symbolic link; the agent home must contain real paths (move it aside)")
        if path.exists() and not path.is_dir():
            raise TokenCrateError(f"{path} is not a directory; move it aside")
        path.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)


def selected_sets(settings: Settings, sets: str | None) -> list[agentsets.AgentSet]:
    return agentsets.select(settings.root, settings.get("LLM_AGENT_SETS") if sets is None else sets)


def render_image(settings: Settings, selected: list[agentsets.AgentSet]) -> dict[str, str]:
    """The pi image is rendered from the selected agent sets; its tag names
    the selection."""
    tag = agentsets.render(settings.root, settings.build_dir, selected)
    names = ", ".join(entry.name for entry in selected) or "none"
    print(f"Agent sets: {names} (image tag suffix {tag}).", flush=True)
    return {"TOKENCRATE_AGENT_SETS_TAG": tag}


def session_variables(project: Path, home: Path, preset: str) -> dict[str, str]:
    """The variables every agent container start hands Compose."""
    return {
        "LLM_AGENT_PROJECT_DIR": str(project),
        "TOKENCRATE_AGENT_HOME": str(home),
        "TOKENCRATE_PRESET": preset,
    }


def prepare(
    settings: Settings,
    engine: Engine,
    configuration: presets.Configuration,
    agent: str,
    preset: str,
    project: Path,
    home: Path,
    *,
    selected: list[agentsets.AgentSet] | None = None,
    ui: agentsets.AgentSet | None = None,
) -> dict[str, str]:
    """The pre-flight every start shares (a preset the running service
    knows, the skill sets, the llama service), the directories its mounts
    need, the image its agent sets render, and the variables those add up
    to. `selected` is the pi selection (oh-my-pi has none); with `ui`, the
    start is a browser UI of that set, whose state directory is mounted
    too. The caller adds the UI launcher's own variables and names the
    profiles and the egress on each Compose call."""
    skill_sets = require_session_ready(settings, engine, configuration, preset)
    prepare_mountpoints(home, agent, ui.ui["state"] if ui is not None else None)
    settings.local_skills_dir.mkdir(parents=True, exist_ok=True)
    variables = session_variables(project, home, preset)
    variables["LLM_SKILL_SETS"] = ",".join(skill_sets)
    if agent == "pi":
        variables.update(render_image(settings, selected or []))
    return variables
