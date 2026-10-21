"""Project-directory rules, the keys file, the one pre-flight and its
launches, session readiness, and the per-project agent home."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import pty
import re
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.support import SOURCE_ROOT, Scratch
from tokencrate import TokenCrateError, agenthome, agents, env, presets, runtime, session


class ProjectDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(**overrides))

    def test_refuses_root_home_missing_and_outside_directories(self) -> None:
        settings = self.settings()
        with self.assertRaisesRegex(TokenCrateError, "refusing to mount the root filesystem"):
            session.resolve_project_directory(settings, "/")
        with self.assertRaisesRegex(TokenCrateError, "whole home directory"):
            session.resolve_project_directory(settings, str(self.scratch.home))
        with self.assertRaisesRegex(TokenCrateError, "does not exist"):
            session.resolve_project_directory(settings, str(self.scratch.home / "missing"))
        with self.assertRaisesRegex(TokenCrateError, "outside your home directory and LLM_PROJECT_ROOTS"):
            session.resolve_project_directory(settings, "/usr")
        self.assertEqual(
            session.resolve_project_directory(settings, str(self.scratch.project)), self.scratch.project.resolve()
        )

    def test_the_control_plane_is_refused_as_a_project_in_both_directions(self) -> None:
        settings = self.settings()
        cases = [
            ("the TokenCrate checkout", settings.root),
            ("the TokenCrate checkout", settings.root / "config"),
            ("the models directory", settings.models_dir),
            ("the models directory", settings.models_dir / "unsloth"),
            ("the agents directory", settings.agents_dir),
            ("the skills directory", settings.skills_dir),
            ("the private skills directory", settings.local_skills_dir),
        ]
        for label, path in cases:
            path.mkdir(parents=True, exist_ok=True)
            with self.assertRaisesRegex(TokenCrateError, f"contains or lies inside {label}"):
                session.resolve_project_directory(settings, str(path))
        # A parent of the checkout contains it (and, here, every storage directory).
        with self.assertRaisesRegex(TokenCrateError, "contains or lies inside the TokenCrate checkout"):
            session.resolve_project_directory(settings, str(self.scratch.tmp))
        # A storage directory that lies below the home is still refused.
        inside_home = self.settings(LLM_SKILLS_DIR=str(self.scratch.home / "skills"))
        (self.scratch.home / "skills" / "set").mkdir(parents=True)
        with self.assertRaisesRegex(TokenCrateError, "contains or lies inside the skills directory"):
            session.resolve_project_directory(inside_home, str(self.scratch.home / "skills" / "set"))

    def test_a_project_that_contains_the_cloud_keys_file_is_refused(self) -> None:
        # Without --cloud the keys would still be mounted, as project files.
        secrets = self.scratch.home / "work" / "secrets"
        (secrets / "sibling").mkdir(parents=True)
        (secrets / "keys.env").write_text("")
        settings = self.settings(LLM_CLOUD_KEYS_FILE=str(secrets / "keys.env"))
        for project in (secrets, secrets.parent):
            with self.assertRaisesRegex(TokenCrateError, "contains or lies inside the cloud keys file: .*keys.env"):
                session.resolve_project_directory(settings, str(project))
        # A directory next to the file does not carry it.
        self.assertEqual(session.resolve_project_directory(settings, str(secrets / "sibling")), secrets / "sibling")

    def test_unsafe_characters_are_refused(self) -> None:
        odd = self.scratch.home / "with space"
        odd.mkdir()
        with self.assertRaisesRegex(TokenCrateError, "cannot express safely"):
            session.resolve_project_directory(self.settings(), str(odd))
        # A path the filesystem holds as bytes that are not UTF-8 reaches the
        # wrapper surrogate-escaped; the home digest could not encode it.
        undecodable = self.scratch.home / b"caf\xe9".decode("utf-8", "surrogateescape")
        undecodable.mkdir()
        with self.assertRaisesRegex(TokenCrateError, r"not valid UTF-8: .*caf\\udce9"):
            session.resolve_project_directory(self.settings(), str(undecodable))

    def test_a_project_root_is_not_a_project(self) -> None:
        # A root is where projects live; one nested below another root (here
        # below the home) is still refused as a project.
        work = self.scratch.home / "work"
        (work / "app").mkdir(parents=True)
        settings = self.settings(LLM_PROJECT_ROOTS=str(work))
        with self.assertRaisesRegex(TokenCrateError, "refusing to mount an LLM_PROJECT_ROOTS entry as a project"):
            session.resolve_project_directory(settings, str(work))
        self.assertEqual(session.resolve_project_directory(settings, str(work / "app")), (work / "app").resolve())

    def test_git_metadata_must_fit_inside_the_project_mount(self) -> None:
        external = self.scratch.home / "other-repository" / ".git"
        external.mkdir(parents=True)
        (external / "HEAD").write_text("ref: refs/heads/main\n")
        marker = self.scratch.project / ".git"
        # A `.git` file is a linked worktree or a submodule; it is refused
        # without being parsed, so its bytes do not matter.
        for content in (f"gitdir: {external}\n".encode(), b"gitdir: \xff\xfe"):
            marker.write_bytes(content)
            with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
                session.resolve_project_directory(self.settings(), str(self.scratch.project))
        marker.unlink()
        # A repository above the project owns the project's metadata; the
        # message names what was found.
        above = self.scratch.home / "src" / ".git"
        above.mkdir()
        with self.assertRaisesRegex(TokenCrateError, f"Git metadata lies outside the project mount \\({above}\\)"):
            session.resolve_project_directory(self.settings(), str(self.scratch.project))
        above.rmdir()
        marker.mkdir()
        (marker / "HEAD").write_text("ref: refs/heads/main\n")
        self.assertEqual(
            session.resolve_project_directory(self.settings(), str(self.scratch.project)), self.scratch.project
        )
        (marker / "commondir").write_text(str(external))
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
            session.resolve_project_directory(self.settings(), str(self.scratch.project))
        # A `.git` link points outside the mount too; the container would
        # see a dangling link.
        shutil.rmtree(marker)
        marker.symlink_to(external)
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
            session.resolve_project_directory(self.settings(), str(self.scratch.project))

    def test_the_git_walk_ends_at_the_home_directory_and_at_a_project_root(self) -> None:
        # A repository that manages the home (dotfiles) or a root owns no
        # project below it; the walk never looks at their `.git`.
        (self.scratch.home / ".git").mkdir()
        (self.scratch.home / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        self.assertEqual(
            session.resolve_project_directory(self.settings(), str(self.scratch.project)), self.scratch.project
        )
        work = self.scratch.tmp / "work"
        (work / ".git").mkdir(parents=True)
        (work / "app").mkdir()
        settings = self.settings(LLM_PROJECT_ROOTS=str(work))
        self.assertEqual(session.resolve_project_directory(settings, str(work / "app")), work / "app")
        # A repository between the root and the project is still outside the mount.
        (work / "group").mkdir()
        (work / "group" / ".git").mkdir()
        (work / "group" / "app").mkdir()
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
            session.resolve_project_directory(settings, str(work / "group" / "app"))

    def test_symlinks_resolve_before_the_rules_apply(self) -> None:
        outside = self.scratch.tmp / "outside"
        outside.mkdir()
        link = self.scratch.home / "link"
        os.symlink(outside, link)
        with self.assertRaisesRegex(TokenCrateError, "outside your home directory"):
            session.resolve_project_directory(self.settings(), str(link))

    def test_project_roots_must_be_absolute_and_a_root_of_slash_allows_everything(self) -> None:
        outside = self.scratch.tmp / "srv" / "app"
        outside.mkdir(parents=True)
        with self.assertRaisesRegex(TokenCrateError, "must be absolute paths: ."):
            session.resolve_project_directory(self.settings(LLM_PROJECT_ROOTS="."), str(outside))
        allowed = self.settings(LLM_PROJECT_ROOTS=f"/nonexistent:{self.scratch.tmp / 'srv'}")
        self.assertEqual(session.resolve_project_directory(allowed, str(outside)), outside.resolve())
        self.assertEqual(
            session.resolve_project_directory(self.settings(LLM_PROJECT_ROOTS="/"), str(outside)), outside.resolve()
        )

    def test_only_retained_sources_are_created_and_ui_state_is_explicit(self) -> None:
        home = self.scratch.storage / "agents" / "pi" / "project-x"
        session.prepare_mountpoints(home, "pi")
        created = {str(path.relative_to(home)) for path in home.rglob("*")}
        self.assertEqual(created, {".pi", ".pi/agent", ".pi/agent/sessions"})
        session.prepare_mountpoints(home, "pi", ".paseo")
        self.assertTrue((home / ".paseo").is_dir())
        self.assertFalse((home / ".pi-web").exists(), "only the started UI's state directory is created")
        omp_home = self.scratch.storage / "agents" / "omp" / "project-x"
        session.prepare_mountpoints(omp_home, "omp")
        for relative in agenthome.PERSISTENT_DIRECTORIES["omp"]:
            self.assertTrue((omp_home / relative).is_dir(), relative)
        # A link anywhere on the way would send the mount elsewhere.
        os.rename(home / ".pi/agent/sessions", home / "sessions-aside")
        os.symlink(self.scratch.project, home / ".pi/agent/sessions")
        with self.assertRaisesRegex(TokenCrateError, "is a symbolic link"):
            session.prepare_mountpoints(home, "pi")

    def test_retained_paths_reject_files_and_nested_links(self) -> None:
        home = self.scratch.storage / "agent-home"
        session.prepare_mountpoints(home, "pi")
        sessions = home / ".pi/agent/sessions"
        sessions.rmdir()
        sessions.write_text("not a directory")
        with self.assertRaisesRegex(TokenCrateError, "is not a directory"):
            session.prepare_mountpoints(home, "pi")
        sessions.unlink()
        sessions.parent.rmdir()
        sessions.parent.symlink_to(self.scratch.project)
        with self.assertRaisesRegex(TokenCrateError, "is a symbolic link"):
            session.prepare_mountpoints(home, "pi")
        self.assertFalse((self.scratch.project / "sessions").exists())

    def test_mount_preparation_refuses_home_and_ancestor_links_before_creating_files(self) -> None:
        outside = self.scratch.tmp / "outside-home"
        outside.mkdir()
        link = self.scratch.storage / "linked-home"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        for home in (link, link / "missing" / "project"):
            with self.subTest(home=home):
                with self.assertRaisesRegex(TokenCrateError, "is a symbolic link"):
                    session.prepare_mountpoints(home, "pi")
                self.assertEqual(list(outside.iterdir()), [])

    def test_agent_home_is_one_directory_per_project_and_agent(self) -> None:
        settings = self.settings()
        home = session.agent_home_directory(settings, "pi", Path("/projects/src/project"))
        self.assertEqual(home.parent, settings.agents_dir / "pi")
        self.assertTrue(home.name.startswith("project-"))
        self.assertEqual(home, session.agent_home_directory(settings, "pi", Path("/projects/src/project")))
        self.assertNotEqual(home, session.agent_home_directory(settings, "pi", Path("/projects/other/project")))
        self.assertNotEqual(home, session.agent_home_directory(settings, "omp", Path("/projects/src/project")))


class CloudKeysFileTests(unittest.TestCase):
    """The file `agent --cloud` mounts: checked, never read, by the wrapper."""

    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(**overrides))

    def test_the_file_must_exist_be_regular_and_carry_a_mountable_path(self) -> None:
        settings = self.settings()
        with self.assertRaisesRegex(TokenCrateError, "no cloud keys file at .*local/cloud-keys.env; write one"):
            session.cloud_keys_file(settings, self.scratch.project)
        settings.cloud_keys_file.parent.mkdir(parents=True, exist_ok=True)
        settings.cloud_keys_file.mkdir()
        with self.assertRaisesRegex(TokenCrateError, "not a regular file"):
            session.cloud_keys_file(settings, self.scratch.project)
        settings.cloud_keys_file.rmdir()
        settings.cloud_keys_file.write_text("OPENAI_API_KEY=sk\n")
        settings.cloud_keys_file.chmod(0o600)
        self.assertEqual(session.cloud_keys_file(settings, self.scratch.project), settings.cloud_keys_file)
        odd = self.scratch.tmp / "a:b.env"
        odd.write_text("")
        odd.chmod(0o600)
        with self.assertRaisesRegex(TokenCrateError, "contains ':' or ','"):
            session.cloud_keys_file(self.settings(LLM_CLOUD_KEYS_FILE=str(odd)), self.scratch.project)

    def test_the_file_must_be_the_callers_and_readable_by_the_caller_alone(self) -> None:
        settings = self.settings()
        path = settings.cloud_keys_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OPENAI_API_KEY=sk\n")
        for mode in (0o644, 0o640, 0o604, 0o660):
            path.chmod(mode)
            with self.assertRaisesRegex(
                TokenCrateError, f"^{path} must be readable by your user only; run: chmod 600 {path}$"
            ):
                session.cloud_keys_file(settings, self.scratch.project)
        for mode in (0o600, 0o400):
            path.chmod(mode)
            self.assertEqual(session.cloud_keys_file(settings, self.scratch.project), path)
        other = os.getuid() + 1
        with mock.patch("tokencrate.env.os.getuid", return_value=other):
            with self.assertRaisesRegex(TokenCrateError, f"^{path} must be owned by your user \\(uid {other}\\)"):
                session.cloud_keys_file(settings, self.scratch.project)

    def test_the_file_is_refused_inside_a_directory_a_container_reads(self) -> None:
        # Every offline session mounts the storage directories and the
        # project; the build context is the .dockerignore allowlist.
        for label, directory in (
            ("the project", self.scratch.project),
            ("the private skills directory", self.scratch.storage / "local-skills"),
            ("the agents directory", self.scratch.storage / "agents"),
            ("the shipped configuration", self.scratch.root / "config"),
            ("the private agent sets", self.scratch.root / "local" / "agent-sets"),
            ("the services directory", self.scratch.root / "services"),
            ("the rendered pi images", self.scratch.root / "build" / "agents" / "pi"),
        ):
            with self.subTest(label=label):
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / "keys.env"
                path.write_text("")
                path.chmod(0o600)
                with self.assertRaisesRegex(TokenCrateError, f"lies inside {label}"):
                    session.cloud_keys_file(self.settings(LLM_CLOUD_KEYS_FILE=str(path)), self.scratch.project)


class LaunchTests(unittest.TestCase):
    """The one pre-flight and the runs it allows, against a mocked engine;
    `prepare` is the pre-flight proper and has its own tests."""

    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.settings = env.load(self.scratch.root, self.scratch.environment(LLM_DEFAULT_PRESET="qwen3.8-27b-q4"))
        self.engine = mock.MagicMock()
        self.engine.name = "docker"
        self.engine.command.return_value.returncode = 0
        self.prepared = mock.patch("tokencrate.session.prepare", return_value={"TOKENCRATE_PRESET": "p"})
        self.prepared.start()
        self.addCleanup(self.prepared.stop)

    def run_arguments(self, index: int) -> tuple[str, ...]:
        return self.engine.compose.call_args_list[index].args

    def test_a_stopped_container_is_tried_again_while_the_provider_creates_it(self) -> None:
        # The Compose client dies with the wrapper's exception; the container
        # it started is stopped by name, tried again while the provider may
        # still be creating it.
        self.engine.command.side_effect = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        with mock.patch("tokencrate.session.time.sleep") as sleep:
            session.stop_container(self.engine, "tokencrate-agent-abc")
        self.assertEqual(
            [call.args for call in self.engine.command.call_args_list],
            [("stop", "--time", "5", "tokencrate-agent-abc")] * 2,
        )
        sleep.assert_called_once()

    def test_an_interrupted_session_stops_its_named_container(self) -> None:
        self.engine.compose.side_effect = [mock.Mock(), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt), mock.patch.object(agents, "terminal_is_ours", return_value=True):
            agents.run_agent(
                self.settings,
                self.engine,
                None,
                "pi",
                preset="",
                project_dir=str(self.scratch.project),
                egress=False,
                arguments=["-p", "hi"],
            )
        build, run = self.engine.compose.call_args_list
        self.assertEqual(build.args, ("build", "agent-pi"))
        name = run.args[run.args.index("--name") + 1]
        self.assertRegex(name, r"^tokencrate-agent-[0-9a-f]{12}$")
        self.assertEqual(run.args, ("run", "--rm", "--name", name, "agent-pi", "pi", "-p", "hi"))
        self.assertEqual(
            run.kwargs,
            {"profiles": ("agent-pi",), "egress": False, "check": False, "stdin": None, "TOKENCRATE_PRESET": "p"},
        )
        self.engine.command.assert_called_once_with("stop", "--time", "5", name, capture=True, check=False)
        # Neither the pre-flight nor the session holds the stack lock.
        self.engine.lock.assert_not_called()

    def test_the_check_names_its_container_and_removes_its_scratch_after_the_stop(self) -> None:
        order: list[str] = []
        self.engine.compose.side_effect = [mock.Mock(), KeyboardInterrupt()]
        self.engine.command.side_effect = lambda *args, **kwargs: order.append(args[0]) or mock.Mock(returncode=0)
        self.engine.network_gateway.return_value = "10.89.1.1"
        with (
            mock.patch.object(agents.shutil, "rmtree", side_effect=lambda *a, **k: order.append("rmtree")) as rmtree,
            self.assertRaises(KeyboardInterrupt),
        ):
            agents.agent_check(self.settings, self.engine, None, "pi", "", ui_targets="egress:tokencrate-ui-x:8504")
        self.assertEqual(order, ["stop", "rmtree"])
        scratch = Path(rmtree.call_args.args[0])
        self.assertTrue(str(scratch.name).startswith("tokencrate-agent-check-"))
        shutil.rmtree(scratch, ignore_errors=True)
        run = self.engine.compose.call_args_list[1]
        name = run.args[run.args.index("--name") + 1]
        self.assertRegex(name, r"^tokencrate-agent-check-[0-9a-f]{12}$")
        self.assertEqual(run.args[:4], ("run", "--rm", "--no-deps", "-T"))
        self.assertIn("TOKENCRATE_UI_TARGETS=egress:tokencrate-ui-x:8504", run.args)
        self.assertIn("TOKENCRATE_AGENTS_GATEWAY=10.89.1.1", run.args)
        self.assertEqual(run.args[-2:], ("agent-pi", "/usr/local/bin/tokencrate-agent-check"))
        self.assertEqual(run.kwargs["check"], False)
        self.engine.lock.assert_called_once_with("smoke --agent")

    def test_cloud_mounts_the_keys_on_every_run_and_implies_egress(self) -> None:
        keys = self.scratch.tmp / "keys.env"
        keys.write_text("A_API_KEY=x\n")
        keys.chmod(0o600)
        settings = env.load(
            self.scratch.root,
            self.scratch.environment(LLM_DEFAULT_PRESET="qwen3.8-27b-q4", LLM_CLOUD_KEYS_FILE=str(keys)),
        )
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            launch = session.plan(settings, self.engine, None, "pi", "", self.scratch.project, cloud=True)
        self.assertTrue(launch.egress)
        self.assertEqual(launch.keys, keys)
        self.assertIn("internet access", stderr.getvalue())
        self.assertIn(f"keyed in {keys}", stderr.getvalue())
        launch.run(self.engine, "tokencrate-agent-000000000000", "-e", "X=1", detach=True)
        self.assertEqual(
            self.run_arguments(0),
            (
                "run",
                "--detach",
                "-T",
                "-e",
                "X=1",
                "--name",
                "tokencrate-agent-000000000000",
                "-v",
                f"{keys}:{session.KEYS_MOUNT_TARGET}:ro",
                "-e",
                "TOKENCRATE_CLOUD=1",
                "agent-pi",
            ),
        )
        self.assertEqual(self.engine.compose.call_args.kwargs["egress"], True)
        self.assertEqual(self.engine.compose.call_args.kwargs["check"], True)

    def test_the_terminal_is_ours_only_in_the_foreground_of_a_terminal(self) -> None:
        with mock.patch.object(sys, "stdin") as stdin, mock.patch.object(sys, "stdout") as stdout:
            stdin.isatty.return_value = stdout.isatty.return_value = True
            stdin.fileno.return_value = 0
            with mock.patch.object(os, "tcgetpgrp", return_value=os.getpgrp()):
                self.assertTrue(agents.terminal_is_ours())
            with mock.patch.object(os, "tcgetpgrp", return_value=os.getpgrp() + 1):
                self.assertFalse(agents.terminal_is_ours(), "a background job: `timeout` from a terminal")
            with mock.patch.object(os, "tcgetpgrp", side_effect=OSError(25, "Inappropriate ioctl")):
                self.assertFalse(agents.terminal_is_ours())
            stdout.isatty.return_value = False
            with mock.patch.object(os, "tcgetpgrp", return_value=os.getpgrp()):
                self.assertFalse(agents.terminal_is_ours())


class CloudSessionTests(unittest.TestCase):
    """What a user observes from bin/tokencrate, through the fake engine,
    which prints the credential variables it sees and the keys file's path
    (from the `-v` of the `run`)."""

    PRESET = "qwen3.8-27b-q4"

    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.scratch.render_fixture(self.PRESET)
        self.project = str(self.scratch.project)
        self.keys = self.scratch.tmp / "cloud-keys.env"
        self.keys.write_text("ANTHROPIC_API_KEY=sk-ant-test\n")
        self.keys.chmod(0o600)
        self.running = {"FAKE_ENGINE_LLAMA_RUNNING": "true", "LLM_CLOUD_KEYS_FILE": str(self.keys)}

    def run_cli(self, *arguments: str, **overrides: str):
        return self.scratch.run(*arguments, **{**self.running, **overrides})

    def expect_failure(self, expected: str, *arguments: str, **overrides: str) -> None:
        result = self.run_cli(*arguments, **overrides)
        self.assertNotEqual(result.returncode, 0, f"unexpectedly succeeded: {arguments}\n{result.stdout}")
        self.assertIn(expected, result.stdout + result.stderr)

    def succeed(self, *arguments: str, **overrides: str) -> str:
        result = self.run_cli(*arguments, **overrides)
        self.assertEqual(result.returncode, 0, f"{arguments} failed:\n{result.stdout}{result.stderr}")
        return result.stdout + result.stderr

    def agent(self, *flags: str) -> tuple[str, ...]:
        return ("agent", "pi", "--preset", self.PRESET, "--dir", self.project, *flags)

    def test_without_cloud_a_session_stays_local_whatever_is_configured(self) -> None:
        for flags, overlay in (((), False), (("--egress",), True)):
            with self.subTest(flags=flags):
                output = self.succeed(*self.agent(*flags))
                self.assertIn("env_keys= key_file= ", output)
                self.assertEqual("compose.agent-egress.yaml" in output, overlay)
                self.assertNotIn("TOKENCRATE_CLOUD", output)
                self.assertNotIn("offers the cloud provider", output)

    def test_cloud_mounts_the_keys_file_read_only_names_the_container_and_implies_egress(self) -> None:
        output = self.succeed(*self.agent("--cloud"))
        self.assertIn("compose.agent-egress.yaml", output)
        self.assertIn(f"this session offers the cloud providers keyed in {self.keys}", output)
        self.assertIn("every process in the session can read the keys", output)
        # Only the `run` mounts the file, with its own `-v`; the build before
        # it sees none, and no key is ever in the engine's environment.
        self.assertIn(f"env_keys= key_file={self.keys} ", output)
        self.assertRegex(
            output,
            rf"run --rm -T --name tokencrate-agent-[0-9a-f]{{12}} -v {self.keys}:{session.KEYS_MOUNT_TARGET}:ro "
            "-e TOKENCRATE_CLOUD=1 agent-pi pi",
        )
        self.assertNotIn("sk-ant-test", output)

    def test_the_terminal_is_attached_only_when_the_session_runs_in_one(self) -> None:
        # Under a pipe (a script, cron, CI) Compose gets -T and attaches no
        # terminal, which would otherwise stop a background job on SIGTTOU;
        # a session started from a terminal keeps it.
        piped = self.succeed(*self.agent(), "--", "-p", "hi")
        session_run = r"run --rm {} --name tokencrate-agent-[0-9a-f]{{12}} agent-pi pi -p hi"
        self.assertRegex(piped, r"compose stdin=(?!tty).*" + session_run.format("-T"))
        on_terminal = self.on_a_terminal()
        self.assertRegex(on_terminal, r"compose stdin=tty .*" + session_run.format("").replace("  ", " "))

    def test_a_terminal_the_wrapper_may_not_read_is_kept_from_the_engine(self) -> None:
        # `timeout` moves itself and the wrapper into a new process group
        # (unless it is already a group leader, which a shell's job or an
        # exec makes it; hence the `sh -c` with a second command, so the
        # shell forks): the terminal's foreground group is another one, so
        # Compose gets -T and the engine gets /dev/null on stdin instead of
        # the terminal it would read from and stop the job with SIGTTIN.
        on_terminal = self.on_a_terminal("sh", "-c", 'timeout 60 "$@"; exit $?', "sh")
        self.assertRegex(
            on_terminal, r"compose stdin=devnull .*run --rm -T --name tokencrate-agent-[0-9a-f]{12} agent-pi pi -p hi"
        )

    def on_a_terminal(self, *prefix: str) -> str:
        """Run `agent pi -- -p hi` on a pseudo-terminal, optionally behind a
        command such as `timeout`, and return what the terminal showed."""
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - the child execs or dies
            try:
                os.chdir(self.scratch.root)
                command = [*prefix, sys.executable, "-m", "tokencrate", *self.agent(), "--", "-p", "hi"]
                os.execvpe(command[0], command, self.scratch.environment(**self.running))
            finally:
                os._exit(127)
        chunks = []
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
        os.close(fd)
        _, status = os.waitpid(pid, 0)
        on_terminal = b"".join(chunks).decode(errors="replace")
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, on_terminal)
        return on_terminal

    def test_cloud_refuses_before_the_session_without_a_usable_file(self) -> None:
        self.keys.unlink()
        self.expect_failure("no cloud keys file at", *self.agent("--cloud"))
        self.expect_failure("no cloud keys file at", "ui", "pi-web", "--dir", self.project, "--cloud")
        self.expect_failure("--cloud is only valid with agent or ui", "bench", "--cloud")
        self.expect_failure("--egress is only valid with smoke --agent, agent, or ui", "bench", "--egress")
        # oh-my-pi reads provider settings from the project's .env files;
        # refused before the file is looked at.
        refused = self.run_cli("agent", "omp", "--preset", self.PRESET, "--dir", self.project, "--cloud")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--cloud applies to pi only", refused.stderr)

    def test_a_cloud_ui_mounts_the_keys_file_into_the_ui_container_alone(self) -> None:
        # The same run arguments as a terminal session, on the UI container's
        # `run` and under the overlay; the forwarder's `run` gets neither.
        common = {"FAKE_ENGINE_UI_SET": "pi-web", "FAKE_ENGINE_UI_PORT": str(self.scratch.ui_port)}
        port = str(self.scratch.ui_port)
        with self.scratch.ui_listener():
            output = self.succeed(
                "ui", "pi-web", "--preset", self.PRESET, "--dir", self.project, "--port", port, "--cloud", **common
            )
        self.assertIn(f"this session offers the cloud providers keyed in {self.keys}", output)
        ui_run, forward_run = (line for line in output.splitlines() if " run --detach " in line)
        self.assertIn("--file compose.agent-egress.yaml --profile ui", ui_run)
        self.assertRegex(
            ui_run,
            r"run --detach --no-deps -T -v \S+/pi/pi-web-state:/run/tokencrate/ui-state --name tokencrate-ui-pi-web "
            + re.escape(f"-v {self.keys}:{session.KEYS_MOUNT_TARGET}:ro -e TOKENCRATE_CLOUD=1 agent-ui"),
        )
        self.assertIn(f"key_file={self.keys} ", ui_run)
        self.assertIn("key_file= ", forward_run)
        self.assertNotIn("TOKENCRATE_CLOUD", forward_run)
        self.assertNotIn("compose.agent-egress.yaml", forward_run)
        self.assertNotIn("sk-ant-test", output)

    def test_the_containment_check_carries_no_key(self) -> None:
        for flags, egress in (((), ""), (("--egress",), "1")):
            with self.subTest(flags=flags):
                check = self.succeed("smoke", "--agent", "pi", "--preset", self.PRESET, *flags)
                self.assertIn(f"-e TOKENCRATE_EGRESS={egress} ", check)
                self.assertIn("env_keys= key_file= ", check)
                self.assertNotIn("TOKENCRATE_CLOUD", check)
        self.expect_failure("--egress applies to smoke --agent", "smoke", "--egress", "--preset", self.PRESET)


class SessionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def test_a_failed_build_cannot_advertise_a_new_preset_to_an_old_router(self) -> None:
        settings = env.load(self.scratch.root, self.scratch.environment(LLM_DEFAULT_PRESET="ci-small"))
        for kind in ("model-sets", "presets"):
            shutil.copy(SOURCE_ROOT / "tests/fixtures" / kind / "ci-small.toml", settings.config_dir / kind)
        configuration = presets.load(settings.config_dir, 999999)
        for entry in configuration.model_sets["ci-small"].files:
            path = settings.models_dir / entry.destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        engine = mock.MagicMock()
        engine.name = "podman"
        engine.running_llama_id.return_value = "old-router"
        engine.network_document.return_value = None
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.render(settings, configuration)
        engine.command.return_value.stdout = runtime.config_digest(settings)
        session.require_session_ready(settings, engine, configuration, "ci-small")
        added = dataclasses.replace(next(p for p in configuration.presets if p.name == "ci-small"), name="ci-added")
        configuration = dataclasses.replace(configuration, presets=configuration.presets + (added,))
        shutil.copy(settings.config_dir / "presets/ci-small.toml", settings.config_dir / "presets/ci-added.toml")
        engine.compose.side_effect = TokenCrateError("injected build failure")
        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(TokenCrateError, "injected build failure"),
        ):
            runtime.start_stack(settings, engine, configuration, 1)
        self.assertIn("ci-added", presets.rendered_model_ids(settings.build_dir))
        with self.assertRaisesRegex(TokenCrateError, "running llama configuration differs"):
            session.require_session_ready(settings, engine, configuration, "ci-added")
        engine.command.return_value.stdout = runtime.config_digest(settings)
        session.require_session_ready(settings, engine, configuration, "ci-added")


if __name__ == "__main__":
    unittest.main()
