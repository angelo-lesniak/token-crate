"""Fetch, verify, and draft pinned Hugging Face GGUF files declared by model-set manifests.

The CLI runs this module in-process on the host: ``models fetch`` calls
:func:`fetch` inside :func:`model_download_lock`, ``models status`` calls
:func:`status`, and ``models draft`` writes the text :func:`draft` returns.
The Hugging Face token arrives as a plain Python argument (the CLI captures
``HF_TOKEN`` in-process), so it never travels through an environment or a
command line, and :func:`open_url` sends it to the Hub host only.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import TokenCrateError
from .names import SET_NAME_RE, SHA256_RE, load_catalog

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MODEL_CARD_URL_RE = re.compile(
    r"^https://huggingface\.co/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/blob/[0-9a-f]{40}/README\.md$"
)
LICENSE_URL_RE = re.compile(
    r"^(?:"
    r"https://huggingface\.co/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/blob/[0-9a-f]{40}/[^\s]+"
    r"|https://cdn\.jsdelivr\.net/gh/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}/[^\s]+"
    r"|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/blob/[0-9a-f]{40}/[^\s]+"
    r")$"
)
TEMPLATE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.jinja$")
# [requires] llama_build: the first llama.cpp build that loads the set, as
# the pin spells it (b11100), or the sentinel for a build that no release
# carries yet; the renderer keeps such a set's presets out of the router.
LLAMA_BUILD_RE = re.compile(r"^b[1-9][0-9]*$")
UNRELEASED_BUILD = "unreleased"
SPLIT_RE = re.compile(r"^(?P<stem>.+)-(?P<index>\d{5})-of-(?P<total>\d{5})\.gguf$")
ROLES = ("weights", "split")
USER_AGENT = "TokenCrate-model-set-tool/1"
HUB_URL = "https://huggingface.co"
CHUNK_SIZE = 8 * 1024 * 1024
REDIRECT_CODES = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 10


@dataclass(frozen=True)
class License:
    name: str
    url: str


@dataclass(frozen=True)
class ModelFile:
    role: str
    repository: str
    revision: str
    source: str
    destination: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSet:
    name: str
    description: str
    upstream_model: str
    model_card: str
    mtp: bool
    chat_template_file: str
    licenses: tuple[License, ...]
    files: tuple[ModelFile, ...]
    # "" when any build loads the set; see LLAMA_BUILD_RE.
    llama_build: str = ""

    @property
    def weights(self) -> ModelFile:
        return next(model_file for model_file in self.files if model_file.role == "weights")

    @property
    def splits(self) -> tuple[ModelFile, ...]:
        return tuple(model_file for model_file in self.files if model_file.role == "split")


def safe_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TokenCrateError(f"{field} must be a non-empty path")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise TokenCrateError(f"{field} contains unsupported characters: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise TokenCrateError(f"{field} must be a safe relative path: {value!r}")
    return path.as_posix()


def require_keys(table: dict, allowed: set[str], context: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise TokenCrateError(f"unknown field(s) in {context}: {', '.join(sorted(unknown))}")


def optional_bool(document: dict, key: str, name: str) -> bool:
    value = document.get(key, False)
    if not isinstance(value, bool):
        raise TokenCrateError(f"{name}: {key} must be true or false")
    return value


def read_manifest(path: Path) -> ModelSet:
    name = path.stem
    if not SET_NAME_RE.fullmatch(name):
        raise TokenCrateError(f"unsafe model-set filename: {path.name}")
    if name == "all":
        raise TokenCrateError("all is reserved and cannot be a model-set filename")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise TokenCrateError(f"could not read {path}: {error}") from error
    if not isinstance(document, dict):
        raise TokenCrateError(f"{path} must contain a TOML table")
    require_keys(
        document,
        {
            "schema",
            "description",
            "upstream_model",
            "model_card",
            "mtp",
            "chat_template_file",
            "license",
            "file",
            "requires",
        },
        name,
    )
    if document.get("schema") != 1:
        raise TokenCrateError(f"{name}: schema must be 1")
    description = document.get("description")
    if not isinstance(description, str) or not description.strip():
        raise TokenCrateError(f"{name}: description must be a non-empty string")
    model_card = document.get("model_card")
    if not isinstance(model_card, str) or MODEL_CARD_URL_RE.fullmatch(model_card) is None:
        raise TokenCrateError(f"{name}: model_card must be an immutable Hugging Face README URL")
    upstream_model = document.get("upstream_model", "")
    if not isinstance(upstream_model, str) or (upstream_model and REPOSITORY_RE.fullmatch(upstream_model) is None):
        raise TokenCrateError(f"{name}: upstream_model must be an owner/repository name")
    mtp = optional_bool(document, "mtp", name)
    chat_template_file = document.get("chat_template_file", "")
    if not isinstance(chat_template_file, str) or (
        chat_template_file and TEMPLATE_FILE_RE.fullmatch(chat_template_file) is None
    ):
        raise TokenCrateError(f"{name}: chat_template_file must be a plain .jinja filename")
    requires = document.get("requires", {})
    if not isinstance(requires, dict):
        raise TokenCrateError(f"{name}: [requires] must be a table")
    require_keys(requires, {"llama_build"}, f"{name} requires")
    llama_build = requires.get("llama_build", "")
    if not isinstance(llama_build, str) or (
        llama_build and llama_build != UNRELEASED_BUILD and LLAMA_BUILD_RE.fullmatch(llama_build) is None
    ):
        raise TokenCrateError(
            f"{name}: llama_build must be a llama.cpp build number as pins.env spells it (b11100) or {UNRELEASED_BUILD}"
        )

    raw_licenses = document.get("license")
    if not isinstance(raw_licenses, list) or not raw_licenses:
        raise TokenCrateError(f"{name}: at least one [[license]] entry is required")
    licenses: list[License] = []
    for index, raw in enumerate(raw_licenses, start=1):
        if not isinstance(raw, dict):
            raise TokenCrateError(f"{name}: license {index} must be a table")
        require_keys(raw, {"name", "url"}, f"{name} license {index}")
        license_name = raw.get("name")
        url = raw.get("url")
        if not isinstance(license_name, str) or not license_name.strip():
            raise TokenCrateError(f"{name}: license {index} needs a name")
        if not isinstance(url, str) or LICENSE_URL_RE.fullmatch(url) is None:
            raise TokenCrateError(f"{name}: license {index} needs an immutable approved HTTPS URL")
        licenses.append(License(license_name.strip(), url))

    raw_files = document.get("file")
    if not isinstance(raw_files, list) or not raw_files:
        raise TokenCrateError(f"{name}: at least one [[file]] entry is required")
    files: list[ModelFile] = []
    destinations: set[str] = set()
    for index, raw in enumerate(raw_files, start=1):
        if not isinstance(raw, dict):
            raise TokenCrateError(f"{name}: file {index} must be a table")
        require_keys(
            raw,
            {"role", "repository", "revision", "source", "destination", "size", "sha256"},
            f"{name} file {index}",
        )
        role = raw.get("role")
        if role not in ROLES:
            raise TokenCrateError(f"{name}: file {index} role must be one of {', '.join(ROLES)}")
        repository = raw.get("repository")
        revision = raw.get("revision")
        source = safe_relative_path(raw.get("source"), f"{name} file {index} source")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            raise TokenCrateError(f"{name}: file {index} has an invalid repository")
        if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
            raise TokenCrateError(f"{name}: file {index} revision must be a full lowercase commit")
        destination = raw.get("destination", f"{repository}/{source}")
        destination = safe_relative_path(destination, f"{name} file {index} destination")
        size = raw.get("size")
        digest = raw.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise TokenCrateError(f"{name}: file {index} size must be a positive integer")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise TokenCrateError(f"{name}: file {index} sha256 must be lowercase hexadecimal")
        if destination in destinations:
            raise TokenCrateError(f"{name}: duplicate destination: {destination}")
        destinations.add(destination)
        files.append(ModelFile(role, repository, revision, source, destination, size, digest))

    validate_roles(name, files)
    return ModelSet(
        name,
        description.strip(),
        upstream_model,
        model_card,
        mtp,
        chat_template_file,
        tuple(licenses),
        tuple(files),
        llama_build,
    )


def validate_roles(name: str, files: list[ModelFile]) -> None:
    by_role: dict[str, list[ModelFile]] = {role: [] for role in ROLES}
    for model_file in files:
        by_role[model_file.role].append(model_file)
    if len(by_role["weights"]) != 1:
        raise TokenCrateError(f'{name}: exactly one file must have role = "weights"')
    weights = by_role["weights"][0]
    splits = by_role["split"]
    weights_match = SPLIT_RE.fullmatch(PurePosixPath(weights.source).name)
    if splits and weights_match is None:
        raise TokenCrateError(f"{name}: split rows need a weights file named *-00001-of-NNNNN.gguf")
    if weights_match is not None:
        total = int(weights_match.group("total"))
        if weights_match.group("index") != "00001":
            raise TokenCrateError(f"{name}: the weights file must be part 00001 of a split model")
        if total < 2 or len(splits) != total - 1:
            raise TokenCrateError(f"{name}: a {total}-part model needs {total - 1} split rows, found {len(splits)}")
        expected_dir = PurePosixPath(weights.destination).parent
        seen_indices = {1}
        for split in splits:
            match = SPLIT_RE.fullmatch(PurePosixPath(split.source).name)
            if (
                match is None
                or match.group("stem") != weights_match.group("stem")
                or match.group("total") != weights_match.group("total")
                or PurePosixPath(split.destination).parent != expected_dir
            ):
                raise TokenCrateError(f"{name}: split {split.source} does not belong to {weights.source}")
            index = int(match.group("index"))
            if index in seen_indices:
                raise TokenCrateError(f"{name}: duplicate split index {index:05d}")
            seen_indices.add(index)
        if seen_indices != set(range(1, total + 1)):
            raise TokenCrateError(f"{name}: split rows must cover parts 00002 to {total:05d}")


def available_sets(manifest_dir: Path) -> dict[str, ModelSet]:
    return load_catalog(manifest_dir, read_manifest, "model set")


def merged_files(selected: list[ModelSet]) -> list[ModelFile]:
    by_destination: dict[str, ModelFile] = {}
    for model_set in selected:
        for model_file in model_set.files:
            previous = by_destination.get(model_file.destination)
            if previous is not None and previous != model_file:
                raise TokenCrateError(
                    f"selected sets disagree about {model_file.destination}; fetch them separately or fix the manifests"
                )
            by_destination[model_file.destination] = model_file
    return list(by_destination.values())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def destination_path(
    models_root: Path,
    destination: str,
    roots: tuple[Path, ...],
    *,
    create_parent: bool,
) -> Path:
    path = models_root.joinpath(*PurePosixPath(destination).parts)
    ancestor = path.parent
    while not os.path.lexists(ancestor):
        if ancestor.parent == ancestor:
            raise TokenCrateError(f"destination has no existing parent: {destination}")
        ancestor = ancestor.parent
    if ancestor.is_symlink() and not ancestor.exists():
        raise TokenCrateError(f"destination uses a dangling directory symlink: {destination}")
    resolved_ancestor = ancestor.resolve(strict=True)
    if not is_within(resolved_ancestor, roots):
        raise TokenCrateError(
            f"destination escapes the model storage: {destination}; keep symlink targets below the models directory"
        )
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.exists():
        parent = path.parent.resolve(strict=True)
        if not is_within(parent, roots):
            raise TokenCrateError(
                f"destination escapes the model storage: {destination}; keep symlink targets below the models directory"
            )
    if path.is_symlink():
        resolved = path.resolve(strict=False)
        if not is_within(resolved, roots):
            raise TokenCrateError(f"destination symlink escapes the model storage: {destination}")
    return path


@contextlib.contextmanager
def model_download_lock(models_root: Path):
    lock_path = models_root / ".tokencrate-model-set.lock"
    if lock_path.is_symlink():
        raise TokenCrateError(f"refusing unsafe lock symlink: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TokenCrateError(f"model-set lock is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TokenCrateError("another model-set download is using this models directory") from error
        yield
    finally:
        os.close(descriptor)


def file_state(path: Path, expected: ModelFile) -> str:
    if path.is_symlink() and not path.exists():
        return "dangling symlink"
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not a regular file"
    if path.stat().st_size != expected.size:
        return "wrong size"
    if sha256_file(path) != expected.sha256:
        return "wrong checksum"
    return "ready"


def print_notices(selected: list[ModelSet]) -> None:
    print("Review and accept the model licenses before downloading:")
    seen: set[tuple[str, str]] = set()
    for model_set in selected:
        for license_entry in model_set.licenses:
            key = (license_entry.name, license_entry.url)
            if key not in seen:
                print(f"  {license_entry.name}: {license_entry.url}")
                seen.add(key)
    print("Pinned model cards:")
    for model_set in selected:
        print(f"  {model_set.name}: {model_set.model_card}")


def prepare_staging_directory(path: Path) -> None:
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    if os.path.lexists(path):
        path_stat = path.lstat()
        if not stat.S_ISDIR(path_stat.st_mode) or path.is_symlink():
            raise TokenCrateError(f"refusing unsafe staging path: {path}")
        if current_uid is not None and path_stat.st_uid != current_uid:
            raise TokenCrateError(f"staging path is owned by another user: {path}")
    else:
        path.mkdir(mode=0o700)
    path.chmod(0o700)

    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        for name in directory_names + file_names:
            entry = Path(directory) / name
            entry_stat = entry.lstat()
            if stat.S_ISLNK(entry_stat.st_mode):
                raise TokenCrateError(f"refusing symlink inside resumable staging: {entry}")
            if current_uid is not None and entry_stat.st_uid != current_uid:
                raise TokenCrateError(f"staging entry is owned by another user: {entry}")
            if stat.S_ISDIR(entry_stat.st_mode):
                entry.chmod(0o700)
            elif not stat.S_ISREG(entry_stat.st_mode):
                raise TokenCrateError(f"refusing unsafe staging entry: {entry}")


def remove_staging_directory(staging: Path, staging_root: Path) -> None:
    shutil.rmtree(staging)
    try:
        staging_root.rmdir()
    except OSError:
        pass


def staging_directory(model_file: ModelFile, destination: Path) -> Path:
    """The resumable staging directory of one pinned file, beside its destination.

    Staging next to the final path lets verified publication be one atomic
    rename; the key names the pinned file, so a manifest change never resumes
    a stale partial download."""
    pinned = f"{model_file.repository}\0{model_file.revision}\0{model_file.source}"
    return destination.parent / ".tokencrate-downloads" / hashlib.sha256(pinned.encode()).hexdigest()[:24]


def staged_paths(model_file: ModelFile, staging: Path) -> tuple[Path, Path]:
    """The complete-download path and the in-progress .part path inside staging."""
    staged = staging / PurePosixPath(model_file.destination).name
    return staged, staged.with_name(staged.name + ".part")


def staged_size(path: Path) -> int:
    """Bytes in a staging file; 0 when it is absent or not a regular file."""
    try:
        path_stat = path.lstat()
    except OSError:
        return 0
    return path_stat.st_size if stat.S_ISREG(path_stat.st_mode) else 0


@dataclass(frozen=True)
class PendingFile:
    """A selected file that is not at its destination, classified by what its staging holds.

    The state is "complete" when the whole download awaits verification,
    "partial" when a .part file can be resumed, and "absent" otherwise;
    ``received`` counts the pinned file's bytes already in staging. Only the
    bytes beyond them need free space, and only an incomplete file needs the
    Hub."""

    model_file: ModelFile
    destination: Path
    staging: Path
    state: str
    received: int

    @property
    def remaining(self) -> int:
        return max(self.model_file.size - self.received, 0)


def pending_file(model_file: ModelFile, destination: Path) -> PendingFile:
    staging = staging_directory(model_file, destination)
    staged, part = staged_paths(model_file, staging)
    if staged_size(staged) == model_file.size:
        return PendingFile(model_file, destination, staging, "complete", model_file.size)
    received = staged_size(part)
    return PendingFile(model_file, destination, staging, "partial" if received else "absent", received)


def require_free_space(models_root: Path, pending: list[PendingFile]) -> None:
    """Refuse to start when the bytes still to download exceed the free space."""
    needed = sum(item.remaining for item in pending)
    try:
        free = shutil.disk_usage(models_root).free
    except OSError:
        return
    if needed > free:
        raise TokenCrateError(
            f"the selected files need {needed / 1_000_000_000:.1f} GB but only "
            f"{free / 1_000_000_000:.1f} GB are free below {models_root}"
        )


# HTTP and HTTPS only (no file:, ftp:, or data: handler) and no redirect
# handler: a redirect raises HTTPError, and open_url decides whether the
# token travels to the new location.
OPENER = urllib.request.OpenerDirector()
for handler in (
    urllib.request.ProxyHandler(),
    urllib.request.HTTPHandler(),
    urllib.request.HTTPSHandler(),
    urllib.request.UnknownHandler(),
    urllib.request.HTTPDefaultErrorHandler(),
    urllib.request.HTTPErrorProcessor(),
):
    OPENER.add_handler(handler)


def open_url(url: str, headers: dict[str, str], token: str | None):
    """GET url and return the response; the token is sent to the Hub host only.

    Redirects are followed here so the Authorization header is dropped when
    the target is another host (the Hugging Face CDN), and a redirect off the
    Hub's URL scheme (https) is refused before anything is sent to it."""
    hub = urllib.parse.urlsplit(HUB_URL)
    for _ in range(MAX_REDIRECTS + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
        if token and urllib.parse.urlsplit(url).hostname == hub.hostname:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            return OPENER.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code not in REDIRECT_CODES or not error.headers.get("Location"):
                raise
            url = urllib.parse.urljoin(url, error.headers["Location"])
            if urllib.parse.urlsplit(url).scheme != hub.scheme:
                raise TokenCrateError(f"refusing a redirect away from {hub.scheme}: {url}") from None
    raise TokenCrateError(f"too many redirects for {url}")


def file_url(model_file: ModelFile) -> str:
    return f"{HUB_URL}/{model_file.repository}/resolve/{model_file.revision}/{urllib.parse.quote(model_file.source)}"


def check_access(model_file: ModelFile, token: str | None) -> None:
    where = f"{model_file.repository}/{model_file.source} at {model_file.revision}"
    try:
        open_url(file_url(model_file), {"Range": "bytes=0-0"}, token).close()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise TokenCrateError(
                f"cannot access {where} (HTTP {error.code}). "
                "For gated repositories, accept the license and set HF_TOKEN in .env."
            ) from error
        if error.code == 404:
            raise TokenCrateError(f"{where} does not exist: the file or the revision is missing") from error
        raise TokenCrateError(f"Hugging Face returned HTTP {error.code} for {where}") from error
    except (OSError, http.client.HTTPException) as error:
        raise TokenCrateError(f"could not reach Hugging Face for {where}: {error}") from error


def download(pending: PendingFile, token: str | None) -> Path:
    """Stream the file into staging, resuming a partial download, and return the staged path.

    The stream goes to <name>.part; a previous .part file is resumed with a
    Range request (206), restarted when the server ignores the range (200),
    and taken as complete when the server has no byte beyond it (416). The
    .part file is renamed only once every byte the manifest promises is on
    disk, so anything else in the staging directory is a complete download
    awaiting verification, which is returned without a request."""
    model_file = pending.model_file
    staged, part = staged_paths(model_file, pending.staging)
    if pending.state == "complete":
        return staged
    received = pending.received
    headers = {"Range": f"bytes={received}-"} if received else {}
    report_step = max(model_file.size // 10, CHUNK_SIZE)
    next_report = report_step
    try:
        with open_url(file_url(model_file), headers, token) as response:
            if response.status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {received}-"):
                    raise TokenCrateError(
                        f"{model_file.destination}: the server resumed at an unexpected offset ({content_range})"
                    )
                total = content_range.rpartition("/")[2]
            elif response.status == 200:
                received = 0
                total = response.headers.get("Content-Length", "")
            else:
                raise TokenCrateError(f"{model_file.destination}: unexpected HTTP status {response.status}")
            if total.isdigit() and int(total) != model_file.size:
                raise TokenCrateError(
                    f"{model_file.destination}: the server reports {total} bytes "
                    f"but the manifest pins {model_file.size}"
                )
            with part.open("r+b" if received else "wb") as handle:
                handle.seek(received)
                for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                    handle.write(chunk)
                    received += len(chunk)
                    if received >= next_report:
                        print(f"  {received / 1_000_000_000:.1f} of {model_file.size / 1_000_000_000:.1f} GB")
                        next_report += report_step
                handle.flush()
                os.fsync(handle.fileno())
    except urllib.error.HTTPError as error:
        if error.code == 416 and received:
            os.replace(part, staged)
            return staged
        raise TokenCrateError(f"download failed for {model_file.destination}: HTTP {error.code}") from error
    except (OSError, http.client.HTTPException) as error:
        raise TokenCrateError(
            f"download of {model_file.destination} stopped after {received} of {model_file.size} bytes ({error}); "
            "run models fetch again to resume"
        ) from error
    if received < model_file.size:
        raise TokenCrateError(
            f"download of {model_file.destination} stopped after {received} of {model_file.size} bytes; "
            "run models fetch again to resume"
        )
    os.replace(part, staged)
    return staged


def fetch(selected: list[ModelSet], models_root: Path, token: str | None) -> None:
    roots = (models_root.resolve(),)
    files = merged_files(selected)
    print_notices(selected)

    pending: list[PendingFile] = []
    for model_file in files:
        destination = destination_path(models_root, model_file.destination, roots, create_parent=True)
        state = file_state(destination, model_file)
        if state == "ready":
            print(f"ready: {model_file.destination}")
        else:
            if state != "missing":
                raise TokenCrateError(
                    f"{model_file.destination} has the {state}; move it aside before downloading the pinned file"
                )
            pending.append(pending_file(model_file, destination))
    if not pending:
        print("All selected model files are ready.")
        return

    require_free_space(models_root, pending)
    incomplete = [item for item in pending if item.state != "complete"]
    if incomplete:
        print("Checking access to every selected Hugging Face file before downloading ...")
        for item in incomplete:
            check_access(item.model_file, token)

    for item in pending:
        model_file, destination, staging = item.model_file, item.destination, item.staging
        staging_root = staging.parent
        prepare_staging_directory(staging_root)
        prepare_staging_directory(staging)
        resolved_staging = staging.resolve(strict=True)
        if not is_within(resolved_staging, roots):
            raise TokenCrateError(f"staging directory escapes the model storage: {model_file.destination}")
        if item.state == "complete":
            print(f"verifying: {model_file.destination}")
        else:
            print(f"downloading: {model_file.destination} ({model_file.size / 1_000_000_000:.1f} GB)")
        downloaded = download(item, token)
        # A complete download that is not the pinned file is discarded. A
        # verified one is moved into place; when that fails, it stays in
        # staging and the next run publishes it without downloading again.
        if downloaded.stat().st_size != model_file.size:
            remove_staging_directory(staging, staging_root)
            raise TokenCrateError(f"downloaded size does not match the manifest: {model_file.destination}")
        if sha256_file(downloaded) != model_file.sha256:
            remove_staging_directory(staging, staging_root)
            raise TokenCrateError(f"downloaded checksum does not match the manifest: {model_file.destination}")
        if os.path.lexists(destination):
            if file_state(destination, model_file) != "ready":
                raise TokenCrateError(
                    f"{model_file.destination} appeared while downloading and was not overwritten; review it and retry"
                )
        else:
            os.replace(downloaded, destination)
        remove_staging_directory(staging, staging_root)
        print(f"installed: {model_file.destination}")
    print("Selected model sets are ready. Render presets and restart with: bash bin/tokencrate up")


def status(selected: list[ModelSet], models_root: Path) -> int:
    roots = (models_root.resolve(),)
    result = 0
    for model_file in merged_files(selected):
        path = destination_path(models_root, model_file.destination, roots, create_parent=False)
        state = file_state(path, model_file)
        print(f"{model_file.destination}: {state}")
        if state != "ready":
            result = 1
    return result


# --- Manifest drafts ---------------------------------------------------------


def hub_json(url: str, token: str | None) -> dict:
    try:
        with open_url(url, {"Accept": "application/json"}, token) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise TokenCrateError(f"Hugging Face returned HTTP {error.code} for {url}") from error
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise TokenCrateError(f"could not query Hugging Face: {error}") from error
    if not isinstance(payload, dict):
        raise TokenCrateError(f"unexpected Hugging Face response for {url}")
    return payload


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def draft(spec: str, token: str | None) -> str:
    match = re.fullmatch(r"hf:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):(?P<file>\S+)", spec)
    if match is None:
        raise TokenCrateError("draft needs hf:<owner>/<repository>:<file.gguf>")
    repository = match.group("repository")
    wanted = safe_relative_path(match.group("file"), "draft file")
    if not wanted.endswith(".gguf"):
        raise TokenCrateError("draft only supports GGUF files")
    encoded = urllib.parse.quote(repository, safe="/")
    payload = hub_json(f"{HUB_URL}/api/models/{encoded}/revision/main?blobs=true", token)
    revision = payload.get("sha")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise TokenCrateError("Hugging Face did not report a commit for the main branch")
    siblings = {
        item["rfilename"]: item
        for item in payload.get("siblings", [])
        if isinstance(item, dict) and isinstance(item.get("rfilename"), str)
    }
    if wanted not in siblings:
        raise TokenCrateError(f"{wanted} is not in {repository} at {revision}")
    card_data = payload.get("cardData") or {}
    license_id = card_data.get("license") if isinstance(card_data, dict) else None
    base_model = card_data.get("base_model") if isinstance(card_data, dict) else None
    if isinstance(base_model, list):
        base_model = base_model[0] if base_model else None

    def row(role: str, filename: str) -> str:
        item = siblings[filename]
        lfs = item.get("lfs") or {}
        size = item.get("size") or lfs.get("size")
        digest = lfs.get("sha256")
        return "\n".join(
            [
                "[[file]]",
                f"role = {toml_string(role)}",
                f"repository = {toml_string(repository)}",
                f"revision = {toml_string(revision)}",
                f"source = {toml_string(filename)}",
                # Quoted so the draft parses and fails per field, not per file.
                f"size = {size}" if isinstance(size, int) else 'size = "TODO"',
                f"sha256 = {toml_string(digest)}" if isinstance(digest, str) else 'sha256 = "TODO"',
            ]
        )

    rows = [row("weights", wanted)]
    split_match = SPLIT_RE.fullmatch(PurePosixPath(wanted).name)
    if split_match is not None:
        if split_match.group("index") != "00001":
            raise TokenCrateError("models draft requires the first shard (00001) of a split GGUF")
        total = int(split_match.group("total"))
        directory = PurePosixPath(wanted).parent
        for index in range(2, total + 1):
            part = f"{split_match.group('stem')}-{index:05d}-of-{total:05d}.gguf"
            candidate = (directory / part).as_posix() if str(directory) != "." else part
            if candidate not in siblings:
                raise TokenCrateError(f"split part is missing from the repository: {candidate}")
            rows.append(row("split", candidate))

    license_label = license_id or "license"
    header = [
        "schema = 1",
        f"description = {toml_string(f'TODO: describe {repository} {PurePosixPath(wanted).name}')}",
        # An empty upstream_model is accepted; "TODO" is not.
        f"upstream_model = {toml_string(base_model)}" if isinstance(base_model, str) else 'upstream_model = ""',
        f"model_card = {toml_string(f'https://huggingface.co/{repository}/blob/{revision}/README.md')}",
        "# Set mtp = true when the GGUF contains multi-token-prediction heads.",
        "mtp = false",
        "",
        "[[license]]",
        f"name = {toml_string(f'TODO: {license_label} ({repository})')}",
        f"url = {toml_string(f'https://huggingface.co/{repository}/blob/{revision}/README.md')}",
        "",
    ]
    return "\n".join(header) + "\n\n".join(rows) + "\n"
