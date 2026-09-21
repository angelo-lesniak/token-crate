"""Unit tests for the pin checker (resolvers with mocked sources and the report text)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import unittest
import urllib.request
from unittest import mock

from tokencrate import TokenCrateError, checkpins

LLAMA_DIGEST = "8d" * 32
BUN_DIGEST = "sha256:" + "cb" * 32


def current(component: str, key: str, value: str) -> checkpins.Resolution:
    return checkpins.Resolution(component, key, value, value)


class PinResolverTests(unittest.TestCase):
    def test_llama_cpp_picks_the_newest_build_of_the_pinned_family(self) -> None:
        values = {"LLAMA_CPP_TAG": "server-cuda13-b10800"}
        tags = ["server-cuda13-b10884", "server-cuda13-b10920", "server-cuda-b10999", "full-cuda13-b10999", "b10999"]
        with (
            mock.patch.object(checkpins, "ghcr_tags", return_value=tags) as listed,
            mock.patch.object(checkpins, "ghcr_manifest_digest", return_value=LLAMA_DIGEST) as resolved,
        ):
            result = checkpins.resolve_component("llama-cpp", values)
        listed.assert_called_once_with("ggml-org/llama.cpp")
        self.assertEqual((result.key, result.latest), ("LLAMA_CPP_TAG", "server-cuda13-b10920"))
        self.assertEqual(
            result.notes, ("  llama.cpp build b10800 -> b10920: https://github.com/ggml-org/llama.cpp/releases",)
        )
        # The digest of the tag it names, so both pins are pasted together.
        resolved.assert_called_once_with("ggml-org/llama.cpp", "server-cuda13-b10920")
        self.assertEqual(result.digest, LLAMA_DIGEST)

    def test_the_ghcr_manifest_digest_is_the_hash_of_the_served_document(self) -> None:
        document = b'{"mediaType": "application/vnd.oci.image.index.v1+json"}'
        with (
            mock.patch.object(checkpins, "ghcr_token", return_value="t"),
            mock.patch.object(checkpins, "request_bytes", return_value=document) as request,
        ):
            digest = checkpins.ghcr_manifest_digest("ggml-org/llama.cpp", "server-cuda13-b10920")
        self.assertEqual(digest, hashlib.sha256(document).hexdigest())
        self.assertEqual(
            request.call_args.args[0], "https://ghcr.io/v2/ggml-org/llama.cpp/manifests/server-cuda13-b10920"
        )
        # The index media types are offered first, so a multi-platform tag
        # resolves to the list a FROM line pulls.
        self.assertTrue(request.call_args.kwargs["accept"].startswith("application/vnd.oci.image.index.v1+json"))

    def test_llama_cpp_is_current_when_no_newer_build_exists(self) -> None:
        # A current pin needs no digest lookup: nothing is pasted for it.
        values = {"LLAMA_CPP_TAG": "server-cuda13-b10920"}
        with mock.patch.object(checkpins, "ghcr_tags", return_value=["server-cuda13-b10920", "server-cuda13-b10884"]):
            result = checkpins.resolve_component("llama-cpp", values)
        self.assertEqual(result.latest, result.current)
        with mock.patch.object(checkpins, "ghcr_tags", return_value=["server-cuda13-b10884"]):
            with self.assertRaisesRegex(TokenCrateError, "older than the current pin"):
                checkpins.resolve_component("llama-cpp", values)
        with mock.patch.object(checkpins, "ghcr_tags", return_value=["server-cuda-b10920"]):
            with self.assertRaisesRegex(TokenCrateError, r"no server-cuda13-b\* image tag"):
                checkpins.resolve_component("llama-cpp", values)

    def test_llama_cpp_rejects_an_unsupported_or_missing_pin(self) -> None:
        with self.assertRaisesRegex(TokenCrateError, "unsupported current LLAMA_CPP_TAG: v255-cuda13-b10920"):
            checkpins.resolve_component("llama-cpp", {"LLAMA_CPP_TAG": "v255-cuda13-b10920"})
        with self.assertRaisesRegex(TokenCrateError, "pins.env has no value for LLAMA_CPP_TAG"):
            checkpins.resolve_component("llama-cpp", {})

    def test_npm_packages_use_the_registry_latest_tag(self) -> None:
        with mock.patch.object(checkpins, "request_json", return_value={"version": "0.86.0"}) as request:
            result = checkpins.resolve_component("pi", {"PI_VERSION": "0.85.1"})
        self.assertEqual((result.key, result.latest), ("PI_VERSION", "0.86.0"))
        self.assertIn("registry.npmjs.org/@earendil-works%2Fpi-coding-agent/latest", request.call_args.args[0])
        with mock.patch.object(checkpins, "request_json", return_value={"version": "18.1.18"}):
            result = checkpins.resolve_component("omp", {"OMP_VERSION": "18.1.18"})
        self.assertEqual(result.latest, result.current)

    def test_npm_rejects_prerelease_or_older_latest(self) -> None:
        with mock.patch.object(checkpins, "request_json", return_value={"version": "1.0.0-beta.1"}):
            with self.assertRaisesRegex(TokenCrateError, "no stable"):
                checkpins.resolve_component("pi", {"PI_VERSION": "0.85.1"})
        with mock.patch.object(checkpins, "request_json", return_value={"version": "0.1.0"}):
            with self.assertRaisesRegex(TokenCrateError, "older than"):
                checkpins.resolve_component("pi", {"PI_VERSION": "0.85.1"})

    def test_node_keeps_the_image_family_and_even_lts_majors(self) -> None:
        values = {"NODE_TAG": "24.21.0-bookworm-slim"}
        tags = [
            "27.0.0-bookworm-slim",
            "26.9.0-alpine",
            "26.9.0-bookworm",
            "26.9.0-bookworm-slim",
            "26.9-bookworm-slim",
            "26-bookworm-slim",
            "25.9.0-bookworm-slim",
        ]
        published = {tag: f"sha256:{index:064x}" for index, tag in enumerate(tags)}
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published):
            result = checkpins.resolve_component("node", values)
        self.assertEqual((result.key, result.latest), ("NODE_TAG", "26.9.0-bookworm-slim"))
        self.assertEqual(result.notes, ("  Image tags: https://hub.docker.com/_/node",))
        # The digest of the chosen tag, from the same listing.
        self.assertEqual(result.digest, f"{3:064x}")
        # A listing without the digest of that tag is refused rather than
        # reported with an empty pin.
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=dict.fromkeys(tags, "")):
            with self.assertRaisesRegex(TokenCrateError, "no sha256 manifest digest"):
                checkpins.resolve_component("node", values)

    def test_a_node_patch_release_is_reported_with_its_digest(self) -> None:
        # The pin names one release in full, so every patch release is a
        # new tag; a major-line tag, which Docker Hub moves to each release,
        # would leave the check silent.
        values = {"NODE_TAG": "26.9.0-bookworm-slim", "NODE_DIGEST": "11" * 32}
        published = {
            "26-bookworm-slim": "sha256:" + "22" * 32,
            "26.9.0-bookworm-slim": "sha256:" + "11" * 32,
            "26.9.1-bookworm-slim": "sha256:" + "22" * 32,
        }
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published):
            output = checkpins.check("node", values)
        self.assertEqual(
            output,
            "node: 26.9.0-bookworm-slim -> 26.9.1-bookworm-slim\n"
            "  Image tags: https://hub.docker.com/_/node\n"
            "\n"
            "Paste into pins.env:\n"
            "NODE_TAG=26.9.1-bookworm-slim\n"
            f"NODE_DIGEST={'22' * 32}\n",
        )

    def test_bun_image_follows_its_suffix(self) -> None:
        published = dict.fromkeys(["1.4.3-slim", "1.4.3", "1.4.3-alpine"], BUN_DIGEST)
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published):
            result = checkpins.resolve_component("bun", {"BUN_TAG": "1.4.2-slim"})
        self.assertEqual((result.key, result.latest, result.digest), ("BUN_TAG", "1.4.3-slim", BUN_DIGEST[7:]))
        self.assertEqual(result.notes, ("  Image tags: https://hub.docker.com/r/oven/bun/tags",))

    def test_the_components_are_exactly_the_pinned_images_and_packages(self) -> None:
        self.assertEqual(checkpins.COMPONENTS, ("llama-cpp", "pi", "omp", "node", "bun"))
        with self.assertRaisesRegex(TokenCrateError, "unknown pin component: cuda"):
            checkpins.resolve_component("cuda", {"CUDA_MIN_DRIVER_MAJOR": "580"})

    def test_request_rejects_non_https_url_before_opening_it(self) -> None:
        with (
            mock.patch.object(urllib.request, "urlopen") as urlopen,
            self.assertRaisesRegex(TokenCrateError, "must use HTTPS"),
        ):
            checkpins.request_bytes("http://registry.example/pkg")
        urlopen.assert_not_called()

    def test_docker_hub_rejects_unsafe_pagination_link(self) -> None:
        payload = {"results": [], "next": "http://hub.docker.com/next"}
        with mock.patch.object(checkpins, "request_json", return_value=payload):
            with self.assertRaisesRegex(TokenCrateError, "unsafe pagination"):
                checkpins.docker_hub_tags("library", "node", "bookworm-slim")


class ReportTests(unittest.TestCase):
    def test_reports_every_component_and_a_paste_block_for_the_newer_ones(self) -> None:
        resolutions = {
            "llama-cpp": checkpins.Resolution(
                "llama-cpp",
                "LLAMA_CPP_TAG",
                "server-cuda13-b1",
                "server-cuda13-b2",
                ("  llama.cpp build b1 -> b2: https://example/llama.cpp",),
                LLAMA_DIGEST,
            ),
            "pi": checkpins.Resolution("pi", "PI_VERSION", "0.85.1", "0.86.0", ("  Package history: https://npm/pi",)),
            "omp": current("omp", "OMP_VERSION", "18.1.18"),
            "node": current("node", "NODE_TAG", "24.21.0-bookworm-slim"),
            "bun": current("bun", "BUN_TAG", "1.4.2-slim"),
        }
        with (
            mock.patch.object(
                checkpins, "resolve_component", side_effect=lambda component, values: resolutions[component]
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            output = checkpins.check("all", {"X": "1"})

        self.assertEqual(
            output,
            "llama-cpp: server-cuda13-b1 -> server-cuda13-b2\n"
            "  llama.cpp build b1 -> b2: https://example/llama.cpp\n"
            "pi: 0.85.1 -> 0.86.0\n"
            "  Package history: https://npm/pi\n"
            "omp: 18.1.18 (latest eligible)\n"
            "node: 24.21.0-bookworm-slim (latest eligible)\n"
            "bun: 1.4.2-slim (latest eligible)\n"
            "\n"
            "Paste into pins.env:\n"
            # The digest belongs to the tag above it; a version pin has none.
            "LLAMA_CPP_TAG=server-cuda13-b2\n"
            f"LLAMA_CPP_DIGEST={LLAMA_DIGEST}\n"
            "PI_VERSION=0.86.0\n",
        )
        # The report is returned, not printed; the CLI prints and saves it.
        self.assertEqual(stdout.getvalue(), "")

    def test_model_sets_waiting_for_a_newer_build_are_listed_under_llama_cpp(self) -> None:
        newer = checkpins.Resolution(
            "llama-cpp", "LLAMA_CPP_TAG", "server-cuda13-b1", "server-cuda13-b2", ("  llama.cpp build b1 -> b2: x",)
        )
        waits = ("model set glm waits for an unreleased llama.cpp build (pinned: b1)",)
        with mock.patch.object(checkpins, "resolve_component", return_value=newer):
            output = checkpins.check("llama-cpp", {"X": "1"}, waits=waits)
        self.assertTrue(
            output.startswith(
                "llama-cpp: server-cuda13-b1 -> server-cuda13-b2\n"
                "  llama.cpp build b1 -> b2: x\n"
                "  model set glm waits for an unreleased llama.cpp build (pinned: b1)\n"
                "\nPaste into pins.env:\n"
            ),
            output,
        )
        with mock.patch.object(
            checkpins, "resolve_component", return_value=current("llama-cpp", "LLAMA_CPP_TAG", "s-b1")
        ):
            output = checkpins.check("llama-cpp", {"X": "1"}, waits=waits)
        self.assertEqual(
            output,
            "llama-cpp: s-b1 (latest eligible)\n"
            "  model set glm waits for an unreleased llama.cpp build (pinned: b1)\n"
            "pins.env has the latest eligible pins.\n",
        )
        # The wait concerns the llama.cpp pin only.
        with mock.patch.object(checkpins, "resolve_component", return_value=current("node", "NODE_TAG", "24")):
            self.assertNotIn("model set", checkpins.check("node", {"X": "1"}, waits=waits))

    def test_reports_latest_eligible_pins_without_a_paste_block(self) -> None:
        resolution = current("node", "NODE_TAG", "24.21.0-bookworm-slim")
        with mock.patch.object(checkpins, "resolve_component", return_value=resolution) as resolve:
            output = checkpins.check("node", {"NODE_TAG": "24.21.0-bookworm-slim"})
        resolve.assert_called_once_with("node", {"NODE_TAG": "24.21.0-bookworm-slim"})
        self.assertEqual(
            output,
            "node: 24.21.0-bookworm-slim (latest eligible)\npins.env has the latest eligible pins.\n",
        )

    def test_raises_and_reports_nothing_when_any_source_fails(self) -> None:
        first = checkpins.Resolution("pi", "PI_VERSION", "0.85.1", "0.86.0")
        with (
            mock.patch.object(
                checkpins,
                "resolve_component",
                side_effect=[first, TokenCrateError("later source failed")],
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            self.assertRaisesRegex(TokenCrateError, "later source failed"),
        ):
            checkpins.check("all", {"X": "1"})
        self.assertEqual(stdout.getvalue(), "")

    def test_rejects_an_unknown_component_before_resolving(self) -> None:
        with (
            mock.patch.object(checkpins, "resolve_component") as resolve,
            self.assertRaisesRegex(
                TokenCrateError, "unknown pin component 'rust'; choose from: llama-cpp, pi, omp, node, bun, all"
            ),
        ):
            checkpins.check("rust", {"X": "1"})
        resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
