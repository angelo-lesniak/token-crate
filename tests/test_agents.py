"""Project-directory rules, session readiness, and the per-project agent home."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.support import SOURCE_ROOT, Scratch
from tokencrate import TokenCrateError, agents, agentsets, env, presets, runtime, session, uis


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
        # A repository above the project owns the project's metadata.
        above = self.scratch.home / "src" / ".git"
        above.mkdir()
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
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
        for relative in session.PERSISTENT_DIRECTORIES["omp"]:
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
        self.assertEqual(session.cloud_keys_file(settings, self.scratch.project), settings.cloud_keys_file)
        odd = self.scratch.tmp / "a:b.env"
        odd.write_text("")
        with self.assertRaisesRegex(TokenCrateError, "contains ':' or ','"):
            session.cloud_keys_file(self.settings(LLM_CLOUD_KEYS_FILE=str(odd)), self.scratch.project)

    def test_the_file_is_refused_inside_a_directory_a_container_reads(self) -> None:
        # Every offline session mounts the storage directories and the
        # project; the build context carries the set directories.
        for label, directory in (
            ("the project", self.scratch.project),
            ("the private skills directory", self.scratch.storage / "local-skills"),
            ("the agents directory", self.scratch.storage / "agents"),
            ("the shipped configuration", self.scratch.root / "config"),
            ("the private agent sets", self.scratch.root / "local" / "agent-sets"),
        ):
            with self.subTest(label=label):
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / "keys.env"
                path.write_text("")
                with self.assertRaisesRegex(TokenCrateError, f"lies inside {label}"):
                    session.cloud_keys_file(self.settings(LLM_CLOUD_KEYS_FILE=str(path)), self.scratch.project)


class SessionStopTests(unittest.TestCase):
    def test_an_interrupted_session_stops_its_named_container(self) -> None:
        # The Compose client dies with the wrapper's exception; the session
        # container it started is stopped by name, tried again while the
        # provider may still be creating it.
        engine = mock.MagicMock()
        engine.command.side_effect = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        with mock.patch("tokencrate.agents.time.sleep") as sleep:
            agents.stop_session(engine, "tokencrate-agent-abc")
        self.assertEqual(
            [call.args for call in engine.command.call_args_list],
            [("stop", "--time", "5", "tokencrate-agent-abc")] * 2,
        )
        sleep.assert_called_once()


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
            rf"run --rm --name tokencrate-agent-[0-9a-f]{{12}} -v {self.keys}:{session.KEYS_MOUNT_TARGET}:ro "
            "-e TOKENCRATE_CLOUD=1 agent-pi pi",
        )
        self.assertNotIn("sk-ant-test", output)

    def test_cloud_refuses_before_the_session_without_a_usable_file(self) -> None:
        self.keys.unlink()
        self.expect_failure("no cloud keys file at", *self.agent("--cloud"))
        self.expect_failure("no cloud keys file at", "ui", "pi-web", "--dir", self.project, "--cloud")
        self.expect_failure("--cloud is only valid with agent or ui", "bench", "--cloud")
        self.expect_failure("--egress is only valid with agent, smoke --agent, or ui", "bench", "--egress")
        # oh-my-pi reads provider settings from the project's .env files;
        # refused before the file is looked at.
        refused = self.run_cli("agent", "omp", "--preset", self.PRESET, "--dir", self.project, "--cloud")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--cloud applies to pi only", refused.stderr)

    def test_a_cloud_ui_mounts_the_keys_file_into_the_ui_container_alone(self) -> None:
        # The same run arguments as a terminal session, on the UI container's
        # `run` and under the overlay; the forwarder's `run` gets neither.
        common = {
            "LLM_UI_PORT_PI_WEB": str(self.scratch.ui_port),
            "FAKE_ENGINE_UI_SET": "pi-web",
            "FAKE_ENGINE_UI_PORT": str(self.scratch.ui_port),
        }
        with self.scratch.ui_listener():
            output = self.succeed("ui", "pi-web", "--preset", self.PRESET, "--dir", self.project, "--cloud", **common)
        self.assertIn(f"this session offers the cloud providers keyed in {self.keys}", output)
        ui_run, forward_run = (line for line in output.splitlines() if " run --detach " in line)
        self.assertIn("--file compose.agent-egress.yaml --profile ui", ui_run)
        self.assertIn(
            f"run --detach --no-deps -T --name tokencrate-ui-pi-web -v {self.keys}:{session.KEYS_MOUNT_TARGET}:ro "
            "-e TOKENCRATE_CLOUD=1 agent-ui",
            ui_run,
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


class UiIdentityTests(unittest.TestCase):
    """One daemon identity per UI set, handed to every project's agent home."""

    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.settings = env.load(self.scratch.root, self.scratch.environment())
        self.entry = agentsets.load_set(self.scratch.root, "paseo")

    def home(self, name: str) -> Path:
        home = self.settings.agents_dir / "pi" / name
        home.mkdir(parents=True, exist_ok=True)
        return home

    def test_the_first_start_fills_the_store_and_later_homes_get_the_same_files(self) -> None:
        first = self.home("first-000000000000")
        uis.seed_ui_identity(self.settings, first, self.entry)
        self.assertFalse((first / ".paseo").exists(), "nothing to seed before a daemon ever ran")
        (first / ".paseo").mkdir()
        (first / ".paseo" / "daemon-keypair.json").write_text('{"v": 2}')
        (first / ".paseo" / "server-id").write_text("srv_first")
        uis.harvest_ui_identity(self.settings, first, self.entry)
        store = uis.ui_identity_store(self.settings, "paseo")
        self.assertEqual((store / ".paseo" / "server-id").read_text(), "srv_first")
        self.assertEqual(oct((store / ".paseo" / "server-id").stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((store / ".paseo").stat().st_mode & 0o777), "0o700")

        second = self.home("second-000000000000")
        uis.seed_ui_identity(self.settings, second, self.entry)
        self.assertEqual((second / ".paseo" / "server-id").read_text(), "srv_first")
        self.assertEqual((second / ".paseo" / "daemon-keypair.json").read_text(), '{"v": 2}')
        # A home that has an identity keeps it, and the store keeps the first.
        (second / ".paseo" / "server-id").write_text("srv_second")
        uis.seed_ui_identity(self.settings, second, self.entry)
        uis.harvest_ui_identity(self.settings, second, self.entry)
        self.assertEqual((second / ".paseo" / "server-id").read_text(), "srv_second")
        self.assertEqual((store / ".paseo" / "server-id").read_text(), "srv_first")

    def test_links_in_the_agent_home_are_not_followed(self) -> None:
        outside = self.scratch.root / "outside"
        outside.mkdir()
        (outside / "server-id").write_text("host secret")
        linked = self.home("linked-000000000000")
        (linked / ".paseo").symlink_to(outside)
        uis.harvest_ui_identity(self.settings, linked, self.entry)
        store = uis.ui_identity_store(self.settings, "paseo")
        self.assertFalse(store.exists())
        # Seeding through a linked directory is refused as well.
        (store / ".paseo").mkdir(parents=True)
        (store / ".paseo" / "server-id").write_text("srv_store")
        uis.seed_ui_identity(self.settings, linked, self.entry)
        self.assertEqual((outside / "server-id").read_text(), "host secret")
        plain = self.home("plain-000000000000")
        (plain / ".paseo").mkdir()
        (plain / ".paseo" / "server-id").symlink_to(outside / "server-id")
        uis.seed_ui_identity(self.settings, plain, self.entry)
        self.assertEqual((outside / "server-id").read_text(), "host secret")

    def test_a_file_swapped_for_a_link_during_the_harvest_is_never_read(self) -> None:
        """The UI container writes its retained directory while the harvest
        runs; a link that replaces the file between the check and the read
        must not be resolved on the host."""
        outside = self.scratch.root / "outside"
        outside.mkdir()
        (outside / "server-id").write_text("host secret")
        home = self.home("racing-000000000000")
        (home / ".paseo").mkdir()
        path = home / ".paseo" / "server-id"
        path.write_text("srv_racing")
        store = uis.ui_identity_store(self.settings, "paseo") / ".paseo" / "server-id"
        stop = threading.Event()

        def swap() -> None:
            link, plain = path.with_name("link"), path.with_name("plain")
            while not stop.is_set():
                link.symlink_to(outside / "server-id")
                os.replace(link, path)
                plain.write_text("srv_racing")
                os.replace(plain, path)

        swapper = threading.Thread(target=swap)
        swapper.start()
        try:
            for _ in range(500):
                with contextlib.suppress(TokenCrateError, OSError):
                    uis.harvest_ui_identity(self.settings, home, self.entry)
                if store.exists():
                    self.assertEqual(store.read_text(), "srv_racing")
                    store.unlink()
        finally:
            stop.set()
            swapper.join()

    def test_a_ui_set_without_identity_files_is_left_alone(self) -> None:
        entry = agentsets.load_set(self.scratch.root, "pi-web")
        home = self.home("web-000000000000")
        uis.seed_ui_identity(self.settings, home, entry)
        uis.harvest_ui_identity(self.settings, home, entry)
        self.assertEqual(list(home.iterdir()), [])
        self.assertFalse(uis.ui_identity_store(self.settings, "pi-web").exists())

    def test_identity_copies_refuse_links_at_the_home_or_store_root(self) -> None:
        real = self.home("real-000000000000")
        (real / ".paseo").mkdir()
        (real / ".paseo/server-id").write_text("srv_real")
        linked = real.parent / "linked-000000000000"
        linked.symlink_to(real)
        uis.harvest_ui_identity(self.settings, linked, self.entry)
        store = uis.ui_identity_store(self.settings, "paseo")
        self.assertFalse(store.exists())
        store.symlink_to(real)
        target = self.home("target-000000000000")
        uis.seed_ui_identity(self.settings, target, self.entry)
        self.assertEqual(list(target.iterdir()), [])
        (real / ".paseo/server-id").unlink()
        (target / ".paseo").mkdir()
        (target / ".paseo/server-id").write_text("srv_target")
        uis.harvest_ui_identity(self.settings, target, self.entry)
        self.assertEqual(list((real / ".paseo").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
