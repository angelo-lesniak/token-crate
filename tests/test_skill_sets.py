from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tokencrate import PROJECT_ROOT, TokenCrateError, skills
from tokencrate.names import select_sets

SKILL_SETS = PROJECT_ROOT / "config" / "skill-sets"
ALLOWED_HOSTS = SKILL_SETS / "allowed-git-hosts.txt"
SHIPPED_SETS = {"pocock-core", "skill-crate"}
REPOSITORY = "https://github.com/example/skills"


def git(path: Path, *arguments: str) -> str:
    environment = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


class SkillSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is required for skill-set tests")

    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir, True)

    def skill(self, name: str, commit: str = "a" * 40, digest: str = "b" * 64) -> skills.Skill:
        return skills.Skill(name, REPOSITORY, commit, f"skills/{name}", digest, "MIT")

    def use_checkout(self, function) -> None:
        """Replace the Git checkout that fetch() and digest_command() call."""
        self.addCleanup(setattr, skills, "checkout_subtree", skills.checkout_subtree)
        skills.checkout_subtree = function

    def make_repository(self) -> tuple[Path, str, str]:
        source = self.workdir / "source"
        (source / "skills" / "demo").mkdir(parents=True)
        (source / "skills" / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill\n---\n\nBody\n", encoding="utf-8"
        )
        (source / "skills" / "demo" / "scripts").mkdir()
        (source / "skills" / "demo" / "scripts" / "run.sh").write_text("echo hi\n", encoding="utf-8")
        git(source, "init", "-q", "-b", "main")
        git(source, "add", ".")
        git(source, "commit", "-q", "-m", "init")
        commit = git(source, "rev-parse", "HEAD")
        digest = skills.tree_digest(source / "skills" / "demo")
        return source, commit, digest

    def test_selection_rules(self):
        catalog = {"demo": object()}
        with self.assertRaisesRegex(TokenCrateError, "provide one or more"):
            select_sets(catalog, [], "skill set")
        with self.assertRaisesRegex(TokenCrateError, "all cannot be combined"):
            select_sets(catalog, ["all", "demo"], "skill set")
        with self.assertRaisesRegex(TokenCrateError, "unknown skill set: missing"):
            select_sets(catalog, ["missing"], "skill set")
        self.assertEqual(select_sets(catalog, ["demo", "demo"], "skill set"), [catalog["demo"]])

    def test_shipped_manifests_parse_with_the_allowlist(self):
        hosts = skills.load_allowed_hosts(ALLOWED_HOSTS)
        self.assertIn("github.com", hosts)

        catalog = skills.available_sets(SKILL_SETS, hosts)

        self.assertEqual(set(catalog), SHIPPED_SETS)
        for skill_set in catalog.values():
            self.assertTrue(skill_set.skills)
            for skill in skill_set.skills:
                self.assertRegex(skill.commit, r"^[0-9a-f]{40}$")
                self.assertRegex(skill.sha256, r"^[0-9a-f]{64}$")

    def test_tree_digest_is_stable_and_rejects_symlinks(self):
        root = self.workdir / "tree"
        (root / "b").mkdir(parents=True)
        (root / "b" / "x.txt").write_text("x", encoding="utf-8")
        (root / "a.txt").write_text("a", encoding="utf-8")
        first = skills.tree_digest(root)
        (root / "a.txt").write_text("a", encoding="utf-8")
        self.assertEqual(first, skills.tree_digest(root))
        (root / "a.txt").write_text("changed", encoding="utf-8")
        self.assertNotEqual(first, skills.tree_digest(root))
        try:
            os.symlink("/etc/passwd", root / "link")
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")
        with self.assertRaisesRegex(TokenCrateError, "symbolic links"):
            skills.tree_digest(root)

    def test_manifest_rejects_unpinned_or_unknown_hosts(self):
        hosts = {"github.com"}
        manifest = self.workdir / "bad.toml"
        manifest.write_text(
            'schema = 1\n[[skill]]\nname = "demo"\nrepository = "https://example.com/a/b"\ncommit = "'
            + "a" * 40
            + '"\npath = "skills/demo"\nsha256 = "'
            + "b" * 64
            + '"\nlicense = "MIT"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(TokenCrateError, "allowed-git-hosts"):
            skills.read_manifest(manifest, hosts)
        manifest.write_text(
            'schema = 1\n[[skill]]\nname = "demo"\nrepository = "https://github.com/a/b"\ncommit = "main"\n'
            'path = "skills/demo"\nsha256 = "' + "b" * 64 + '"\nlicense = "MIT"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(TokenCrateError, "full lowercase Git commit"):
            skills.read_manifest(manifest, hosts)

    def test_fetch_requires_an_existing_directory_target(self):
        skill_set = skills.SkillSet("fixture", "Fixture", (self.skill("demo"),))
        with self.assertRaisesRegex(TokenCrateError, "skills directory does not exist"):
            skills.fetch([skill_set], self.workdir / "missing", verify_only=True)
        real = self.workdir / "real"
        real.mkdir()
        link = self.workdir / "link"
        try:
            os.symlink(real, link, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")
        with self.assertRaisesRegex(TokenCrateError, "must not be a symlink"):
            skills.fetch([skill_set], link, verify_only=True)

    def test_fetch_verifies_digest_and_publishes_then_status_agrees(self):
        source, commit, digest = self.make_repository()
        repository = source.resolve().as_uri()
        skill = skills.Skill("demo", repository, commit, "skills/demo", digest, "MIT")
        skill_set = skills.SkillSet("fixture", "Fixture", (skill,))
        target = self.workdir / "skills"
        target.mkdir()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(skills.fetch([skill_set], target, verify_only=False), 0)
        self.assertIn("fetched", output.getvalue())
        self.assertTrue((target / "fixture" / "demo" / "SKILL.md").is_file())
        self.assertFalse(list(target.glob(".tokencrate-skill-*")))
        self.assertFalse(list((target / "fixture").glob(".tokencrate-skill-*")))
        self.assertEqual(skills.missing_skills(skill_set, target), [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(skills.fetch([skill_set], target, verify_only=True), 0)

        (target / "fixture" / "demo" / "SKILL.md").write_text("tampered", encoding="utf-8")
        stale = target / "fixture" / "retired"
        stale.mkdir()
        (stale / "SKILL.md").write_text("old skill")
        hidden = target / "fixture" / ".retained"
        hidden.mkdir()
        linked = target / "fixture" / "linked"
        linked.symlink_to(source)
        plain_file = target / "fixture" / "readme"
        plain_file.write_text("keep")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(skills.fetch([skill_set], target, verify_only=True), 1)
        self.assertTrue(stale.is_dir(), "status must not prune")
        self.assertIn("different-digest", output.getvalue())

        wrong = skills.Skill("demo", repository, commit, "skills/demo", "0" * 64, "MIT")
        wrong_set = skills.SkillSet("fixture", "Fixture", (wrong,))
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(TokenCrateError, "does not match the pinned"):
                skills.fetch([wrong_set], target, verify_only=False)
        self.assertEqual((target / "fixture" / "demo" / "SKILL.md").read_text(encoding="utf-8"), "tampered")
        self.assertFalse(list((target / "fixture").glob(".tokencrate-skill-*")))
        self.assertTrue(stale.is_dir(), "a failed fetch must not prune")

        # A fetch with the right pin repairs the tampered copy and drops the backup.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(skills.fetch([skill_set], target, verify_only=False), 0)
        self.assertEqual(skills.tree_digest(target / "fixture" / "demo"), digest)
        self.assertFalse((target / "fixture" / ".demo.previous").exists())
        self.assertFalse(stale.exists())
        self.assertTrue(hidden.is_dir())
        self.assertTrue(linked.is_symlink())
        self.assertTrue((source / "skills" / "demo" / "SKILL.md").is_file())
        self.assertEqual(plain_file.read_text(), "keep")

    def test_a_linked_set_directory_is_refused_without_pruning_its_target(self):
        source = self.workdir / "outside"
        (source / "retired").mkdir(parents=True)
        target = self.workdir / "skills"
        target.mkdir()
        (target / "fixture").symlink_to(source)
        skill_set = skills.SkillSet("fixture", "Fixture", (self.skill("demo"),))
        for verify_only in (True, False):
            with self.assertRaisesRegex(TokenCrateError, "must not be a symlink"):
                skills.fetch([skill_set], target, verify_only=verify_only)
            self.assertTrue((source / "retired").is_dir())

    def test_failed_first_fetch_leaves_no_set_directory(self):
        def refuse(repository, commit, subpath, workdir):
            raise TokenCrateError("fixture: checkout refused")

        self.use_checkout(refuse)
        skill_set = skills.SkillSet("fixture", "Fixture", (self.skill("demo"),))
        target = self.workdir / "skills"
        target.mkdir()

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(TokenCrateError, "checkout refused"):
                skills.fetch([skill_set], target, verify_only=False)

        self.assertFalse((target / "fixture").exists())
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(skills.missing_skills(skill_set, target), ["demo"])

    def test_missing_skills_reports_the_names_not_fetched(self):
        skill_set = skills.SkillSet("fixture", "Fixture", (self.skill("demo"), self.skill("other")))
        target = self.workdir / "skills"
        target.mkdir()
        self.assertEqual(skills.missing_skills(skill_set, target), ["demo", "other"])

        (target / "fixture" / "demo").mkdir(parents=True)
        self.assertEqual(skills.missing_skills(skill_set, target), ["other"])

        try:
            os.symlink(target / "fixture" / "demo", target / "fixture" / "other", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")
        self.assertEqual(skills.missing_skills(skill_set, target), ["other"])

        (target / "fixture" / "other").unlink()
        (target / "fixture" / "other").mkdir()
        self.assertEqual(skills.missing_skills(skill_set, target), [])

    def test_digest_command_returns_the_tree_digest(self):
        root = self.workdir / "demo"
        root.mkdir()
        (root / "SKILL.md").write_text("---\nname: demo\ndescription: Demo skill\n---\n\nBody\n", encoding="utf-8")
        seen: list[tuple[str, str, str]] = []

        def local_checkout(repository, commit, subpath, workdir):
            seen.append((repository, commit, subpath))
            return root

        self.use_checkout(local_checkout)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            digest = skills.digest_command(REPOSITORY + ".git", "c" * 40, "skills/demo", {"github.com"})

        self.assertEqual(digest, skills.tree_digest(root))
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(seen, [(REPOSITORY, "c" * 40, "skills/demo")])
        with self.assertRaisesRegex(TokenCrateError, "full lowercase Git commit"):
            skills.digest_command(REPOSITORY, "main", "skills/demo", {"github.com"})
        with self.assertRaisesRegex(TokenCrateError, "allowed-git-hosts"):
            skills.digest_command("https://example.com/a/b", "c" * 40, "skills/demo", {"github.com"})

    def test_frontmatter_name_must_match_directory(self):
        root = self.workdir / "wrong"
        root.mkdir()
        (root / "SKILL.md").write_text("---\nname: other\ndescription: x\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(TokenCrateError, "must equal the directory name"):
            skills.validate_skill_document(root, "wrong")

    def test_shipped_repository_skills_have_valid_frontmatter(self):
        for skill_dir in sorted((PROJECT_ROOT / "config" / "skills").iterdir()):
            if skill_dir.is_dir():
                skills.validate_skill_document(skill_dir, skill_dir.name)
                skills.tree_digest(skill_dir)


if __name__ == "__main__":
    unittest.main()
