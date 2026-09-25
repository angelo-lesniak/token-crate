from __future__ import annotations

import contextlib
import hashlib
import http.server
import io
import json
import os
import shutil
import tempfile
import threading
import tomllib
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.support import shipped
from tokencrate import PROJECT_ROOT, TokenCrateError, models
from tokencrate.names import select_sets

MANIFESTS = PROJECT_ROOT / "config" / "model-sets"
REAL_DISK_USAGE = shutil.disk_usage

MANIFEST_HEAD = """schema = 1
description = "Fixture"
model_card = "https://huggingface.co/example/model/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/README.md"
[[license]]
name = "Test"
url = "https://huggingface.co/example/model/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/LICENSE"
"""


def file_row(role: str, source: str, destination: str | None = None) -> str:
    row = f"""[[file]]
role = "{role}"
repository = "example/model"
revision = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
source = "{source}"
size = 1
sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
"""
    if destination is not None:
        row += f'destination = "{destination}"\n'
    return row


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def serve_bytes(handler, content: bytes, *, honor_range: bool = True, send_only: int | None = None) -> None:
    """Answer a GET with content like a file server: 206 for a satisfiable
    Range, 416 past the end, 200 otherwise. send_only truncates the body
    after the headers promised more, like a dropped connection."""
    body, status, start = content, 200, 0
    range_header = handler.headers.get("Range")
    if range_header and honor_range:
        first, _, last = range_header.removeprefix("bytes=").partition("-")
        start = int(first)
        if start >= len(content):
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{len(content)}")
            handler.end_headers()
            return
        end = int(last) if last else len(content) - 1
        body, status = content[start : end + 1], 206
    handler.send_response(status)
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{start + len(body) - 1}/{len(content)}")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body if send_only is None else body[:send_only])


class ModelSetTests(unittest.TestCase):
    def fixture_set(self, content: bytes = b"small pinned model", *, size: int | None = None):
        model_file = models.ModelFile(
            role="weights",
            repository="example/models",
            revision="a" * 40,
            source="weights/model.gguf",
            destination="example/models/weights/model.gguf",
            size=len(content) if size is None else size,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        model_set = models.ModelSet(
            name="fixture",
            description="Fixture",
            upstream_model="example/base",
            model_card="https://huggingface.co/example/models/blob/" + "b" * 40 + "/README.md",
            mtp=False,
            chat_template_file="",
            licenses=(
                models.License(
                    "Fixture",
                    "https://huggingface.co/example/models/blob/" + "c" * 40 + "/LICENSE",
                ),
            ),
            files=(model_file,),
        )
        return model_set, model_file

    def read(self, body: str):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "fixture.toml"
            manifest.write_text(body, encoding="utf-8")
            return models.read_manifest(manifest)

    def serve(self, respond) -> int:
        """Start a local HTTP server whose GETs call respond(handler); return its port."""

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                respond(self)

            def log_message(self, *arguments):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def use_hub(self, port: int) -> None:
        """Point the module's Hub URL at a local server; the token rule keys on its host."""
        self.addCleanup(setattr, models, "HUB_URL", models.HUB_URL)
        models.HUB_URL = f"http://127.0.0.1:{port}"

    def use_free_space(self, free: int) -> None:
        """Make shutil.disk_usage, which the free-space check consults, report `free` bytes."""
        self.addCleanup(setattr, shutil, "disk_usage", REAL_DISK_USAGE)
        shutil.disk_usage = lambda path: types.SimpleNamespace(free=free)

    def fetch(self, model_set, models_root: Path, token: str | None) -> None:
        with quiet():
            models.fetch([model_set], models_root, token)

    def test_shipped_catalog_is_strict_and_complete(self):
        catalog = models.available_sets(MANIFESTS)

        self.assertEqual(sorted(catalog), sorted(shipped("model-sets")))
        for model_set in catalog.values():
            self.assertEqual([model_file.role for model_file in model_set.files].count("weights"), 1)
            self.assertEqual(model_set.weights.role, "weights")
            if model_set.chat_template_file:
                self.assertTrue((PROJECT_ROOT / "config" / "chat-templates" / model_set.chat_template_file).is_file())

    def test_default_destination_follows_the_repository_layout(self):
        model_set = self.read(MANIFEST_HEAD + file_row("weights", "sub/model.gguf"))

        self.assertEqual(model_set.weights.destination, "example/model/sub/model.gguf")

    def test_exactly_one_weights_role_is_required(self):
        with self.assertRaisesRegex(TokenCrateError, "exactly one"):
            self.read(MANIFEST_HEAD + file_row("split", "m-00002-of-00002.gguf"))
        with self.assertRaisesRegex(TokenCrateError, "exactly one"):
            self.read(MANIFEST_HEAD + file_row("weights", "a.gguf") + file_row("weights", "b.gguf"))
        with self.assertRaisesRegex(TokenCrateError, "role must be one of weights, split"):
            self.read(MANIFEST_HEAD + file_row("mmproj", "mmproj.gguf"))

    def test_split_rows_must_match_the_weights_file(self):
        body = MANIFEST_HEAD + file_row("weights", "m-00001-of-00003.gguf") + file_row("split", "m-00002-of-00003.gguf")
        with self.assertRaisesRegex(TokenCrateError, "needs 2 split rows"):
            self.read(body)
        body += file_row("split", "other-00003-of-00003.gguf")
        with self.assertRaisesRegex(TokenCrateError, "does not belong"):
            self.read(body)
        complete = (
            MANIFEST_HEAD
            + file_row("weights", "m-00001-of-00003.gguf")
            + file_row("split", "m-00002-of-00003.gguf")
            + file_row("split", "m-00003-of-00003.gguf")
        )
        self.assertEqual(len(self.read(complete).splits), 2)

    def test_manifest_rejects_mutable_model_card_and_unknown_keys(self):
        mutable = MANIFEST_HEAD.replace("blob/" + "a" * 40 + "/README.md", "blob/main/README.md")
        with self.assertRaisesRegex(TokenCrateError, "model_card"):
            self.read(mutable + file_row("weights", "a.gguf"))
        with self.assertRaisesRegex(TokenCrateError, "unknown field"):
            self.read(MANIFEST_HEAD + "workflow_urls = []\n" + file_row("weights", "a.gguf"))

    def test_llama_build_requirement_is_a_build_number_or_unreleased(self):
        row = file_row("weights", "a.gguf")
        self.assertEqual(self.read(MANIFEST_HEAD + row).llama_build, "")
        self.assertEqual(self.read(MANIFEST_HEAD + row + '[requires]\nllama_build = "b11100"\n').llama_build, "b11100")
        self.assertEqual(
            self.read(MANIFEST_HEAD + row + '[requires]\nllama_build = "unreleased"\n').llama_build, "unreleased"
        )
        for value in ('"11100"', '"B11100"', '"b0"', '"latest"', "11100"):
            with self.assertRaisesRegex(TokenCrateError, "llama_build must be a llama.cpp build number"):
                self.read(MANIFEST_HEAD + row + f"[requires]\nllama_build = {value}\n")
        with self.assertRaisesRegex(TokenCrateError, "unknown field.*fixture requires: vram_gib"):
            self.read(MANIFEST_HEAD + row + "[requires]\nvram_gib = 1\n")
        with self.assertRaisesRegex(TokenCrateError, r"\[requires\] must be a table"):
            self.read("requires = 1\n" + MANIFEST_HEAD + row)

    def test_all_is_reserved_as_a_manifest_name(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "all.toml"
            manifest.write_text("schema = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(TokenCrateError, "reserved"):
                models.read_manifest(manifest)

    def test_manifest_rejects_path_traversal(self):
        with self.assertRaisesRegex(TokenCrateError, "source must be a relative path"):
            self.read(MANIFEST_HEAD + file_row("weights", "../secret"))

    def test_selection_rules(self):
        catalog = models.available_sets(MANIFESTS)
        first = next(iter(catalog))
        with self.assertRaisesRegex(TokenCrateError, "provide one or more"):
            select_sets(catalog, [], "model set")
        with self.assertRaisesRegex(TokenCrateError, "all cannot be combined"):
            select_sets(catalog, ["all", first], "model set")
        with self.assertRaisesRegex(TokenCrateError, "unknown model set: missing"):
            select_sets(catalog, ["missing"], "model set")
        self.assertEqual(select_sets(catalog, [first, first], "model set"), [catalog[first]])
        self.assertEqual(select_sets(catalog, ["all"], "model set"), list(catalog.values()))

    def test_fetch_streams_verifies_then_atomically_publishes(self):
        content = b"small pinned model"
        model_set, model_file = self.fixture_set(content)
        requests: list[tuple[str, str | None, str | None]] = []

        def respond(handler):
            requests.append((handler.path, handler.headers.get("Range"), handler.headers.get("Authorization")))
            serve_bytes(handler, content)

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            self.fetch(model_set, models_root, "fixture-token")
            self.assertEqual((models_root / model_file.destination).read_bytes(), content)
            with quiet():
                self.assertEqual(models.status([model_set], models_root), 0)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))

        # Every request to the Hub asks for the pinned file with the token.
        url_path = "/example/models/resolve/" + "a" * 40 + "/weights/model.gguf"
        self.assertTrue(requests)
        self.assertEqual({(path, token) for path, _, token in requests}, {(url_path, "Bearer fixture-token")})

    def test_interrupted_download_resumes_with_a_range_request(self):
        content = bytes(range(256)) * 64
        half = len(content) // 2
        model_set, model_file = self.fixture_set(content)
        ranges: list[str | None] = []
        truncate_first = [half]

        def respond(handler):
            ranges.append(handler.headers.get("Range"))
            if handler.headers.get("Range") == "bytes=0-0":
                serve_bytes(handler, content)
            else:
                serve_bytes(handler, content, send_only=truncate_first.pop() if truncate_first else None)

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            with self.assertRaisesRegex(TokenCrateError, "run models fetch again to resume"):
                self.fetch(model_set, models_root, None)
            partial = list(models_root.rglob("*.part"))
            self.assertEqual(len(partial), 1)
            self.assertEqual(partial[0].stat().st_size, half)
            self.assertFalse((models_root / model_file.destination).exists())

            self.fetch(model_set, models_root, None)
            self.assertEqual((models_root / model_file.destination).read_bytes(), content)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))
        # The second run resumes where the first stopped.
        self.assertEqual(ranges[-1], f"bytes={half}-")

    def test_a_full_answer_to_a_range_request_restarts_the_file(self):
        content = bytes(range(256)) * 64
        half = len(content) // 2
        model_set, model_file = self.fixture_set(content)
        data_requests = [dict(send_only=half), dict(honor_range=False)]

        def respond(handler):
            if handler.headers.get("Range") == "bytes=0-0":
                serve_bytes(handler, content)
            else:
                serve_bytes(handler, content, **data_requests.pop(0))

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            with self.assertRaisesRegex(TokenCrateError, "run models fetch again to resume"):
                self.fetch(model_set, models_root, None)
            self.fetch(model_set, models_root, None)
            self.assertEqual((models_root / model_file.destination).read_bytes(), content)
        self.assertEqual(data_requests, [])

    def test_redirect_to_another_host_drops_the_token(self):
        content = b"small pinned model"
        model_set, model_file = self.fixture_set(content)
        cdn_requests: list[str | None] = []

        def cdn(handler):
            cdn_requests.append(handler.headers.get("Authorization"))
            serve_bytes(handler, content)

        # Same loopback interface, different host name: the token must stay behind.
        cdn_url = f"http://localhost:{self.serve(cdn)}"
        hub_requests: list[str | None] = []

        def hub(handler):
            hub_requests.append(handler.headers.get("Authorization"))
            handler.send_response(302)
            handler.send_header("Location", cdn_url + handler.path)
            handler.end_headers()

        self.use_hub(self.serve(hub))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            self.fetch(model_set, models_root, "fixture-token")
            self.assertEqual((models_root / model_file.destination).read_bytes(), content)
        self.assertTrue(hub_requests and cdn_requests)
        self.assertEqual(set(hub_requests), {"Bearer fixture-token"})
        self.assertEqual(set(cdn_requests), {None})

    def test_redirect_off_the_hub_scheme_is_refused_before_any_request(self):
        model_set, _ = self.fixture_set()
        target_requests: list[str | None] = []
        # The Hub fixture speaks http; a redirect to https (or file:) must be
        # refused before a request, and the token with it, reaches the target.
        target_port = self.serve(lambda handler: target_requests.append(handler.headers.get("Authorization")))
        target_url = f"https://localhost:{target_port}"

        def hub(handler):
            handler.send_response(302)
            handler.send_header("Location", target_url + handler.path)
            handler.end_headers()

        self.use_hub(self.serve(hub))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TokenCrateError, "refusing a redirect away from http:"):
                self.fetch(model_set, Path(directory), "fixture-token")
        self.assertEqual(target_requests, [])

    def test_access_errors_are_reported_before_downloading(self):
        model_set, _ = self.fixture_set()
        statuses = [401, 404]

        def respond(handler):
            handler.send_response(statuses.pop(0))
            handler.end_headers()

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            with self.assertRaisesRegex(TokenCrateError, "accept the license and set HF_TOKEN"):
                self.fetch(model_set, models_root, None)
            with self.assertRaisesRegex(TokenCrateError, "does not exist"):
                self.fetch(model_set, models_root, None)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))

    def test_wrong_existing_file_is_never_overwritten(self):
        model_set, model_file = self.fixture_set()
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            destination = models_root / model_file.destination
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"user file")

            with self.assertRaisesRegex(TokenCrateError, "move it aside"):
                self.fetch(model_set, models_root, None)

            self.assertEqual(destination.read_bytes(), b"user file")

    def test_integrity_failure_discards_completed_staging(self):
        model_set, _ = self.fixture_set(b"small pinned model")
        self.use_hub(self.serve(lambda handler: serve_bytes(handler, b"wrong pinned model")))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            with self.assertRaisesRegex(TokenCrateError, "checksum"):
                self.fetch(model_set, models_root, None)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))

    def test_publication_failure_keeps_the_verified_download_for_the_next_run(self):
        content = b"small pinned model"
        model_set, model_file = self.fixture_set(content)
        ranges: list[str | None] = []

        def respond(handler):
            ranges.append(handler.headers.get("Range"))
            serve_bytes(handler, content)

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            destination = models_root / model_file.destination
            real_replace = os.replace

            def replace_except_publication(source, target):
                if Path(target) == destination:
                    raise PermissionError("read-only")
                real_replace(source, target)

            with (
                mock.patch("tokencrate.models.os.replace", side_effect=replace_except_publication),
                self.assertRaises(PermissionError),
            ):
                self.fetch(model_set, models_root, None)
            self.assertFalse(destination.exists())
            staged = list(models_root.rglob("*.gguf"))
            self.assertEqual([path.read_bytes() for path in staged], [content])
            seen = len(ranges)

            self.fetch(model_set, models_root, None)

            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))
            # The staged file was verified and published without a request.
            self.assertEqual(ranges[seen:], [])

    def test_a_complete_staged_download_needs_neither_space_nor_network(self):
        content = b"small pinned model"
        model_set, model_file = self.fixture_set(content)
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            destination = models_root / model_file.destination
            destination.parent.mkdir(parents=True)
            staging = models.staging_directory(model_file, destination)
            staging.mkdir(parents=True)
            staged, _ = models.staged_paths(model_file, staging)
            staged.write_bytes(content)
            self.use_free_space(0)

            with mock.patch.object(models, "open_url", side_effect=AssertionError("no network")):
                self.fetch(model_set, models_root, None)

            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))

    def test_free_space_is_checked_before_network_access(self):
        model_set, _ = self.fixture_set()
        requests: list[str] = []
        self.use_hub(self.serve(lambda handler: requests.append(handler.path)))
        self.use_free_space(0)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TokenCrateError, "are free"):
                self.fetch(model_set, Path(directory), None)
        self.assertEqual(requests, [])

    def test_free_space_counts_a_resumable_part_file_as_downloaded(self):
        # Scaled down: a 17.6 GB file with 17 GB in its .part needs 0.6 GB, not 17.6 GB.
        model_set, model_file = self.fixture_set(size=17_600)
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            destination = models_root / model_file.destination
            destination.parent.mkdir(parents=True)
            self.use_free_space(600)
            with self.assertRaisesRegex(TokenCrateError, "are free"):
                models.require_free_space(models_root, [models.pending_file(model_file, destination)])

            staging = models.staging_directory(model_file, destination)
            staging.mkdir(parents=True)
            _, part = models.staged_paths(model_file, staging)
            part.write_bytes(b"x" * 17_000)
            pending = [models.pending_file(model_file, destination)]
            models.require_free_space(models_root, pending)
            self.use_free_space(599)
            with self.assertRaisesRegex(TokenCrateError, "are free"):
                models.require_free_space(models_root, pending)

    def test_fetch_resumes_a_part_file_with_only_the_remaining_space_free(self):
        content = bytes(range(256)) * 64
        done = 3 * len(content) // 4
        model_set, model_file = self.fixture_set(content)
        ranges: list[str | None] = []

        def respond(handler):
            ranges.append(handler.headers.get("Range"))
            serve_bytes(handler, content)

        self.use_hub(self.serve(respond))
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            destination = models_root / model_file.destination
            destination.parent.mkdir(parents=True)
            # The .part sits where fetch() stages, so the estimate and the resume agree.
            staging = models.staging_directory(model_file, destination)
            staging.mkdir(parents=True)
            _, part = models.staged_paths(model_file, staging)
            part.write_bytes(content[:done])
            self.use_free_space(len(content) - done)

            self.fetch(model_set, models_root, None)

            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(list(models_root.rglob(".tokencrate-downloads")))
        self.assertEqual(ranges[-1], f"bytes={done}-")

    def test_status_reports_missing_without_creating_directories(self):
        model_set, _ = self.fixture_set()
        with tempfile.TemporaryDirectory() as directory:
            models_root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(models.status([model_set], models_root), 1)

            self.assertIn("example/models/weights/model.gguf: missing", output.getvalue())
            self.assertFalse((models_root / "example").exists())

    def test_status_rejects_a_symlink_outside_model_storage(self):
        model_set, model_file = self.fixture_set()
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            models_root = Path(directory)
            target = Path(outside) / "model.gguf"
            target.write_bytes(b"small pinned model")
            destination = models_root / model_file.destination
            destination.parent.mkdir(parents=True)
            try:
                os.symlink(target, destination)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(TokenCrateError, "symlink escapes"):
                models.status([model_set], models_root)

    def test_draft_renders_pinned_rows_from_hub_metadata(self):
        payload = {
            "sha": "d" * 40,
            "cardData": {"license": "apache-2.0", "base_model": "example/base"},
            "siblings": [
                {"rfilename": "README.md", "size": 10},
                {"rfilename": "model-00001-of-00002.gguf", "size": 5, "lfs": {"sha256": "1" * 64}},
                {"rfilename": "model-00002-of-00002.gguf", "size": 6, "lfs": {"sha256": "2" * 64}},
                {"rfilename": "mmproj-F16.gguf", "size": 7, "lfs": {"sha256": "3" * 64}},
            ],
        }
        self.addCleanup(setattr, models, "hub_json", models.hub_json)
        models.hub_json = lambda url, token: payload
        text = models.draft("hf:example/model:model-00001-of-00002.gguf", None)
        with self.assertRaisesRegex(TokenCrateError, "requires the first shard"):
            models.draft("hf:example/model:model-00002-of-00002.gguf", None)

        self.assertIn('role = "weights"', text)
        self.assertIn('role = "split"', text)
        self.assertIn('source = "model-00002-of-00002.gguf"', text)
        self.assertNotIn("mmproj", text)
        self.assertIn('upstream_model = "example/base"', text)
        self.assertIn('name = "TODO: apache-2.0 (example/model)"', text)
        self.assertIn("/blob/" + "d" * 40 + "/README.md", text)
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "draft.toml"
            manifest.write_text(text, encoding="utf-8")
            model_set = models.read_manifest(manifest)
        self.assertEqual(len(model_set.splits), 1)
        self.assertEqual(json.dumps(model_set.weights.destination), '"example/model/model-00001-of-00002.gguf"')

    def test_draft_without_a_card_license_falls_back_to_a_placeholder(self):
        payload = {"sha": "d" * 40, "siblings": [{"rfilename": "m.gguf", "size": 5, "lfs": {"sha256": "1" * 64}}]}
        self.addCleanup(setattr, models, "hub_json", models.hub_json)
        models.hub_json = lambda url, token: payload

        text = models.draft("hf:example/model:m.gguf", None)

        self.assertIn('name = "TODO: license (example/model)"', text)
        # read_manifest refuses "TODO" here and accepts an empty name.
        self.assertIn('upstream_model = ""', text)

    def test_a_draft_missing_every_hub_field_is_still_valid_toml(self):
        # The Hub does not always report size or sha256; a draft the maintainer
        # cannot parse is worse than one that names the fields to fill in.
        payload = {"sha": "d" * 40, "siblings": [{"rfilename": "m.gguf"}]}
        self.addCleanup(setattr, models, "hub_json", models.hub_json)
        models.hub_json = lambda url, token: payload

        text = models.draft("hf:example/model:m.gguf", None)

        self.assertIn('size = "TODO"', text)
        self.assertIn('sha256 = "TODO"', text)
        self.assertEqual(tomllib.loads(text)["file"][0]["size"], "TODO")


if __name__ == "__main__":
    unittest.main()
