"""The real-container harness's cleanup ownership, without starting containers."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests import integration


class IntegrationCleanupTests(unittest.TestCase):
    def test_only_an_attempted_up_registers_stack_cleanup(self) -> None:
        for failure in (("skills", "fetch"), ("skills", "status"), ("up",)):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                for kind in ("model-sets", "presets"):
                    (root / "config" / kind).mkdir(parents=True)
                (root / ".env").touch()
                calls = []

                class Probe(integration.IntegrationTests):
                    reports = []

                def wrapper(*args, calls=calls, root=root, failure=failure, probe=Probe, **kwargs):
                    calls.append(args)
                    if args == ("down",):
                        self.assertTrue(probe.scratch.is_dir(), "down must precede file cleanup")
                        self.assertTrue((root / "config/presets/ci-small.toml").is_file())
                    if args[: len(failure)] == failure:
                        raise RuntimeError("injected setup failure")

                with (
                    mock.patch.object(integration, "ROOT", root),
                    mock.patch.object(integration, "tokencrate", wrapper),
                    mock.patch.object(
                        integration.env, "load", return_value=types.SimpleNamespace(agents_dir=root / "agents")
                    ),
                    mock.patch.object(integration.engines, "detect", return_value=types.SimpleNamespace(name="mock")),
                    mock.patch.dict(os.environ),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    try:
                        with self.assertRaisesRegex(RuntimeError, "injected setup failure"):
                            Probe.setUpClass()
                    finally:
                        Probe.doClassCleanups()
                    self.assertEqual(Probe.tearDown_exceptions, [])
                self.assertEqual(("down",) in calls, failure == ("up",))
                self.assertFalse(Probe.scratch.exists())
                self.assertFalse(list((root / "config").rglob("*.toml")))

    def test_project_check_detects_rewrites_as_well_as_added_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            check = integration.IntegrationTests("test_pi_runs_each_selection")
            check.project = Path(raw)
            readme = check.project / "README.md"
            readme.write_bytes(integration.README_TEXT.encode("utf-8"))
            check.assert_project_untouched()
            readme.write_text("changed content")
            with self.assertRaises(AssertionError):
                check.assert_project_untouched()
            readme.write_bytes(integration.README_TEXT.encode("utf-8"))
            (check.project / "added").touch()
            with self.assertRaises(AssertionError):
                check.assert_project_untouched()
