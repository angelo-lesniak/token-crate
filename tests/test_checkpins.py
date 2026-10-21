"""Unit tests for the pin checker (resolvers with mocked sources and the report text)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tokencrate import TokenCrateError, checkpins

LLAMA_DIGEST = "8d" * 32
BUN_DIGEST = "sha256:" + "cb" * 32
# A pins.env as `env.load_pins` returns it: every pin in file order.
PINS = {
    "LLAMA_CPP_TAG": "server-cuda13-b1",
    "LLAMA_CPP_DIGEST": "a" * 64,
    "PI_VERSION": "0.85.1",
    "OMP_VERSION": "18.1.18",
    "NODE_TAG": "24.21.0-bookworm-slim",
    "NODE_DIGEST": "b" * 64,
    "BUN_TAG": "1.4.2-slim",
    "BUN_DIGEST": "c" * 64,
    "VICTORIAMETRICS_TAG": "v1.152.0",
    "VICTORIAMETRICS_DIGEST": "d" * 64,
    "GRAFANA_TAG": "13.2.2",
    "GRAFANA_DIGEST": "e" * 64,
    "DCGM_EXPORTER_TAG": "4.6.1-4.8.4",
    "DCGM_EXPORTER_DIGEST": "f" * 64,
    "CUDA_MIN_DRIVER_MAJOR": "580",
}


def current(key: str, value: str) -> checkpins.Resolution:
    return checkpins.Resolution(key, value, value)


def resolve(key: str, values: dict[str, str]) -> checkpins.Resolution:
    return checkpins.RESOLVERS[key](values)


def releases(*builds: int) -> list[dict[str, str]]:
    return [{"tag_name": f"b{build}", "name": f"b{build}"} for build in builds]


class LlamaCppTests(unittest.TestCase):
    def test_the_newest_build_with_an_image_of_the_pinned_family_wins(self) -> None:
        values = {"LLAMA_CPP_TAG": "server-cuda13-b10800"}
        # The images are published for builds of their own, not for releases:
        # the newest release (b10999) has none, b10997 has one. The walk goes
        # build by build with one GHCR token for the whole check.
        manifests = {"server-cuda13-b10997": b'{"mediaType": "index"}'}
        with (
            mock.patch.object(checkpins, "llama_cpp_release_builds", return_value=[10999, 10920, 10884]),
            mock.patch.object(checkpins, "ghcr_token", return_value="tok") as token,
            mock.patch.object(
                checkpins, "ghcr_manifest", side_effect=lambda repo, tag, token: manifests.get(tag)
            ) as fetched,
        ):
            result = resolve("LLAMA_CPP_TAG", values)
        self.assertEqual((result.key, result.latest), ("LLAMA_CPP_TAG", "server-cuda13-b10997"))
        self.assertEqual(
            result.notes, ("  llama.cpp build b10800 -> b10997: https://github.com/ggml-org/llama.cpp/releases",)
        )
        token.assert_called_once_with("ggml-org/llama.cpp")
        self.assertEqual(
            fetched.call_args_list,
            [mock.call("ggml-org/llama.cpp", f"server-cuda13-b{build}", "tok") for build in (10999, 10998, 10997)],
        )
        # The manifest that confirmed the image is the digest pasted beside the tag.
        self.assertEqual(result.digest, hashlib.sha256(manifests["server-cuda13-b10997"]).hexdigest())

    def test_llama_cpp_is_current_when_no_newer_build_has_an_image(self) -> None:
        values = {"LLAMA_CPP_TAG": "server-cuda13-b10920"}
        # A current pin fetches no token and no manifest: nothing is pasted for it.
        with (
            mock.patch.object(checkpins, "llama_cpp_release_builds", return_value=[10920, 10884]),
            mock.patch.object(checkpins, "ghcr_token") as token,
            mock.patch.object(checkpins, "ghcr_manifest") as fetched,
        ):
            self.assertEqual(resolve("LLAMA_CPP_TAG", values).latest, "server-cuda13-b10920")
        token.assert_not_called()
        fetched.assert_not_called()
        # Newer builds without the image leave the pin current; the walk stops at the pin.
        with (
            mock.patch.object(checkpins, "llama_cpp_release_builds", return_value=[10925, 10920]),
            mock.patch.object(checkpins, "ghcr_token", return_value="tok"),
            mock.patch.object(checkpins, "ghcr_manifest", return_value=None) as fetched,
        ):
            self.assertEqual(resolve("LLAMA_CPP_TAG", values).latest, "server-cuda13-b10920")
        self.assertEqual(len(fetched.call_args_list), 5)
        with mock.patch.object(checkpins, "llama_cpp_release_builds", return_value=[10884]):
            with self.assertRaisesRegex(TokenCrateError, "older than the current pin"):
                resolve("LLAMA_CPP_TAG", values)
        # A pin far behind with no image within the probe limit is a lookup failure, not "current".
        with (
            mock.patch.object(checkpins, "llama_cpp_release_builds", return_value=[10999, 10998]),
            mock.patch.object(checkpins, "ghcr_token", return_value="tok"),
            mock.patch.object(checkpins, "ghcr_manifest", return_value=None) as fetched,
        ):
            with self.assertRaisesRegex(TokenCrateError, "none of the 60 builds below b10999 has a server-cuda13"):
                resolve("LLAMA_CPP_TAG", {"LLAMA_CPP_TAG": "server-cuda13-b10"})
        self.assertEqual(len(fetched.call_args_list), checkpins.LLAMA_CPP_PROBE_LIMIT)

    def test_llama_cpp_rejects_an_unsupported_or_missing_pin(self) -> None:
        with self.assertRaisesRegex(TokenCrateError, "unsupported current LLAMA_CPP_TAG: v255-cuda13-b10920"):
            resolve("LLAMA_CPP_TAG", {"LLAMA_CPP_TAG": "v255-cuda13-b10920"})
        with self.assertRaisesRegex(TokenCrateError, "pins.env has no value for LLAMA_CPP_TAG"):
            resolve("LLAMA_CPP_TAG", {})

    def test_the_release_list_is_read_newest_first_from_the_releases_api(self) -> None:
        payload = releases(10884, 10920) + [{"tag_name": "gguf-v0.4.0"}, "junk"]
        with mock.patch.object(checkpins, "request_json", return_value=payload) as request:
            self.assertEqual(checkpins.llama_cpp_release_builds(), [10920, 10884])
        self.assertEqual(
            request.call_args.args[0], "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"
        )
        with mock.patch.object(checkpins, "request_json", return_value=[{"tag_name": "gguf-v0.4.0"}]):
            with self.assertRaisesRegex(TokenCrateError, "no llama.cpp release tagged"):
                checkpins.llama_cpp_release_builds()
        with mock.patch.object(checkpins, "request_json", return_value={"message": "rate limited"}):
            with self.assertRaisesRegex(TokenCrateError, "invalid llama.cpp release list"):
                checkpins.llama_cpp_release_builds()

    def test_the_ghcr_manifest_is_the_served_document_or_none_for_a_missing_tag(self) -> None:
        document = b'{"mediaType": "application/vnd.oci.image.index.v1+json"}'
        with (
            mock.patch.object(checkpins, "ghcr_token", return_value="t"),
            mock.patch.object(checkpins, "request_bytes", return_value=document) as request,
        ):
            self.assertEqual(checkpins.ghcr_manifest("ggml-org/llama.cpp", "server-cuda13-b10920"), document)
        self.assertEqual(
            request.call_args.args[0], "https://ghcr.io/v2/ggml-org/llama.cpp/manifests/server-cuda13-b10920"
        )
        self.assertEqual(request.call_args.kwargs["headers"], {"Authorization": "Bearer t"})
        self.assertTrue(request.call_args.kwargs["missing_ok"])
        # The index media types are offered first, so a multi-platform tag
        # resolves to the list a FROM line pulls.
        self.assertTrue(request.call_args.kwargs["accept"].startswith("application/vnd.oci.image.index.v1+json"))

    def test_a_404_is_none_only_when_the_caller_allows_a_missing_source(self) -> None:
        bodies = []

        def not_found(request, timeout):
            bodies.append(io.BytesIO())
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, bodies[-1])

        with mock.patch.object(urllib.request, "urlopen", side_effect=not_found):
            self.assertIsNone(checkpins.request_bytes("https://ghcr.io/v2/x/manifests/y", missing_ok=True))
            with self.assertRaisesRegex(TokenCrateError, "could not read pin source .*: HTTP 404"):
                checkpins.request_bytes("https://ghcr.io/v2/x/manifests/y")
        # The refused response is closed on both paths, not left to the GC.
        self.assertEqual([body.closed for body in bodies], [True, True])

    def test_a_refusal_names_the_rate_limit_headers(self) -> None:
        headers = {"X-RateLimit-Remaining": "0", "Retry-After": "42"}

        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", headers, io.BytesIO())

        with mock.patch.object(urllib.request, "urlopen", side_effect=refused):
            with self.assertRaisesRegex(TokenCrateError, "HTTP 403, rate limit remaining 0, retry after 42 seconds$"):
                checkpins.request_bytes("https://api.github.com/repos/x/releases")


class RegistryResolverTests(unittest.TestCase):
    def test_npm_packages_use_the_registry_latest_tag(self) -> None:
        with mock.patch.object(checkpins, "request_json", return_value={"version": "0.86.0"}) as request:
            result = resolve("PI_VERSION", {"PI_VERSION": "0.85.1"})
        self.assertEqual((result.key, result.latest), ("PI_VERSION", "0.86.0"))
        self.assertIn("registry.npmjs.org/@earendil-works%2Fpi-coding-agent/latest", request.call_args.args[0])
        with mock.patch.object(checkpins, "request_json", return_value={"version": "18.1.18"}) as request:
            result = resolve("OMP_VERSION", {"OMP_VERSION": "18.1.18"})
        self.assertIn("registry.npmjs.org/@oh-my-pi%2Fpi-coding-agent/latest", request.call_args.args[0])
        self.assertEqual(result.latest, result.current)

    def test_npm_rejects_prerelease_or_older_latest(self) -> None:
        with mock.patch.object(checkpins, "request_json", return_value={"version": "1.0.0-beta.1"}):
            with self.assertRaisesRegex(TokenCrateError, "no stable"):
                resolve("PI_VERSION", {"PI_VERSION": "0.85.1"})
        with mock.patch.object(checkpins, "request_json", return_value={"version": "0.1.0"}):
            with self.assertRaisesRegex(TokenCrateError, "older than"):
                resolve("PI_VERSION", {"PI_VERSION": "0.85.1"})

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
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published) as listed:
            result = resolve("NODE_TAG", values)
        self.assertEqual(listed.call_args.args[:3], ("library", "node", "bookworm-slim"))
        self.assertEqual((result.key, result.latest), ("NODE_TAG", "26.9.0-bookworm-slim"))
        self.assertEqual(result.notes, ("  Image tags: https://hub.docker.com/_/node",))
        # The digest of the chosen tag, from the same listing.
        self.assertEqual(result.digest, f"{3:064x}")
        # A listing without the digest of that tag is refused rather than
        # reported with an empty pin.
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=dict.fromkeys(tags, "")):
            with self.assertRaisesRegex(TokenCrateError, "no sha256 manifest digest"):
                resolve("NODE_TAG", values)

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
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published) as listed:
            result = resolve("BUN_TAG", {"BUN_TAG": "1.4.2-slim"})
        self.assertEqual(listed.call_args.args[:3], ("oven", "bun", "slim"))
        self.assertEqual((result.key, result.latest, result.digest), ("BUN_TAG", "1.4.3-slim", BUN_DIGEST[7:]))
        self.assertEqual(result.notes, ("  Image tags: https://hub.docker.com/r/oven/bun/tags",))

    def test_the_dashboard_images_follow_release_tags_within_their_major(self) -> None:
        values = {"VICTORIAMETRICS_TAG": "v1.150.0", "GRAFANA_TAG": "13.2.2"}
        published = {
            tag: f"sha256:{index:064x}" for index, tag in enumerate(["v1.152.0", "v1.152.0-cluster", "v1.151.0"])
        }
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published) as listed:
            result = resolve("VICTORIAMETRICS_TAG", values)
        self.assertEqual(listed.call_args.args[:3], ("victoriametrics", "victoria-metrics", "v1."))
        self.assertEqual((result.key, result.latest, result.digest), ("VICTORIAMETRICS_TAG", "v1.152.0", "00" * 32))
        published = {tag: f"sha256:{index:064x}" for index, tag in enumerate(["13.2.2", "13.2.2-ubuntu", "13.3.0"])}
        with mock.patch.object(checkpins, "docker_hub_tags", return_value=published) as listed:
            result = resolve("GRAFANA_TAG", values)
        self.assertEqual(listed.call_args.args[:3], ("grafana", "grafana", "13."))
        self.assertEqual((result.key, result.latest), ("GRAFANA_TAG", "13.3.0"))

    def test_request_rejects_non_https_url_before_opening_it(self) -> None:
        with (
            mock.patch.object(urllib.request, "urlopen") as urlopen,
            self.assertRaisesRegex(TokenCrateError, "must use HTTPS"),
        ):
            checkpins.request_bytes("http://registry.example/pkg")
        urlopen.assert_not_called()

    def test_request_refuses_a_redirect_off_https_and_a_body_over_the_cap(self) -> None:
        def served(url: str, body: bytes) -> mock._patch:
            response = mock.Mock(url=url, read=lambda size: body[:size])
            return mock.patch.object(urllib.request, "urlopen", return_value=contextlib.nullcontext(response))

        with served("http://registry.example/pkg", b"{}"), self.assertRaisesRegex(TokenCrateError, "away from HTTPS"):
            checkpins.request_bytes("https://registry.example/pkg")
        # The body is read one byte past the cap, so a longer one is refused
        # without trusting a Content-Length header.
        too_long = b"x" * (checkpins.MAX_RESPONSE_BYTES + 1)
        with served("https://registry.example/pkg", too_long), self.assertRaisesRegex(TokenCrateError, "too large"):
            checkpins.request_bytes("https://registry.example/pkg")
        with served("https://registry.example/pkg", too_long[1:]):
            self.assertEqual(len(checkpins.request_bytes("https://registry.example/pkg")), checkpins.MAX_RESPONSE_BYTES)

    def test_docker_hub_rejects_unsafe_pagination_link(self) -> None:
        payload = {"results": [], "next": "http://hub.docker.com/next"}
        with mock.patch.object(checkpins, "request_json", return_value=payload):
            with self.assertRaisesRegex(TokenCrateError, "unsafe pagination"):
                checkpins.docker_hub_tags("library", "node", "bookworm-slim")


class ReportTests(unittest.TestCase):
    def test_the_component_names_are_derived_from_the_pin_keys(self) -> None:
        names = [checkpins.component_name(key) for key in PINS if not key.endswith("_DIGEST")]
        self.assertEqual(
            names,
            [
                "llama-cpp",
                "pi",
                "omp",
                "node",
                "bun",
                "victoriametrics",
                "grafana",
                "dcgm-exporter",
                "cuda-min-driver-major",
            ],
        )
        # Every resolver is keyed by a pin the shipped file has.
        self.assertTrue(set(checkpins.RESOLVERS) <= set(PINS))

    def test_reports_every_pin_and_a_paste_block_for_the_newer_ones(self) -> None:
        resolutions = {
            "LLAMA_CPP_TAG": checkpins.Resolution(
                "LLAMA_CPP_TAG",
                "server-cuda13-b1",
                "server-cuda13-b2",
                ("  llama.cpp build b1 -> b2: https://example/llama.cpp",),
                LLAMA_DIGEST,
            ),
            "PI_VERSION": checkpins.Resolution(
                "PI_VERSION", "0.85.1", "0.86.0", ("  Package history: https://npm/pi",)
            ),
            "OMP_VERSION": current("OMP_VERSION", "18.1.18"),
            "NODE_TAG": current("NODE_TAG", "24.21.0-bookworm-slim"),
            "BUN_TAG": current("BUN_TAG", "1.4.2-slim"),
            "VICTORIAMETRICS_TAG": current("VICTORIAMETRICS_TAG", "v1.152.0"),
            "GRAFANA_TAG": current("GRAFANA_TAG", "13.2.2"),
        }
        resolvers = {key: mock.Mock(return_value=resolution) for key, resolution in resolutions.items()}
        with (
            mock.patch.dict(checkpins.RESOLVERS, resolvers, clear=True),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            output = checkpins.check("all", PINS)

        self.assertEqual(
            output,
            "llama-cpp: server-cuda13-b1 -> server-cuda13-b2\n"
            "  llama.cpp build b1 -> b2: https://example/llama.cpp\n"
            "pi: 0.85.1 -> 0.86.0\n"
            "  Package history: https://npm/pi\n"
            "omp: 18.1.18 (latest eligible)\n"
            "node: 24.21.0-bookworm-slim (latest eligible)\n"
            "bun: 1.4.2-slim (latest eligible)\n"
            "victoriametrics: v1.152.0 (latest eligible)\n"
            "grafana: 13.2.2 (latest eligible)\n"
            # The pins without a resolver are rows too, so the coverage of
            # the check is its output.
            "dcgm-exporter: 4.6.1-4.8.4 (no resolver; look it up by hand)\n"
            "cuda-min-driver-major: 580 (no resolver; look it up by hand)\n"
            "\n"
            "Paste into pins.env:\n"
            # The digest belongs to the tag above it; a version pin has none.
            "LLAMA_CPP_TAG=server-cuda13-b2\n"
            f"LLAMA_CPP_DIGEST={LLAMA_DIGEST}\n"
            "PI_VERSION=0.86.0\n",
        )
        for resolver in resolvers.values():
            resolver.assert_called_once_with(PINS)
        # The report is returned, not printed; the CLI prints and saves it.
        self.assertEqual(stdout.getvalue(), "")

    def test_a_pin_without_a_resolver_can_be_selected_and_qualifies_the_summary(self) -> None:
        with mock.patch.dict(checkpins.RESOLVERS, {}, clear=True):
            self.assertEqual(
                checkpins.check("dcgm-exporter", PINS), "dcgm-exporter: 4.6.1-4.8.4 (no resolver; look it up by hand)\n"
            )
        resolvers = {"NODE_TAG": mock.Mock(return_value=current("NODE_TAG", "24.21.0-bookworm-slim"))}
        with mock.patch.dict(checkpins.RESOLVERS, resolvers, clear=True):
            output = checkpins.check(
                "all", {"NODE_TAG": "24.21.0-bookworm-slim", "NODE_DIGEST": "b" * 64, "CUDA_MIN_DRIVER_MAJOR": "580"}
            )
        self.assertEqual(
            output,
            "node: 24.21.0-bookworm-slim (latest eligible)\n"
            "cuda-min-driver-major: 580 (no resolver; look it up by hand)\n"
            "The resolved pins are the latest eligible.\n",
        )

    def test_model_sets_waiting_for_a_newer_build_are_listed_under_llama_cpp(self) -> None:
        newer = checkpins.Resolution(
            "LLAMA_CPP_TAG", "server-cuda13-b1", "server-cuda13-b2", ("  llama.cpp build b1 -> b2: x",)
        )
        waits = ("model set glm waits for an unreleased llama.cpp build (pinned: b1)",)
        with mock.patch.dict(checkpins.RESOLVERS, {"LLAMA_CPP_TAG": mock.Mock(return_value=newer)}, clear=True):
            output = checkpins.check("llama-cpp", PINS, waits=waits)
        self.assertTrue(
            output.startswith(
                "llama-cpp: server-cuda13-b1 -> server-cuda13-b2\n"
                "  llama.cpp build b1 -> b2: x\n"
                "  model set glm waits for an unreleased llama.cpp build (pinned: b1)\n"
                "\nPaste into pins.env:\n"
            ),
            output,
        )
        resolvers = {"LLAMA_CPP_TAG": mock.Mock(return_value=current("LLAMA_CPP_TAG", "server-cuda13-b1"))}
        with mock.patch.dict(checkpins.RESOLVERS, resolvers, clear=True):
            output = checkpins.check("llama-cpp", PINS, waits=waits)
        self.assertEqual(
            output,
            "llama-cpp: server-cuda13-b1 (latest eligible)\n"
            "  model set glm waits for an unreleased llama.cpp build (pinned: b1)\n"
            "pins.env has the latest eligible pins.\n",
        )
        # The wait concerns the llama.cpp pin only.
        resolvers = {"NODE_TAG": mock.Mock(return_value=current("NODE_TAG", "24.21.0-bookworm-slim"))}
        with mock.patch.dict(checkpins.RESOLVERS, resolvers, clear=True):
            self.assertNotIn("model set", checkpins.check("node", PINS, waits=waits))

    def test_reports_latest_eligible_pins_without_a_paste_block(self) -> None:
        resolver = mock.Mock(return_value=current("NODE_TAG", "24.21.0-bookworm-slim"))
        with mock.patch.dict(checkpins.RESOLVERS, {"NODE_TAG": resolver}, clear=True):
            output = checkpins.check("node", PINS)
        resolver.assert_called_once_with(PINS)
        self.assertEqual(
            output,
            "node: 24.21.0-bookworm-slim (latest eligible)\npins.env has the latest eligible pins.\n",
        )

    def test_a_failing_source_is_one_row_and_the_report_is_raised(self) -> None:
        # The other pins are still reported (Docker Hub refused page eleven
        # of a listing once, and the rows before it were lost), and the
        # exception carries the report so the command can print it and
        # still exit with a failure.
        resolvers = {
            "PI_VERSION": mock.Mock(return_value=checkpins.Resolution("PI_VERSION", "0.85.1", "0.86.0")),
            "NODE_TAG": mock.Mock(side_effect=TokenCrateError("later source failed")),
        }
        with (
            mock.patch.dict(checkpins.RESOLVERS, resolvers, clear=True),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            self.assertRaises(checkpins.LookupsFailed) as raised,
        ):
            checkpins.check("all", PINS)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(raised.exception.failed, ["node"])
        self.assertIn("pins check could not read the source of: node", str(raised.exception))
        report = raised.exception.report
        self.assertIn("pi: 0.85.1 -> 0.86.0\n", report)
        self.assertIn("node: 24.21.0-bookworm-slim (lookup failed: later source failed)\n", report)
        self.assertIn("Paste into pins.env:\nPI_VERSION=0.86.0\n", report)

    def test_docker_hub_is_read_newest_first_and_stops_behind_the_latest(self) -> None:
        # Three pages newest first: the latest release is on the first, the
        # second adds nothing newer, so the third is never requested.
        pages = [
            {
                "results": [{"name": "latest", "digest": "sha256:l"}, {"name": "v1.154.0", "digest": "sha256:a"}],
                "next": "https://hub.docker.com/v2/x?page=2",
            },
            {
                "results": [{"name": "v1.136.20", "digest": "sha256:b"}],
                "next": "https://hub.docker.com/v2/x?page=3",
            },
            {"results": [{"name": "v1.153.0", "digest": "sha256:c"}], "next": None},
        ]
        pattern = re.compile(rf"^v{checkpins.STABLE_TAG_RE}$")
        with mock.patch.object(checkpins, "request_json", side_effect=pages) as request:
            tags = checkpins.docker_hub_tags(
                "victoriametrics", "victoria-metrics", "v1.", lambda tag: checkpins.version_key(tag, pattern)
            )
        self.assertEqual(request.call_count, 2)
        self.assertIn("ordering=last_updated", request.call_args_list[0].args[0])
        self.assertEqual(tags, {"latest": "sha256:l", "v1.154.0": "sha256:a", "v1.136.20": "sha256:b"})

    def test_docker_hub_stops_at_the_anonymous_page_limit(self) -> None:
        page = {"results": [{"name": "x", "digest": ""}], "next": "https://hub.docker.com/v2/x?page=2"}
        with (
            mock.patch.object(checkpins, "request_json", return_value=page),
            self.assertRaisesRegex(TokenCrateError, "10-page listing limit"),
        ):
            checkpins.docker_hub_tags("library", "node", "26.")

    def test_rejects_an_unknown_component_before_resolving(self) -> None:
        resolver = mock.Mock()
        with (
            mock.patch.dict(checkpins.RESOLVERS, {"NODE_TAG": resolver}, clear=True),
            self.assertRaisesRegex(
                TokenCrateError,
                "unknown pin component 'rust'; choose from: llama-cpp, pi, omp, node, bun, "
                "victoriametrics, grafana, dcgm-exporter, cuda-min-driver-major, all",
            ),
        ):
            checkpins.check("rust", PINS)
        resolver.assert_not_called()
        # A digest is resolved with its tag, never selected on its own.
        with self.assertRaisesRegex(TokenCrateError, "unknown pin component 'node-digest'"):
            checkpins.check("node-digest", PINS)


if __name__ == "__main__":
    unittest.main()
