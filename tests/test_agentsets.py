"""Agent sets: manifest validation, the rendered Dockerfile stage, and the
files the entrypoint reads."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path

from tokencrate import PROJECT_ROOT, TokenCrateError, agentsets

BASE = "FROM node AS pi\nRUN true\n"
MANIFEST_TEMPLATE = """
schema = 1
description = "A tool set"
check = []
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
        self.assertEqual(
            catalog["pi-web"].ui,
            {"command": "tokencrate-ui-pi-web", "port": 8504, "state": ".pi-web", "identity": [], "host_port": 4224},
        )
        self.assertEqual(
            catalog["paseo"].ui,
            {
                "command": "tokencrate-ui-paseo",
                "port": 6767,
                "state": ".paseo",
                "identity": [".paseo/daemon-keypair.json", ".paseo/server-id"],
                "host_port": 4250,
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
        # The tag is a digest of the rendered files, so a changed base, set,
        # or renderer is a new image, and one tag is one content. A set file
        # that no rendered file carries (the wrapper is copied by the build)
        # leaves the tag alone; its content reaches the image through the
        # build context.
        self.assertEqual(rendered.tag, agentsets.render_selection(BASE, selected).tag)
        self.assertNotEqual(rendered.tag, agentsets.render_selection(BASE + "RUN false\n", selected).tag)
        renamed = dataclasses.replace(selected[0], note="tool is installed elsewhere.")
        self.assertNotEqual(rendered.tag, agentsets.render_selection(BASE, [renamed]).tag)

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
                self.write_set(
                    name, 'schema = 1\ndescription = "build script"\ncheck = []\nbuild = ' + json.dumps(lines)
                )
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

    def test_a_rendered_selection_is_complete_or_absent_and_parallel_renders_agree(self) -> None:
        # The directory is renamed into place whole, so a reader never sees
        # a partial render, and a second render of the same selection finds
        # it done. Files the staging left behind are removed.
        selected = agentsets.select(self.root, "")
        build = self.root / "build"
        tags = set()
        errors: list[BaseException] = []

        def render() -> None:
            try:
                tags.add(agentsets.render(self.root, build, selected))
            except BaseException as error:
                errors.append(error)

        workers = [threading.Thread(target=render) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(errors, [])
        (tag,) = tags
        output = build / "agents" / "pi" / tag
        self.assertEqual(
            sorted(path.name for path in output.iterdir()),
            ["AGENTS.md", "Dockerfile", "checks", "pi-lens.json", "pi-packages.txt"],
        )
        self.assertEqual(output.stat().st_mode & 0o777, 0o755)
        self.assertEqual([path.name for path in output.parent.iterdir()], [tag])
        # A directory that exists is complete: nothing is rewritten.
        (output / "Dockerfile").write_text("kept\n")
        self.assertEqual(agentsets.render(self.root, build, selected), tag)
        self.assertEqual((output / "Dockerfile").read_text(), "kept\n")

    def test_every_shipped_set_declares_its_check_lines(self) -> None:
        # `check` is what smoke --agent runs for the set; a shipped set says
        # what it probes, or that nothing of it can be probed.
        for manifest in sorted((PROJECT_ROOT / "config" / "agent-sets").glob(f"*/{agentsets.MANIFEST}")):
            self.assertIn("check", tomllib.loads(manifest.read_text(encoding="utf-8")), manifest)

    def test_selection_names_must_exist_once_and_local_sets_are_found(self) -> None:
        self.write_set("mine", 'schema = 1\ndescription = "private"\ncheck = []\napt = ["shellcheck"]\n', private=True)
        [selected] = agentsets.select(self.root, "mine")
        self.assertEqual(selected.source, "local/agent-sets/mine")
        with self.assertRaisesRegex(TokenCrateError, "unknown agent set: other"):
            agentsets.select(self.root, "mine,other")
        # A hand-edited list: spaces, empty entries, and repeats change nothing.
        self.assertEqual([entry.name for entry in agentsets.select(self.root, " mine,,mine ,")], ["mine"])
        with self.assertRaisesRegex(TokenCrateError, "unsafe agent set name: '../x'"):
            agentsets.select(self.root, "mine,../x")
        # Only the named manifests are read: a broken private set does not
        # block a selection that does not name it.
        self.write_set("broken", "not toml", private=True)
        self.assertEqual([entry.name for entry in agentsets.select(self.root, "mine")], ["mine"])
        with self.assertRaisesRegex(TokenCrateError, "cannot read the manifest"):
            agentsets.select(self.root, "broken")
        self.write_set("mine", 'schema = 1\ndescription = "shadow"\ncheck = []\n')
        with self.assertRaisesRegex(TokenCrateError, "exists in both"):
            agentsets.select(self.root, "mine")

    def test_ui_command_names_are_reserved_only_for_ui_sets(self) -> None:
        head = 'schema = 1\ndescription = "private tools"\ncheck = []\n'
        for name in ("stop", "logs"):
            with self.subTest(name=name):
                directory = self.write_set(name, head, private=True)
                self.assertIsNone(agentsets.load_set(self.root, name).ui)
                (directory / "set.toml").write_text(head + '[ui]\ncommand = "demo-ui"\nport = 8080\nstate = ".demo"\n')
                with self.assertRaisesRegex(TokenCrateError, f"UI set name '{name}' is reserved for a ui command"):
                    agentsets.load_set(self.root, name)

    def test_a_ui_set_name_fits_its_container_names(self) -> None:
        head = 'schema = 1\ndescription = "private tools"\ncheck = []\n'
        ui = '[ui]\ncommand = "demo-ui"\nport = 8080\nstate = ".demo"\n'
        for name in ("custom.UI", "Custom", "forward-x", "under_score", "a" * 42):
            with self.subTest(name=name):
                directory = self.write_set(name, head, private=True)
                self.assertIsNone(agentsets.load_set(self.root, name).ui)
                (directory / "set.toml").write_text(head + ui)
                with self.assertRaisesRegex(TokenCrateError, "lowercase letters, digits, and hyphens"):
                    agentsets.load_set(self.root, name)
        self.write_set("a" * 41, head + ui, private=True)
        self.assertIsNotNone(agentsets.load_set(self.root, "a" * 41).ui)

    def test_manifests_are_validated(self) -> None:
        head = 'schema = 1\ndescription = "x"\ncheck = []\n'
        ui = '[ui]\ncommand = "x"\nport = 8080\nstate = ".paseo"\n'
        digest = "a" * 64
        tgz = f'[[asset]]\nurl = "https://x/y.tgz"\nsha256 = "{digest}"\ninto = "/opt/y"\n'
        zipped = f'[[asset]]\nurl = "https://x/y.zip"\nsha256 = "{digest}"\ninto = "/opt/y"\n'
        cases = {
            'schema = 2\ndescription = "x"\ncheck = []\n': "schema must be 1",
            "schema = 1\n": "description must be one non-empty line",
            'schema = 1\ndescription = "x\\nRUN evil"\ncheck = []\n': "description must be one non-empty line",
            head + "extra = 1\n": "unknown key",
            head + 'apt = ["Bad Name"]\n': "not a Debian package name",
            head + f'[[asset]]\nurl = "http://x/y.tgz"\nsha256 = "{digest}"\ninto = "/opt/y"\n': "https URL",
            head + f'[[asset]]\nurl = "https://x/y;id"\nsha256 = "{digest}"\ninto = "/opt/y"\n': "plain characters",
            head + '[[asset]]\nurl = "https://x/y.tgz"\ninto = "/opt/y"\n': "exactly one of sha256",
            head + f'[[asset]]\nurl = "https://x/y.tgz"\nsha256 = "{digest}"\ninto = "opt/y"\n': "absolute path",
            head + zipped + "strip = 1\n": "tar.gz assets only",
            head + tgz + 'mode = "0755"\n': "plain files only",
            head + 'pi_packages = ["../escape"]\n': "pi_packages entry must be a relative path",
            head + '[env]\npath = "/x"\n': "not a variable name",
            head + '[env]\nX = "a b"\n': "may not contain whitespace",
            # An empty value renders `ENV PATH=${PATH}:`, and that trailing
            # entry is the working directory the entrypoint changed into.
            head + '[env]\nPATH = ""\n': "may not contain whitespace",
            head + "[npm]\nomit_peer = true\n": "npm needs package.json",
            head + 'build = ["a\\nb"]\n': "single non-empty shell lines",
            head + 'build = ["# a comment"]\n': "not comments",
            'schema = 1\ndescription = "x"\ncheck = ["# only a comment"]\n': "check lines must be single non-empty",
            head + '[ui]\ncommand = "x"\n': "command, port, and state, and at most identity and host_port",
            head + '[ui]\ncommand = "x"\nport = 8080\n': "command, port, and state",
            head + ui + 'identity = "a"\n': "list of file paths",
            head + ui + 'identity = ["../a"]\n': "directly below the state directory .paseo",
            head + ui + 'identity = ["/a"]\n': "directly below",
            head + ui + 'identity = ["id"]\n': "directly below",
            head + ui + 'identity = [".paseo/keys/id"]\n': "directly below",
            head + ui + 'identity = [".paseo/.."]\n': "directly below",
            head + ui + 'identity = [".other/id"]\n': "directly below",
            head + '[ui]\ncommand = "/usr/bin/x"\nport = 8080\nstate = ".x"\n': "program name without a path",
            head
            + '[ui]\ncommand = "x"\nport = 80\nstate = ".x"\n': "ui port must be an integer between 1024 and 65535",
            head + '[ui]\ncommand = "x"\nport = true\nstate = ".x"\n': "between 1024 and 65535",
            head + ui + "host_port = 80\n": "ui host_port must be an integer between 1024 and 65535",
            head + '[ui]\ncommand = "x"\nport = 8080\nstate = ".pi"\n': "not the agent's own",
            head + '[ui]\ncommand = "x"\nport = 8080\nstate = "a/b"\n': "one directory below the agent home",
            head + '[ui]\ncommand = "x"\nport = 8080\nstate = ""\n': "one directory below the agent home",
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
