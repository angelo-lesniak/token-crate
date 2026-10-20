"""Exercise the launchers' real startup writers without starting UI daemons."""

from __future__ import annotations

import json
import os
import re
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
        # Stop before the daemon's address is read from the container's
        # interfaces, and so before any daemon, socket operation, or network
        # request. Everything before this boundary is the production startup
        # writer, executed by bash.
        boundary = "address=$(ui_address)"
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

    def test_the_daemons_bind_the_ui_network_address_only(self) -> None:
        # Both daemons listen on the one address the discovery prints, never
        # on every interface: with --egress or --cloud the container has a
        # second interface, on the default network, which the forwarder's
        # Host check does not cover. The discovery is written in both
        # launchers (each set installs its own), so the two copies must agree.
        sources = {
            ui: (SOURCE_ROOT / "config/agent-sets" / ui / f"tokencrate-ui-{ui}").read_text()
            for ui in ("pi-web", "paseo")
        }
        functions = []
        for ui, source in sources.items():
            match = re.search(r"^ui_address\(\) \{\n.*?^\}\n", source, re.DOTALL | re.MULTILINE)
            self.assertIsNotNone(match, f"{ui} must define ui_address")
            functions.append(match.group(0))
            # Loopback appears only as the discovery's answer for a container
            # with no network at all; no bind or health check names it.
            self.assertNotIn("0.0.0.0", source, ui)
            self.assertNotIn("127.0.0.1", source.replace(match.group(0), ""), ui)
            self.assertIn('console.log("127.0.0.1")', match.group(0), ui)
            self.assertIn("/proc/net/route", match.group(0))
            self.assertLess(source.index("address=$(ui_address)"), source.index("listens on $address:$PORT"), ui)
        self.assertEqual(functions[0], functions[1], "the two launchers must share one discovery")
        self.assertIn("export PI_WEB_HOST=$address\n", sources["pi-web"])
        self.assertIn("export PASEO_LISTEN=$address:$PORT\n", sources["paseo"])
        self.assertIn('HEALTH="http://$address:$PORT/api/health"', sources["paseo"])

    def test_paseo_carries_its_daemon_identity_through_the_shared_state_mount(self) -> None:
        # The wrapper mounts one directory per UI set at this path
        # (uis.UI_STATE_MOUNT); the launcher copies the identity files a
        # daemon created out to it, and into a home that lacks them before
        # its daemon starts, so every project's daemon presents the same one.
        source = (SOURCE_ROOT / "config/agent-sets/paseo/tokencrate-ui-paseo").read_text()
        self.assertIn("readonly STATE=/run/tokencrate/ui-state\n", source)
        self.assertIn("readonly IDENTITY=(daemon-keypair.json server-id)\n", source)
        copy_in, start, copy_out = (
            source.index('copy_identity "$STATE" "$PASEO_HOME"'),
            source.index("paseo daemon start --foreground"),
            source.index('copy_identity "$PASEO_HOME" "$STATE"'),
        )
        self.assertLess(copy_in, start)
        self.assertLess(source.index("exit 1\nfi\n", start), copy_out, "the copy out follows the health check")
        function = re.search(r"^readonly IDENTITY=.*?^copy_identity\(\) \{.*?^\}\n", source, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(function)
        store, home = self.root / "state", self.home / ".paseo"
        store.mkdir()
        home.mkdir()
        (home / "daemon-keypair.json").write_text("first")
        (home / "daemon-keypair.json").chmod(0o600)
        (home / "server-id").write_text("srv_first")
        (store / "server-id").write_text("srv_store")
        script = (
            f'{function.group(0)}\ncopy_identity "{home}" "{store}"\ncopy_identity "{store}" "{home}"\n'
            # A start outside `ui` has no state mount; the copy is a no-op then.
            f'copy_identity "{home}" "{store}/absent"\ncopy_identity "{store}/absent" "{home}"\n'
        )
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Each side keeps what it had and gains only what it lacked.
        self.assertEqual((store / "daemon-keypair.json").read_text(), "first")
        self.assertEqual(oct((store / "daemon-keypair.json").stat().st_mode & 0o777), "0o600")
        self.assertEqual((store / "server-id").read_text(), "srv_store")
        self.assertEqual((home / "server-id").read_text(), "srv_first")
        self.assertEqual(sorted(p.name for p in home.iterdir()), ["daemon-keypair.json", "server-id"])

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
