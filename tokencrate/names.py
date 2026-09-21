"""Names of the reviewed data files under config/ (presets), and the catalog
and selection shared by model sets and skill sets."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from . import TokenCrateError

PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
SET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# These CLI verbs cannot also name a UI set.
UI_ACTIONS = ("stop", "logs")


# A lowercase hex SHA-256, as the manifests and lockfiles spell it.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def preset_file(config_dir: Path, name: str) -> Path:
    if not PRESET_NAME_RE.fullmatch(name):
        raise TokenCrateError(f"unsafe preset name: {name}")
    path = config_dir / "presets" / f"{name}.toml"
    if not path.is_file():
        raise TokenCrateError(f"unknown preset: {name} (run: bash bin/tokencrate presets list)")
    return path


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
