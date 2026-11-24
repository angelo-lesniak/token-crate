"""Exercise the pi-web launcher's real startup steps without starting its server."""

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

LAUNCHER = SOURCE_ROOT / "config/agent-sets/pi-web/tokencrate-ui-pi-web"
PACKAGE = "opt/tokencrate/sets/pi-web/node_modules/@agegr/pi-web"
NEXT_DIR = "run/tokencrate/pi-web-next"
STATE = "pi-web-session-state.json"
PUBLISHED = {
    "previewModeId": "0" * 32,
    "previewModeSigningKey": "1" * 64,
    "previewModeEncryptionKey": "2" * 64,
}


@unittest.skipUnless(shutil.which("node"), "node is required to run the launcher's startup steps")
class UiLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="tokencrate-ui-launcher-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.prefix = self.root / "prefix"
        self.home = self.root / "home"
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi-web").mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        # The build output as the image ships it: a few files and
        # directories, and the two files that hold the published secrets.
        image = self.prefix / PACKAGE / ".next-image"
        (image / "server/app").mkdir(parents=True)
        (image / "static").mkdir()
        (image / "BUILD_ID").write_text("build")
        (image / ".hidden").write_text("hidden")
        (image / "server/app/page.js").write_text("// page")
        (image / "prerender-manifest.json").write_text(json.dumps({"version": 4, "preview": PUBLISHED}))
        (image / "server/preview-props.json").write_text(json.dumps(PUBLISHED))

    def start(self, then: str = "") -> subprocess.CompletedProcess:
        """Everything the launcher runs before it reads the container's
        interfaces, and so before the server or any network request, executed
        by bash with the container paths below a temporary root; `then` runs
        after it in the same shell."""
        source = LAUNCHER.read_text()
        boundary = "address=$(ui_address)"
        self.assertIn(boundary, source)
        return subprocess.run(
            ["bash", "-c", source.split(boundary, 1)[0] + then],
            cwd=self.project,
            env={
                **os.environ,
                "HOME": str(self.home),
                "TOKENCRATE_UI_PORT": "8504",
                "TOKENCRATE_PREFIX": str(self.prefix),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def preview(self) -> tuple[dict, dict]:
        live = self.prefix / NEXT_DIR
        for name in ("prerender-manifest.json", "server/preview-props.json"):
            self.assertFalse((live / name).is_symlink(), name)
        manifest = json.loads((live / "prerender-manifest.json").read_text())
        return manifest, json.loads((live / "server/preview-props.json").read_text())

    def test_the_build_output_is_linked_with_fresh_preview_secrets(self) -> None:
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        live, image = self.prefix / NEXT_DIR, self.prefix / PACKAGE / ".next-image"
        for name in ("BUILD_ID", ".hidden", "static", "server/app"):
            self.assertEqual((live / name).resolve(), (image / name).resolve(), name)
        self.assertTrue((live / "server").is_dir() and not (live / "server").is_symlink())
        manifest, props = self.preview()
        self.assertEqual(manifest["version"], 4)
        self.assertEqual(manifest["preview"], props)
        self.assertEqual(props.keys(), PUBLISHED.keys())
        for key, value in props.items():
            self.assertNotEqual(value, PUBLISHED[key], key)
            self.assertEqual(len(value), len(PUBLISHED[key]), key)
        # The image's files are left as they are, and every start draws new secrets.
        self.assertEqual(json.loads((image / "server/preview-props.json").read_text()), PUBLISHED)
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.preview()[1], props)

    def test_the_sidebar_state_is_restored_and_saved(self) -> None:
        retained, live = self.home / ".pi-web" / STATE, self.home / ".pi/agent" / STATE
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(live.exists(), "a first start has no state to restore")
        retained.write_text('{"revision":1}')
        result = self.start(
            f'test "$(cat {live})" = \'{{"revision":1}}\'\n' + f"echo '{{\"revision\":2}}' > {live}\nsave_state\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained.read_text(), '{"revision":2}\n')
        self.assertEqual(sorted(path.name for path in retained.parent.iterdir()), [STATE])

    def test_a_save_follows_no_planted_link_or_directory(self) -> None:
        retained, live = self.home / ".pi-web" / STATE, self.home / ".pi/agent" / STATE
        outside = self.root / "outside.json"
        planted = retained.with_name(f"{STATE}.tmp")
        save = f"echo '{{\"revision\":2}}' > {live}\n"
        # A link planted at the temporary name after the start is removed,
        # not written through, and the save goes ahead.
        outside.write_text("outside")
        result = self.start(f"ln -s {outside} {planted}\n{save}save_state\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((outside.read_text(), retained.read_text()), ("outside", '{"revision":2}\n'))
        self.assertFalse(planted.exists() or planted.is_symlink())
        # A directory at either name fails the save instead of taking the file.
        for directory in (planted, retained):
            with self.subTest(directory=directory.name):
                retained.unlink(missing_ok=True)
                result = self.start(f"mkdir {directory}\n{save}save_state\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"could not save {retained}", result.stderr)
                self.assertEqual(list(directory.iterdir()), [])
                directory.rmdir()
        # A live file that is a link is not copied.
        outside.write_text('{"revision":9}')
        retained.write_text('{"revision":1}')
        result = self.start(f"rm -f {live}; ln -s {outside} {live}\nsave_state\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained.read_text(), '{"revision":1}')

    def test_a_state_pi_web_set_aside_is_retained(self) -> None:
        # pi-web renames a file it cannot parse and writes a fresh one; the
        # saved copy is kept under the set-aside name before it is replaced.
        retained, live = self.home / ".pi-web" / STATE, self.home / ".pi/agent" / STATE
        retained.write_text("not json")
        result = self.start(f"mv {live} {live}.corrupt-1\necho '{{\"revision\":1}}' > {live}\nsave_state\nsave_state\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained.with_name(f"{STATE}.corrupt-1").read_text(), "not json")
        self.assertEqual(retained.read_text(), '{"revision":1}\n')

    def test_state_links_are_refused(self) -> None:
        target = self.root / "outside.json"
        for name in (STATE, f"{STATE}.tmp"):
            for exists in (False, True):
                with self.subTest(name=name, exists=exists):
                    if exists:
                        target.write_text('{"untouched":true}')
                    link = self.home / ".pi-web" / name
                    link.symlink_to(target)
                    result = self.start()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(str(link), result.stderr)
                    self.assertEqual(
                        target.read_text() if exists else target.exists(), '{"untouched":true}' if exists else False
                    )
                    self.assertFalse((self.home / ".pi/agent" / STATE).exists())
                    link.unlink()
                    target.unlink(missing_ok=True)

    def test_the_server_binds_the_ui_network_address_only(self) -> None:
        # The server listens on the one address the discovery prints, never
        # on every interface: with --egress or --cloud the container has a
        # second interface, on the default network, which the forwarder's
        # Host check does not cover.
        source = LAUNCHER.read_text()
        match = re.search(r"^ui_address\(\) \{\n.*?^\}\n", source, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(match, "the launcher must define ui_address")
        # Loopback appears only as the discovery's answer for a container
        # with no network at all; no bind or health check names it.
        self.assertNotIn("0.0.0.0", source)
        self.assertNotIn("127.0.0.1", source.replace(match.group(0), ""))
        self.assertIn('console.log("127.0.0.1")', match.group(0))
        self.assertIn("/proc/net/route", match.group(0))
        self.assertLess(source.index("address=$(ui_address)"), source.index("listens on $address:$PORT"))
        self.assertIn('pi-web --hostname "$address" --port "$PORT" --no-open &\n', source)
