"""The container engine: detection, Compose invocation, container lookup.

Podman is selected before Docker; `CONTAINER_ENGINE` fixes the choice. Podman
must be rootless and run crun (the keep-id mapping relies on it), and its
Compose provider must keep CDI device requests when the GPU is wanted (the
Docker Compose plugin drops them).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import TokenCrateError
from .env import Settings

ENGINES = ("podman", "docker")
# Both Docker Compose and podman-compose apply these labels.
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"


def publishes(container: dict, port: str) -> bool:
    ports = (container.get("NetworkSettings") or {}).get("Ports") or {}
    return any(
        bound.get("HostIp") == "127.0.0.1" and str(bound.get("HostPort")) == port
        for bound in ports.get("8080/tcp") or []
    )


def _run(command: list[str], env: dict[str, str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, env=env, check=False, **kwargs)


def _refuse_on_failure(result: subprocess.CompletedProcess, capture: bool, summary: str) -> None:
    """One wording for a failed engine call: the summary, and the first
    line of stderr when it was captured."""
    if result.returncode == 0:
        return
    detail = (result.stderr or "").strip() if capture else ""
    raise TokenCrateError(summary + (f": {detail}" if detail else ""))


def run_tool(command: list[str], env: dict[str, str]) -> tuple[str | None, str]:
    """(stdout, cause): the stdout of a host tool and an empty cause, or None
    and the first line of what went wrong when the tool is missing, cannot
    be started, or fails."""
    if shutil.which(command[0], path=env.get("PATH")) is None:
        return None, f"{command[0]} was not found"
    try:
        result = _run(command, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as error:
        return None, str(error)
    if result.returncode == 0:
        return result.stdout, ""
    cause = (result.stderr or "").strip().partition("\n")[0]
    return None, cause or f"exit status {result.returncode}"


def tool_output(command: list[str], env: dict[str, str]) -> str | None:
    """stdout of a host tool, or None when it did not succeed."""
    return run_tool(command, env)[0]


def compose_provider_version(name: str, env: dict[str, str]) -> str:
    """The Compose provider's version line. `podman compose version` prints
    Podman's own version first and the provider's line after it."""
    output = tool_output([name, "compose", "version"], env) or ""
    for line in output.splitlines():
        if "compose" in line.lower():
            return line.strip()
    return ""


def podman_compose_keeps_cdi(provider: str) -> bool:
    """`podman compose` can delegate to the Docker Compose plugin, which drops
    CDI `devices:` entries; the GPU path needs podman-compose. `provider` is
    the line `podman compose version` printed."""
    provider = provider.lower()
    return "docker-compose" not in provider and "docker compose" not in provider


def podman_rootless_crun(env: dict[str, str]) -> tuple[str, str]:
    """(rootless, runtime) as Podman reports them, or empty strings."""
    output = tool_output(["podman", "info", "--format", "{{.Host.Security.Rootless}}/{{.Host.OCIRuntime.Name}}"], env)
    if not output or "/" not in output:
        return "", ""
    rootless, _, runtime = output.strip().partition("/")
    return rootless, runtime


@dataclass
class EngineFacts:
    """What the probes reported for one engine candidate; `doctor` prints
    them one finding each, `detect` accepts or refuses on them."""

    name: str
    present: bool = False
    version_line: str = ""
    reachable: bool = False
    # The first line of what the engine said when it was not reachable.
    error: str = ""
    provider: str = ""
    # Docker: the daemon's version, which is what the network options need.
    server_version: str = ""
    rootless: str = ""
    runtime: str = ""
    keeps_cdi: bool = True

    @property
    def usable(self) -> bool:
        """Reachable with a Compose provider; Podman also rootless with crun."""
        if not (self.reachable and self.provider):
            return False
        return self.name != "podman" or (self.rootless, self.runtime) == ("true", "crun")


def inspect_engine(name: str, env: dict[str, str]) -> EngineFacts:
    """Run the probes for one engine, stopping at the first missing piece."""
    facts = EngineFacts(name=name)
    facts.present = shutil.which(name, path=env.get("PATH")) is not None
    if not facts.present:
        return facts
    facts.version_line = (tool_output([name, "--version"], env) or "").strip() or f"{name} is installed"
    info, facts.error = run_tool([name, "info"], env)
    facts.reachable = info is not None
    if not facts.reachable:
        return facts
    facts.provider = compose_provider_version(name, env)
    if name == "docker":
        server = tool_output(["docker", "version", "--format", "{{.Server.Version}}"], env)
        facts.server_version = (server or "").strip()
    if name == "podman" and facts.provider:
        facts.rootless, facts.runtime = podman_rootless_crun(env)
        facts.keeps_cdi = podman_compose_keeps_cdi(facts.provider)
    return facts


@dataclass
class Engine:
    name: str
    settings: Settings

    @property
    def env(self) -> dict[str, str]:
        return self.settings.subprocess_env()

    def command(self, *args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
        """Run an engine command (`podman ...` or `docker ...`)."""
        result = _run(
            [self.name, *args],
            self.env,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            text=True,
        )
        if check:
            _refuse_on_failure(result, capture, f"{self.name} {args[0]} failed")
        return result

    def compose(
        self,
        *args: str,
        profiles: tuple[str, ...] = (),
        egress: bool = False,
        capture: bool = False,
        check: bool = True,
        **extra: str,
    ) -> subprocess.CompletedProcess:
        """Run `engine compose` with the wrapper's file list, from the repository root."""
        files = ["--file", "compose.yaml"]
        if self.settings.gpu:
            files += ["--file", "compose.gpu.yaml"]
        if self.name == "podman":
            files += ["--file", "compose.podman.yaml"]
        elif self.name == "docker":
            files += ["--file", "compose.docker.yaml"]
        if egress:
            files += ["--file", "compose.agent-egress.yaml"]
        for profile in profiles:
            files += ["--profile", profile]
        env = self.settings.subprocess_env(**extra)
        # A user's Compose environment must not turn a targeted start into
        # removal of a sibling UI or a terminal `run` container.
        env["COMPOSE_REMOVE_ORPHANS"] = "false"
        # Podman rejects tmpfs uid=/gid=; U assigns the configured container
        # user. Docker accepts uid=/gid= and does not understand U.
        env["TOKENCRATE_HOME_OWNER"] = "U" if self.name == "podman" else f"uid={env['HOST_UID']},gid={env['HOST_GID']}"
        if self.name == "podman":
            # Podman's OCI output cannot retain Dockerfile SHELL metadata; keep
            # the Bash/pipefail build semantics for every Podman-backed provider.
            env["BUILDAH_FORMAT"] = "docker"
        result = _run(
            [self.name, "compose", *files, "--env-file", "pins.env", *args],
            env,
            cwd=self.settings.root,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            text=True,
        )
        if check:
            _refuse_on_failure(
                result,
                capture,
                f"{self.name} compose {args[0] if args else ''} failed (status {result.returncode})",
            )
        return result

    @property
    def lock_file(self) -> Path:
        # Hash avoids path syntax in project names; engines own separate stacks.
        key = hashlib.sha256(self.settings.project_name.encode()).hexdigest()[:16]
        return self.settings.build_dir / "locks" / f"{self.name}-{key}.lock"

    @contextlib.contextmanager
    def lock(self):
        """Serialize model/UI startup and shutdown for this checkout's stack."""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_file.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def containers(self, *, all_states: bool = True) -> list[dict]:
        result = self.command(
            "ps",
            *(["--all"] if all_states else []),
            "--quiet",
            "--filter",
            f"label={PROJECT_LABEL}={self.settings.project_name}",
            capture=True,
        )
        found = []
        for cid in result.stdout.split():
            inspected = self.command("inspect", "--format", "{{json .}}", cid, capture=True, check=False)
            if inspected.returncode:
                # A terminal run --rm may disappear between ps and inspect.
                if self.container_missing(inspected.stderr):
                    continue
                raise TokenCrateError(f"could not inspect container {cid}: {(inspected.stderr or '').strip()}")
            found.append(json.loads(inspected.stdout))
        return found

    @staticmethod
    def container_missing(message: str | None) -> bool:
        return any(
            text in (message or "").lower() for text in ("no such container", "no such object", "no container with")
        )

    def remove_containers(self, owned: list[dict]) -> None:
        for item in owned:
            for action in ("stop", "rm"):
                deadline = time.monotonic() + 30
                while True:
                    result = self.command(action, item["Id"], capture=True, check=False)
                    # Stopping a run --rm container also removes it. Docker
                    # may still be removing it when stop returns; wait before
                    # proceeding to network removal.
                    if not result.returncode or self.container_missing(result.stderr):
                        break
                    detail = (result.stderr or "").strip()
                    removing = "removal of container " in detail and "is already in progress" in detail
                    if not removing or time.monotonic() >= deadline:
                        raise TokenCrateError(f"{self.name} {action} failed: {detail}")
                    time.sleep(0.1)

    def require_port(self, name: str, port: str) -> None:
        """Accept an occupied port only when the named service or container
        publishes it (llama is one service; a UI forwarder is one container
        of the shared `ui-forward` service)."""
        for item in self.containers(all_states=False):
            if publishes(item, port):
                if name in (item["Config"]["Labels"].get(SERVICE_LABEL), (item.get("Name") or "").lstrip("/")):
                    return
                raise TokenCrateError(f"host port {port} belongs to another container; choose another port")
        with socket.socket() as listener:
            # A recently closed connection in TIME_WAIT must not prevent restart.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", int(port)))
            except OSError as error:
                raise TokenCrateError(f"cannot use host port {port}: {error}") from error

    def container_ids(self, service: str, *, all_states: bool = False) -> list[str]:
        """The running container(s) of one service of this Compose project
        (every state with all_states), asked from the engine directly
        through the standard Compose labels."""
        result = self.command(
            "ps",
            *(["--all"] if all_states else []),
            "--quiet",
            "--filter",
            f"label={PROJECT_LABEL}={self.settings.project_name}",
            "--filter",
            f"label={SERVICE_LABEL}={service}",
            capture=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def llama_container_ids(self) -> list[str]:
        return self.container_ids("llama")

    def running_llama_id(self) -> str:
        ids = self.llama_container_ids()
        if not ids:
            raise TokenCrateError("the llama container is not running (run: bash bin/tokencrate up)")
        if len(ids) > 1:
            raise TokenCrateError("multiple running llama containers were found for this Compose project")
        return ids[0]

    def network_document(self, network: str, *, missing_ok: bool = False) -> dict | None:
        """`network inspect` of one Compose network of this project, as the
        engine reports it; with missing_ok, None for a network the engine
        does not know."""
        name = f"{self.settings.project_name}_{network}"
        result = self.command("network", "inspect", "--format", "{{json .}}", name, capture=True, check=not missing_ok)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise TokenCrateError(f"{self.name} network inspect {name} returned invalid JSON") from error

    def network_gateway(self, network: str, *, missing_ok: bool = False) -> str:
        """The gateway address of one Compose network of this project
        (Docker: `IPAM.Config[].Gateway`; Podman: `subnets[].gateway`), or
        an empty string when the network has none, which is what Docker's
        isolated gateway mode leaves, or (with missing_ok) does not exist."""
        return network_gateway(self.network_document(network, missing_ok=missing_ok) or {})

    def container_state(self, container_id: str) -> str:
        """`.State.Status` of a container, by id or name (running, exited,
        ...), or `removed` when the engine no longer knows the container."""
        result = self.command("inspect", "--format", "{{.State.Status}}", container_id, capture=True, check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "removed"


def network_gateway(document: dict) -> str:
    """The gateway address in a `network inspect` document of either engine."""
    subnets = (document.get("IPAM") or {}).get("Config") or document.get("subnets") or []
    for subnet in subnets:
        gateway = subnet.get("Gateway") or subnet.get("gateway") if isinstance(subnet, dict) else None
        if gateway:
            return str(gateway)
    return ""


# The wording of the engine gate, shared so that `detect`, which refuses,
# and `doctor`, which reports, cannot drift apart. `detect` adds the
# pointer to `doctor`; `doctor` is already the report.
NO_USABLE_ENGINE = "neither Podman nor Docker has both a reachable engine and Compose provider"
RUN_DOCTOR = "run: bash bin/tokencrate doctor"
COMPOSE_PLUGIN_DROPS_CDI = "the Podman compose provider is the Docker Compose plugin, which drops CDI GPU devices"
INSTALL_PODMAN_COMPOSE = "install podman-compose or set LLM_GPU=false for CPU-only checks"


def unsupported_engine(name: str) -> str:
    return f"unsupported CONTAINER_ENGINE={name}"


@dataclass(frozen=True)
class Selection:
    """Which engine CONTAINER_ENGINE and the probes point at: the chosen
    facts, which are unusable when a named engine cannot run; the engines
    that are present but unusable, when nothing was named; and a name this
    project does not support. `detect` refuses on these and `doctor`
    reports them, from the one wording above."""

    chosen: EngineFacts | None = None
    candidates: tuple[EngineFacts, ...] = ()
    unsupported: str = ""


def select(env: dict[str, str], requested: str) -> Selection:
    """The requested engine wins and must be usable; otherwise the first
    usable of ENGINES, in order."""
    if requested:
        if requested not in ENGINES:
            return Selection(unsupported=requested)
        return Selection(chosen=inspect_engine(requested, env))
    present: list[EngineFacts] = []
    for candidate in ENGINES:
        facts = inspect_engine(candidate, env)
        if facts.usable:
            return Selection(chosen=facts)
        if facts.present:
            present.append(facts)
    return Selection(candidates=tuple(present))


def detect(settings: Settings, *, launching: bool = True) -> Engine:
    env = settings.subprocess_env()
    selection = select(env, settings.get("CONTAINER_ENGINE"))
    if selection.unsupported:
        raise TokenCrateError(unsupported_engine(selection.unsupported))
    facts = selection.chosen
    if facts is None:
        raise TokenCrateError(f"{NO_USABLE_ENGINE}; {RUN_DOCTOR}")
    if not facts.usable:
        raise TokenCrateError(
            f"{facts.name} needs a reachable engine and a working Compose provider (Podman: rootless with crun); "
            f"{RUN_DOCTOR}"
        )
    if launching and facts.name == "podman" and settings.gpu and not facts.keeps_cdi:
        raise TokenCrateError(f"{COMPOSE_PLUGIN_DROPS_CDI}; {INSTALL_PODMAN_COMPOSE}")
    return Engine(facts.name, settings)
