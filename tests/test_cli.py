"""The promises a user can observe from bin/tokencrate without a container
engine, routed through the fake engine in tests/fixtures/engine-bin."""

from __future__ import annotations

import json
import re
import signal
import tomllib
import unittest

from tests.support import SOURCE_ROOT, Scratch, shipped
from tokencrate import cli, env, presets

# The build-gate messages name the pinned build, which moves with every
# llama.cpp upgrade; read it from the file the scratch checkout copies.
PINNED_BUILD = f"b{env.pinned_llama_build(env.load_pins(SOURCE_ROOT / 'pins.env'))}"
VALIDATED = f"Validated {len(shipped('presets'))} preset(s) against {len(shipped('model-sets'))} model set(s)."


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def expect_failure(self, expected: str, *arguments: str, **overrides: str) -> None:
        result = self.scratch.run(*arguments, **overrides)
        self.assertNotEqual(result.returncode, 0, f"unexpectedly succeeded: {arguments}\n{result.stdout}")
        self.assertIn(expected, result.stdout + result.stderr, f"{arguments}\n{result.stdout}{result.stderr}")

    def succeed(self, *arguments: str, **overrides: str) -> str:
        result = self.scratch.run(*arguments, **overrides)
        self.assertEqual(result.returncode, 0, f"{arguments} failed:\n{result.stdout}{result.stderr}")
        return result.stdout + result.stderr

    def test_help_pins_and_listings_work_without_the_engine(self) -> None:
        self.expect_failure("--sets applies to smoke --agent", "smoke", "--sets", "missing", PATH="/usr/bin:/bin")
        self.assertIn("Usage:", self.succeed("--help"))
        self.assertIn("Usage:", self.succeed())
        self.assertIn("LLAMA_CPP_TAG=", self.succeed("pins", PATH="/usr/bin:/bin"))
        model_sets = self.succeed("models", "list", PATH="/usr/bin:/bin")
        self.assertIn("qwen3.8-27b-ud-q4-k-xl", model_sets)
        self.assertIn("gpt-oss-20b-mxfp4", model_sets)
        # One line per shipped preset: name, model set, requirements, and
        # for a gated one its wait; the values are the preset files' own.
        preset_list = self.succeed("presets", "list", PATH="/usr/bin:/bin")
        for preset in presets.load(self.scratch.root / "config", PINNED_BUILD).presets:
            self.assertIn(f"{preset.name} [{preset.model_set}] needs ", preset_list)
        self.assertIn(
            f"waits for an unreleased llama.cpp build (pinned: {PINNED_BUILD}) - GLM-5.3-Flash UD-Q2_K_XL",
            preset_list,
        )
        skill_sets = self.succeed("skills", "list", PATH="/usr/bin:/bin")
        self.assertIn("pocock-core", skill_sets)
        self.assertIn("skill-crate", skill_sets)

    def test_shim_runs_the_package_from_a_project_directory(self) -> None:
        result = self.scratch.run_shim("pins")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PI_VERSION=", result.stdout)

    def test_shim_ignores_a_tokencrate_package_inside_the_project(self) -> None:
        # A regular package (with __init__.py) in the caller's directory would
        # shadow the real one on a default module path; -P keeps it off.
        decoy = self.scratch.project / "tokencrate"
        decoy.mkdir()
        (decoy / "__init__.py").write_text("")
        (decoy / "__main__.py").write_text('import sys\nprint("HIJACKED")\nsys.exit(99)\n')
        result = self.scratch.run_shim("pins")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PI_VERSION=", result.stdout)
        self.assertNotIn("HIJACKED", result.stdout + result.stderr)

    def test_doctor_reads_the_preset_requirements_from_the_preset_file(self) -> None:
        output = self.succeed("doctor", "--preset", "qwen3.8-27b-q4", CONTAINER_ENGINE="podman", LLM_GPU="false")
        self.assertIn("checking host requirements of preset qwen3.8-27b-q4", output)
        self.assertIn("LLM_GPU=false", output)
        self.assertIn("podman version 6.1.0-fake", output)
        self.assertIn("Doctor completed with 0 failure(s)", output)

    def gate_the_gpt_oss_set(self) -> str:
        """Make the shipped gpt-oss set require an unreleased build in the scratch checkout."""
        manifest = self.scratch.root / "config" / "model-sets" / "gpt-oss-20b-mxfp4.toml"
        manifest.write_text(manifest.read_text() + '\n[requires]\nllama_build = "unreleased"\n')
        return f"waits for an unreleased llama.cpp build (pinned: {PINNED_BUILD})"

    def test_a_preset_behind_the_build_gate_is_marked_everywhere_and_never_the_default(self) -> None:
        wait = self.gate_the_gpt_oss_set()
        listing = self.succeed("presets", "list", PATH="/usr/bin:/bin")
        self.assertRegex(
            listing, rf"gpt-oss-20b-fast \[gpt-oss-20b-mxfp4\] needs [0-9]+ GiB GPU memory; {re.escape(wait)} - "
        )
        self.assertRegex(listing, r"qwen3.8-27b-q4 \[qwen3.8-27b-ud-q4-k-xl\] needs [0-9]+ GiB GPU memory - ")
        rendered = self.succeed("presets", "render", PATH="/usr/bin:/bin")
        self.assertIn(f"gpt-oss-20b-fast: {wait}\n", rendered)
        self.assertIn(VALIDATED, rendered)
        checked = self.succeed("doctor", "--preset", "gpt-oss-20b-fast", CONTAINER_ENGINE="podman", LLM_GPU="false")
        self.assertIn(f"[warn] preset gpt-oss-20b-fast {wait}; up leaves it out of the router", checked)
        self.assertIn("Doctor completed with 0 failure(s) and 2 warning(s).", checked)
        # up refuses the gated default before the stack starts, and before
        # the download a model-set argument asks for.
        for arguments in (("up",), ("up", "--model-set", "gpt-oss-20b-mxfp4")):
            refused = self.scratch.run(*arguments, LLM_DEFAULT_PRESET="gpt-oss-20b-fast", LLM_GPU="false")
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertIn(f"preset gpt-oss-20b-fast {wait}; bash bin/tokencrate presets list", refused.stderr)
            self.assertNotIn("Downloading", refused.stdout + refused.stderr)
            self.assertNotIn("huggingface.co", refused.stdout + refused.stderr)
        # A session or a probe on the waiting preset names the wait, not a fetch.
        named = f"preset gpt-oss-20b-fast {wait}; bash bin/tokencrate presets list shows the loadable ones"
        running = {"FAKE_ENGINE_LLAMA_RUNNING": "true"}
        self.expect_failure(named, "smoke", "--preset", "gpt-oss-20b-fast", **running)
        self.expect_failure(named, "bench", "--preset", "gpt-oss-20b-fast", **running)
        self.expect_failure(named, "smoke", "--agent", "pi", "--preset", "gpt-oss-20b-fast", **running)

    def test_render_validates_without_an_engine_and_writes_nothing(self) -> None:
        output = self.succeed("presets", "render", PATH="/usr/bin:/bin")
        self.assertIn(VALIDATED, output)
        self.assertFalse((self.scratch.root / "build").exists())
        self.expect_failure("unknown option for render: --check", "presets", "render", "--check")

    def test_up_runs_the_host_checks_first_and_stops_on_a_failure(self) -> None:
        # The scratch host has no GPU: with the GPU wanted, doctor fails and
        # up stops before the download and the stack start.
        result = self.scratch.run("up", LLM_DEFAULT_PRESET="gpt-oss-20b-fast")
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[fail] nvidia-smi found no NVIDIA GPU", output)
        self.assertIn("fix the [fail] lines above before starting", output)
        self.assertNotIn("build llama", output)
        self.assertNotIn("is not loadable", output)
        # A .env that names a preset that does not exist fails before the
        # download, naming the preset.
        self.expect_failure(
            "unknown preset: no-such-preset", "up", LLM_DEFAULT_PRESET="no-such-preset", LLM_GPU="false"
        )

    def test_up_refuses_a_default_preset_without_files_and_traces_the_stack_start(self) -> None:
        self.expect_failure("is not loadable", "up", LLM_DEFAULT_PRESET="gpt-oss-20b-fast", LLM_GPU="false")
        # Nothing listens on the scratch port, so the readiness wait times out
        # after the stack start was traced through the fake engine.
        result = self.scratch.run(
            "up", "--timeout", "1", HF_TOKEN="secret-fixture", FAKE_ENGINE_LLAMA_RUNNING="true", LLM_GPU="false"
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Doctor completed with 0 failure(s)", output)
        self.assertIn("build llama", output)
        # A network created without the Docker overlay keeps its gateway;
        # up refuses until down has removed it.
        plain = json.dumps(
            {
                "IPAM": {"Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]},
                "Internal": True,
                "Labels": {"com.docker.compose.project": "tokencrate"},
            }
        )
        refused = self.scratch.run("up", FAKE_ENGINE_LLAMA_RUNNING="true", FAKE_ENGINE_NETWORK=plain, LLM_GPU="false")
        self.assertIn("the agents network keeps a host gateway address (172.18.0.1)", refused.stderr)
        # A network that is not internal, or not this project's, is refused on both engines.
        for engine_name in ("docker", "podman"):
            for document, problem in (
                (
                    '{"subnets": [], "internal": false, "labels": {"com.docker.compose.project": "tokencrate"}}',
                    "is not internal",
                ),
                ('{"subnets": [], "internal": true}', "was not created by this Compose project"),
            ):
                with self.subTest(engine=engine_name, problem=problem):
                    self.expect_failure(
                        f"the agents network {problem}",
                        "up",
                        CONTAINER_ENGINE=engine_name,
                        FAKE_ENGINE_LLAMA_RUNNING="true",
                        FAKE_ENGINE_NETWORK=document,
                        LLM_GPU="false",
                    )
        # Refused before the container starts.
        self.assertNotIn("up --no-build --detach llama", refused.stdout)
        self.expect_failure(
            "the ui network keeps a host gateway address (172.18.0.1)",
            "up",
            FAKE_ENGINE_LLAMA_RUNNING="true",
            FAKE_ENGINE_NETWORK_UI=plain,
            LLM_GPU="false",
        )
        self.assertIn("up --no-build --detach llama", output)
        self.assertNotIn("secret-fixture", output)
        self.assertRegex(output, r"sha=[0-9a-f]{64}")
        self.assertIn("did not become ready within 1s", output)
        self.expect_failure(
            "container is exited before it was ready",
            "up",
            FAKE_ENGINE_LLAMA_RUNNING="true",
            FAKE_ENGINE_STATE="exited",
            LLM_GPU="false",
        )

    def test_agent_refuses_dangerous_or_unprepared_sessions(self) -> None:
        project = str(self.scratch.project)
        self.scratch.render_fixture("qwen3.8-27b-q4")
        # The project rules are tested in tests/test_agents.py; one case here
        # proves the refusal precedes the pre-flight and the engine.
        self.expect_failure(
            "refusing to mount the root filesystem", "agent", "pi", "--preset", "qwen3.8-27b-q4", "--dir", "/"
        )
        self.expect_failure("no preset selected", "agent", "pi", "--dir", project)
        self.expect_failure("unsupported agent", "agent", "claude")
        self.expect_failure(
            "is not rendered as loadable", "agent", "pi", "--preset", "qwen3.8-27b-q4-mtp", "--dir", project
        )
        self.expect_failure("is not running", "agent", "pi", "--preset", "qwen3.8-27b-q4", "--dir", project)
        for command in (
            ("agent", "pi", "--dir", project),
            ("ui", "pi-web", "--dir", project),
            ("smoke", "--agent", "pi"),
        ):
            for digest in ("", "stale-digest"):
                with self.subTest(command=command, digest=digest):
                    self.expect_failure(
                        "running llama configuration differs",
                        *command,
                        "--preset",
                        "qwen3.8-27b-q4",
                        FAKE_ENGINE_LLAMA_RUNNING="true",
                        FAKE_ENGINE_CONFIG_SHA256=digest,
                    )
        # `up` is not the command that puts an agent on the agents network:
        # every session checks the gateway too, not `up` alone.
        self.expect_failure(
            "the agents network keeps a host gateway address (172.18.0.1)",
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            FAKE_ENGINE_LLAMA_RUNNING="true",
            FAKE_ENGINE_NETWORK=json.dumps(
                {
                    "IPAM": {"Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]},
                    "Internal": True,
                    "Labels": {"com.docker.compose.project": "tokencrate"},
                }
            ),
        )
        self.expect_failure(
            "skill set pocock-core is not fetched",
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            LLM_SKILL_SETS="pocock-core",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        # A set directory with one of seventeen skills present is incomplete.
        (self.scratch.storage / "skills" / "pocock-core" / "tdd").mkdir(parents=True)
        self.expect_failure(
            "skill set pocock-core is incomplete (missing: code-review",
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            LLM_SKILL_SETS="pocock-core",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.expect_failure(
            "--preset may be given once with agent",
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--preset",
            "qwen3.8-27b-q4",
        )

    def test_agent_session_joins_the_internal_network_unless_egress_is_requested(self) -> None:
        project = str(self.scratch.project)
        self.scratch.render_fixture("qwen3.8-27b-q4")
        session = self.succeed(
            "agent",
            "omp",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            "--egress",
            "--",
            "--help",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.assertIn("compose.agent-egress.yaml", session)
        self.assertIn("internet access (egress enabled)", session)
        self.assertIn(f"project={project}", session)
        self.assertRegex(session, r"run --rm --name tokencrate-agent-[0-9a-f]{12} agent-omp omp --help")
        # A pi session renders the selected agent sets first and tags the
        # image with the selection; --sets overrides LLM_AGENT_SETS.
        rendered = self.succeed(
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--sets",
            "debug",
            "--dir",
            project,
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.assertIn("Agent sets: debug (image tag suffix ", rendered)
        [render_dir] = (self.scratch.root / "build" / "agents" / "pi").iterdir()
        self.assertIn("/opt/tokencrate/sets/debug/piex-dap", (render_dir / "pi-packages.txt").read_text())
        self.expect_failure(
            "--sets applies to pi only",
            "agent",
            "omp",
            "--preset",
            "qwen3.8-27b-q4",
            "--sets",
            "",
            "--dir",
            project,
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.expect_failure(
            "unknown agent set: nope",
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--sets",
            "nope",
            "--dir",
            project,
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.expect_failure("--sets is only valid with agent", "bench", "--sets", "debug")
        listing = self.succeed("agent-sets", "list")
        self.assertIn("coding - ", listing)
        self.assertIn("odin - ", listing)
        plain = self.succeed(
            "agent", "pi", "--preset", "qwen3.8-27b-q4", "--dir", project, FAKE_ENGINE_LLAMA_RUNNING="true"
        )
        self.assertNotIn("compose.agent-egress.yaml", plain)
        self.assertIn("preset=qwen3.8-27b-q4", plain)
        self.assertIn(f"home={self.scratch.storage / 'agents' / 'pi' / 'project-'}", plain)
        # The skill sets pre-flight checked are the ones the container mounts:
        # the value reaches the engine even when no setting names it.
        self.assertIn("skill_sets= ", plain)
        for manifest in (self.scratch.root / "config" / "skill-sets").glob("*.toml"):
            for skill in tomllib.loads(manifest.read_text())["skill"]:
                (self.scratch.storage / "skills" / manifest.stem / skill["name"]).mkdir(parents=True)
        omitted = self.succeed(
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            FAKE_ENGINE_LLAMA_RUNNING="true",
            LLM_SKILL_SETS=None,
        )
        self.assertIn("skill_sets=pocock-core,skill-crate ", omitted)

    def test_ui_starts_the_ui_set_detached_behind_the_forwarder(self) -> None:
        project = str(self.scratch.project)
        self.scratch.render_fixture("qwen3.8-27b-q4")
        common = {
            "FAKE_ENGINE_LLAMA_RUNNING": "true",
            "LLM_UI_PORT_PI_WEB": str(self.scratch.ui_port),
            "LLM_UI_PORT_PASEO": str(self.scratch.ui_port),
            "FAKE_ENGINE_UI_SET": "pi-web",
            "FAKE_ENGINE_UI_PORT": str(self.scratch.ui_port),
        }
        self.expect_failure("is not a UI set", "ui", "coding", "--preset", "qwen3.8-27b-q4", "--dir", project, **common)
        self.expect_failure(
            "unknown agent set: nope", "ui", "nope", "--preset", "qwen3.8-27b-q4", "--dir", project, **common
        )
        self.expect_failure("unsafe agent set name", "ui", "../x", **common)
        self.expect_failure("no preset selected", "ui", "pi-web", "--dir", project, **common)
        # Nothing answers on the UI port and the container is reported as
        # exited: the start fails with the logs hint instead of waiting.
        self.expect_failure(
            "the container tokencrate-ui-pi-web is exited before it answered",
            "ui",
            "pi-web",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            project,
            FAKE_ENGINE_STATE="exited",
            **common,
        )
        with self.scratch.ui_listener():
            started = self.succeed("ui", "pi-web", "--preset", "qwen3.8-27b-q4", "--dir", project, **common)
        # The UI set is appended to LLM_AGENT_SETS, the image is built for
        # that selection, and the UI and its forwarder start detached under
        # their fixed names in the ui profile; without a flag, never under
        # the egress overlay.
        self.assertIn("Agent sets: coding, pi-web (image tag suffix ", started)
        self.assertIn("--profile ui --env-file pins.env build agent-ui", started)
        self.assertIn(
            "--profile ui --env-file pins.env run --detach --no-deps -T --name tokencrate-ui-pi-web agent-ui", started
        )
        self.assertIn(
            "--profile ui --env-file pins.env run --detach --no-deps -T --service-ports --name "
            "tokencrate-ui-forward-pi-web ui-forward",
            started,
        )
        self.assertNotIn("compose.agent-egress.yaml", started)
        self.assertNotIn("internet access", started)
        self.assertIn(f"pi-web is ready at http://127.0.0.1:{self.scratch.ui_port}/ for {project}", started)
        self.assertIn("bash bin/tokencrate ui stop", started)
        [render_dir] = (self.scratch.root / "build" / "agents" / "pi").iterdir()
        self.assertIn("agent set pi-web", (render_dir / "Dockerfile").read_text())
        with self.scratch.ui_listener():
            paseo = self.succeed(
                "ui",
                "paseo",
                "--preset",
                "qwen3.8-27b-q4",
                "--sets",
                "paseo",
                "--dir",
                project,
                **{**common, "FAKE_ENGINE_UI_SET": "paseo"},
            )
        self.assertIn("Agent sets: paseo (image tag suffix ", paseo)
        # --egress puts the UI container alone under the overlay.
        with self.scratch.ui_listener():
            egress = self.succeed("ui", "pi-web", "--preset", "qwen3.8-27b-q4", "--dir", project, "--egress", **common)
        ui_run, forward_run = (line for line in egress.splitlines() if " run --detach " in line)
        self.assertIn("--file compose.agent-egress.yaml --profile ui", ui_run)
        self.assertNotIn("compose.agent-egress.yaml", forward_run)
        self.assertIn("internet access (egress enabled)", egress)
        # --cloud mounts the keys file on the UI run alone, with the overlay,
        # and the forwarder run gets neither.
        keys = self.scratch.tmp / "cloud-keys.env"
        keys.write_text("OPENAI_API_KEY=sk-test\n")
        with self.scratch.ui_listener():
            cloud = self.succeed(
                "ui",
                "pi-web",
                "--preset",
                "qwen3.8-27b-q4",
                "--dir",
                project,
                "--cloud",
                **{**common, "LLM_CLOUD_KEYS_FILE": str(keys)},
            )
        ui_run, forward_run = (line for line in cloud.splitlines() if " run --detach " in line)
        self.assertIn(f"key_file={keys} ", ui_run)
        self.assertIn("--file compose.agent-egress.yaml --profile ui", ui_run)
        self.assertIn("-e TOKENCRATE_CLOUD=1 agent-ui", ui_run)
        self.assertIn("key_file= ", forward_run)
        self.assertNotIn("compose.agent-egress.yaml", forward_run)
        self.assertNotIn("sk-test", cloud)
        self.assertIn(f"offers the cloud providers keyed in {keys}", cloud)
        # The engine's labels are what status and the check read: an egress
        # UI ends its status line with the flag, and its name marks the
        # check's target list.
        marked = {**common, "FAKE_ENGINE_UI_EGRESS": "1"}
        self.assertIn(
            f"UI pi-web: forwarder running http://127.0.0.1:{self.scratch.ui_port}/ project=unknown egress".replace(
                "running", "unknown"
            ),
            self.succeed("status", **marked),
        )
        check = self.succeed("smoke", "--agent", "pi", "--preset", "qwen3.8-27b-q4", "--egress", **marked)
        self.assertIn(
            "-e 'TOKENCRATE_UI_TARGETS=egress:tokencrate-ui-pi-web:8504 tokencrate-ui-forward-pi-web:8080'", check
        )
        self.succeed("ui", "stop", **common)
        self.assertIn("logs --follow tokencrate-ui-pi-web", self.succeed("ui", "logs", **common))
        self.succeed("down", **common)
        self.expect_failure("usage: bin/tokencrate ui stop", "ui", "stop", "../now", **common)
        self.expect_failure("usage: bin/tokencrate ui <set>", "ui", **common)
        self.expect_failure("--egress is only valid with agent, smoke --agent, or ui", "bench", "--egress")

    def test_agent_check_uses_the_selected_preset_and_never_egress(self) -> None:
        # The check starts the container the way `agent` does, so the same
        # pre-flight applies: the preset must be rendered as loadable.
        self.expect_failure(
            "is not rendered as loadable",
            "smoke",
            "--agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4-mtp",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.scratch.render_fixture("qwen3.8-27b-q4-mtp")
        check = self.succeed(
            "smoke", "--agent", "pi", "--preset", "qwen3.8-27b-q4-mtp", FAKE_ENGINE_LLAMA_RUNNING="true"
        )
        self.assertIn("tokencrate-agent-check", check)
        # The gateway of the agents network, as the engine reports it, goes
        # into the check; the fake reports none (Docker's isolated mode).
        self.assertIn(
            "-e TOKENCRATE_ENGINE=docker -e TOKENCRATE_AGENTS_GATEWAY= -e TOKENCRATE_UI_TARGETS= "
            "-e TOKENCRATE_EGRESS= agent-pi",
            check,
        )
        self.assertIn("preset=qwen3.8-27b-q4-mtp", check)
        self.assertNotIn("compose.agent-egress.yaml", check)
        self.assertNotIn(f"project={self.scratch.root / 'build'}", check)
        self.assertNotIn(f"home={self.scratch.storage / 'agents'}", check)
        self.expect_failure(
            "no preset selected; set LLM_DEFAULT_PRESET in .env or pass --preset",
            "smoke",
            "--agent",
            "pi",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.expect_failure(
            "--basic is not valid with --agent",
            "smoke",
            "--agent",
            "pi",
            "--basic",
            LLM_DEFAULT_PRESET="qwen3.8-27b-q4",
        )

    def test_relative_storage_paths_resolve_from_the_repository_not_the_caller(self) -> None:
        self.scratch.render_fixture("qwen3.8-27b-q4")
        foreign = self.scratch.tmp / "foreign-cwd"
        foreign.mkdir(exist_ok=True)
        output = self.succeed(
            "agent",
            "pi",
            "--preset",
            "qwen3.8-27b-q4",
            "--dir",
            str(self.scratch.project),
            cwd=foreign,
            LLM_AGENTS_DIR="data/cli-test-agents",
            FAKE_ENGINE_LLAMA_RUNNING="true",
        )
        self.assertIn(f"home={self.scratch.root / 'data' / 'cli-test-agents' / 'pi' / 'project-'}", output)
        self.assertEqual(list(foreign.iterdir()), [])
        self.assertTrue((self.scratch.root / "data" / "cli-test-agents" / "pi").is_dir())

    def test_status(self) -> None:
        output = self.succeed("status", FAKE_ENGINE_LLAMA_RUNNING="true")
        self.assertIn("fake-llama-container", output)
        self.assertIn("(not reachable yet)", output)

    def test_logs_needs_exactly_one_llama_container(self) -> None:
        self.expect_failure("logs needs exactly one llama container", "logs")
        self.assertIn("logs --follow fake-llama-container", self.succeed("logs", FAKE_ENGINE_LLAMA_RUNNING="true"))

    def test_recovery_does_not_validate_launch_pins_or_gpu_provider(self) -> None:
        (self.scratch.root / "pins.env").write_text("invalid pin edit\n")
        for command in (("down",), ("status",), ("logs",), ("ui", "stop"), ("ui", "logs", "pi-web")):
            with self.subTest(command=command):
                self.succeed(
                    *command,
                    CONTAINER_ENGINE="podman",
                    FAKE_ENGINE_LLAMA_RUNNING="true",
                    FAKE_ENGINE_UI_SET="pi-web",
                    FAKE_PODMAN_COMPOSE_DOCKER_PLUGIN="true",
                )

    def test_a_filesystem_error_is_reported_in_the_wrapper_voice(self) -> None:
        # No function converts an OSError; the dispatcher reports every one.
        self.expect_failure("TokenCrate: filesystem operation failed", "init", LLM_MODELS_DIR="/dev/null/models")

    def test_option_errors(self) -> None:
        self.expect_failure("unexpected argument for up: extra", "up", "extra")
        self.expect_failure("positive integer", "up", "--timeout", "nope")
        self.expect_failure("--timeout is only valid with up", "smoke", "--timeout", "1")
        self.expect_failure("unknown command: wait", "wait")
        self.expect_failure("unknown option for up: --refresh", "up", "--refresh")
        self.expect_failure("all is available through models fetch", "up", "--model-set", "all")
        self.expect_failure("unknown model set: missing-set (available: ", "up", "--model-set", "missing-set")
        self.expect_failure("unknown option: --refresh", "models", "status", "--refresh", "qwen3.8-27b-ud-q4-k-xl")
        self.expect_failure("--preset is only valid with", "presets", "render", "--preset", "missing")
        self.expect_failure("--basic is only valid with smoke", "bench", "--basic")
        self.expect_failure("usage: bin/tokencrate pins check", "pins", "check", "node", "extra")
        self.expect_failure("unknown pin component 'rust'", "pins", "check", "rust")
        self.expect_failure("no preset selected", "smoke", FAKE_ENGINE_LLAMA_RUNNING="true")
        self.expect_failure("model draft needs", "models", "draft", "not-a-spec")
        self.expect_failure("unknown command", "frobnicate")
        # doctor keeps the host checks and warns about a preset it cannot find.
        self.assertIn(
            "unknown preset nope, so its host requirements were not checked",
            self.succeed("doctor", "--preset", "nope", LLM_GPU="false"),
        )

    def test_models_status_reports_missing_files_without_the_engine(self) -> None:
        result = self.scratch.run(
            "models", "status", "qwen3.8-27b-ud-q4-k-xl", PATH="/usr/bin:/bin", HF_TOKEN="secret-fixture"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Qwen3.8-27B-UD-Q4_K_XL.gguf: missing", result.stdout)


class SignalTests(unittest.TestCase):
    def test_a_hang_up_or_termination_unwinds_and_an_inherited_ignore_is_left_alone(self) -> None:
        # nohup and setsid ignore SIGHUP; a backgrounded command keeps running.
        previous = {signum: signal.getsignal(signum) for signum in (signal.SIGHUP, signal.SIGTERM)}
        self.addCleanup(lambda: [signal.signal(signum, handler) for signum, handler in previous.items()])
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        cli.install_signal_handlers()
        self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
        with self.assertRaises(SystemExit) as exited:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        self.assertEqual(exited.exception.code, 128 + signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
