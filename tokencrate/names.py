"""Names of the reviewed data files under config/ (presets), the catalog
and selection shared by model sets and skill sets, and the rules every
manifest kind and every comma-separated list share: one reader, one list
parser, one relative-path rule, one description rule, one hex pattern per
digest length."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path

from . import TokenCrateError

PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
SET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# These CLI verbs cannot also name a UI set.
UI_ACTIONS = ("stop", "logs")
# Every manifest kind carries this schema number.
SCHEMA = 1

# A lowercase hex SHA-256, as the manifests and lockfiles spell it, and a
# full lowercase Git commit or Hugging Face revision.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
# A relative path a manifest names: below its own directory, no `.` or `..`
# segment, and only characters that survive a rendered Dockerfile line and a
# shell command unquoted, because the agent-set renderer writes them there.
# Every shipped skill path and model-set destination fits.
RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._+@-]+(/[A-Za-z0-9._+@-]+)*$")


def parse_list(value: str, kind: str, pattern: re.Pattern[str] = SET_NAME_RE) -> list[str]:
    """The names in a comma-separated list, each once, in order. A
    hand-edited list carries spaces around a name, empty entries, and
    repeats; none of them changes what is selected. A name the pattern
    rejects is refused before anything looks it up."""
    names: list[str] = []
    for raw in value.split(","):
        name = raw.strip()
        if not name:
            continue
        if not pattern.fullmatch(name):
            raise TokenCrateError(f"unsafe {kind} name: {name!r}")
        if name not in names:
            names.append(name)
    return names


def read_toml(path: Path, known_keys: set[str], context: str) -> dict:
    """A manifest's top-level table: readable, only known keys, schema 1.
    Every manifest kind words these three failures the same way."""
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise TokenCrateError(f"{context}: cannot read the manifest ({error})") from error
    unknown = sorted(set(table) - known_keys)
    if unknown:
        raise TokenCrateError(f"{context}: unknown key(s): {', '.join(unknown)}")
    if table.get("schema") != SCHEMA:
        raise TokenCrateError(f"{context}: schema must be {SCHEMA}")
    return table


def description(table: dict, context: str) -> str:
    """The one-line description every manifest kind carries, stripped."""
    value = table.get("description")
    if not isinstance(value, str) or not value.strip() or "\n" in value.strip():
        raise TokenCrateError(f"{context}: description must be one non-empty line")
    return value.strip()


def relative_path(value: object, what: str, context: str) -> str:
    """A path below the manifest's own directory (see RELATIVE_PATH_RE)."""
    if not isinstance(value, str) or not RELATIVE_PATH_RE.fullmatch(value) or {".", ".."} & set(value.split("/")):
        raise TokenCrateError(f"{context}: {what} must be a relative path of letters, digits, and ._+@-: {value!r}")
    return value


def load_catalog(manifest_dir: Path, read_manifest: Callable[[Path], object], kind: str) -> dict:
    """Every manifest below manifest_dir, keyed by name, in set-name order:
    sorting file names would put `<name>-suffix` before `<name>`, because
    the dash sorts before the dot of the extension."""
    catalog: dict = {}
    for path in sorted(manifest_dir.glob("*.toml"), key=lambda item: item.stem):
        entry = read_manifest(path)
        catalog[entry.name] = entry
    if not catalog:
        raise TokenCrateError(f"no {kind}s found in {manifest_dir}")
    return catalog


def select_sets(catalog: dict, names: list[str], kind: str) -> list:
    """The catalog entries named on the command line (each once), or every
    entry for `all`."""
    if not names:
        raise TokenCrateError(f"provide one or more {kind} names, or all")
    if "all" in names:
        if len(names) != 1:
            raise TokenCrateError(f"all cannot be combined with named {kind}s")
        return list(catalog.values())
    selected: list = []
    seen: set[str] = set()
    for name in names:
        if not SET_NAME_RE.fullmatch(name):
            raise TokenCrateError(f"unsafe {kind} name: {name}")
        if name not in catalog:
            raise TokenCrateError(f"unknown {kind}: {name} (available: {', '.join(catalog)})")
        if name not in seen:
            selected.append(catalog[name])
            seen.add(name)
    return selected
