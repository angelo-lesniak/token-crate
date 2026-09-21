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
from tokencrate import TokenCrateError, agents, agentsets, env, presets, runtime


class ProjectDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(**overrides))

    def test_refuses_root_home_missing_and_outside_directories(self) -> None:
        settings = self.settings()
        with self.assertRaisesRegex(TokenCrateError, "refusing to mount the root filesystem"):
            agents.resolve_project_directory(settings, "/")
        with self.assertRaisesRegex(TokenCrateError, "whole home directory"):
            agents.resolve_project_directory(settings, str(self.scratch.home))
        with self.assertRaisesRegex(TokenCrateError, "does not exist"):
            agents.resolve_project_directory(settings, str(self.scratch.home / "missing"))
        with self.assertRaisesRegex(TokenCrateError, "outside your home directory and LLM_PROJECT_ROOTS"):
            agents.resolve_project_directory(settings, "/usr")
        self.assertEqual(
            agents.resolve_project_directory(settings, str(self.scratch.project)), self.scratch.project.resolve()
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
                agents.resolve_project_directory(settings, str(path))
        # A parent of the checkout contains it (and, here, every storage directory).
        with self.assertRaisesRegex(TokenCrateError, "contains or lies inside the TokenCrate checkout"):
            agents.resolve_project_directory(settings, str(self.scratch.tmp))
        # A storage directory that lies below the home is still refused.
        inside_home = self.settings(LLM_SKILLS_DIR=str(self.scratch.home / "skills"))
        (self.scratch.home / "skills" / "set").mkdir(parents=True)
        with self.assertRaisesRegex(TokenCrateError, "contains or lies inside the skills directory"):
            agents.resolve_project_directory(inside_home, str(self.scratch.home / "skills" / "set"))

    def test_unsafe_characters_are_refused(self) -> None:
        odd = self.scratch.home / "with space"
        odd.mkdir()
        with self.assertRaisesRegex(TokenCrateError, "cannot express safely"):
            agents.resolve_project_directory(self.settings(), str(odd))

    def test_git_metadata_must_fit_inside_the_project_mount(self) -> None:
        external = self.scratch.home / "other-repository" / ".git"
        external.mkdir(parents=True)
        (external / "HEAD").write_text("ref: refs/heads/main\n")
        marker = self.scratch.project / ".git"
        marker.write_text(f"gitdir: {external}\n")
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
            agents.resolve_project_directory(self.settings(), str(self.scratch.project))
        marker.unlink()
        marker.mkdir()
        (marker / "HEAD").write_text("ref: refs/heads/main\n")
        self.assertEqual(
            agents.resolve_project_directory(self.settings(), str(self.scratch.project)), self.scratch.project
        )
        (marker / "commondir").write_text(str(external))
        with self.assertRaisesRegex(TokenCrateError, "Git metadata lies outside"):
            agents.resolve_project_directory(self.settings(), str(self.scratch.project))

    def test_symlinks_resolve_before_the_rules_apply(self) -> None:
        outside = self.scratch.tmp / "outside"
        outside.mkdir()
        link = self.scratch.home / "link"
        os.symlink(outside, link)
        with self.assertRaisesRegex(TokenCrateError, "outside your home directory"):
            agents.resolve_project_directory(self.settings(), str(link))

    def test_project_roots_must_be_absolute_and_a_root_of_slash_allows_everything(self) -> None:
        outside = self.scratch.tmp / "srv" / "app"
        outside.mkdir(parents=True)
        with self.assertRaisesRegex(TokenCrateError, "must be absolute paths: ."):
            agents.resolve_project_directory(self.settings(LLM_PROJECT_ROOTS="."), str(outside))
        allowed = self.settings(LLM_PROJECT_ROOTS=f"/nonexistent:{self.scratch.tmp / 'srv'}")
        self.assertEqual(agents.resolve_project_directory(allowed, str(outside)), outside.resolve())
        self.assertEqual(
            agents.resolve_project_directory(self.settings(LLM_PROJECT_ROOTS="/"), str(outside)), outside.resolve()
        )

    def test_only_retained_sources_are_created_and_ui_state_is_explicit(self) -> None:
        home = self.scratch.storage / "agents" / "pi" / "project-x"
        agents.prepare_mountpoints(home, "pi")
        created = {str(path.relative_to(home)) for path in home.rglob("*")}
        self.assertEqual(created, {".pi", ".pi/agent", ".pi/agent/sessions"})
        agents.prepare_mountpoints(home, "pi", ui=True)
        for relative in agents.UI_DIRECTORIES:
            self.assertTrue((home / relative).is_dir(), relative)
        omp_home = self.scratch.storage / "agents" / "omp" / "project-x"
        agents.prepare_mountpoints(omp_home, "omp")
        for relative in agents.PERSISTENT_DIRECTORIES["omp"]:
            self.assertTrue((omp_home / relative).is_dir(), relative)
        # A link anywhere on the way would send the mount elsewhere.
        os.rename(home / ".pi/agent/sessions", home / "sessions-aside")
        os.symlink(self.scratch.project, home / ".pi/agent/sessions")
        with self.assertRaisesRegex(TokenCrateError, "is a symbolic link"):
            agents.prepare_mountpoints(home, "pi")

    def test_retained_paths_reject_files_and_nested_links(self) -> None:
        home = self.scratch.storage / "agent-home"
        agents.prepare_mountpoints(home, "pi")
        sessions = home / ".pi/agent/sessions"
        sessions.rmdir()
        sessions.write_text("not a directory")
        with self.assertRaisesRegex(TokenCrateError, "is not a directory"):
            agents.prepare_mountpoints(home, "pi")
        sessions.unlink()
        sessions.parent.rmdir()
        sessions.parent.symlink_to(self.scratch.project)
        with self.assertRaisesRegex(TokenCrateError, "is a symbolic link"):
            agents.prepare_mountpoints(home, "pi")
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
                    agents.prepare_mountpoints(home, "pi")
                self.assertEqual(list(outside.iterdir()), [])

    def test_agent_home_is_one_directory_per_project_and_agent(self) -> None:
        settings = self.settings()
        home = agents.agent_home_directory(settings, "pi", Path("/projects/src/project"))
        self.assertEqual(home.parent, settings.agents_dir / "pi")
        self.assertTrue(home.name.startswith("project-"))
        self.assertEqual(home, agents.agent_home_directory(settings, "pi", Path("/projects/src/project")))
        self.assertNotEqual(home, agents.agent_home_directory(settings, "pi", Path("/projects/other/project")))
        self.assertNotEqual(home, agents.agent_home_directory(settings, "omp", Path("/projects/src/project")))


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
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.render(settings, configuration)
        engine.command.return_value.stdout = runtime.config_digest(settings)
        agents.require_session_ready(settings, engine, configuration, "ci-small")
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
            agents.require_session_ready(settings, engine, configuration, "ci-added")
        engine.command.return_value.stdout = runtime.config_digest(settings)
        agents.require_session_ready(settings, engine, configuration, "ci-added")


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
        agents.seed_ui_identity(self.settings, first, self.entry)
        self.assertFalse((first / ".paseo").exists(), "nothing to seed before a daemon ever ran")
        (first / ".paseo").mkdir()
        (first / ".paseo" / "daemon-keypair.json").write_text('{"v": 2}')
        (first / ".paseo" / "server-id").write_text("srv_first")
        agents.harvest_ui_identity(self.settings, first, self.entry)
        store = agents.ui_identity_store(self.settings, "paseo")
        self.assertEqual((store / ".paseo" / "server-id").read_text(), "srv_first")
        self.assertEqual(oct((store / ".paseo" / "server-id").stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((store / ".paseo").stat().st_mode & 0o777), "0o700")

        second = self.home("second-000000000000")
        agents.seed_ui_identity(self.settings, second, self.entry)
        self.assertEqual((second / ".paseo" / "server-id").read_text(), "srv_first")
        self.assertEqual((second / ".paseo" / "daemon-keypair.json").read_text(), '{"v": 2}')
        # A home that has an identity keeps it, and the store keeps the first.
        (second / ".paseo" / "server-id").write_text("srv_second")
        agents.seed_ui_identity(self.settings, second, self.entry)
        agents.harvest_ui_identity(self.settings, second, self.entry)
        self.assertEqual((second / ".paseo" / "server-id").read_text(), "srv_second")
        self.assertEqual((store / ".paseo" / "server-id").read_text(), "srv_first")

    def test_links_in_the_agent_home_are_not_followed(self) -> None:
        outside = self.scratch.root / "outside"
        outside.mkdir()
        (outside / "server-id").write_text("host secret")
        linked = self.home("linked-000000000000")
        (linked / ".paseo").symlink_to(outside)
        agents.harvest_ui_identity(self.settings, linked, self.entry)
        store = agents.ui_identity_store(self.settings, "paseo")
        self.assertFalse(store.exists())
        # Seeding through a linked directory is refused as well.
        (store / ".paseo").mkdir(parents=True)
        (store / ".paseo" / "server-id").write_text("srv_store")
        agents.seed_ui_identity(self.settings, linked, self.entry)
        self.assertEqual((outside / "server-id").read_text(), "host secret")
        plain = self.home("plain-000000000000")
        (plain / ".paseo").mkdir()
        (plain / ".paseo" / "server-id").symlink_to(outside / "server-id")
        agents.seed_ui_identity(self.settings, plain, self.entry)
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
        store = agents.ui_identity_store(self.settings, "paseo") / ".paseo" / "server-id"
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
                    agents.harvest_ui_identity(self.settings, home, self.entry)
                if store.exists():
                    self.assertEqual(store.read_text(), "srv_racing")
                    store.unlink()
        finally:
            stop.set()
            swapper.join()

    def test_a_ui_set_without_identity_files_is_left_alone(self) -> None:
        entry = agentsets.load_set(self.scratch.root, "pi-web")
        home = self.home("web-000000000000")
        agents.seed_ui_identity(self.settings, home, entry)
        agents.harvest_ui_identity(self.settings, home, entry)
        self.assertEqual(list(home.iterdir()), [])
        self.assertFalse(agents.ui_identity_store(self.settings, "pi-web").exists())

    def test_identity_copies_refuse_links_at_the_home_or_store_root(self) -> None:
        real = self.home("real-000000000000")
        (real / ".paseo").mkdir()
        (real / ".paseo/server-id").write_text("srv_real")
        linked = real.parent / "linked-000000000000"
        linked.symlink_to(real)
        agents.harvest_ui_identity(self.settings, linked, self.entry)
        store = agents.ui_identity_store(self.settings, "paseo")
        self.assertFalse(store.exists())
        store.symlink_to(real)
        target = self.home("target-000000000000")
        agents.seed_ui_identity(self.settings, target, self.entry)
        self.assertEqual(list(target.iterdir()), [])
        (real / ".paseo/server-id").unlink()
        (target / ".paseo").mkdir()
        (target / ".paseo/server-id").write_text("srv_target")
        agents.harvest_ui_identity(self.settings, target, self.entry)
        self.assertEqual(list((real / ".paseo").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
