"""Read and validate model-set manifests into :class:`ModelSet` records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .. import TokenCrateError
from ..names import SET_NAME_RE, SHA1_RE, SHA256_RE, load_catalog, read_toml, relative_path
from ..names import description as read_description

REPOSITORY_RE = re.compile(r"^(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+$")
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
    known = {"schema", "description", "upstream_model", "model_card", "mtp", "chat_template_file", "license", "file"}
    document = read_toml(path, known | {"requires"}, name)
    description = read_description(document, name)
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
    licenses = [read_license(raw, index, name) for index, raw in enumerate(raw_licenses, start=1)]

    raw_files = document.get("file")
    if not isinstance(raw_files, list) or not raw_files:
        raise TokenCrateError(f"{name}: at least one [[file]] entry is required")
    files: list[ModelFile] = []
    destinations: set[str] = set()
    for index, raw in enumerate(raw_files, start=1):
        model_file = read_file(raw, index, name)
        if model_file.destination in destinations:
            raise TokenCrateError(f"{name}: duplicate destination: {model_file.destination}")
        destinations.add(model_file.destination)
        files.append(model_file)

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


def read_license(raw: object, index: int, name: str) -> License:
    """One [[license]] entry: a name and an immutable approved HTTPS URL."""
    if not isinstance(raw, dict):
        raise TokenCrateError(f"{name}: license {index} must be a table")
    require_keys(raw, {"name", "url"}, f"{name} license {index}")
    license_name = raw.get("name")
    url = raw.get("url")
    if not isinstance(license_name, str) or not license_name.strip():
        raise TokenCrateError(f"{name}: license {index} needs a name")
    if not isinstance(url, str) or LICENSE_URL_RE.fullmatch(url) is None:
        raise TokenCrateError(f"{name}: license {index} needs an immutable approved HTTPS URL")
    return License(license_name.strip(), url)


def read_file(raw: object, index: int, name: str) -> ModelFile:
    """One [[file]] entry: a pinned Hugging Face file; the library keeps it at <repository>/<source>."""
    if not isinstance(raw, dict):
        raise TokenCrateError(f"{name}: file {index} must be a table")
    require_keys(raw, {"role", "repository", "revision", "source", "size", "sha256"}, f"{name} file {index}")
    role = raw.get("role")
    if role not in ROLES:
        raise TokenCrateError(f"{name}: file {index} role must be one of {', '.join(ROLES)}")
    repository = raw.get("repository")
    revision = raw.get("revision")
    source = relative_path(raw.get("source"), "source", f"{name} file {index}")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise TokenCrateError(f"{name}: file {index} has an invalid repository")
    if not isinstance(revision, str) or not SHA1_RE.fullmatch(revision):
        raise TokenCrateError(f"{name}: file {index} revision must be a full lowercase commit")
    size = raw.get("size")
    digest = raw.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise TokenCrateError(f"{name}: file {index} size must be a positive integer")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise TokenCrateError(f"{name}: file {index} sha256 must be lowercase hexadecimal")
    return ModelFile(role, repository, revision, source, f"{repository}/{source}", size, digest)


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
        if len(splits) != total - 1:
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


def catalog(config_dir: Path) -> dict[str, ModelSet]:
    """Every model set under config_dir/model-sets, by name."""
    return load_catalog(config_dir / "model-sets", read_manifest, "model set")


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
