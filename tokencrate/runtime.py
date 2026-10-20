"""The llama service: host directories, rendering, start, wait, status."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from . import TokenCrateError, presets, warn
from .agenthome import AGENTS
from .engine import PROJECT_LABEL, Engine
from .env import Settings
from .localhttp import http_get, http_post

# A container in one of these states will not answer (`removed`: the engine
# no longer knows it); anything else is polled again until the timeout.
STOPPED_STATES = ("exited", "dead", "stopped", "removing", "removed")
# How many polls (two seconds apart) the default preset may still read
# `unloaded` after this run's own load request before that counts as failed.
LOAD_GRACE_POLLS = 3


# What `init` writes: `.env.example` stays the defaults layer, so a setting
# is copied into `.env` only to change it, and a later checkout's new
# default applies without an edit.
ENV_HEADER = """\
# Settings for this machine, read by bin/tokencrate and by Compose; not
# committed. Every setting and its default is documented in .env.example.
# A setting omitted here keeps that default: copy a line here only to
# change it (for example LLM_MODELS_DIR, CONTAINER_ENGINE, or the Git
# identity for the agent's commits).
"""


def init_project(settings: Settings) -> None:
    env_file = settings.root / ".env"
    if not env_file.is_file():
        env_file.write_text(ENV_HEADER, encoding="utf-8")
        print(f"Created {env_file}")
    else:
        print(f"Keeping existing {env_file}")
    env_file.chmod(0o600)
    prepare_host_directories(settings)
    print("TokenCrate host directories are ready. Review .env before starting.")


def prepare_host_directories(settings: Settings) -> None:
    """The storage entries `init` owns, plus the home directory of each
    agent below the agents directory."""
    for place in settings.storage:
        if place.created_by_init:
            place.path.mkdir(parents=True, exist_ok=True)
    for agent in AGENTS:
        (settings.agents_dir / agent).mkdir(exist_ok=True)


def models_directory(settings: Settings) -> Path:
    path = settings.models_dir
    if not path.is_dir():
        raise TokenCrateError(f"models directory does not exist: {path} (run: bash bin/tokencrate init)")
    return Path(os.path.realpath(path))


def render(settings: Settings, configuration: presets.Configuration) -> list[presets.RenderedPreset]:
    """Render config/presets and config/model-sets into build/, leaving out a
    preset whose model files are missing and one whose model set needs a
    newer llama.cpp build than pins.env pins."""
    return presets.render(
        configuration,
        output_dir=settings.build_dir,
        models_root=models_directory(settings),
        default_preset=settings.default_preset,
    )


def config_digest(settings: Settings) -> str:
    return hashlib.sha256((settings.build_dir / presets.CONFIG_FILE_NAME).read_bytes()).hexdigest()


# The dashboard profile's services, started by name: `compose up llama`
# starts llama alone, and a profile flag by itself starts nothing. The GPU
# exporter has its own profile, added when the stack uses the GPU.
DASHBOARD_SERVICES = ("llama-exporter", "victoriametrics", "grafana")
DASHBOARD_GPU_SERVICE = "gpu-exporter"
DASHBOARD_RETENTION = "90 days"


def start_stack(settings: Settings, engine: Engine, configuration: presets.Configuration, timeout: int) -> None:
    """Render presets against the downloaded model files, build the runtime
    image, start the llama service in the background, and wait until it is
    ready. The rendered preset file's hash travels as a container label, so
    Compose recreates the container when the file changed and keeps it
    otherwise. With LLM_DASHBOARD=true the dashboard profile follows. The
    stack lock covers the Compose `up` calls and the stack record only: the
    image build is content-addressed and the readiness wait polls, so a
    `down` meanwhile removes the container and the wait reports that."""
    # The ports are judged first so a taken one fails before the build,
    # and again under the lock, which is the judgement that counts.
    engine.require_port("llama", settings.port)
    if settings.dashboard:
        if settings.dashboard_port == settings.port:
            raise TokenCrateError("LLM_DASHBOARD_PORT must differ from LLM_PORT")
        engine.require_port("grafana", settings.dashboard_port)
    rendered = render(settings, configuration)
    default_preset = settings.default_preset
    if default_preset and default_preset not in {item.preset.name for item in rendered if item.loadable}:
        raise TokenCrateError(
            f"the default preset {default_preset} is not loadable; download its model set "
            f"(bash bin/tokencrate models fetch {configuration.find(default_preset).model_set}) "
            "or set LLM_DEFAULT_PRESET to a preset listed as loadable above"
        )
    extra = {"TOKENCRATE_CONFIG_SHA256": config_digest(settings)}
    engine.compose("build", "llama", **extra)
    with engine.lock("up"):
        engine.require_port("llama", settings.port)
        engine.compose("up", "--no-build", "--detach", "llama", **extra)
        engine.record_stack()
    wait_until_ready(settings, engine, timeout)
    if settings.dashboard:
        with engine.lock("up"):
            engine.require_port("grafana", settings.dashboard_port)
            start_dashboard(settings, engine)


def start_dashboard(settings: Settings, engine: Engine) -> None:
    """The dashboard profile beside the running model: VictoriaMetrics'
    samples live under data/dashboard, Grafana answers on loopback."""
    services, profiles = list(DASHBOARD_SERVICES), ["dashboard"]
    if settings.gpu:
        services.append(DASHBOARD_GPU_SERVICE)
        profiles.append("dashboard-gpu")
    engine.compose("up", "--no-build", "--detach", *services, profiles=tuple(profiles))
    print(
        f"Dashboard at http://127.0.0.1:{settings.dashboard_port}/ "
        f"(Grafana over VictoriaMetrics; the samples of the last {DASHBOARD_RETENTION} stay under data/dashboard)"
    )


def stop_stack(engine: Engine) -> None:
    """Remove all project-owned containers and networks without launch
    config, then the stack record, so the next `up` may choose its engine."""
    with engine.lock("down"):
        owned = engine.containers()
        engine.remove_containers(owned)
        pods = sorted({item["Pod"] for item in owned if item.get("Pod")})
        if engine.name == "podman" and pods:
            engine.command("pod", "rm", *pods)
        networks = engine.command(
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label={PROJECT_LABEL}={engine.settings.project_name}",
            capture=True,
        ).stdout.split()
        if networks:
            engine.command("network", "rm", *networks)
        engine.forget_stack()


def require_isolated_networks(engine: Engine) -> None:
    """The internal networks as the Compose files declare them: internal,
    created by this Compose project, on Docker without a gateway address
    (compose.docker.yaml), and on rootless Podman with IPv4 forwarding
    off on the bridge, which is what keeps a session on another network
    from reaching the containers on it (docs/privacy.md: an internal
    bridge created before forwarding was switched on in the engine's
    network namespace forwards). Compose keeps an existing network with
    the options it was created with, so a network made without the
    overlay, or by hand under the project's name, would keep its options
    silently. `up` refuses before any download, and every agent session
    refuses before its container starts, until the network is gone."""
    for network in ("agents", "ui", "dashboard"):
        document = engine.network_document(network, missing_ok=True)
        if document is None:
            continue
        labels = document.get("Labels") or document.get("labels") or {}
        if labels.get(PROJECT_LABEL) != engine.settings.project_name:
            name = f"{engine.settings.project_name}_{network}"
            raise TokenCrateError(
                f"the {network} network was not created by this Compose project; "
                f"remove it ({engine.name} network rm {name}) and run: bash bin/tokencrate up"
            )
        if not document.get("Internal", document.get("internal")):
            raise TokenCrateError(f"the {network} network is not internal. Run: bash bin/tokencrate down, then up")
        if engine.name == "docker" and (gateway := engine.network_gateway(network)):
            raise TokenCrateError(
                f"the {network} network keeps a host gateway address ({gateway}); it was created without "
                "gateway mode isolated. Run: bash bin/tokencrate down, then up"
            )
        if engine.name == "podman" and (interface := document.get("network_interface")):
            flag, cause = engine.bridge_forwarding(str(interface))
            if flag == "1":
                raise TokenCrateError(
                    f"the {network} network's bridge {interface} forwards IPv4 traffic, so a session on "
                    "another network can reach it. Run: bash bin/tokencrate down, then up"
                )
            # No bridge exists while no container uses the network; it is
            # created with the first one. Anything else is worth a line,
            # not a refusal: the probe failed, the boundary is unjudged.
            if not flag and "No such file" not in cause:
                warn(f"could not read the forwarding flag of bridge {interface}: {cause}")


def model_states(settings: Settings) -> dict[str, str] | None:
    """The router's model listing (GET /models) as {id: status}, where the
    status is `unloaded`, `loading`, `loaded`, or `sleeping`; None when the
    service does not answer."""
    body = http_get(f"{settings.service_url}/models")
    if body is None:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    states: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            status = entry.get("status")
            states[entry["id"]] = str(status.get("value", "")) if isinstance(status, dict) else ""
    return states


def poll(state, timeout: int, *, stopped: str, timed_out: str, sleep=time.sleep, clock=time.monotonic):
    """Yield every two seconds while the container runs and the deadline has
    not passed; the caller returns from its loop body once it is ready.
    `state` reports the container's state; one of `STOPPED_STATES` raises
    `stopped` with `{state}` filled in, the deadline raises `timed_out`."""
    deadline = clock() + timeout
    while True:
        current = state()
        if current in STOPPED_STATES:
            raise TokenCrateError(stopped.format(state=current))
        yield
        if clock() >= deadline:
            raise TokenCrateError(timed_out)
        sleep(2)


def wait_until_ready(settings: Settings, engine: Engine, timeout: int, **poll_options) -> None:
    """Wait until the router answers on the published port and, when a default
    preset is set, until it reports that preset as loaded.

    A fresh container loads the preset at start (`loading`, then `loaded`);
    `unloaded` after that means its model server exited. Compose keeps a
    running container whose configuration did not change: when another
    preset holds the single model slot, the router loads the default on its
    first request and `up` says so; when nothing is loaded (an earlier load
    failed), `up` asks the router to load the preset once. The container
    must stay running throughout; an exit or removal fails immediately."""
    container_id = engine.running_llama_id()
    preset = settings.default_preset
    load_started = False
    polls = asked = 0
    refused = ""
    for _ in poll(
        lambda: engine.container_state(container_id),
        timeout,
        stopped="container is {state} before it was ready. Check the logs: bash bin/tokencrate logs",
        timed_out=f"container did not become ready within {timeout}s. Check the logs: bash bin/tokencrate logs",
        **poll_options,
    ):
        polls += 1
        states = model_states(settings)
        if states is None:
            continue
        if not preset:
            print(f"TokenCrate is healthy at {settings.service_url}/")
            return
        status = states.get(preset, "")
        if status in ("loaded", "sleeping"):
            print(f"TokenCrate is ready at {settings.service_url}/ with preset {preset} loaded")
            return
        if status == "loading":
            load_started = True
            continue
        if status == "unloaded" and not load_started and not refused:
            if not asked:
                if occupied := [name for name, value in states.items() if value in ("loading", "loaded", "sleeping")]:
                    print(
                        f"TokenCrate is running at {settings.service_url}/ with preset {occupied[0]} loaded; "
                        f"preset {preset} loads on its first request"
                    )
                    return
                refused = http_post(f"{settings.service_url}/models/load", {"model": preset})
                asked = polls
                continue
            if polls - asked <= LOAD_GRACE_POLLS:
                # The router spawns the model server after answering the
                # load request; the listing may still say unloaded.
                continue
        # `loading` then `unloaded` is a model server that exited; a load
        # this run asked for and that never began was refused outright or
        # failed at once, and the refusal is the more useful half.
        cause = f" (the load request was refused: {refused})" if refused else ""
        raise TokenCrateError(
            f"preset {preset} is {status or 'not listed'} instead of loaded{cause}. "
            "Check the logs: bash bin/tokencrate logs"
        )


def print_containers(settings: Settings, engine: Engine) -> None:
    engine.command("ps", "--all", "--filter", f"label={PROJECT_LABEL}={settings.project_name}")


def print_models(settings: Settings, engine: Engine) -> None:
    if engine.llama_container_ids():
        print("Models (GET /models):")
        states = model_states(settings)
        if states is None:
            print("  (not reachable yet)")
        for name, status in (states or {}).items():
            print(f"  {name}: {status}")
        print()


def save_report(settings: Settings, kind: str, text: str) -> Path:
    reports = settings.root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    return path
