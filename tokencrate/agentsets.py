"""Agent sets: reviewed manifests that add toolchains and pi extensions to
the pi agent image.

A set is a directory with a `set.toml` (config/agent-sets/<name> in the
repository, local/agent-sets/<name> for private sets). The user names the
sets to load in LLM_AGENT_SETS or with `--sets`; the wrapper renders the
base pi stage plus one `agent` stage with every selected set into
build/agents/pi/<tag>/, together with the files the entrypoint reads (the pi
package list, the tools note, the pi-lens configuration). The tag is a
digest of the selection, so images of different selections coexist and
parallel starts of different selections never share a render directory.
Nothing is installed at run time.

A manifest is code: its lines run as root while the image builds, with the
build's network access. The keys are a vocabulary that keeps a reviewer's
reading of a diff honest, not a sandbox.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import TokenCrateError, presets
from .names import SET_NAME_RE, SHA256_RE, UI_ACTIONS

SCHEMA = 1
MANIFEST = "set.toml"
SETS_ROOT = "/opt/tokencrate/sets"
HOME_SEED = "/opt/tokencrate/home-seed"
# Where a rendered stage puts the files the entrypoint reads.
PACKAGES_FILE = "/opt/tokencrate/pi-packages.txt"
NOTE_FILE = f"{HOME_SEED}/.pi/agent/AGENTS.md"
PI_LENS_FILE = "/opt/tokencrate/pi-lens.json"
NOTE_HEADER = (
    "This container has no internet. "
    "Package installs (npm, pip, apt) fail unless the session was started with --egress."
)
ROOTS = (("config", "config/agent-sets"), ("local", "local/agent-sets"))

APT_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Non-empty: an empty value renders `ENV PATH=${PATH}:`, whose trailing
# entry is the working directory, which the entrypoint has set to the project.
ENV_VALUE_RE = re.compile(r"^[^\s\"'\\$`]+$")
URL_RE = re.compile(r"^https://[A-Za-z0-9._~%+:/@-]+$")
ABSOLUTE_RE = re.compile(r"^/[A-Za-z0-9._+/@-]+$")
RELATIVE_RE = re.compile(r"^[A-Za-z0-9._+@-]+(/[A-Za-z0-9._+@-]+)*$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
SHA512_RE = re.compile(r"^[0-9a-f]{128}$")
KNOWN_KEYS = {"schema", "description", "apt", "asset", "npm", "env", "build", "note", "pi_packages", "pi_lens", "ui"}
ASSET_KEYS = {"url", "sha256", "sha512", "into", "strip", "mode"}
UI_KEYS = {"command", "port"}
UI_OPTIONAL_KEYS = {"identity"}
UI_DIRECTORIES = (".pi-web", ".paseo")
COMMAND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class AgentSet:
    name: str
    directory: Path
    # The set directory relative to the repository root (the build context).
    source: str
    description: str
    apt: list[str] = field(default_factory=list)
    assets: list[dict] = field(default_factory=list)
    npm: dict | None = None
    env: dict[str, str] = field(default_factory=dict)
    build: list[str] = field(default_factory=list)
    note: str = ""
    pi_packages: list[str] = field(default_factory=list)
    pi_lens: dict = field(default_factory=dict)
    # A set that provides a browser UI: the program `ui <set>` runs instead
    # of `pi` (a name on the image's PATH, no arguments) and the container
    # port it listens on.
    ui: dict | None = None

    @property
    def target(self) -> str:
        return f"{SETS_ROOT}/{self.name}"


def fail(context: str, message: str) -> TokenCrateError:
    return TokenCrateError(f"{context}: {message}")


def expect_list_of_strings(table: dict, key: str, context: str) -> list[str]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise fail(context, f"{key} must be a list of strings")
    return value


def relative_path(value: object, what: str, context: str) -> str:
    if not isinstance(value, str) or not RELATIVE_RE.fullmatch(value) or ".." in value.split("/"):
        raise fail(context, f"{what} must be a relative path below the set directory: {value!r}")
    return value


def absolute_path(value: object, what: str, context: str) -> str:
    if not isinstance(value, str) or not ABSOLUTE_RE.fullmatch(value) or ".." in value.split("/"):
        raise fail(context, f"{what} must be an absolute path: {value!r}")
    return value


def asset_kind(url: str) -> str:
    """How an asset is installed: extracted (`tar`, `zip`) or copied as one file."""
    if url.endswith((".tar.gz", ".tgz")):
        return "tar"
    if url.endswith(".zip"):
        return "zip"
    return "file"


def read_asset(entry: dict, context: str) -> dict:
    unknown = sorted(set(entry) - ASSET_KEYS)
    if unknown:
        raise fail(context, f"asset has unknown key(s): {', '.join(unknown)}")
    url = entry.get("url")
    if isinstance(url, str) and "@" in url.partition("://")[2].split("/", 1)[0]:
        raise fail(context, "asset url must not contain credentials")
    if not isinstance(url, str) or not URL_RE.fullmatch(url):
        raise fail(context, f"asset url must be an https URL of plain characters: {url!r}")
    sha256, sha512 = entry.get("sha256"), entry.get("sha512")
    if (sha256 is None) == (sha512 is None):
        raise fail(context, f"asset {url} needs exactly one of sha256 and sha512")
    if sha256 is not None and not (isinstance(sha256, str) and SHA256_RE.fullmatch(sha256)):
        raise fail(context, f"asset {url}: sha256 must be 64 hex characters")
    if sha512 is not None and not (isinstance(sha512, str) and SHA512_RE.fullmatch(sha512)):
        raise fail(context, f"asset {url}: sha512 must be 128 hex characters")
    into = absolute_path(entry.get("into"), "asset into", context)
    kind = asset_kind(url)
    strip = entry.get("strip", 0)
    if not isinstance(strip, int) or strip < 0 or (strip and kind != "tar"):
        raise fail(context, f"asset {url}: strip is a non-negative integer and applies to .tar.gz assets only")
    mode = entry.get("mode", "0644")
    if not isinstance(mode, str) or not MODE_RE.fullmatch(mode) or ("mode" in entry and kind != "file"):
        raise fail(context, f"asset {url}: mode is an octal mode such as 0755 and applies to plain files only")
    return {"url": url, "sha256": sha256, "sha512": sha512, "into": into, "strip": strip, "mode": mode, "kind": kind}


def read_manifest(directory: Path, source: str) -> AgentSet:
    path = directory / MANIFEST
    context = str(path)
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise fail(context, f"cannot read the manifest ({error})") from error
    unknown = sorted(set(table) - KNOWN_KEYS)
    if unknown:
        raise fail(context, f"unknown key(s): {', '.join(unknown)}")
    if table.get("schema") != SCHEMA:
        raise fail(context, f"schema must be {SCHEMA}")
    name = directory.name
    if not SET_NAME_RE.fullmatch(name):
        raise fail(context, f"unsafe set name: {name}")
    description = table.get("description")
    if not isinstance(description, str) or not description.strip() or "\n" in description.strip():
        raise fail(context, "description must be one non-empty line")

    apt = expect_list_of_strings(table, "apt", context)
    for package in apt:
        if not APT_RE.fullmatch(package):
            raise fail(context, f"apt package name is not a Debian package name: {package!r}")

    assets_raw = table.get("asset", [])
    if not isinstance(assets_raw, list) or not all(isinstance(item, dict) for item in assets_raw):
        raise fail(context, "asset must be an array of tables")
    assets = [read_asset(entry, context) for entry in assets_raw]

    npm = table.get("npm")
    if npm is not None:
        if not isinstance(npm, dict) or set(npm) - {"omit_peer"} or not isinstance(npm.get("omit_peer", False), bool):
            raise fail(context, "npm accepts only omit_peer (a boolean)")
        for required in ("package.json", "package-lock.json"):
            if not (directory / required).is_file():
                raise fail(context, f"npm needs {required} next to the manifest")
        npm = {"omit_peer": bool(npm.get("omit_peer", False))}

    env = table.get("env", {})
    if not isinstance(env, dict):
        raise fail(context, "env must be a table")
    for key, value in env.items():
        if not ENV_KEY_RE.fullmatch(key):
            raise fail(context, f"env key is not a variable name: {key!r}")
        if not isinstance(value, str) or not ENV_VALUE_RE.fullmatch(value):
            raise fail(context, f"env {key}: the value may not contain whitespace, quotes, or shell characters")

    build = expect_list_of_strings(table, "build", context)
    for line in build:
        if not line.strip() or "\n" in line or line.lstrip().startswith("#"):
            raise fail(context, "build lines must be single non-empty shell lines, not comments")

    note = table.get("note", "")
    if not isinstance(note, str):
        raise fail(context, "note must be a string")

    pi_packages = [
        relative_path(item, "pi_packages entry", context)
        for item in expect_list_of_strings(table, "pi_packages", context)
    ]

    pi_lens = table.get("pi_lens", {})
    if not isinstance(pi_lens, dict):
        raise fail(context, "pi_lens must be a table")

    ui = table.get("ui")
    if ui is not None:
        if name in UI_ACTIONS:
            raise fail(context, f"UI set name {name!r} is reserved for a ui command")
        if not isinstance(ui, dict) or not UI_KEYS <= set(ui) <= UI_KEYS | UI_OPTIONAL_KEYS:
            raise fail(context, "ui must be a table with command and port, and at most identity")
        if not isinstance(ui["command"], str) or not COMMAND_RE.fullmatch(ui["command"]):
            raise fail(context, f"ui command must be a program name without a path or arguments: {ui['command']!r}")
        if not isinstance(ui["port"], int) or isinstance(ui["port"], bool) or not 1024 <= ui["port"] <= 65535:
            raise fail(context, "ui port must be an integer between 1024 and 65535")
        identity = ui.get("identity", [])
        if not isinstance(identity, list) or not all(isinstance(item, str) for item in identity):
            raise fail(context, "ui identity must be a list of file paths relative to the agent home")
        for item in identity:
            parts = item.split("/")
            if len(parts) != 2 or parts[0] not in UI_DIRECTORIES or parts[1] in ("", ".", ".."):
                raise fail(
                    context, f"ui identity path must name a file directly below {' or '.join(UI_DIRECTORIES)}: {item!r}"
                )
        ui = {"command": ui["command"], "port": ui["port"], "identity": list(identity)}

    return AgentSet(
        name,
        directory,
        source,
        description.strip(),
        apt,
        assets,
        npm,
        dict(env),
        build,
        note.strip(),
        pi_packages,
        pi_lens,
        ui,
    )


def set_directories(root: Path, name: str) -> list[tuple[Path, str]]:
    """Where a set of this name exists below the checkout root: under
    config/, under local/, or both."""
    if not SET_NAME_RE.fullmatch(name):
        raise TokenCrateError(f"unsafe agent set name: {name}")
    found = []
    for prefix, relative in ROOTS:
        directory = root / prefix / "agent-sets" / name
        if (directory / MANIFEST).is_file():
            found.append((directory, f"{relative}/{name}"))
    return found


def catalog(root: Path) -> dict[str, AgentSet]:
    """Every set under config/agent-sets and local/agent-sets, by name."""
    sets: dict[str, AgentSet] = {}
    for prefix, _ in ROOTS:
        base = root / prefix / "agent-sets"
        if not base.is_dir():
            continue
        for directory in sorted(path for path in base.iterdir() if (path / MANIFEST).is_file()):
            sets[directory.name] = load_set(root, directory.name)
    return sets


def load_set(root: Path, name: str) -> AgentSet:
    found = set_directories(root, name)
    if not found:
        raise TokenCrateError(f"unknown agent set: {name} (run: bash bin/tokencrate agent-sets list)")
    if len(found) > 1:
        raise TokenCrateError(f"agent set {name} exists in both config/agent-sets and local/agent-sets")
    directory, source = found[0]
    return read_manifest(directory, source)


def select(root: Path, requested: str) -> list[AgentSet]:
    """The sets named in `requested` (a comma-separated list), each once, in
    order; only the named manifests are read."""
    names = [name for name in requested.split(",") if name]
    if len(names) != len(set(names)):
        raise TokenCrateError(f"an agent set is named twice: {requested}")
    return [load_set(root, name) for name in names]


# --- Rendering ---------------------------------------------------------------


def run_lines(lines: list[str]) -> str:
    return "RUN " + " \\\n    && ".join(lines) + "\n"


def asset_lines(asset: dict) -> list[str]:
    """Download to a fixed name, verify, install; the URL is only ever quoted."""
    algorithm, checksum = ("sha256", asset["sha256"]) if asset["sha256"] else ("sha512", asset["sha512"])
    download = {"tar": "/tmp/asset.tar.gz", "zip": "/tmp/asset.zip", "file": "/tmp/asset"}[asset["kind"]]
    lines = [f'curl -fsSL -o {download} "{asset["url"]}"', f'echo "{checksum}  {download}" | {algorithm}sum -c -']
    into = asset["into"]
    if asset["kind"] == "tar":
        strip = f" --strip-components={asset['strip']}" if asset["strip"] else ""
        lines += [f"mkdir -p {into}", f"tar -xzf {download} -C {into}{strip}"]
    elif asset["kind"] == "zip":
        lines += [f"mkdir -p {into}", f"unzip -q {download} -d {into}"]
    else:
        lines.append(f"install -D -m {asset['mode']} {download} {into}")
    lines.append(f"rm -f {download}")
    return lines


def render_set(entry: AgentSet) -> str:
    """One set: variables, packages, and assets (which depend only on the
    manifest text) before the set directory copy, so an edit to the
    manifest or a set file does not repeat the downloads."""
    target = entry.target
    out = [f"\n# --- agent set {entry.name}\n"]
    if entry.env:
        assignments = [
            f"PATH=${{PATH}}:{value}" if key == "PATH" else f"{key}={value}" for key, value in entry.env.items()
        ]
        out.append("ENV " + " \\\n    ".join(assignments) + "\n")
    if entry.apt:
        packages = " ".join(sorted(entry.apt))
        out.append(
            run_lines(
                [
                    "apt-get update",
                    f"apt-get install -y --no-install-recommends {packages}",
                    "rm -rf /var/lib/apt/lists/*",
                ]
            )
        )
    for asset in entry.assets:
        out.append(run_lines(asset_lines(asset)))
    out.append(f"COPY {entry.source} {target}\n")
    if entry.npm or entry.build:
        out.append(f"WORKDIR {target}\n")
        if entry.npm:
            omit = " --omit=peer" if entry.npm["omit_peer"] else ""
            out.append(run_lines([f"npm ci --ignore-scripts{omit}", "npm audit signatures", "npm cache clean --force"]))
        if entry.build:
            # JSON keeps real line breaks inside Bash's script: Dockerfile
            # continuations would let an inline comment swallow later steps.
            command = ["/bin/bash", "-e", "-o", "pipefail", "-c", "\n".join(entry.build)]
            out.append("RUN " + json.dumps(command) + "\n")
        out.append("WORKDIR /\n")
    return "".join(out)


def merge(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def selection_tag(base_dockerfile: str, selected: list[AgentSet]) -> str:
    """A digest of everything the rendered image is a function of: the base
    Dockerfile, the selection in order, and every file of every set.

    A node_modules a maintainer left in a set directory is not part of it:
    .dockerignore keeps it out of the build context, so it reaches no
    image, and hashing it would change the tag on every local install."""
    digest = hashlib.sha256(base_dockerfile.encode())
    for entry in selected:
        digest.update(b"\0set\0" + entry.source.encode())
        for path in sorted(p for p in entry.directory.rglob("*") if p.is_file() and "node_modules" not in p.parts):
            digest.update(b"\0" + str(path.relative_to(entry.directory)).encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@dataclass(frozen=True)
class Rendered:
    tag: str
    dockerfile: str
    packages: str
    note: str
    pi_lens: str


def render_selection(base_dockerfile: str, selected: list[AgentSet]) -> Rendered:
    """The rendered files for one selection: the base Dockerfile plus one
    `agent` stage with every selected set, and the files the stage copies."""
    tag = selection_tag(base_dockerfile, selected)
    stage = [
        (
            "\n\n# The `agent` stage: the pi stage plus the selected agent sets, rendered\n"
            "# by the wrapper from the manifests under config/agent-sets and\n"
            "# local/agent-sets. Do not edit; edit a manifest.\n"
            "FROM pi AS agent\n"
        )
    ]
    packages: list[str] = []
    notes = [NOTE_HEADER]
    pi_lens: dict = {}
    for entry in selected:
        stage.append(render_set(entry))
        packages += [f"{entry.target}/{package}" for package in entry.pi_packages]
        if entry.note:
            notes.append(entry.note)
        pi_lens = merge(pi_lens, entry.pi_lens)
    stage.append(
        "\n# The files the entrypoint reads, rendered from the selection.\n"
        f"COPY build/agents/pi/{tag}/pi-packages.txt {PACKAGES_FILE}\n"
        f"COPY build/agents/pi/{tag}/AGENTS.md {NOTE_FILE}\n"
        f"COPY build/agents/pi/{tag}/pi-lens.json {PI_LENS_FILE}\n"
    )
    return Rendered(
        tag,
        base_dockerfile.rstrip("\n") + "".join(stage),
        "".join(f"{package}\n" for package in packages),
        "\n".join(notes) + "\n",
        json.dumps(pi_lens, indent=2) + "\n",
    )


def render(root: Path, build_dir: Path, selected: list[AgentSet]) -> str:
    """Write build/agents/pi/<tag>/{Dockerfile,pi-packages.txt,AGENTS.md,pi-lens.json}
    below build_dir for the selection and return the tag."""
    base = (root / "services" / "agents" / "Dockerfile").read_text(encoding="utf-8")
    rendered = render_selection(base, selected)
    output = build_dir / "agents" / "pi" / rendered.tag
    output.mkdir(parents=True, exist_ok=True)
    presets.write_atomic(output / "Dockerfile", rendered.dockerfile)
    presets.write_atomic(output / "pi-packages.txt", rendered.packages)
    presets.write_atomic(output / "AGENTS.md", rendered.note)
    presets.write_atomic(output / "pi-lens.json", rendered.pi_lens)
    return rendered.tag
