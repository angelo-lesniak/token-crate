"""Local settings: `.env`, the shell environment, the storage paths, and the
pins in `pins.env`.

Precedence is the same for the wrapper and for Compose: a shell environment
variable overrides `.env` for one command, and `.env` overrides the defaults
in `.env.example`, which is the defaults layer itself (a deleted line
changes nothing). Every key the example file sets is exported to Compose
with its effective value, so Compose never applies a fallback of its own; a
`.env` key the example does not list is reported and not exported. The
pins in `pins.env` cannot be overridden: every pin key is removed from the
environment handed to a subprocess so Compose reads the file's value. The
Hugging Face token is moved out of the settings, this process's environment
and the environment of every subprocess into `Settings.hf_token`, which the
downloader reads. Provider keys are not settings at all: they live in the
file `LLM_CLOUD_KEYS_FILE` names, which the wrapper never reads (`agents`).
The container identity (`HOST_UID`, `HOST_GID`) is the calling user, never
a setting. `.env` and the keys file are the two files that may hold a
credential; `require_private` is the one check that each is the calling
user's and readable by that user alone, and `Settings.storage` the one
list of the host paths the wrapper owns or mounts with the rules that
apply to each.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from . import PROJECT_ROOT, TokenCrateError, warn
from .names import SHA256_RE

# The model downloader's token: read into `Settings.hf_token`, never a
# setting, never exported. It is also the key of the agents' Hugging Face
# provider, which is why it stays out of the agents unless the keys file
# names it.
TOKEN_KEY = "HF_TOKEN"
# Host paths, resolved from the repository root when relative and to their
# real path always, so the mounts below them and the symbolic-link checks
# above them see one spelling of a directory.
PATH_KEYS = ("LLM_MODELS_DIR", "LLM_AGENTS_DIR", "LLM_SKILLS_DIR", "LLM_LOCAL_SKILLS_DIR", "LLM_CLOUD_KEYS_FILE")
# The switches the wrapper itself reads (Compose reads the rest as text):
# a misspelling must not silently mean false.
BOOLEAN_KEYS = ("LLM_GPU", "LLM_DASHBOARD")
BOOLEAN_WORDS = {"1": True, "true": True, "yes": True, "on": True} | dict.fromkeys(("0", "false", "no", "off"), False)
# What podman-compose keeps of a project name (Docker Compose's rule is the
# same); anything else would silently name another project's containers.
PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# A pin line as written: no prefix, an upper-case key, nothing trimmed.
PIN_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
# A setting `.env.example` documents, commented out or not.
DOCUMENTED_KEY_RE = re.compile(r"^#?\s*([A-Za-z_][A-Za-z0-9_]*)=")
# The published address is fixed in compose.yaml; nothing can widen it.
SERVICE_HOST = "127.0.0.1"
# A port as Compose publishes it and the forwarder's allowed hosts spell it:
# no leading zero, so the value is used as written and never normalised.
PORT_RE = re.compile(r"^[1-9][0-9]{0,4}$")

# pins.env is self-describing by its key names: `<NAME>_TAG` is an image tag
# and pairs with `<NAME>_DIGEST`, the bare sha256 hex of the manifest list the
# tag points at (the Dockerfiles and compose.yaml add the `@sha256:` prefix),
# because a tag can be moved and the digest is what the build pulls;
# `<NAME>_VERSION` is a package version; CUDA_MIN_DRIVER_MAJOR is the driver
# major `doctor` checks. Every key exactly once, a plain value without quotes
# or whitespace, and no other key shape. Compose reads the file itself through
# --env-file and interpolates every image from it; the wrapper reads it for
# the two keys below and for `pins check`.
PIN_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*_(TAG|DIGEST|VERSION)$")
WRAPPER_PIN_KEYS = ("LLAMA_CPP_TAG", "CUDA_MIN_DRIVER_MAJOR")
# Image tags, package versions, digests, and integers: no quotes, no whitespace.
PIN_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
# The llama.cpp build number at the end of the server image tag
# (server-cuda13-b10920); services/llama/Dockerfile asserts the same suffix
# against the pulled image, and the renderer compares it with what a model
# set requires.
LLAMA_BUILD_SUFFIX_RE = re.compile(r"-b([1-9][0-9]*)$")


def is_true(value: str, key: str) -> bool:
    """A switch the wrapper reads: one of the eight words, or a refusal."""
    try:
        return BOOLEAN_WORDS[value.strip().lower()]
    except KeyError:
        raise TokenCrateError(f"{key} must be one of 1/true/yes/on or 0/false/no/off, not {value!r}") from None


def require_private(path: Path, info: os.stat_result) -> None:
    """A file that may hold a credential (`.env`, the cloud keys file) is
    the calling user's and readable by that user alone (SECURITY.md);
    `info` is its `os.stat`."""
    if info.st_uid != os.getuid():
        raise TokenCrateError(f"{path} must be owned by your user (uid {os.getuid()}), since it may hold credentials")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise TokenCrateError(f"{path} must be readable by your user only; run: chmod 600 {path}")


def parse_env_file(path: Path, *, plain: bool = False) -> dict[str, str]:
    """Read `KEY=VALUE` lines, each key once. Comment lines start with `#`;
    a value may be wrapped in matching single or double quotes; nothing is
    expanded or executed; a byte-order mark is skipped. With `plain` (the
    pins file), keys are upper case and a value is a bare token: no quotes,
    no whitespace."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # A pin is matched as written: a stray space is refused, not trimmed.
        match = PIN_LINE_RE.match(raw) if plain else ENV_LINE_RE.match(line)
        if match is None:
            raise TokenCrateError(f"{path}:{number}: expected KEY=VALUE")
        key, value = match.group(1), match.group(2) if plain else match.group(2).strip()
        if key in values:
            raise TokenCrateError(f"{path}:{number}: {key} is set twice; keep one line")
        if plain:
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
    """Read pins.env: every key a pin by the naming convention above, in file order."""
    values = parse_env_file(path, plain=True)
    missing = [key for key in WRAPPER_PIN_KEYS if key not in values]
    if missing:
        raise TokenCrateError(f"pins file must define {', '.join(missing)}: {path}")
    unknown = sorted(key for key in values if key != "CUDA_MIN_DRIVER_MAJOR" and not PIN_KEY_RE.fullmatch(key))
    if unknown:
        raise TokenCrateError(
            f"pins file defines unknown key(s) {', '.join(unknown)} "
            f"(a pin is <NAME>_TAG with <NAME>_DIGEST, <NAME>_VERSION, or CUDA_MIN_DRIVER_MAJOR): {path}"
        )
    if not values["CUDA_MIN_DRIVER_MAJOR"].isdigit():
        raise TokenCrateError(f"CUDA_MIN_DRIVER_MAJOR must be a driver major version: {path}")
    for key, value in values.items():
        if key.endswith("_DIGEST"):
            if not SHA256_RE.fullmatch(value):
                raise TokenCrateError(f"{key} must be the 64 hex characters of a sha256 digest: {path}")
            if key.removesuffix("_DIGEST") + "_TAG" not in values:
                raise TokenCrateError(f"{key} has no {key.removesuffix('_DIGEST')}_TAG beside it: {path}")
        elif key.endswith("_TAG") and key.removesuffix("_TAG") + "_DIGEST" not in values:
            raise TokenCrateError(
                f"{key} has no {key.removesuffix('_TAG')}_DIGEST beside it (the build pulls the digest): {path}"
            )
    pinned_llama_build(values)
    return values


def pin_keys(path: Path) -> tuple[str, ...]:
    """The keys of the `KEY=VALUE` lines of pins.env, as a scan that refuses
    nothing: `subprocess_env` removes them whatever else the file holds,
    since a recovery command (`down`, `status`, `logs`) runs without
    validating the pins."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return tuple(match.group(1) for line in lines if (match := PIN_LINE_RE.match(line)))


# The shipped pins.env's keys; the contract tests iterate them.
PIN_KEYS = pin_keys(PROJECT_ROOT / "pins.env")
DIGEST_KEYS = tuple(key for key in PIN_KEYS if key.endswith("_DIGEST"))


def pinned_llama_build(pinned: dict[str, str]) -> int:
    """The llama.cpp build number the LLAMA_CPP_TAG pin names."""
    tag = pinned.get("LLAMA_CPP_TAG", "")
    match = LLAMA_BUILD_SUFFIX_RE.search(tag)
    if match is None:
        raise TokenCrateError(f"LLAMA_CPP_TAG must end in the llama.cpp build number (-b<N>): {tag!r}")
    return int(match.group(1))


@dataclass(frozen=True)
class HostPath:
    """One host path the wrapper owns or mounts, and the rules that apply
    to it: `mounted` into agent containers (it must not contain the
    checkout, whose `.env` would otherwise reach every container),
    `writable` by them (what `doctor` checks, read access otherwise),
    `created_by_init`, `refuses_projects` (a project must not contain it
    or lie inside it), and `refuses_keys` (the cloud keys file must not
    lie inside it, since containers or image builds read it). `key` is
    the setting that names it, if one does."""

    label: str
    path: Path
    key: str = ""
    mounted: bool = False
    writable: bool = False
    created_by_init: bool = False
    refuses_projects: bool = False
    refuses_keys: bool = False


@dataclass
class Settings:
    root: Path
    values: dict[str, str]
    # The keys `.env.example` sets: what the wrapper defaults and exports.
    defaults: dict[str, str]
    # The `.env` keys the example file lists; the others were reported.
    file_values: dict[str, str]
    environ: dict[str, str]
    # The token found in the shell environment or `.env`, if any.
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
    def cloud_keys_file(self) -> Path:
        return Path(self.values["LLM_CLOUD_KEYS_FILE"])

    @property
    def default_preset(self) -> str:
        return self.values["LLM_DEFAULT_PRESET"]

    @property
    def gpu(self) -> bool:
        return is_true(self.values["LLM_GPU"], "LLM_GPU")

    @property
    def dashboard(self) -> bool:
        return is_true(self.values["LLM_DASHBOARD"], "LLM_DASHBOARD")

    @property
    def dashboard_port(self) -> str:
        return validate_port(self.values["LLM_DASHBOARD_PORT"], "LLM_DASHBOARD_PORT")

    @property
    def project_name(self) -> str:
        return self.values["COMPOSE_PROJECT_NAME"]

    @property
    def port(self) -> str:
        return validate_port(self.values["LLM_PORT"], "LLM_PORT")

    @property
    def service_url(self) -> str:
        return f"http://{SERVICE_HOST}:{self.port}"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def storage(self) -> tuple[HostPath, ...]:
        """Every host path the wrapper owns or mounts, with its rules: the
        one list that the project rules, the keys-file rules, `init`, and
        `doctor` iterate. The storage directories are real paths already;
        the checkout is resolved here so the rules see one spelling."""
        root = Path(os.path.realpath(self.root))
        shared = {"mounted": True, "created_by_init": True, "refuses_projects": True, "refuses_keys": True}
        return (
            HostPath("the TokenCrate checkout", root, refuses_projects=True),
            HostPath("the models directory", self.models_dir, "LLM_MODELS_DIR", writable=True, **shared),
            HostPath("the agents directory", self.agents_dir, "LLM_AGENTS_DIR", writable=True, **shared),
            HostPath("the skills directory", self.skills_dir, "LLM_SKILLS_DIR", writable=True, **shared),
            HostPath("the private skills directory", self.local_skills_dir, "LLM_LOCAL_SKILLS_DIR", **shared),
            # Agent containers mount config/agents; the image build's context
            # is the .dockerignore allowlist: services, config/agent-sets,
            # local/agent-sets, build/agents/pi.
            HostPath("the shipped configuration", root / "config", refuses_keys=True),
            HostPath("the private agent sets", root / "local" / "agent-sets", refuses_keys=True),
            HostPath("the services directory", root / "services", refuses_keys=True),
            HostPath("the rendered pi images", root / "build" / "agents" / "pi", refuses_keys=True),
            HostPath("the cloud keys file", self.cloud_keys_file, "LLM_CLOUD_KEYS_FILE", refuses_projects=True),
            HostPath("the reports directory", root / "reports", created_by_init=True),
            HostPath("the dashboard's samples", root / "data" / "dashboard" / "victoria", created_by_init=True),
        )

    def subprocess_env(self, **extra: str) -> dict[str, str]:
        """The environment for every subprocess: the documented `.env`
        values, the shell environment on top, the pins removed (Compose
        reads pins.env), every key the wrapper defaults with its effective
        value, and the calling user as the container identity. The token is
        in none of those (`load` moved it into `hf_token`). Exporting the
        effective values keeps Compose from applying a default of its own;
        otherwise an omitted `LLM_SKILL_SETS` line would make pre-flight
        require the default sets while the entrypoint links none."""
        env = dict(self.file_values)
        env.update(self.environ)
        for key in PIN_KEYS:
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
        # Every subprocess inherits this process's environment, so the
        # token leaves it here; the downloader gets it as an argument.
        os.environ.pop(TOKEN_KEY, None)
    else:
        environ = dict(environ)
    example = root / ".env.example"
    if not example.is_file():
        raise TokenCrateError(f"the checkout has no settings reference: {example}")
    defaults = parse_env_file(example)
    env_file = root / ".env"
    if env_file.is_symlink():
        raise TokenCrateError(f"refusing symbolic link for local settings: {env_file}")
    file_values = {}
    if env_file.is_file():
        # It may hold the token; `init` creates it with mode 0600.
        require_private(env_file, os.stat(env_file))
        file_values = parse_env_file(env_file)
    documented = documented_keys(example)
    unknown = sorted(key for key in file_values if key not in documented)
    if unknown:
        warn(f".env: keys not listed in .env.example are ignored: {', '.join(unknown)}")
        for key in unknown:
            del file_values[key]
    # The shell wins over the file, as for every setting; an empty shell
    # value means "no token" and suppresses the file's.
    defaults.pop(TOKEN_KEY, None)
    hf_token = environ.pop(TOKEN_KEY, file_values.pop(TOKEN_KEY, None)) or None

    values = dict(defaults)
    values.update(file_values)
    values.update(environ)
    project_name = values.get("COMPOSE_PROJECT_NAME") or defaults["COMPOSE_PROJECT_NAME"]
    if not PROJECT_NAME_RE.fullmatch(project_name):
        raise TokenCrateError(
            f"COMPOSE_PROJECT_NAME must be lowercase letters, digits, - and _, starting with a letter or digit: "
            f"{project_name!r}"
        )
    values["COMPOSE_PROJECT_NAME"] = project_name
    # Relative paths are relative to the repository root, whichever
    # directory the wrapper runs from (for example a project, with `agent`).
    for key in PATH_KEYS:
        value = values[key]
        if not value:
            raise TokenCrateError(f"{key} must not be empty; omit the line to take the default ({defaults[key]})")
        values[key] = os.path.realpath(value if value.startswith("/") else root / value.removeprefix("./"))
    for key in BOOLEAN_KEYS:
        is_true(values[key], key)
    settings = Settings(root, values, defaults, file_values, environ, hf_token)
    # The checkout (with .env) is what the next start trusts; a storage
    # directory that is or contains it would be mounted into every agent
    # container.
    checkout = Path(os.path.realpath(root))
    for place in settings.storage:
        if place.mounted and checkout.is_relative_to(place.path):
            raise TokenCrateError(f"{place.key} must not be or contain the TokenCrate checkout: {place.path}")
    return settings


def validate_port(value: str, label: str) -> str:
    if not PORT_RE.fullmatch(value) or int(value) > 65535:
        raise TokenCrateError(f"{label} requires a port from 1 to 65535")
    return value
