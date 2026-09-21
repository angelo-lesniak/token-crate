"""The agent entrypoint (services/agents/entrypoint.sh) run against a
temporary root that stands in for the container's fixed paths."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import SOURCE_ROOT

ENTRYPOINT = SOURCE_ROOT / "services" / "agents" / "entrypoint.sh"
PI_SETTINGS = SOURCE_ROOT / "config" / "agents" / "pi" / "settings.json"


@unittest.skipUnless(shutil.which("node"), "node is required to run the entrypoint")
class EntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prefix = Path(tempfile.mkdtemp(prefix="tokencrate-entrypoint-"))
        self.addCleanup(shutil.rmtree, self.prefix, True)
        self.home = self.prefix / "home"
        self.project = self.prefix / "project"
        self.static = self.prefix / "etc" / "tokencrate" / "agent"
        self.generated = self.prefix / "etc" / "tokencrate" / "agent-generated"
        self.image = self.prefix / "opt" / "tokencrate"
        self.fetched = self.image / "skills"
        self.repo_skills = self.image / "skills-repo"
        self.local_skills = self.image / "skills-local"
        for path in (
            self.project,
            self.static,
            self.generated,
            self.fetched,
            self.repo_skills,
            self.local_skills,
        ):
            path.mkdir(parents=True)
        shutil.copy(PI_SETTINGS, self.static / "settings.json")
        shutil.copy(SOURCE_ROOT / "config" / "agents" / "omp" / "config.yml", self.static / "config.yml")
        (self.generated / "models.json").write_text(
            '{"providers":{"tokencrate":{"models":[{"id":"fixture-preset"}]}}}\n'
        )
        (self.generated / "models.yml").write_text(
            '{"providers": {"tokencrate": {"models": [{"id": "fixture-preset"}]}}}\n'
        )
        (self.project / "README.md").write_text("project file\n")

    def make_skill(self, root: Path, name: str) -> None:
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\n")

    def run_entrypoint(self, agent: str, *command: str, **extra: str) -> subprocess.CompletedProcess:
        # The container home is a fresh tmpfs at every start.
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir()
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "TOKENCRATE_AGENT": agent,
            "TOKENCRATE_PROJECT_DIR": str(self.project),
            "TOKENCRATE_PRESET": "fixture-preset",
            "TOKENCRATE_PREFIX": str(self.prefix),
        }
        env.update(extra)
        return subprocess.run(["bash", str(ENTRYPOINT), *command], env=env, capture_output=True, text=True, check=False)

    def settings(self) -> dict:
        return json.loads((self.home / ".pi" / "agent" / "settings.json").read_text())

    def test_pi_merges_skills_writes_settings_and_leaves_the_project_alone(self) -> None:
        self.make_skill(self.fetched / "pocock-core", "tdd")
        self.make_skill(self.repo_skills, "repo-skill")
        self.make_skill(self.local_skills, "private-skill")
        before = sorted(str(path) for path in self.project.rglob("*"))
        result = self.run_entrypoint(
            "pi",
            "bash",
            "-c",
            'printf "cwd=%s\\n" "$PWD"; ls -1 "$HOME/.agents/skills"; '
            "git config --global --get user.name; git config --global --get safe.directory",
            TOKENCRATE_SKILL_SETS="pocock-core",
            GIT_AUTHOR_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture@example.invalid",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"cwd={self.project}", result.stdout)
        for name in ("tdd", "repo-skill", "private-skill"):
            self.assertIn(name, result.stdout)
        self.assertIn("Fixture", result.stdout)
        self.assertIn("*", result.stdout)
        self.assertTrue((self.home / ".agents" / "skills").is_symlink())
        settings = self.settings()
        self.assertIs(settings["enableInstallTelemetry"], False)
        self.assertEqual((settings["defaultProvider"], settings["defaultModel"]), ("tokencrate", "fixture-preset"))
        self.assertTrue((self.home / ".pi" / "agent" / "models.json").is_file())
        self.assertEqual(before, sorted(str(path) for path in self.project.rglob("*")))

    def test_the_settings_are_the_repository_file_plus_the_preset_and_the_image_package_list(self) -> None:
        # The image declares the pi packages it ships and the files it seeds
        # into the agent home.
        packages = ["/opt/tokencrate/sets/coding/node_modules/pi-lens", "/opt/tokencrate/sets/coding/subagent"]
        (self.image / "pi-packages.txt").write_text("".join(f"{package}\n" for package in packages))
        seed = self.image / "home-seed"
        (seed / ".pi" / "agent" / "agents").mkdir(parents=True)
        (seed / ".pi" / "agent" / "AGENTS.md").write_text("tools note\n")
        (seed / ".pi" / "agent" / "agents" / "scout.md").write_text("---\nname: scout\n---\n")
        (seed / ".nuget" / "NuGet").mkdir(parents=True)
        (seed / ".nuget" / "NuGet" / "NuGet.Config").write_text("<configuration/>\n")
        result = self.run_entrypoint("pi", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads(PI_SETTINGS.read_text())
        expected.update(defaultProvider="tokencrate", defaultModel="fixture-preset", packages=packages)
        self.assertEqual(self.settings(), expected)
        self.assertEqual((self.home / ".pi" / "agent" / "AGENTS.md").read_text(), "tools note\n")
        self.assertEqual((self.home / ".pi" / "agent" / "agents" / "scout.md").read_text(), "---\nname: scout\n---\n")
        self.assertTrue((self.home / ".nuget" / "NuGet" / "NuGet.Config").is_file())

    def test_without_an_image_package_list_no_package_is_configured(self) -> None:
        self.assertEqual(self.run_entrypoint("pi", "true").returncode, 0)
        self.assertEqual(self.settings()["packages"], [])

    def test_omp_settings_are_the_repository_file_plus_the_default_model(self) -> None:
        result = self.run_entrypoint("omp", "bash", "-c", 'printf "%s\\n" "$PI_CONFIG_FILES"')
        self.assertEqual(result.returncode, 0, result.stderr)
        # The repository file is the overlay, which outranks the home copy;
        # the home copy is the file oh-my-pi reads and rewrites, so a model
        # chosen in a session applies to it.
        self.assertEqual(result.stdout.strip(), f"{self.static}/config.yml")
        config = self.home / ".omp" / "agent" / "config.yml"
        written = config.read_text()
        self.assertIn("shellPath: /bin/bash", written)
        self.assertIn("modelRoles:\n  default: tokencrate/fixture-preset\n", written)
        self.assertTrue(os.access(config, os.W_OK), "oh-my-pi must be able to save its settings for the session")
        self.assertTrue((self.home / ".omp" / "agent" / "models.yml").is_file())

    def test_a_skill_whose_frontmatter_name_differs_from_its_directory_is_refused(self) -> None:
        self.make_skill(self.fetched / "one", "tdd")
        self.make_skill(self.repo_skills, "repo-skill")
        self.make_skill(self.local_skills, "private-skill")
        self.assertEqual(self.run_entrypoint("pi", "true", TOKENCRATE_SKILL_SETS="one").returncode, 0)
        # The check applies to every source: here the private skill lies.
        skill_file = self.local_skills / "private-skill" / "SKILL.md"
        skill_file.write_text("---\nname: 'other-name'\ndescription: x\n---\n")
        result = self.run_entrypoint("pi", "true", TOKENCRATE_SKILL_SETS="one")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "skill private-skill: SKILL.md frontmatter name is 'other-name', not the directory name", result.stderr
        )
        skill_file.write_text("no frontmatter\n")
        result = self.run_entrypoint("pi", "true", TOKENCRATE_SKILL_SETS="one")
        self.assertIn("frontmatter name is 'missing'", result.stderr)

    def test_rejections(self) -> None:
        self.assertIn("must be pi or omp", self.run_entrypoint("claude", "true").stderr)
        self.assertIn("must be pi or omp", self.run_entrypoint("pi-odin", "true").stderr)
        self.assertIn("is not fetched", self.run_entrypoint("pi", "true", TOKENCRATE_SKILL_SETS="missing-set").stderr)
        self.make_skill(self.fetched / "one", "shared")
        self.make_skill(self.fetched / "two", "shared")
        self.assertIn("duplicate skill name", self.run_entrypoint("pi", "true", TOKENCRATE_SKILL_SETS="one,two").stderr)
        self.assertNotEqual(self.run_entrypoint("pi", "true", TOKENCRATE_PRESET="../bad").returncode, 0)
        shutil.rmtree(self.project)
        self.assertIn("project directory is not mounted", self.run_entrypoint("pi", "true").stderr)


if __name__ == "__main__":
    unittest.main()
