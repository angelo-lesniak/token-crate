"""Keep the on-disk model library: destinations, the download lock, verification stamps, and staging."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .. import TokenCrateError
from ..files import write_atomic
from .manifest import ModelFile

# Written beside a file once its checksum matched; see file_state.
STAMP_SUFFIX = ".tokencrate-verified"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def destination_path(models_root: Path, destination: str, roots: tuple[Path, ...]) -> Path:
    """The library path of a destination, checked but not created; fetch creates the parent when it stages."""
    path = models_root.joinpath(*PurePosixPath(destination).parts)
    ancestor = path.parent
    while not os.path.lexists(ancestor):
        if ancestor.parent == ancestor:
            raise TokenCrateError(f"destination has no existing parent: {destination}")
        ancestor = ancestor.parent
    if ancestor.is_symlink() and not ancestor.exists():
        raise TokenCrateError(f"destination uses a dangling directory symlink: {destination}")
    if not is_within(ancestor.resolve(strict=True), roots):
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


def stamp_path(path: Path) -> Path:
    return path.with_name(path.name + STAMP_SUFFIX)


def stamp_of(path_stat: os.stat_result, sha256: str) -> dict:
    """What a stamp records: the checksum, and the size and mtime of the file it was computed from."""
    return {"sha256": sha256, "size": path_stat.st_size, "mtime_ns": path_stat.st_mtime_ns}


def read_stamp(path: Path) -> dict | None:
    """The stamp beside a file, or None when it is missing or unreadable."""
    try:
        return json.loads(stamp_path(path).read_bytes())
    except (OSError, ValueError):
        return None


def write_stamp(path: Path, sha256: str) -> None:
    """Record the verified file beside it; a library that cannot be written is hashed again next time."""
    with contextlib.suppress(OSError):
        write_atomic(stamp_path(path), json.dumps(stamp_of(path.stat(), sha256)), mode=0o600)


def is_stamped(path: Path, path_stat: os.stat_result, expected: ModelFile) -> bool:
    return read_stamp(path) == stamp_of(path_stat, expected.sha256)


def file_state(path: Path, expected: ModelFile, *, verify: bool = False) -> str:
    """Classify the file at a destination.

    Hashing a model library takes minutes per 10 GB, so a file is hashed
    once: the match is recorded in a stamp beside it, and later calls trust
    the stamp while the file's size, mtime, and the manifest's checksum
    are the recorded ones. ``verify`` hashes regardless. The stamp
    is trusted because only the host writes the library; the llama
    container mounts it read-only."""
    if path.is_symlink() and not path.exists():
        return "dangling symlink"
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not a regular file"
    path_stat = path.stat()
    if path_stat.st_size != expected.size:
        return "wrong size"
    if verify or not is_stamped(path, path_stat, expected):
        if sha256_file(path) != expected.sha256:
            return "wrong checksum"
        write_stamp(path, expected.sha256)
    return "ready"


def announce_hashing(located: list[tuple[Path, ModelFile]], verify: bool = False) -> None:
    """Say up front how many present files file_state is about to hash."""
    to_hash = [
        model_file
        for path, model_file in located
        if path.is_file() and (verify or not is_stamped(path, path.stat(), model_file))
    ]
    if to_hash:
        total = sum(model_file.size for model_file in to_hash) / 1_000_000_000
        print(
            f"verifying: {len(to_hash)} file(s) ({total:.1f} GB) by checksum; "
            "later runs trust the record written beside each verified file"
        )


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
            f"{free / 1_000_000_000:.1f} GB are free below {models_root}; make room or fetch fewer sets"
        )
