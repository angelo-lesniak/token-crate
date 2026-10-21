"""Settings: precedence, storage paths, the token, and the subprocess environment."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import SOURCE_ROOT
from tokencrate import TokenCrateError, agentsets, env, skills
from tokencrate.env import PIN_KEYS


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        # The example file is the defaults layer; a checkout always has it.
        (self.tmp / ".env.example").write_text((SOURCE_ROOT / ".env.example").read_text())

    def write_env(self, text: str) -> None:
        (self.tmp / ".env").write_text(text)
        (self.tmp / ".env").chmod(0o600)

    def test_shell_environment_wins_over_env_file_which_wins_over_defaults(self) -> None:
        self.write_env("LLM_PORT=4210\nLLM_DEFAULT_PRESET=from-file\n")
        settings = env.load(self.tmp, {"LLM_PORT": "4300"})
        self.assertEqual(settings.port, "4300")
        self.assertEqual(settings.default_preset, "from-file")
        self.assertEqual(settings.service_url, "http://127.0.0.1:4300")
        self.assertEqual(settings.project_name, "tokencrate")

    def test_the_example_file_is_the_defaults_layer(self) -> None:
        # Deleting a line from .env changes nothing: the value comes from
        # .env.example, and a checkout without that file is refused.
        settings = env.load(self.tmp, {})
        self.assertEqual(settings.default_preset, "qwen3.8-27b-q4-mtp")
        self.assertEqual(settings.get("LLM_SKILL_SETS"), "pocock-core,skill-crate")
        self.assertEqual(settings.get("CONTAINER_ENGINE"), "")
        self.assertTrue(settings.gpu)
        self.assertNotIn("HF_TOKEN", settings.defaults)
        (self.tmp / ".env.example").unlink()
        with self.assertRaisesRegex(TokenCrateError, "no settings reference"):
            env.load(self.tmp, {})

    def test_the_default_preset_and_agent_sets_are_shipped_files(self) -> None:
        settings = env.load(self.tmp, {})
        preset = SOURCE_ROOT / "config" / "presets" / f"{settings.default_preset}.toml"
        self.assertTrue(preset.is_file(), f".env.example must default LLM_DEFAULT_PRESET to a shipped preset: {preset}")
        for entry in agentsets.select(SOURCE_ROOT, settings.get("LLM_AGENT_SETS")):
            self.assertEqual(entry.directory.parent, SOURCE_ROOT / "config" / "agent-sets", entry.source)

    def test_every_wrapper_default_reaches_subprocesses_with_its_effective_value(self) -> None:
        # An omitted line means the same to the wrapper and to Compose: the
        # effective value is exported, so no Compose fallback applies (otherwise
        # an omitted LLM_SKILL_SETS would make pre-flight require the default
        # sets while the container mounts none).
        self.write_env("LLM_PORT=4210\n")
        subprocess_env = env.load(self.tmp, {}).subprocess_env()
        self.assertEqual(subprocess_env["LLM_SKILL_SETS"], "pocock-core,skill-crate")
        self.assertEqual(subprocess_env["LLM_PORT"], "4210")
        for key, default in env.parse_env_file(SOURCE_ROOT / ".env.example").items():
            if key not in env.PATH_KEYS and key != "LLM_PORT":
                self.assertEqual(subprocess_env[key], default, key)
        self.write_env("LLM_SKILL_SETS=\n")
        self.assertEqual(env.load(self.tmp, {}).subprocess_env()["LLM_SKILL_SETS"], "")

    def test_container_identity_is_the_calling_user_and_never_a_setting(self) -> None:
        self.write_env("HOST_UID=1\nHOST_GID=1\n")
        with contextlib.redirect_stderr(io.StringIO()):
            subprocess_env = env.load(self.tmp, {"HOST_UID": "2"}).subprocess_env()
        self.assertEqual(subprocess_env["HOST_UID"], str(os.getuid()))
        self.assertEqual(subprocess_env["HOST_GID"], str(os.getgid()))

    def test_relative_storage_paths_are_anchored_to_the_repository_root(self) -> None:
        self.write_env("LLM_MODELS_DIR=./data/models\nLLM_AGENTS_DIR=data/agents\nLLM_SKILLS_DIR=/abs/skills\n")
        settings = env.load(self.tmp, {})
        self.assertEqual(settings.models_dir, self.tmp / "data" / "models")
        self.assertEqual(settings.agents_dir, self.tmp / "data" / "agents")
        self.assertEqual(settings.skills_dir, Path("/abs/skills"))
        self.assertEqual(settings.local_skills_dir, self.tmp / "local" / "skills")
        self.assertEqual(settings.subprocess_env()["LLM_MODELS_DIR"], str(self.tmp / "data" / "models"))

    def test_the_token_is_captured_and_never_reaches_a_subprocess_environment(self) -> None:
        # Read from the file or the shell into `hf_token`, and out of
        # everything exported; the shell wins, and an empty shell value
        # means "no token".
        self.write_env("HF_TOKEN=file-token\n")
        from_file = env.load(self.tmp, {})
        self.assertEqual(from_file.hf_token, "file-token")
        from_shell = env.load(self.tmp, {"HF_TOKEN": "shell-token"})
        self.assertEqual(from_shell.hf_token, "shell-token")
        for settings in (from_file, from_shell):
            for view in (settings.subprocess_env(), settings.values, settings.environ, settings.file_values):
                self.assertNotIn("HF_TOKEN", view)
        self.assertIsNone(env.load(self.tmp, {"HF_TOKEN": ""}).hf_token)

    def test_provider_keys_are_not_settings(self) -> None:
        # A key left in .env is an unknown key: reported, ignored, and not
        # exported. The keys file is a path setting like the storage ones.
        self.write_env("ANTHROPIC_API_KEY=sk-ant\nLLM_CLOUD_KEYS_FILE=keys.env\n")
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            settings = env.load(self.tmp, {})
        self.assertIn("ignored: ANTHROPIC_API_KEY", stderr.getvalue())
        self.assertNotIn("ANTHROPIC_API_KEY", settings.subprocess_env())
        self.assertEqual(settings.cloud_keys_file, self.tmp / "keys.env")
        self.write_env("")
        self.assertEqual(env.load(self.tmp, {}).cloud_keys_file, self.tmp / "local" / "cloud-keys.env")

    def test_a_duplicate_key_and_a_byte_order_mark_are_handled(self) -> None:
        self.write_env("LLM_PORT=4210\nLLM_PORT=4211\n")
        with self.assertRaisesRegex(TokenCrateError, r"\.env:2: LLM_PORT is set twice"):
            env.load(self.tmp, {})
        (self.tmp / ".env").write_bytes(b"\xef\xbb\xbfLLM_PORT=4212\n")
        self.assertEqual(env.load(self.tmp, {}).port, "4212")

    def test_the_project_name_is_what_compose_keeps_of_it(self) -> None:
        # podman-compose drops every other character silently, which would
        # name another project's containers and networks.
        for name in ("Token.Crate", "-x", "a b", ""):
            with self.subTest(name=name):
                if name:
                    with self.assertRaisesRegex(TokenCrateError, "COMPOSE_PROJECT_NAME must be"):
                        env.load(self.tmp, {"COMPOSE_PROJECT_NAME": name})
                else:
                    self.assertEqual(env.load(self.tmp, {"COMPOSE_PROJECT_NAME": ""}).project_name, "tokencrate")
        self.assertEqual(env.load(self.tmp, {"COMPOSE_PROJECT_NAME": "crate_2-b"}).project_name, "crate_2-b")

    def test_an_empty_path_setting_is_refused_not_defaulted(self) -> None:
        # Every Compose setting is required; the wrapper reads these five
        # itself, so it is the one that names the variable and the remedy.
        for key in env.PATH_KEYS:
            with self.subTest(key=key):
                with self.assertRaisesRegex(TokenCrateError, f"^{key} must not be empty; omit the line to take"):
                    env.load(self.tmp, {key: ""})
        self.write_env("LLM_MODELS_DIR=\n")
        with self.assertRaisesRegex(TokenCrateError, r"^LLM_MODELS_DIR must not be empty; .*\(\./data/models\)$"):
            env.load(self.tmp, {})

    def test_a_port_is_used_as_written_so_it_has_no_leading_zero(self) -> None:
        # Compose publishes the value as written and the forwarder's allowed
        # hosts compare it as text, so "04210" is refused, not normalised.
        for value in ("0", "04210", "65536", "4210 ", "x"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TokenCrateError, "^LLM_PORT requires a port from 1 to 65535$"):
                    env.validate_port(value, "LLM_PORT")
        self.assertEqual(env.load(self.tmp, {"LLM_PORT": "65535"}).port, "65535")

    def test_storage_paths_are_real_paths_that_do_not_contain_the_checkout(self) -> None:
        # A storage directory that is or contains the checkout would mount
        # .env into every agent container; a linked one is resolved once
        # here, so the mounts and the link checks below it see one path.
        for value in (str(self.tmp), str(self.tmp.parent), "."):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TokenCrateError, "must not be or contain the TokenCrate checkout"):
                    env.load(self.tmp, {"LLM_LOCAL_SKILLS_DIR": value})
        real = self.tmp / "real-agents"
        real.mkdir()
        os.symlink(real, self.tmp / "linked-agents")
        self.assertEqual(env.load(self.tmp, {"LLM_AGENTS_DIR": str(self.tmp / "linked-agents")}).agents_dir, real)

    def test_pins_cannot_be_overridden_from_the_shell_or_env_file(self) -> None:
        self.write_env("PI_VERSION=from-file\n")
        with contextlib.redirect_stderr(io.StringIO()):
            settings = env.load(self.tmp, {"LLAMA_CPP_TAG": "from-shell"})
        subprocess_env = settings.subprocess_env()
        for key in PIN_KEYS:
            self.assertNotIn(key, subprocess_env)

    def test_the_pinned_llama_build_is_the_tag_suffix(self) -> None:
        self.assertEqual(env.pinned_llama_build({"LLAMA_CPP_TAG": "server-cuda13-b10920"}), 10920)
        # The shipped tag must carry a build number; the number itself moves
        # with every upgrade.
        shipped = env.load_pins(SOURCE_ROOT / "pins.env")["LLAMA_CPP_TAG"]
        self.assertGreater(env.pinned_llama_build({"LLAMA_CPP_TAG": shipped}), 0)
        for tag in ("server-cuda13", "server-cuda13-b0", "b10920-cuda13", ""):
            with self.assertRaisesRegex(TokenCrateError, "must end in the llama.cpp build number"):
                env.pinned_llama_build({"LLAMA_CPP_TAG": tag})
        # load_pins refuses a tag without the suffix, so the renderer's
        # comparison and the Dockerfile's assertion read the same number.
        pins = (SOURCE_ROOT / "pins.env").read_text().replace(shipped, "server-cuda13-latest")
        (self.tmp / "pins.env").write_text(pins)
        with self.assertRaisesRegex(TokenCrateError, "must end in the llama.cpp build number"):
            env.load_pins(self.tmp / "pins.env")

    def test_env_file_values_reach_subprocesses_and_quotes_are_stripped(self) -> None:
        self.write_env("GIT_AUTHOR_NAME=\"Ada Lovelace\"\nexport LLM_TMPFS_SIZE='3g'\n# comment\n\n")
        settings = env.load(self.tmp, {"PATH": "/usr/bin"})
        subprocess_env = settings.subprocess_env(EXTRA="1")
        self.assertEqual(subprocess_env["GIT_AUTHOR_NAME"], "Ada Lovelace")
        self.assertEqual(subprocess_env["LLM_TMPFS_SIZE"], "3g")
        self.assertEqual(subprocess_env["PATH"], "/usr/bin")
        self.assertEqual(subprocess_env["EXTRA"], "1")

    def test_malformed_env_line_is_reported_with_its_number(self) -> None:
        self.write_env("LLM_PORT=1\nnot a setting\n")
        with self.assertRaisesRegex(TokenCrateError, r"\.env:2: expected KEY=VALUE"):
            env.load(self.tmp, {})

    def test_the_env_file_must_be_the_users_and_readable_by_the_user_alone(self) -> None:
        # It may hold the token; `init` creates it with mode 0600, a copy by
        # hand may not. The remedy is the same as for the cloud keys file.
        self.write_env("LLM_PORT=4210\n")
        path = self.tmp / ".env"
        for mode in (0o644, 0o640, 0o604):
            path.chmod(mode)
            with self.assertRaisesRegex(
                TokenCrateError, f"^{path} must be readable by your user only; run: chmod 600 {path}$"
            ):
                env.load(self.tmp, {})
        path.chmod(0o400)
        self.assertEqual(env.load(self.tmp, {}).port, "4210")
        other = os.getuid() + 1
        with mock.patch("tokencrate.env.os.getuid", return_value=other):
            with self.assertRaisesRegex(TokenCrateError, f"^{path} must be owned by your user \\(uid {other}\\)"):
                env.load(self.tmp, {})

    def test_the_wrappers_switches_accept_eight_words_and_refuse_the_rest(self) -> None:
        for word, expected in (("1", True), ("YES", True), (" on ", True), ("0", False), ("No", False), ("off", False)):
            self.assertEqual(env.load(self.tmp, {"LLM_GPU": word}).gpu, expected, word)
            self.assertEqual(env.load(self.tmp, {"LLM_DASHBOARD": word}).dashboard, expected, word)
        for key in env.BOOLEAN_KEYS:
            with self.assertRaisesRegex(
                TokenCrateError, f"^{key} must be one of 1/true/yes/on or 0/false/no/off, not 'ture'$"
            ):
                env.load(self.tmp, {key: "ture"})
        # Compose-only switches stay text: nothing parses them here.
        self.assertEqual(env.load(self.tmp, {"RESTART_POLICY": "ture"}).get("RESTART_POLICY"), "ture")

    def test_the_storage_map_names_every_path_the_rules_apply_to(self) -> None:
        settings = env.load(self.tmp, {"LLM_CLOUD_KEYS_FILE": "/keys/cloud.env"})
        by_label = {place.label: place for place in settings.storage}
        self.assertEqual(
            {place.key for place in settings.storage if place.key},
            {"LLM_MODELS_DIR", "LLM_AGENTS_DIR", "LLM_SKILLS_DIR", "LLM_LOCAL_SKILLS_DIR", "LLM_CLOUD_KEYS_FILE"},
        )
        # What agent containers mount must not contain the checkout, is
        # protected from projects and from the keys file, and is what
        # `doctor` and `init` look after; private skills are read-only.
        mounted = [place for place in settings.storage if place.mounted]
        self.assertEqual(
            [place.label for place in mounted if place.writable],
            [
                "the models directory",
                "the agents directory",
                "the skills directory",
            ],
        )
        self.assertFalse(by_label["the private skills directory"].writable)
        for place in mounted:
            self.assertTrue(place.created_by_init and place.refuses_projects and place.refuses_keys, place.label)
        # The checkout and the keys file are refused as projects; the build
        # contexts refuse the keys file; nothing mounts any of them.
        self.assertEqual(by_label["the TokenCrate checkout"].path, self.tmp.resolve())
        self.assertTrue(by_label["the TokenCrate checkout"].refuses_projects)
        self.assertFalse(by_label["the TokenCrate checkout"].refuses_keys, "the default keys file lies below local/")
        self.assertEqual(by_label["the cloud keys file"].path, Path("/keys/cloud.env"))
        self.assertTrue(by_label["the cloud keys file"].refuses_projects)
        for label in (
            "the shipped configuration",
            "the private agent sets",
            "the services directory",
            "the rendered pi images",
        ):
            self.assertTrue(by_label[label].refuses_keys and not by_label[label].mounted, label)
        self.assertEqual(
            {
                place.path.relative_to(self.tmp.resolve())
                for place in settings.storage
                if not place.mounted and not place.key
            },
            {
                Path(),
                Path("config"),
                Path("local/agent-sets"),
                Path("services"),
                Path("build/agents/pi"),
                Path("reports"),
                Path("data/dashboard/victoria"),
            },
        )

    def test_symlinked_env_file_is_refused(self) -> None:
        (self.tmp / "real.env").write_text("LLM_PORT=1\n")
        os.symlink(self.tmp / "real.env", self.tmp / ".env")
        with self.assertRaisesRegex(TokenCrateError, "refusing symbolic link"):
            env.load(self.tmp, {})

    def test_the_token_leaves_this_process_so_no_subprocess_inherits_it(self) -> None:
        self.write_env("LLM_PORT=4208\n")
        os.environ["HF_TOKEN"] = "shell-token"
        self.addCleanup(os.environ.pop, "HF_TOKEN", None)
        settings = env.load(self.tmp)
        self.assertEqual(settings.hf_token, "shell-token")
        self.assertNotIn("HF_TOKEN", os.environ)
        # git runs for `skills fetch`; it inherits this process's environment.
        self.assertNotIn("HF_TOKEN", skills.git_environment())

    def test_values_that_expect_shell_expansion_are_refused(self) -> None:
        for value in ("$HOME/models", "~/models", "4208 # the port"):
            self.write_env(f"LLM_MODELS_DIR={value}\n")
            with self.assertRaisesRegex(TokenCrateError, "used literally"):
                env.load(self.tmp, {})
        self.write_env('GIT_AUTHOR_NAME="Ada # Lovelace"\n')
        self.assertEqual(env.load(self.tmp, {}).subprocess_env()["GIT_AUTHOR_NAME"], "Ada # Lovelace")

    def test_env_keys_missing_from_the_example_file_are_reported(self) -> None:
        # A key that nothing reads would otherwise be silent; a commented-out
        # key of the example (HF_TOKEN) counts as listed.
        self.write_env("LLM_PORT=4210\nHF_TOKEN=secret\nLLM_BIND_ADDRESS=0.0.0.0\nLLM_ALLOW_REMOTE=true\n")
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            env.load(self.tmp, {})
        self.assertEqual(
            stderr.getvalue(),
            "TokenCrate: .env: keys not listed in .env.example are ignored: LLM_ALLOW_REMOTE, LLM_BIND_ADDRESS\n",
        )


if __name__ == "__main__":
    unittest.main()
