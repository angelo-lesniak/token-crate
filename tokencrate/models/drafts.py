"""Draft a model-set manifest from what the Hub reports about a GGUF file."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import PurePosixPath

from .. import TokenCrateError
from ..names import SHA1_RE, relative_path
from .hub import HUB_URL, hub_json
from .manifest import REPOSITORY_RE, SPLIT_RE


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def draft(spec: str, token: str | None) -> str:
    match = re.fullmatch(r"hf:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):(?P<file>\S+)", spec)
    if match is None or not REPOSITORY_RE.fullmatch(match.group("repository")):
        raise TokenCrateError("draft needs hf:<owner>/<repository>:<file.gguf>")
    repository = match.group("repository")
    wanted = relative_path(match.group("file"), "file", "draft")
    if not wanted.endswith(".gguf"):
        raise TokenCrateError("draft only supports GGUF files")
    encoded = urllib.parse.quote(repository, safe="/")
    payload = hub_json(f"{HUB_URL}/api/models/{encoded}/revision/main?blobs=true", token)
    revision = payload.get("sha")
    if not isinstance(revision, str) or not SHA1_RE.fullmatch(revision):
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
