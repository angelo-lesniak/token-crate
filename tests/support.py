"""Shared helpers for the package tests: a scratch checkout, a controlled
environment, and the fake engine on PATH."""

from __future__ import annotations

import contextlib
import http.server
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
ENGINE_BIN = SOURCE_ROOT / "tests" / "fixtures" / "engine-bin"
COPIED = (
    "bin",
    "tokencrate",
    "config",
    "services",
    "compose.yaml",
    "compose.gpu.yaml",
    "compose.podman.yaml",
    "compose.docker.yaml",
    "compose.agent-egress.yaml",
    "pins.env",
    ".env.example",
)


def shipped(kind: str) -> list[str]:
    """The names of the shipped entries under config/<kind> (one TOML file
    each), in name order, which is the order the package reads them."""
    return sorted(path.stem for path in (SOURCE_ROOT / "config" / kind).glob("*.toml"))


def free_port() -> int:
    """A port nothing listens on, so `up` and `status` see no service."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Scratch:
    """A temporary copy of the repository with its own home, storage, and
    project directories, so no test touches the real checkout or $HOME."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tokencrate-test-"))
        self.root = self.tmp / "checkout"
        self.root.mkdir()
        for name in COPIED:
            source = SOURCE_ROOT / name
            if source.is_dir():
                shutil.copytree(source, self.root / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, self.root / name)
        self.home = self.tmp / "home"
        self.project = self.home / "src" / "project"
        self.project.mkdir(parents=True)
        self.storage = self.tmp / "storage"
        for name in ("models", "agents", "skills", "local-skills"):
            (self.storage / name).mkdir(parents=True)
        self.port = str(free_port())
        self.ui_port = free_port()

    @contextlib.contextmanager
    def ui_listener(self):
        """Something that answers on the UI port, the way the forwarder does
        once the UI container is up."""
        handler = type("Answer", (http.server.BaseHTTPRequestHandler,), {})
        handler.log_message = lambda *_args: None
        handler.do_GET = lambda self: (self.send_response(200), self.end_headers())
        server = http.server.HTTPServer(("127.0.0.1", self.ui_port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def environment(self, **overrides: str) -> dict[str, str]:
        env = {
            "PATH": f"{ENGINE_BIN}:/usr/bin:/bin",
            "HOME": str(self.home),
            "PYTHONPATH": str(self.root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CONTAINER_ENGINE": "docker",
            "LLM_MODELS_DIR": str(self.storage / "models"),
            "LLM_AGENTS_DIR": str(self.storage / "agents"),
            "LLM_SKILLS_DIR": str(self.storage / "skills"),
            "LLM_LOCAL_SKILLS_DIR": str(self.storage / "local-skills"),
            "LLM_SKILL_SETS": "",
            "LLM_DEFAULT_PRESET": "",
            "LLM_GPU": "true",
            "LLM_PORT": self.port,
        }
        env.update(overrides)
        return {key: value for key, value in env.items() if value is not None}

    def run(self, *arguments: str, cwd: Path | None = None, **overrides: str) -> subprocess.CompletedProcess:
        """Run the package the way the shim does and capture both streams."""
        return subprocess.run(
            [sys.executable, "-m", "tokencrate", *arguments],
            cwd=cwd or self.root,
            env=self.environment(**overrides),
            capture_output=True,
            text=True,
            check=False,
        )

    def run_shim(self, *arguments: str, **overrides: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.root / "bin" / "tokencrate"), *arguments],
            cwd=self.project,
            env=self.environment(**overrides),
            capture_output=True,
            text=True,
            check=False,
        )

    def render_fixture(self, *preset_ids: str) -> None:
        """Pretend a render happened: build/models.ini has a section per preset."""
        path = self.root / "build" / "models.ini"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[*]\njinja = true\n" + "".join(f"\n[{name}]\nmodel = /models/{name}.gguf\n" for name in preset_ids)
        )
