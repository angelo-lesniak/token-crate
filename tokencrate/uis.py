"""Temporary UI launch definitions and container ownership.

Compose itself resolves the shared templates; JSON fragments extend those
resolved services. No YAML parser is needed in the runtime package. Container
labels, rather than launch-time shell variables, identify lifecycle targets.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
from pathlib import Path

from . import TokenCrateError
from .engine import SERVICE_LABEL, Engine
from .names import SET_NAME_RE

UI_LABEL = "io.tokencrate.ui-set"


def services(name: str) -> tuple[str, str]:
    if not SET_NAME_RE.fullmatch(name):
        raise TokenCrateError(f"unsafe agent set name: {name}")
    # The manifest vocabulary includes uppercase, dots and underscores; a
    # digest gives each exact name a DNS-safe identity without collisions.
    key = hashlib.sha256(name.encode()).hexdigest()[:16]
    return f"agent-ui-{key}", f"ui-forward-{key}"


def containers(engine: Engine, *, all_states: bool = True) -> list[dict]:
    return [item for item in engine.containers(all_states=all_states) if set_name(item)]


def set_name(container: dict) -> str:
    return (container.get("Config", {}).get("Labels") or {}).get(UI_LABEL, "")


@contextlib.contextmanager
def snapshot(engine: Engine, name: str, extra: dict[str, str]):
    """Resolve one UI's engine overlays and settings for build and startup.

    Compose resolves paths and interpolation; TOKENCRATE_ROOT makes bind sources
    absolute even with podman-compose, whose config leaves relative binds.
    """
    ui, forward = services(name)
    rendered = engine.compose("config", profiles=("ui",), capture=True, **extra).stdout
    # Docker config escapes dollar signs for a subsequent Compose read;
    # podman-compose emits literal dollars and needs that escaping here.
    if engine.name == "podman":
        rendered = rendered.replace("$", "$$")
    with tempfile.TemporaryDirectory(prefix="tokencrate-ui-") as temporary:
        directory = Path(temporary)
        frozen = directory / "resolved.yaml"
        frozen.write_text(rendered)
        document = {
            "services": {
                service: {
                    "extends": {"file": str(frozen).replace("$", "$$"), "service": template},
                    "labels": {UI_LABEL: name},
                }
                for service, template in zip((ui, forward), ("agent-ui", "ui-forward"), strict=True)
            }
        }
        document["services"][forward]["depends_on"] = [ui]
        candidate = directory / "services.json"
        candidate.write_text(json.dumps(document))
        yield candidate


def stop(engine: Engine, name: str = "") -> int:
    if name:
        services(name)
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
    if name:
        services(name)
    owned = containers(engine)
    if not name:
        names = sorted({set_name(item) for item in owned})
        if len(names) > 1:
            raise TokenCrateError("several UIs are present; name one: bash bin/tokencrate ui logs <set>")
        name = names[0] if names else ""
    matches = [item for item in owned if name and item["Config"]["Labels"].get(SERVICE_LABEL) == services(name)[0]]
    if not matches:
        raise TokenCrateError(f"no UI container found{': ' + name if name else ''}")
    return engine.command("logs", "--follow", matches[0]["Id"], check=False).returncode


def print_status(engine: Engine) -> None:
    owned = containers(engine)
    projects = {
        set_name(item): dict(value.split("=", 1) for value in item["Config"].get("Env") or [] if "=" in value).get(
            "TOKENCRATE_PROJECT_DIR", "unknown"
        )
        for item in owned
        if item["Config"]["Labels"].get(SERVICE_LABEL, "").startswith("agent-ui-")
    }
    for item in sorted(owned, key=set_name):
        labels = item["Config"]["Labels"]
        if labels.get(SERVICE_LABEL, "").startswith("ui-forward"):
            state = (item.get("State") or {}).get("Status", "unknown")
            ports = (item.get("NetworkSettings") or {}).get("Ports") or {}
            addresses = ", ".join(
                f"http://{entry['HostIp']}:{entry['HostPort']}/" for entry in ports.get("8080/tcp") or []
            )
            print(
                f"UI {set_name(item)}: forwarder {state} {addresses} project={projects.get(set_name(item), 'unknown')}"
            )


def peer_targets(engine: Engine) -> str:
    """Names and effective IP:port targets for terminal containment probes."""
    targets = []
    for item in sorted(containers(engine, all_states=False), key=set_name):
        labels = item["Config"]["Labels"]
        service = labels[SERVICE_LABEL]
        environment = dict(value.split("=", 1) for value in item["Config"].get("Env") or [] if "=" in value)
        port = "8080" if service.startswith("ui-forward") else environment.get("TOKENCRATE_UI_PORT", "")
        if not port:
            continue
        targets.append(f"{service}:{port}")
        for network in (item.get("NetworkSettings", {}).get("Networks") or {}).values():
            if address := network.get("IPAddress"):
                targets.append(f"{address}:{port}")
    return " ".join(targets)
