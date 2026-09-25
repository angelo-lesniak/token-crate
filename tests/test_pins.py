"""pins.env (read by tokencrate.env): exactly the pinned keys, as plain values."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tokencrate import PROJECT_ROOT, TokenCrateError, env


class PinsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "pins.env"

    def write(self, **overrides: str) -> Path:
        values = {
            "LLAMA_CPP_TAG": "server-cuda13-b10920",
            "LLAMA_CPP_DIGEST": "a" * 64,
            "PI_VERSION": "0.85.1",
            "OMP_VERSION": "18.1.18",
            "NODE_TAG": "24-bookworm-slim",
            "NODE_DIGEST": "b" * 64,
            "BUN_TAG": "1.4.2-slim",
            "BUN_DIGEST": "c" * 64,
            "CUDA_MIN_DRIVER_MAJOR": "580",
        }
        values.update(overrides)
        self.path.write_text("# comment\n\n" + "".join(f"{key}={value}\n" for key, value in values.items()))
        return self.path

    def test_the_shipped_file_defines_exactly_the_pinned_keys(self) -> None:
        values = env.load_pins(PROJECT_ROOT / "pins.env")
        self.assertEqual(set(values), set(env.PIN_KEYS))
        self.assertTrue(values["LLAMA_CPP_TAG"].startswith("server-"))
        self.assertRegex(values["LLAMA_CPP_TAG"], r"-b\d+$")

    def test_quotes_and_whitespace_are_refused(self) -> None:
        for value in ('"server-cuda13-b10920"', "server-cuda13-b10920 ", "server cuda13", "ghcr.io/x:b10920"):
            self.write(LLAMA_CPP_TAG=value)
            with self.assertRaisesRegex(TokenCrateError, "unsafe value for LLAMA_CPP_TAG"):
                env.load_pins(self.path)

    def test_a_missing_duplicate_or_unknown_key_is_refused(self) -> None:
        self.path.write_text("PI_VERSION=0.85.1\n")
        with self.assertRaisesRegex(TokenCrateError, "must define LLAMA_CPP_TAG"):
            env.load_pins(self.path)
        self.write()
        self.path.write_text(self.path.read_text() + "PI_VERSION=0.85.2\n")
        with self.assertRaisesRegex(TokenCrateError, "PI_VERSION is set twice"):
            env.load_pins(self.path)
        self.write()
        self.path.write_text(self.path.read_text() + "TOOL_PYTHON_IMAGE=python\n")
        with self.assertRaisesRegex(TokenCrateError, "unknown key"):
            env.load_pins(self.path)

    def test_the_driver_minimum_must_be_a_number(self) -> None:
        self.write(CUDA_MIN_DRIVER_MAJOR="latest")
        with self.assertRaisesRegex(TokenCrateError, "driver major version"):
            env.load_pins(self.path)

    def test_a_digest_must_be_the_bare_sha256_hex(self) -> None:
        # The sha256: prefix is refused by the plain-value rule before this one.
        for value in ("a" * 63, "A" * 64, "sha256-" + "a" * 57):
            self.write(NODE_DIGEST=value)
            with self.assertRaisesRegex(TokenCrateError, "NODE_DIGEST must be the 64 hex characters"):
                env.load_pins(self.path)

    def test_a_malformed_line_names_its_number(self) -> None:
        self.write()
        self.path.write_text(self.path.read_text() + "not a pin\n")
        with self.assertRaisesRegex(TokenCrateError, r"pins\.env:12: expected KEY=VALUE"):
            env.load_pins(self.path)
        self.write()
        self.path.write_text(self.path.read_text().replace("PI_VERSION=", "export PI_VERSION=", 1))
        with self.assertRaisesRegex(TokenCrateError, r"pins\.env:5: expected KEY=VALUE"):
            env.load_pins(self.path)

    def test_pinned_lines_prints_the_values_without_comments(self) -> None:
        printed = env.pinned_lines(self.write())
        self.assertNotIn("# comment", printed)
        self.assertIn("PI_VERSION=0.85.1\n", printed)
        self.assertEqual(len(printed.strip().splitlines()), len(env.PIN_KEYS))


if __name__ == "__main__":
    unittest.main()
