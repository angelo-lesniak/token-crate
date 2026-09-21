"""Agent sets: manifest validation, the rendered Dockerfile stage, and the
files the entrypoint reads."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokencrate import PROJECT_ROOT, TokenCrateError, agentsets

BASE = "FROM node AS pi\nRUN true\n"
MANIFEST_TEMPLATE = """
schema = 1
description = "A tool set"
apt = ["shellcheck", "python3"]
build = ["install -m 0755 wrapper /usr/local/bin/wrapper", "tool --version"]
pi_packages = ["node_modules/pi-thing"]
note = "tool is installed."

[npm]
omit_peer = true

[[asset]]
url = "https://example.invalid/tool-1.0.tar.gz"
sha256 = "{sha256}"
into = "/opt/tool"
strip = 1

[[asset]]
url = "https://example.invalid/helper"
sha512 = "{sha512}"
into = "/usr/local/bin/helper"
mode = "0755"

[env]
TOOL_HOME = "/opt/tool"
PATH = "/opt/tool/bin"

[pi_lens.lsp.servers.tool]
command = "tool-ls"
"""


class AgentSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="tokencrate-agentsets-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "services" / "agents").mkdir(parents=True)
        (self.root / "services" / "agents" / "Dockerfile").write_text(BASE)

    def write_set(
        self, name: str, manifest: str, *, private: bool = False, files: dict[str, str] | None = None
    ) -> Path:
        directory = self.root / ("local" if private else "config") / "agent-sets" / name
        directory.mkdir(parents=True)
        (directory / "set.toml").write_text(manifest)
        for file_name, content in (files or {}).items():
            (directory / file_name).write_text(content)
        return directory

    def test_the_shipped_sets_validate_and_render(self) -> None:
        catalog = agentsets.catalog(PROJECT_ROOT)
        self.assertEqual(
            set(catalog), {path.parent.name for path in (PROJECT_ROOT / "config" / "agent-sets").glob("*/set.toml")}
        )
        self.assertEqual(catalog["pi-web"].ui, {"command": "tokencrate-ui-pi-web", "port": 8504, "identity": []})
        self.assertEqual(
            catalog["paseo"].ui,
            {
                "command": "tokencrate-ui-paseo",
                "port": 6767,
                "identity": [".paseo/daemon-keypair.json", ".paseo/server-id"],
            },
        )
        self.assertIsNone(catalog["coding"].ui)
        base = (PROJECT_ROOT / "services" / "agents" / "Dockerfile").read_text()
        rendered = agentsets.render_selection(base, list(catalog.values()))
        for entry in catalog.values():
            self.assertIn(
                f"COPY config/agent-sets/{entry.name} /opt/tokencrate/sets/{entry.name}\n", rendered.dockerfile
            )
        self.assertIn("/opt/tokencrate/sets/coding/node_modules/pi-lens\n", rendered.packages)
        self.assertIn("/opt/tokencrate/sets/debug/piex-dap\n", rendered.packages)
        self.assertEqual(json.loads(rendered.pi_lens)["lsp"]["servers"]["ols"]["command"], "ols")
        self.assertIs(json.loads(rendered.pi_lens)["tools"]["effective_config"]["enabled"], False)
        self.assertTrue(rendered.note.startswith(agentsets.NOTE_HEADER))

    def test_a_manifest_renders_every_step_kind_in_order(self) -> None:
        self.write_set(
            "tools",
            MANIFEST_TEMPLATE.format(sha256="ab" * 32, sha512="cd" * 64),
            files={"wrapper": "#!/bin/sh\n", "package.json": "{}", "package-lock.json": "{}"},
        )
        selected = agentsets.select(self.root, "tools")
        rendered = agentsets.render_selection(BASE, selected)
        text = rendered.dockerfile
        self.assertTrue(text.startswith(BASE.rstrip("\n")))
        stage = text[text.index("FROM pi AS agent") :]
        # Variables, packages, and assets come before the set directory copy,
        # so a note or lockfile edit does not repeat the downloads.
        expected_order = [
            "ENV TOOL_HOME=/opt/tool \\\n    PATH=${PATH}:/opt/tool/bin\n",
            "apt-get install -y --no-install-recommends python3 shellcheck",
            'curl -fsSL -o /tmp/asset.tar.gz "https://example.invalid/tool-1.0.tar.gz"',
            f'echo "{"ab" * 32}  /tmp/asset.tar.gz" | sha256sum -c -',
            "tar -xzf /tmp/asset.tar.gz -C /opt/tool --strip-components=1",
            f'echo "{"cd" * 64}  /tmp/asset" | sha512sum -c -',
            "install -D -m 0755 /tmp/asset /usr/local/bin/helper",
            "COPY config/agent-sets/tools /opt/tokencrate/sets/tools\n",
            "WORKDIR /opt/tokencrate/sets/tools\n",
            "npm ci --ignore-scripts --omit=peer",
            'RUN ["/bin/bash", "-e", "-o", "pipefail", "-c", '
            '"install -m 0755 wrapper /usr/local/bin/wrapper\\ntool --version"]\n',
            "WORKDIR /\n",
            f"COPY build/agents/pi/{rendered.tag}/pi-packages.txt /opt/tokencrate/pi-packages.txt\n",
        ]
        position = 0
        for snippet in expected_order:
            found = stage.find(snippet, position)
            self.assertNotEqual(found, -1, f"missing or out of order: {snippet!r}")
            position = found + len(snippet)
        self.assertEqual(rendered.packages, "/opt/tokencrate/sets/tools/node_modules/pi-thing\n")
        self.assertEqual(rendered.note, f"{agentsets.NOTE_HEADER}\ntool is installed.\n")
        self.assertEqual(json.loads(rendered.pi_lens), {"lsp": {"servers": {"tool": {"command": "tool-ls"}}}})
        # The tag follows the base Dockerfile, the selection, and the set
        # files, so a changed wrapper or base is a new image; the render is
        # a pure function of those inputs.
        self.assertEqual(rendered.tag, agentsets.render_selection(BASE, selected).tag)
        self.assertNotEqual(rendered.tag, agentsets.render_selection(BASE + "RUN false\n", selected).tag)
        (self.root / "config" / "agent-sets" / "tools" / "wrapper").write_text("#!/bin/sh\nexec true\n")
        self.assertNotEqual(rendered.tag, agentsets.render_selection(BASE, selected).tag)

    def test_build_script_preserves_comments_literals_and_failure_boundaries(self) -> None:
        cases = (
            (
                ["value=hello # an inline comment", 'printf "%s:%s\\n" "${#value}" "#literal"', "printf second"],
                0,
                "5:#literal\nsecond",
            ),
            (["false # stop here", "printf skipped"], 1, ""),
            (["false | true # pipefail applies", "printf skipped"], 1, ""),
        )
        for index, (lines, status, output) in enumerate(cases):
            with self.subTest(lines=lines):
                name = f"script-{index}"
                self.write_set(name, 'schema = 1\ndescription = "build script"\nbuild = ' + json.dumps(lines))
                rendered = agentsets.render_set(agentsets.load_set(self.root, name))
                command = next(line.removeprefix("RUN ") for line in rendered.splitlines() if line.startswith("RUN ["))
                result = subprocess.run(json.loads(command), capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stdout, output)

    def test_render_writes_the_build_files_and_an_empty_selection_is_plain_pi(self) -> None:
        tag = agentsets.render(self.root, self.root / "build", agentsets.select(self.root, ""))
        output = self.root / "build" / "agents" / "pi" / tag
        self.assertEqual(len(tag), 12)
        self.assertEqual((output / "pi-packages.txt").read_text(), "")
        self.assertEqual((output / "AGENTS.md").read_text(), agentsets.NOTE_HEADER + "\n")
        self.assertEqual((output / "pi-lens.json").read_text(), "{}\n")
        self.assertIn("FROM pi AS agent\n", (output / "Dockerfile").read_text())

    def test_failed_publication_preserves_the_existing_build_file(self) -> None:
        selected = agentsets.select(self.root, "")
        tag = agentsets.render(self.root, self.root / "build", selected)
        output = self.root / "build" / "agents" / "pi" / tag
        for name in ("Dockerfile", "pi-packages.txt", "AGENTS.md", "pi-lens.json"):
            path = output / name
            path.write_text("previous complete file\n")
            replace = agentsets.presets.os.replace

            def refuse(source, destination, path=path, replace=replace):
                if destination == path:
                    raise OSError("publication failed")
                replace(source, destination)

            with self.subTest(file=name), mock.patch.object(agentsets.presets.os, "replace", refuse):
                with self.assertRaisesRegex(OSError, "publication failed"):
                    agentsets.render(self.root, self.root / "build", selected)
                self.assertEqual(path.read_text(), "previous complete file\n")
                self.assertFalse(list(output.glob(f".{name}.*")))

    def test_selection_names_must_exist_once_and_local_sets_are_found(self) -> None:
        self.write_set("mine", 'schema = 1\ndescription = "private"\napt = ["shellcheck"]\n', private=True)
        [selected] = agentsets.select(self.root, "mine")
        self.assertEqual(selected.source, "local/agent-sets/mine")
        with self.assertRaisesRegex(TokenCrateError, "unknown agent set: other"):
            agentsets.select(self.root, "mine,other")
        with self.assertRaisesRegex(TokenCrateError, "named twice"):
            agentsets.select(self.root, "mine,mine")
        # Only the named manifests are read: a broken private set does not
        # block a selection that does not name it.
        self.write_set("broken", "not toml", private=True)
        self.assertEqual([entry.name for entry in agentsets.select(self.root, "mine")], ["mine"])
        with self.assertRaisesRegex(TokenCrateError, "cannot read the manifest"):
            agentsets.select(self.root, "broken")
        self.write_set("mine", 'schema = 1\ndescription = "shadow"\n')
        with self.assertRaisesRegex(TokenCrateError, "exists in both"):
            agentsets.select(self.root, "mine")

    def test_ui_command_names_are_reserved_only_for_ui_sets(self) -> None:
        head = 'schema = 1\ndescription = "private tools"\n'
        for name in ("stop", "logs"):
            with self.subTest(name=name):
                directory = self.write_set(name, head, private=True)
                self.assertIsNone(agentsets.load_set(self.root, name).ui)
                (directory / "set.toml").write_text(head + '[ui]\ncommand = "demo-ui"\nport = 8080\n')
                with self.assertRaisesRegex(TokenCrateError, f"UI set name '{name}' is reserved for a ui command"):
                    agentsets.load_set(self.root, name)

    def test_manifests_are_validated(self) -> None:
        head = 'schema = 1\ndescription = "x"\n'
        digest = "a" * 64
        tgz = f'[[asset]]\nurl = "https://x/y.tgz"\nsha256 = "{digest}"\ninto = "/opt/y"\n'
        zipped = f'[[asset]]\nurl = "https://x/y.zip"\nsha256 = "{digest}"\ninto = "/opt/y"\n'
        cases = {
            'schema = 2\ndescription = "x"\n': "schema must be 1",
            "schema = 1\n": "description must be one non-empty line",
            'schema = 1\ndescription = "x\\nRUN evil"\n': "description must be one non-empty line",
            head + "extra = 1\n": "unknown key",
            head + 'apt = ["Bad Name"]\n': "not a Debian package name",
            head + f'[[asset]]\nurl = "http://x/y.tgz"\nsha256 = "{digest}"\ninto = "/opt/y"\n': "https URL",
            head + f'[[asset]]\nurl = "https://x/y;id"\nsha256 = "{digest}"\ninto = "/opt/y"\n': "plain characters",
            head + '[[asset]]\nurl = "https://x/y.tgz"\ninto = "/opt/y"\n': "exactly one of sha256",
            head + f'[[asset]]\nurl = "https://x/y.tgz"\nsha256 = "{digest}"\ninto = "opt/y"\n': "absolute path",
            head + zipped + "strip = 1\n": "tar.gz assets only",
            head + tgz + 'mode = "0755"\n': "plain files only",
            head + 'pi_packages = ["../escape"]\n': "relative path below the set directory",
            head + '[env]\npath = "/x"\n': "not a variable name",
            head + '[env]\nX = "a b"\n': "may not contain whitespace",
            # An empty value renders `ENV PATH=${PATH}:`, and that trailing
            # entry is the working directory the entrypoint changed into.
            head + '[env]\nPATH = ""\n': "may not contain whitespace",
            head + "[npm]\nomit_peer = true\n": "npm needs package.json",
            head + 'build = ["a\\nb"]\n': "single non-empty shell lines",
            head + 'build = ["# a comment"]\n': "not comments",
            head + '[ui]\ncommand = "x"\n': "command and port, and at most identity",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = "a"\n': "list of file paths",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = ["../a"]\n': "directly below",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = ["/a"]\n': "directly below",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = ["id"]\n': "directly below",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = [".paseo/keys/id"]\n': "directly below",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = [".paseo/.."]\n': "directly below",
            head + '[ui]\ncommand = "x"\nport = 8080\nidentity = [".other/id"]\n': "directly below",
            head + '[ui]\ncommand = "/usr/bin/x"\nport = 8080\n': "program name without a path",
            head + '[ui]\ncommand = "x"\nport = 80\n': "between 1024 and 65535",
            head + '[ui]\ncommand = "x"\nport = true\n': "between 1024 and 65535",
        }
        for index, (manifest, message) in enumerate(cases.items()):
            directory = self.write_set(f"case{index}", manifest)
            with self.subTest(message=message):
                with self.assertRaisesRegex(TokenCrateError, message):
                    agentsets.read_manifest(directory, f"config/agent-sets/case{index}")

    def test_asset_credentials_are_refused_without_echoing_them(self) -> None:
        for url in ("https://user:secret@host/file", "https://user:secret@host/file?query"):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(TokenCrateError, "must not contain credentials") as caught,
            ):
                agentsets.read_asset({"url": url}, "fixture")
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
