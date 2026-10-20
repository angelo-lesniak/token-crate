"""Fetch, verify, and draft pinned Hugging Face GGUF files declared by model-set manifests.

The CLI runs this package in-process on the host: ``models fetch`` calls
:func:`fetch` inside :func:`model_download_lock`, ``models status`` calls
:func:`status`, and ``models draft`` writes the text :func:`draft` returns.
The Hugging Face token arrives as a plain Python argument (the CLI captures
``HF_TOKEN`` in-process), so it never travels through an environment or a
command line, and :func:`hub.open_url` sends it to the Hub host only.

The modules layer upward: :mod:`manifest` reads the TOML, :mod:`library`
keeps the on-disk model library, :mod:`hub` talks to Hugging Face,
:mod:`download` fetches and reports, and :mod:`drafts` writes new manifests.
"""

from __future__ import annotations

from .download import fetch, status
from .drafts import draft
from .library import model_download_lock
from .manifest import UNRELEASED_BUILD, License, ModelFile, ModelSet, available_sets, merged_files, read_manifest

__all__ = [
    "UNRELEASED_BUILD",
    "License",
    "ModelFile",
    "ModelSet",
    "available_sets",
    "draft",
    "fetch",
    "merged_files",
    "model_download_lock",
    "read_manifest",
    "status",
]
