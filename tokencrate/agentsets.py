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
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import TokenCrateError
from .names import SET_NAME_RE, SHA256_RE, UI_ACTIONS, parse_list, read_toml, relative_path
from .names import description as read_description

MANIFEST = "set.toml"
SETS_ROOT = "/opt/tokencrate/sets"
HOME_SEED = "/opt/tokencrate/home-seed"
# Where a rendered stage puts the files the entrypoint reads.
PACKAGES_FILE = "/opt/tokencrate/pi-packages.txt"
NOTE_FILE = f"{HOME_SEED}/.pi/agent/AGENTS.md"
PI_LENS_FILE = "/opt/tokencrate/pi-lens.json"
# One script per selected set with `check` lines; the containment check
# runs each as the container user.
CHECKS_DIR = "/opt/tokencrate/checks"
# True whichever way the session was started: the note cannot see the flag.
NOTE_HEADER = (
    "This container has no internet unless the session was started with --egress or --cloud; "
    "without it, package installs (npm, pip, apt) fail. "
    "Try an install once before working around a missing package."
)
ROOTS = (("config", "config/agent-sets"), ("local", "local/agent-sets"))

APT_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Non-empty: an empty value renders `ENV PATH=${PATH}:`, whose trailing
# entry is the working directory, which the entrypoint has set to the project.
ENV_VALUE_RE = re.compile(r"^[^\s\"'\\$`]+$")
URL_RE = re.compile(r"^https://[A-Za-z0-9._~%+:/@-]+$")
ABSOLUTE_RE = re.compile(r"^/[A-Za-z0-9._+/@-]+$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
SHA512_RE = re.compile(r"^[0-9a-f]{128}$")
KNOWN_KEYS = {
    "schema",
    "description",
    "apt",
    "asset",
    "npm",
    "env",
    "build",
    "check",
    "note",
    "pi_packages",
    "pi_lens",
    "ui",
}
ASSET_KEYS = {"url", "sha256", "sha512", "into", "strip", "mode"}
UI_KEYS = {"command", "port", "state"}
UI_OPTIONAL_KEYS = {"identity", "host_port"}
# A UI set's name ends the names of its two containers, `tokencrate-ui-<set>`
# and `tokencrate-ui-forward-<set>`: a DNS label (63 characters), and no
# set may name another set's forwarder.
UI_SET_NAME_RE = re.compile(r"^(?!forward-)[a-z0-9][a-z0-9-]{0,40}$")
# The home directories an agent's own state occupies; a UI's state directory
# is a sibling of them, never one of them.
RESERVED_HOME_DIRECTORIES = {".", "..", ".pi", ".omp", ".agents", ".config", ".local", ".cache"}
COMMAND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STATE_RE = re.compile(r"^\.?[A-Za-z0-9][A-Za-z0-9._-]*$")


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
    # What `smoke --agent` runs inside the container to prove the set works
    # for the container user with no route out; the last line it prints is
    # the report. tests/test_agentsets.py requires it of every shipped set.
    check: list[str] = field(default_factory=list)
    note: str = ""
    pi_packages: list[str] = field(default_factory=list)
    pi_lens: dict = field(default_factory=dict)
    # A set that provides a browser UI: the program `ui <set>` runs instead
    # of `pi` (a name on the image's PATH, no arguments), the container port
    # it listens on, the home directory that holds its state (the one UI
    # path bound from the host), the identity files kept per set, and the
    # host port it publishes by default (None: `--port` or the setting).
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
    table = read_toml(path, KNOWN_KEYS, context)
    name = directory.name
    if not SET_NAME_RE.fullmatch(name):
        raise fail(context, f"unsafe set name: {name}")
    description = read_description(table, context)

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
    check = expect_list_of_strings(table, "check", context)
    for key, lines in (("build", build), ("check", check)):
        for line in lines:
            if not line.strip() or "\n" in line or line.lstrip().startswith("#"):
                raise fail(context, f"{key} lines must be single non-empty shell lines, not comments")

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
        # The name goes into the containers' names, one of which resolves
        # on the ui network: a DNS label, and never a sibling's forwarder.
        if not UI_SET_NAME_RE.fullmatch(name):
            raise fail(
                context,
                f"UI set name {name!r} must be lowercase letters, digits, and hyphens, at most 41 characters, "
                "and not start with forward-",
            )
        if not isinstance(ui, dict) or not UI_KEYS <= set(ui) <= UI_KEYS | UI_OPTIONAL_KEYS:
            raise fail(context, "ui must be a table with command, port, and state, and at most identity and host_port")
        if not isinstance(ui["command"], str) or not COMMAND_RE.fullmatch(ui["command"]):
            raise fail(context, f"ui command must be a program name without a path or arguments: {ui['command']!r}")
        for key in ("port", "host_port"):
            value = ui.get(key, 1024)
            if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
                raise fail(context, f"ui {key} must be an integer between 1024 and 65535")
        state = ui["state"]
        if not isinstance(state, str) or not STATE_RE.fullmatch(state) or state in RESERVED_HOME_DIRECTORIES:
            raise fail(
                context, f"ui state must name one directory below the agent home, not the agent's own: {state!r}"
            )
        identity = ui.get("identity", [])
        if not isinstance(identity, list) or not all(isinstance(item, str) for item in identity):
            raise fail(context, "ui identity must be a list of file paths relative to the agent home")
        for item in identity:
            parts = item.split("/")
            if len(parts) != 2 or parts[0] != state or parts[1] in ("", ".", ".."):
                raise fail(
                    context, f"ui identity path must name a file directly below the state directory {state}: {item!r}"
                )
        ui = {
            "command": ui["command"],
            "port": ui["port"],
            "state": state,
            "identity": list(identity),
            "host_port": ui.get("host_port"),
        }

    return AgentSet(
        name,
        directory,
        source,
        description,
        apt,
        assets,
        npm,
        dict(env),
        build,
        check,
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
    return [load_set(root, name) for name in parse_list(requested, "agent set")]


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


def selection_tag(files: tuple[str, ...]) -> str:
    """A digest of the rendered files themselves, so that two renders with
    the same tag have the same content whatever produced them: a change to
    a manifest, to the base Dockerfile, or to the renderer changes the
    tag. A set's other files reach the image through the build context,
    whose COPY layer the engine hashes itself, so an edit there rebuilds
    the image under the same tag."""
    digest = hashlib.sha256()
    for text in files:
        digest.update(text.encode() + b"\0")
    return digest.hexdigest()[:12]


@dataclass(frozen=True)
class Rendered:
    tag: str
    dockerfile: str
    packages: str
    note: str
    pi_lens: str
    # Set name -> the check script; only sets with check lines.
    checks: dict[str, str]


def render_selection(base_dockerfile: str, selected: list[AgentSet]) -> Rendered:
    """The rendered files for one selection: the base Dockerfile plus one
    `agent` stage with every selected set, and the files the stage copies.

    A node_modules a maintainer left in a set directory is not part of it:
    .dockerignore keeps it out of the build context, so it reaches no
    image, and the manifest, not the directory, is what is rendered."""
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
    checks: dict[str, str] = {}
    for entry in selected:
        stage.append(render_set(entry))
        packages += [f"{entry.target}/{package}" for package in entry.pi_packages]
        if entry.note:
            notes.append(entry.note)
        pi_lens = merge(pi_lens, entry.pi_lens)
        if entry.check:
            checks[entry.name] = (
                f"# Rendered from {entry.source}/{MANIFEST} [check]; do not edit. Run by the\n"
                "# containment check as the container user, in a scratch directory.\n" + "\n".join(entry.check) + "\n"
            )
    # The Dockerfile names its own directory, so the tag is taken before
    # that line is written, over everything else the directory holds.
    stage.append("\n# The files the entrypoint and the containment check read, rendered from the selection.\n")
    dockerfile = base_dockerfile.rstrip("\n") + "".join(stage)
    files = (
        "".join(f"{package}\n" for package in packages),
        "\n".join(notes) + "\n",
        json.dumps(pi_lens, indent=2) + "\n",
    )
    tag = selection_tag((dockerfile, *files, *(f"{name}\0{script}" for name, script in sorted(checks.items()))))
    dockerfile += (
        f"COPY build/agents/pi/{tag}/pi-packages.txt {PACKAGES_FILE}\n"
        f"COPY build/agents/pi/{tag}/AGENTS.md {NOTE_FILE}\n"
        f"COPY build/agents/pi/{tag}/pi-lens.json {PI_LENS_FILE}\n"
        f"COPY build/agents/pi/{tag}/checks {CHECKS_DIR}\n"
    )
    return Rendered(tag, dockerfile, *files, checks)


def render(root: Path, build_dir: Path, selected: list[AgentSet]) -> str:
    """Write build/agents/pi/<tag>/{Dockerfile,pi-packages.txt,AGENTS.md,pi-lens.json}
    and checks/<set> below build_dir for the selection and return the tag.

    The tag is a digest of everything the files are a function of, so a
    directory of that name is complete: it is written beside its place
    and renamed into it, and a start that finds it does nothing. Parallel
    starts of one selection therefore never see a half-written render or
    remove each other's files."""
    base = (root / "services" / "agents" / "Dockerfile").read_text(encoding="utf-8")
    rendered = render_selection(base, selected)
    parent = build_dir / "agents" / "pi"
    output = parent / rendered.tag
    # The rename is atomic, so the Dockerfile's presence means the whole
    # directory; a directory without it is repaired.
    if (output / "Dockerfile").is_file():
        return rendered.tag
    parent.mkdir(parents=True, exist_ok=True)
    # Named for .dockerignore: a staging directory a crash left behind must
    # not enter the build context.
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{rendered.tag}-", dir=parent))
    try:
        # The build context is read by the engine; a temporary directory is
        # private by default.
        staging.chmod(0o755)
        (staging / "Dockerfile").write_text(rendered.dockerfile, encoding="utf-8")
        (staging / "pi-packages.txt").write_text(rendered.packages, encoding="utf-8")
        (staging / "AGENTS.md").write_text(rendered.note, encoding="utf-8")
        (staging / "pi-lens.json").write_text(rendered.pi_lens, encoding="utf-8")
        (staging / "checks").mkdir()
        for name, script in rendered.checks.items():
            (staging / "checks" / name).write_text(script, encoding="utf-8")
        try:
            if output.is_dir() and not any(output.iterdir()):
                output.rmdir()
            staging.rename(output)
        except OSError:
            # Another start renamed its own render into place first.
            if not (output / "Dockerfile").is_file():
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return rendered.tag
