"""Fetch or inspect commit-pinned Agent Skills declared by skill-set manifests.

The CLI runs this module in-process on the host: ``skills fetch`` and
``skills status`` call :func:`fetch`, and ``agent`` refuses to start while
:func:`missing_skills` names skills of a selected set that were never
fetched. :func:`digest_command` is not wired to a command; CONTRIBUTING.md
documents it as the snippet that prints a skill set's tree digest.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from . import TokenCrateError
from .names import SET_NAME_RE, SHA256_RE, load_catalog

SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATH_RE = re.compile(r"^/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:\.git)?$")
LICENSE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*['\"]?([^'\"\s]+)['\"]?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Skill:
    name: str
    repository: str
    commit: str
    path: str
    sha256: str
    license: str


@dataclass(frozen=True)
class SkillSet:
    name: str
    description: str
    skills: tuple[Skill, ...]


def load_allowed_hosts(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TokenCrateError(f"could not read allowed Git hosts: {error}") from error
    hosts = {line.strip().lower() for line in lines if line.strip() and not line.lstrip().startswith("#")}
    if not hosts or any(not HOST_RE.fullmatch(host) for host in hosts):
        raise TokenCrateError("allowed Git hosts must contain valid lowercase host names")
    return hosts


def normalize_public_repository(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not REPOSITORY_PATH_RE.fullmatch(parsed.path)
    ):
        return None
    path = parsed.path[:-4] if parsed.path.lower().endswith(".git") else parsed.path
    return f"https://{parsed.hostname.lower()}{path}"


def validate_repository(value: object, allowed_hosts: set[str]) -> str:
    normalized = normalize_public_repository(value)
    if normalized is None or urlsplit(normalized).hostname not in allowed_hosts:
        raise TokenCrateError(
            "skill repositories must be credential-free HTTPS owner/repository URLs "
            "on a host listed in allowed-git-hosts.txt"
        )
    return normalized


def safe_subpath(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise TokenCrateError(f"{context}: path must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts) or "\\" in value:
        raise TokenCrateError(f"{context}: path must be a safe relative path: {value!r}")
    return path.as_posix()


def read_manifest(path: Path, allowed_hosts: set[str]) -> SkillSet:
    name = path.stem
    if not SET_NAME_RE.fullmatch(name) or name == "all":
        raise TokenCrateError(f"unsafe skill-set filename: {path.name}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise TokenCrateError(f"could not read skill-set manifest {path}: {error}") from error
    unknown = set(document) - {"schema", "description", "skill"}
    if unknown:
        raise TokenCrateError(f"{name}: unknown field(s): {', '.join(sorted(unknown))}")
    if document.get("schema") != 1:
        raise TokenCrateError(f"{name}: schema must be 1")
    description = document.get("description", "")
    if not isinstance(description, str):
        raise TokenCrateError(f"{name}: description must be a string")
    raw_skills = document.get("skill")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise TokenCrateError(f"{name}: at least one [[skill]] entry is required")
    skills: list[Skill] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_skills, start=1):
        context = f"{name} skill {index}"
        if not isinstance(raw, dict) or set(raw) != {"name", "repository", "commit", "path", "sha256", "license"}:
            raise TokenCrateError(
                f"{context}: must contain exactly name, repository, commit, path, sha256, and license"
            )
        skill_name = raw["name"]
        if not isinstance(skill_name, str) or not SKILL_NAME_RE.fullmatch(skill_name):
            raise TokenCrateError(f"{context}: name must be a lowercase Agent Skills name")
        if skill_name in names:
            raise TokenCrateError(f"{name}: duplicate skill name: {skill_name}")
        names.add(skill_name)
        commit = raw["commit"]
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise TokenCrateError(f"{context}: commit must be a full lowercase Git commit")
        digest = raw["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise TokenCrateError(f"{context}: sha256 must be a lowercase tree digest")
        license_id = raw["license"]
        if not isinstance(license_id, str) or not LICENSE_RE.fullmatch(license_id):
            raise TokenCrateError(f"{context}: license must be an SPDX identifier")
        skills.append(
            Skill(
                name=skill_name,
                repository=validate_repository(raw["repository"], allowed_hosts),
                commit=commit,
                path=safe_subpath(raw["path"], context),
                sha256=digest,
                license=license_id,
            )
        )
    return SkillSet(name, description.strip(), tuple(skills))


def available_sets(manifest_dir: Path, allowed_hosts: set[str]) -> dict[str, SkillSet]:
    return load_catalog(manifest_dir, lambda path: read_manifest(path, allowed_hosts), "skill set")


# --- Git ---------------------------------------------------------------------


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_ASKPASS": "/bin/false",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_COUNT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": tempfile.gettempdir(),
        }
    )
    return environment


def git(path: Path, *arguments: str) -> str:
    command = [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=/bin/false",
        "-c",
        "http.followRedirects=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.untrackedCache=false",
        "-C",
        str(path),
        *arguments,
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=git_environment(),
    )
    if result.returncode != 0:
        raise TokenCrateError(f"git {' '.join(arguments[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def checkout_subtree(repository: str, commit: str, subpath: str, workdir: Path) -> Path:
    """Fetch exactly one commit and return the requested subtree inside workdir."""
    clone = workdir / "repository"
    clone.mkdir()
    git(clone, "init", "-q")
    git(clone, "remote", "add", "origin", repository)
    git(clone, "fetch", "-q", "--depth=1", "origin", commit)
    git(clone, "checkout", "-q", "--detach", "FETCH_HEAD")
    head = git(clone, "rev-parse", "HEAD").lower()
    if head != commit:
        raise TokenCrateError(f"{repository} resolved to {head}, expected {commit}")
    subtree = clone.joinpath(*PurePosixPath(subpath).parts)
    if subtree.is_symlink() or not subtree.is_dir():
        raise TokenCrateError(f"{repository}@{commit[:12]} has no directory at {subpath}")
    # An untrusted checkout could point an intermediate component outside the
    # clone through a symbolic link; the skill must live inside the clone.
    if not subtree.resolve().is_relative_to(clone.resolve()):
        raise TokenCrateError(f"{repository}@{commit[:12]}: {subpath} leaves the repository through a symbolic link")
    return subtree


# --- Tree digests ------------------------------------------------------------


def tree_digest(root: Path) -> str:
    """SHA-256 over sorted `<file sha256>  <relative path>` lines; symlinks are rejected."""
    entries: list[str] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        for name in sorted(file_names):
            path = Path(directory) / name
            if path.is_symlink():
                raise TokenCrateError(f"skills must not contain symbolic links: {path.relative_to(root)}")
            if not path.is_file():
                raise TokenCrateError(f"skills must contain regular files only: {path.relative_to(root)}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(f"{digest}  {path.relative_to(root).as_posix()}\n")
        for name in list(directory_names):
            if (Path(directory) / name).is_symlink():
                raise TokenCrateError(
                    f"skills must not contain symbolic links: {Path(directory, name).relative_to(root)}"
                )
    if not entries:
        raise TokenCrateError(f"skill directory is empty: {root}")
    return hashlib.sha256("".join(entries).encode("utf-8")).hexdigest()


def validate_skill_document(root: Path, expected_name: str) -> None:
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise TokenCrateError(f"skill {expected_name} has no SKILL.md")
    text = skill_file.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        raise TokenCrateError(f"skill {expected_name}: SKILL.md must start with YAML frontmatter")
    frontmatter = text.split("---", 2)
    if len(frontmatter) < 3:
        raise TokenCrateError(f"skill {expected_name}: SKILL.md frontmatter is not closed")
    match = FRONTMATTER_NAME_RE.search(frontmatter[1])
    if match is None or match.group(1) != expected_name:
        raise TokenCrateError(f"skill {expected_name}: SKILL.md frontmatter name must equal the directory name")
    if "description:" not in frontmatter[1]:
        raise TokenCrateError(f"skill {expected_name}: SKILL.md frontmatter needs a description")


# --- Actions -----------------------------------------------------------------


def installed_state(destination: Path, skill: Skill) -> str:
    if destination.is_symlink():
        return "conflict (symlink)"
    if not destination.exists():
        return "missing"
    if not destination.is_dir():
        return "conflict (not a directory)"
    try:
        digest = tree_digest(destination)
    except TokenCrateError:
        return "conflict (unsafe entries)"
    if digest != skill.sha256:
        return "different-digest"
    return "ready"


def missing_skills(skill_set: SkillSet, target: Path) -> list[str]:
    """Names of the set's skills that have no directory below target / set name.

    A symbolic link does not count: the agent must only load skills that
    fetch() verified and published in place."""
    set_dir = target / skill_set.name
    return [
        skill.name
        for skill in skill_set.skills
        if (set_dir / skill.name).is_symlink() or not (set_dir / skill.name).is_dir()
    ]


def fetch(selected: list[SkillSet], target: Path, *, verify_only: bool) -> int:
    """Install every skill of the selected sets below target, or with verify_only
    report each skill's state; the result is 1 when any skill is not ready.

    A skill is checked out, digested, and validated in a staging directory and
    then swapped into place with one rename; the previous copy survives as
    `.<name>.previous` until the swap has succeeded."""
    if target.is_symlink():
        raise TokenCrateError(f"skills target must not be a symlink: {target}")
    if not target.is_dir():
        raise TokenCrateError(f"skills directory does not exist: {target}")
    result = 0
    for skill_set in selected:
        set_dir = target / skill_set.name
        if set_dir.is_symlink():
            raise TokenCrateError(f"skill set directory must not be a symlink: {set_dir}")
        if skill_set.description:
            print(f"{skill_set.name}: {skill_set.description}")
        for skill in skill_set.skills:
            destination = set_dir / skill.name
            state = installed_state(destination, skill)
            if state == "ready":
                print(f"  {skill.name}: ready ({skill.commit[:12]})")
                continue
            if verify_only:
                print(f"  {skill.name}: {state} ({skill.commit[:12]})")
                result = 1
                continue
            if state.startswith("conflict"):
                raise TokenCrateError(f"{skill_set.name}/{skill.name}: {state}; move it aside and retry")
            # Stage below the set directory when it exists, otherwise below
            # target, and create the set directory only for a verified skill:
            # a fetch that fails on its first skill leaves nothing behind.
            staging_parent = set_dir if set_dir.is_dir() else target
            with tempfile.TemporaryDirectory(prefix=".tokencrate-skill-", dir=staging_parent) as raw_workdir:
                workdir = Path(raw_workdir)
                subtree = checkout_subtree(skill.repository, skill.commit, skill.path, workdir)
                staged = workdir / "staged"
                shutil.copytree(subtree, staged, symlinks=True)
                digest = tree_digest(staged)
                if digest != skill.sha256:
                    raise TokenCrateError(
                        f"{skill_set.name}/{skill.name}: tree digest {digest} does not match the pinned "
                        f"{skill.sha256}; review the upstream change before updating the manifest"
                    )
                validate_skill_document(staged, skill.name)
                set_dir.mkdir(parents=True, exist_ok=True)
                backup = set_dir / f".{skill.name}.previous"
                if backup.exists():
                    shutil.rmtree(backup)
                if destination.exists():
                    destination.replace(backup)
                staged.replace(destination)
                if backup.exists():
                    shutil.rmtree(backup)
            print(f"  {skill.name}: fetched ({skill.commit[:12]}, {skill.license})")
        if not verify_only and set_dir.is_dir():
            declared = {skill.name for skill in skill_set.skills}
            for path in set_dir.iterdir():
                if (
                    path.name not in declared
                    and not path.name.startswith(".")
                    and not path.is_symlink()
                    and path.is_dir()
                ):
                    shutil.rmtree(path)
                    print(f"  {path.name}: removed (not in the manifest)")
    return result


def digest_command(repository: str, commit: str, subpath: str, allowed_hosts: set[str]) -> str:
    """Return the tree digest of one pinned skill directory, for a new manifest row."""
    repository = validate_repository(repository, allowed_hosts)
    if not COMMIT_RE.fullmatch(commit):
        raise TokenCrateError("commit must be a full lowercase Git commit")
    subpath = safe_subpath(subpath, "digest")
    with tempfile.TemporaryDirectory(prefix="tokencrate-skill-digest-") as raw_workdir:
        subtree = checkout_subtree(repository, commit, subpath, Path(raw_workdir))
        digest = tree_digest(subtree)
        validate_skill_document(subtree, PurePosixPath(subpath).name)
    return digest
