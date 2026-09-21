"""Local settings: `.env`, the shell environment, the storage paths, and the
pins in `pins.env`.

Precedence is the same for the wrapper and for Compose: a shell environment
variable overrides `.env` for one command, and `.env` overrides the defaults
in `.env.example`, which is the defaults layer itself (a deleted line
changes nothing). Every key the example file sets is exported to Compose
with its effective value, so Compose never applies a fallback of its own.
The pins in `pins.env` cannot be overridden: every pin key is removed from
the environment handed to a subprocess so Compose reads the file's value.
`HF_TOKEN` is captured in-process and stripped from the environment of every
subprocess. The container identity (`HOST_UID`, `HOST_GID`) is the calling
user, never a setting.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import TokenCrateError, warn

STORAGE_KEYS = ("LLM_MODELS_DIR", "LLM_AGENTS_DIR", "LLM_SKILLS_DIR", "LLM_LOCAL_SKILLS_DIR")
ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# A pin line as written: no prefix, an upper-case key, nothing trimmed.
PIN_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
# A setting `.env.example` documents, commented out or not.
DOCUMENTED_KEY_RE = re.compile(r"^#?\s*([A-Za-z_][A-Za-z0-9_]*)=")
# The published address is fixed in compose.yaml; nothing can widen it.
SERVICE_HOST = "127.0.0.1"

# pins.env: Compose reads the file itself through --env-file and interpolates
# every image tag from it; the wrapper reads it for the driver minimum and
# for `pins check`. Every key exactly once, a plain value without quotes or
# whitespace, and no other keys.
PIN_KEYS = (
    "LLAMA_CPP_TAG",
    "LLAMA_CPP_DIGEST",
    "PI_VERSION",
    "OMP_VERSION",
    "NODE_TAG",
    "NODE_DIGEST",
    "BUN_TAG",
    "BUN_DIGEST",
    "CUDA_MIN_DRIVER_MAJOR",
)
# The sha256 of a base image's manifest list, as bare hex; the Dockerfiles
# and compose.yaml add the `@sha256:` prefix.
DIGEST_KEYS = ("LLAMA_CPP_DIGEST", "NODE_DIGEST", "BUN_DIGEST")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
# Image tags, package versions, digests, and integers: no quotes, no whitespace.
PIN_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
# The llama.cpp build number at the end of the server image tag
# (server-cuda13-b10920); services/llama/Dockerfile asserts the same suffix
# against the pulled image, and the renderer compares it with what a model
# set requires.
LLAMA_BUILD_SUFFIX_RE = re.compile(r"-b([1-9][0-9]*)$")


def is_true(value: object) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_env_file(path: Path, *, plain: bool = False) -> dict[str, str]:
    """Read `KEY=VALUE` lines. Comment lines start with `#`; a value may be
    wrapped in matching single or double quotes; nothing is expanded or
    executed. With `plain` (the pins file), keys are upper case and given
    once, and a value is a bare token: no quotes, no whitespace."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # A pin is matched as written: a stray space is refused, not trimmed.
        match = PIN_LINE_RE.match(raw) if plain else ENV_LINE_RE.match(line)
        if match is None:
            raise TokenCrateError(f"{path}:{number}: expected KEY=VALUE")
        key, value = match.group(1), match.group(2) if plain else match.group(2).strip()
        if plain:
            if key in values:
                raise TokenCrateError(f"pins file must define {key} exactly once: {path}")
            if not PIN_VALUE_RE.fullmatch(value):
                raise TokenCrateError(
                    f"pins file has an unsafe value for {key} (quotes and whitespace are not allowed): {path}"
                )
            values[key] = value
            continue
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
        if quoted:
            value = value[1:-1]
        elif "$" in value or value.startswith("~") or " #" in value:
            raise TokenCrateError(
                f"{path}:{number}: {key}: values are used literally; write the full value "
                "and keep comments on their own line"
            )
        values[key] = value
    return values


def documented_keys(example: Path) -> set[str]:
    """Every key `.env.example` lists, commented out or not, so a key that
    neither the wrapper nor the Compose files read can be reported instead
    of silently doing nothing."""
    lines = example.read_text(encoding="utf-8").splitlines()
    return {match.group(1) for line in lines if (match := DOCUMENTED_KEY_RE.match(line.strip()))}


def load_pins(path: Path) -> dict[str, str]:
    """Read pins.env and return exactly the pinned keys."""
    values = parse_env_file(path, plain=True)
    missing = [key for key in PIN_KEYS if key not in values]
    if missing:
        raise TokenCrateError(f"pins file must define {', '.join(missing)}: {path}")
    unknown = sorted(set(values) - set(PIN_KEYS))
    if unknown:
        raise TokenCrateError(f"pins file defines unknown key(s) {', '.join(unknown)}: {path}")
    if not values["CUDA_MIN_DRIVER_MAJOR"].isdigit():
        raise TokenCrateError(f"CUDA_MIN_DRIVER_MAJOR must be a driver major version: {path}")
    for key in DIGEST_KEYS:
        if not DIGEST_RE.fullmatch(values[key]):
            raise TokenCrateError(f"{key} must be the 64 hex characters of a sha256 digest: {path}")
    pinned_llama_build(values)
    return values


def pinned_llama_build(pinned: dict[str, str]) -> int:
    """The llama.cpp build number the LLAMA_CPP_TAG pin names."""
    tag = pinned.get("LLAMA_CPP_TAG", "")
    match = LLAMA_BUILD_SUFFIX_RE.search(tag)
    if match is None:
        raise TokenCrateError(f"LLAMA_CPP_TAG must end in the llama.cpp build number (-b<N>): {tag!r}")
    return int(match.group(1))


def pinned_lines(path: Path) -> str:
    """The non-comment lines of pins.env, as `bin/tokencrate pins` prints them."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return "\n".join(lines) + "\n"


@dataclass
class Settings:
    root: Path
    values: dict[str, str]
    # The keys `.env.example` sets: what the wrapper defaults and exports.
    defaults: dict[str, str]
    file_values: dict[str, str]
    environ: dict[str, str]
    hf_token: str | None

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    @property
    def models_dir(self) -> Path:
        return Path(self.values["LLM_MODELS_DIR"])

    @property
    def agents_dir(self) -> Path:
        return Path(self.values["LLM_AGENTS_DIR"])

    @property
    def skills_dir(self) -> Path:
        return Path(self.values["LLM_SKILLS_DIR"])

    @property
    def local_skills_dir(self) -> Path:
        return Path(self.values["LLM_LOCAL_SKILLS_DIR"])

    @property
    def default_preset(self) -> str:
        return self.values["LLM_DEFAULT_PRESET"]

    @property
    def gpu(self) -> bool:
        return is_true(self.get("LLM_GPU", "false"))

    @property
    def project_name(self) -> str:
        return self.values["COMPOSE_PROJECT_NAME"]

    @property
    def port(self) -> str:
        return validate_port(self.values["LLM_PORT"], "LLM_PORT")

    @property
    def service_url(self) -> str:
        return f"http://{SERVICE_HOST}:{self.port}"

    def ui_port(self, ui_set: str, requested: str = "") -> str:
        if requested:
            return validate_port(requested, "--port")
        keys = {"pi-web": "LLM_PI_WEB_PORT", "paseo": "LLM_PASEO_PORT"}
        key = keys.get(ui_set)
        if key is None:
            raise TokenCrateError(f"custom UI set {ui_set} needs an explicit --port")
        return validate_port(self.get(key), key)

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    def subprocess_env(self, **extra: str) -> dict[str, str]:
        """The environment for every subprocess: `.env` values, the shell
        environment on top, the pins removed (Compose reads pins.env), the
        token removed, every key the wrapper defaults with its effective
        value, and the calling user as the container identity. Exporting the
        effective values keeps Compose from applying a default of its own;
        otherwise an omitted `LLM_SKILL_SETS` line would make pre-flight
        require the default sets while the entrypoint links none."""
        env = dict(self.file_values)
        env.update(self.environ)
        for key in (*PIN_KEYS, "HF_TOKEN"):
            env.pop(key, None)
        for key in self.defaults:
            env[key] = self.values[key]
        env["TOKENCRATE_ROOT"] = str(self.root)
        env["HOST_UID"] = str(os.getuid())
        env["HOST_GID"] = str(os.getgid())
        env.update(extra)
        return env


def load(root: Path, environ: dict[str, str] | None = None) -> Settings:
    if environ is None:
        environ = dict(os.environ)
        # Every subprocess inherits this process's environment, so the token
        # leaves it here; the commands that need it pass it as an argument.
        os.environ.pop("HF_TOKEN", None)
    else:
        environ = dict(environ)
    example = root / ".env.example"
    if not example.is_file():
        raise TokenCrateError(f"the checkout has no settings reference: {example}")
    defaults = parse_env_file(example)
    defaults.pop("HF_TOKEN", None)
    env_file = root / ".env"
    if env_file.is_symlink():
        raise TokenCrateError(f"refusing symbolic link for local settings: {env_file}")
    file_values = parse_env_file(env_file) if env_file.is_file() else {}
    documented = documented_keys(example)
    unknown = sorted(key for key in file_values if key not in documented)
    if unknown:
        warn(f".env: keys not listed in .env.example: {', '.join(unknown)}")
    hf_token = environ.get("HF_TOKEN", file_values.get("HF_TOKEN")) or None
    environ.pop("HF_TOKEN", None)
    file_values.pop("HF_TOKEN", None)

    values = dict(defaults)
    values.update(file_values)
    values.update(environ)
    values["COMPOSE_PROJECT_NAME"] = values.get("COMPOSE_PROJECT_NAME") or defaults["COMPOSE_PROJECT_NAME"]
    # Relative storage paths are relative to the repository root, whichever
    # directory the wrapper runs from (for example a project, with `agent`).
    for key in STORAGE_KEYS:
        value = values.get(key) or defaults[key]
        values[key] = value if value.startswith("/") else str(root / value.removeprefix("./"))
    return Settings(root, values, defaults, file_values, environ, hf_token)


def validate_port(value: str, label: str) -> str:
    if not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= 65535:
        raise TokenCrateError(f"{label} requires a port from 1 to 65535")
    return str(int(value))
