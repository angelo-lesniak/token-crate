"""Exercise the launchers' real startup writers without starting UI daemons."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import SOURCE_ROOT


@unittest.skipUnless(shutil.which("node"), "node is required to run the UI startup writers")
class UiLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="tokencrate-ui-writers-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()

    def seed(self, ui: str) -> subprocess.CompletedProcess:
        source = (SOURCE_ROOT / "config/agent-sets" / ui / f"tokencrate-ui-{ui}").read_text()
        # Stop before any daemon, socket operation, or network request. Everything
        # before this boundary is the production startup writer, executed by bash.
        boundary = 'rm -f "$SOCKET"' if ui == "pi-web" else 'echo "TokenCrate UI: Paseo listens'
        self.assertIn(boundary, source)
        return subprocess.run(
            ["bash", "-c", source.split(boundary, 1)[0]],
            cwd=self.project,
            env={**os.environ, "HOME": str(self.home), "TOKENCRATE_UI_PORT": "8504", "TOKENCRATE_PRESET": "fixture"},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_seeds_are_valid_and_restarts_keep_existing_state(self) -> None:
        for ui in ("pi-web", "paseo"):
            result = self.seed(ui)
            self.assertEqual(result.returncode, 0, result.stderr)
        web = self.home / ".pi-web"
        projects = json.loads((web / "projects.json").read_text())
        self.assertEqual(projects["projects"][0]["path"], str(self.project))
        dismissals = json.loads((web / "pi-package-dismissals.json").read_text())
        self.assertEqual(dismissals["dismissals"][0]["profileDir"], str(self.home / ".pi/agent"))
        paseo = self.home / ".paseo"
        config = json.loads((paseo / "config.json").read_text())
        self.assertEqual(config["agents"]["providers"]["pi"]["additionalModels"][0]["id"], "tokencrate/fixture")
        config["daemon"]["agentProfiles"][0]["name"] = "Retained choice"
        (paseo / "config.json").write_text(json.dumps(config))
        (paseo / "paseo.pid").write_text("1")
        before = {file: file.read_bytes() for file in self.home.rglob("*.json")}
        for ui in ("pi-web", "paseo"):
            result = self.seed(ui)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {file: file.read_bytes() for file in self.home.rglob("*.json")})
        self.assertFalse((paseo / "paseo.pid").exists())
        self.assertFalse(list(self.home.rglob("*.tmp")))

    def test_pi_web_publishes_over_a_hardlink_without_modifying_its_other_name(self) -> None:
        directory = self.home / ".pi-web"
        directory.mkdir()
        outside = self.root / "outside.json"
        outside.write_text('{"projects":[]}')
        os.link(outside, directory / "projects.json")
        result = self.seed("pi-web")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outside.read_text(), '{"projects":[]}')
        self.assertEqual(len(json.loads((directory / "projects.json").read_text())["projects"]), 1)

    def test_seed_file_links_are_refused_even_when_the_target_is_missing(self) -> None:
        for ui, names in (("pi-web", ("projects.json", "pi-package-dismissals.json")), ("paseo", ("config.json",))):
            directory = self.home / f".{ui}"
            directory.mkdir()
            for name in names:
                for exists in (False, True):
                    with self.subTest(ui=ui, name=name, exists=exists):
                        target = self.root / "outside.json"
                        if exists:
                            target.write_text('{"untouched":true}')
                        link = directory / name
                        link.symlink_to(target)
                        result = self.seed(ui)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(str(link), result.stderr)
                        self.assertEqual(
                            target.read_text() if exists else target.exists(), '{"untouched":true}' if exists else False
                        )
                        self.assertEqual(list(directory.iterdir()), [link])
                        link.unlink()
                        target.unlink(missing_ok=True)
