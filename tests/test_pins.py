"""pins.env (read by tokencrate.env): pins by naming convention, as plain values."""

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
            "VICTORIAMETRICS_TAG": "v1.152.0",
            "VICTORIAMETRICS_DIGEST": "d" * 64,
            "GRAFANA_TAG": "13.2.2",
            "GRAFANA_DIGEST": "e" * 64,
            "DCGM_EXPORTER_TAG": "4.6.1-4.8.4",
            "DCGM_EXPORTER_DIGEST": "f" * 64,
            "CUDA_MIN_DRIVER_MAJOR": "580",
        }
        values.update(overrides)
        self.path.write_text("# comment\n\n" + "".join(f"{key}={value}\n" for key, value in values.items()))
        return self.path

    def test_the_shipped_file_follows_the_naming_convention(self) -> None:
        values = env.load_pins(PROJECT_ROOT / "pins.env")
        # The module-level key lists are the shipped file's, in file order.
        self.assertEqual(tuple(values), env.PIN_KEYS)
        self.assertEqual(env.DIGEST_KEYS, tuple(key for key in values if key.endswith("_DIGEST")))
        self.assertIn("LLAMA_CPP_DIGEST", env.DIGEST_KEYS)
        self.assertTrue(values["LLAMA_CPP_TAG"].startswith("server-"))
        self.assertRegex(values["LLAMA_CPP_TAG"], r"-b\d+$")

    def test_a_new_pin_needs_no_code_when_it_follows_the_convention(self) -> None:
        self.write(TOOL_VERSION="1.2.3", OTHER_TAG="v2", OTHER_DIGEST="0" * 64)
        values = env.load_pins(self.path)
        self.assertEqual(values["TOOL_VERSION"], "1.2.3")
        self.assertEqual(values["OTHER_TAG"], "v2")
        # File order is kept: `pins check` reports the pins in it.
        self.assertEqual(list(values)[:2], ["LLAMA_CPP_TAG", "LLAMA_CPP_DIGEST"])

    def test_quotes_and_whitespace_are_refused(self) -> None:
        for value in ('"server-cuda13-b10920"', "server-cuda13-b10920 ", "server cuda13", "ghcr.io/x:b10920"):
            self.write(LLAMA_CPP_TAG=value)
            with self.assertRaisesRegex(TokenCrateError, "unsafe value for LLAMA_CPP_TAG"):
                env.load_pins(self.path)

    def test_a_missing_duplicate_or_unknown_key_is_refused(self) -> None:
        # The wrapper itself reads two pins; Compose requires the rest.
        self.path.write_text("PI_VERSION=0.85.1\n")
        with self.assertRaisesRegex(TokenCrateError, "must define LLAMA_CPP_TAG, CUDA_MIN_DRIVER_MAJOR"):
            env.load_pins(self.path)
        self.write()
        self.path.write_text(self.path.read_text() + "PI_VERSION=0.85.2\n")
        with self.assertRaisesRegex(TokenCrateError, "PI_VERSION is set twice"):
            env.load_pins(self.path)
        for key in ("TOOL_PYTHON_IMAGE", "TAG", "NODE_TAG_SHA"):
            self.write()
            self.path.write_text(self.path.read_text() + f"{key}=python\n")
            with self.assertRaisesRegex(TokenCrateError, f"unknown key\\(s\\) {key} \\(a pin is <NAME>_TAG"):
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

    def test_a_tag_and_its_digest_come_as_a_pair(self) -> None:
        self.write(TOOL_DIGEST="0" * 64)
        with self.assertRaisesRegex(TokenCrateError, "TOOL_DIGEST has no TOOL_TAG beside it"):
            env.load_pins(self.path)
        self.write(TOOL_TAG="1.0")
        with self.assertRaisesRegex(TokenCrateError, "TOOL_TAG has no TOOL_DIGEST beside it"):
            env.load_pins(self.path)

    def test_a_malformed_line_names_its_number(self) -> None:
        self.write()
        self.path.write_text(self.path.read_text() + "not a pin\n")
        with self.assertRaisesRegex(TokenCrateError, r"pins\.env:18: expected KEY=VALUE"):
            env.load_pins(self.path)
        self.write()
        self.path.write_text(self.path.read_text().replace("PI_VERSION=", "export PI_VERSION=", 1))
        with self.assertRaisesRegex(TokenCrateError, r"pins\.env:5: expected KEY=VALUE"):
            env.load_pins(self.path)

    def test_the_key_scan_refuses_nothing_so_recovery_commands_run(self) -> None:
        # `subprocess_env` removes these keys whatever else the file holds;
        # a broken pins.env is reported by the launch commands, not at import.
        self.assertEqual(env.pin_keys(self.write())[:3], ("LLAMA_CPP_TAG", "LLAMA_CPP_DIGEST", "PI_VERSION"))
        self.path.write_text('invalid pin edit\nNODE_TAG="quoted"\n')
        self.assertEqual(env.pin_keys(self.path), ("NODE_TAG",))
        with self.assertRaisesRegex(TokenCrateError, "expected KEY=VALUE"):
            env.load_pins(self.path)


if __name__ == "__main__":
    unittest.main()
