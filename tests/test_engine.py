"""Engine detection and the Compose invocation, against the fake engine."""

from __future__ import annotations

import hashlib
import subprocess
import unittest
from unittest.mock import patch

from tests.support import Scratch
from tokencrate import TokenCrateError, engine, env


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(**overrides))

    def test_requested_engine_is_used_and_unknown_values_are_refused(self) -> None:
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="docker")).name, "docker")
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="podman")).name, "podman")
        with self.assertRaisesRegex(TokenCrateError, "unsupported CONTAINER_ENGINE=lxc"):
            engine.detect(self.settings(CONTAINER_ENGINE="lxc"))

    def test_podman_is_preferred_and_must_be_rootless_with_crun(self) -> None:
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="")).name, "podman")
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="", FAKE_PODMAN_ROOTLESS="false")).name, "docker")
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="", FAKE_PODMAN_RUNTIME="runc")).name, "docker")
        with self.assertRaisesRegex(TokenCrateError, "rootless with crun"):
            engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_PODMAN_ROOTLESS="false"))

    def test_docker_compose_plugin_under_podman_blocks_the_gpu_path_only(self) -> None:
        with self.assertRaisesRegex(TokenCrateError, "drops CDI GPU devices"):
            engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_PODMAN_COMPOSE_DOCKER_PLUGIN="true"))
        cpu = engine.detect(
            self.settings(CONTAINER_ENGINE="podman", FAKE_PODMAN_COMPOSE_DOCKER_PLUGIN="true", LLM_GPU="false")
        )
        self.assertEqual(cpu.name, "podman")

    def test_compose_file_list_follows_gpu_engine_and_egress(self) -> None:
        docker = engine.detect(self.settings(CONTAINER_ENGINE="docker"))
        trace = docker.compose("ps", capture=True).stdout
        self.assertIn(
            "--file compose.yaml --file compose.gpu.yaml --file compose.docker.yaml --env-file pins.env ps", trace
        )
        self.assertNotIn("compose.podman.yaml", trace)
        podman = engine.detect(self.settings(CONTAINER_ENGINE="podman", LLM_GPU="false"))
        trace = podman.compose("ps", profiles=("agent-pi",), egress=True, capture=True).stdout
        self.assertIn(
            "--file compose.yaml --file compose.podman.yaml --file compose.agent-egress.yaml "
            "--profile agent-pi --env-file pins.env ps",
            trace,
        )
        self.assertNotIn("compose.gpu.yaml", trace)
        self.assertNotIn("compose.docker.yaml", trace)

    def test_home_tmpfs_owner_uses_the_engine_and_actual_host_identity(self) -> None:
        for name, owner in (("docker", "uid=1234,gid=2345"), ("podman", "U")):
            selected = engine.detect(self.settings(CONTAINER_ENGINE=name))
            with patch("os.getuid", return_value=1234), patch("os.getgid", return_value=2345):
                with patch("tokencrate.engine._run") as run:
                    run.return_value.returncode = 0
                    selected.compose("config", TOKENCRATE_HOME_OWNER="unsafe")
                self.assertEqual(run.call_args.args[1]["TOKENCRATE_HOME_OWNER"], owner)

    def test_network_gateway_reads_either_engine_and_is_empty_without_one(self) -> None:
        docker = engine.detect(self.settings(CONTAINER_ENGINE="docker"))
        # The fake answers with Docker's shape and no gateway (isolated mode).
        self.assertEqual(docker.network_gateway("agents"), "")
        plain = '{"IPAM": {"Config": [{"Subnet": "172.19.0.0/16", "Gateway": "172.19.0.1"}]}}'
        self.assertEqual(
            engine.detect(self.settings(CONTAINER_ENGINE="docker", FAKE_ENGINE_NETWORK=plain)).network_gateway(
                "agents"
            ),
            "172.19.0.1",
        )
        podman = '{"subnets": [{"subnet": "10.89.0.0/24", "gateway": "10.89.0.1"}]}'
        self.assertEqual(
            engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_ENGINE_NETWORK=podman)).network_gateway(
                "agents"
            ),
            "10.89.0.1",
        )
        with self.assertRaisesRegex(TokenCrateError, "invalid JSON"):
            engine.detect(self.settings(CONTAINER_ENGINE="docker", FAKE_ENGINE_NETWORK="nope")).network_gateway(
                "agents"
            )
        # The fake answers Podman's shape for the podman name without a setting.
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="podman")).network_gateway("ui"), "10.89.0.1")
        missing = engine.detect(self.settings(CONTAINER_ENGINE="docker", FAKE_ENGINE_NETWORK="missing"))
        with self.assertRaisesRegex(TokenCrateError, "docker network failed"):
            missing.network_gateway("agents")
        self.assertEqual(missing.network_gateway("agents", missing_ok=True), "")

    def test_inspect_engine_reads_the_docker_server_version(self) -> None:
        settings = self.settings(CONTAINER_ENGINE="docker")
        facts = engine.inspect_engine("docker", settings.subprocess_env())
        self.assertEqual((facts.usable, facts.server_version), (True, "29.7.2-fake"))
        self.assertEqual(engine.inspect_engine("podman", settings.subprocess_env()).server_version, "")

    def test_token_and_pins_never_reach_the_engine_environment(self) -> None:
        settings = self.settings(CONTAINER_ENGINE="docker", HF_TOKEN="secret-fixture", PI_VERSION="from-shell")
        self.assertEqual(settings.hf_token, "secret-fixture")
        # The fake engine exits 1 when HF_TOKEN is in its environment.
        docker = engine.detect(settings)
        self.assertEqual(docker.compose("ps", capture=True).returncode, 0)

    def test_container_lookup_and_state(self) -> None:
        idle = engine.detect(self.settings(CONTAINER_ENGINE="docker"))
        self.assertEqual(idle.llama_container_ids(), [])
        with self.assertRaisesRegex(TokenCrateError, "is not running"):
            idle.running_llama_id()
        running = engine.detect(self.settings(CONTAINER_ENGINE="docker", FAKE_ENGINE_LLAMA_RUNNING="true"))
        self.assertEqual(running.running_llama_id(), "fake-llama-container")
        self.assertEqual(running.container_state("fake-llama-container"), "running")
        exited = engine.detect(self.settings(CONTAINER_ENGINE="docker", FAKE_ENGINE_STATE="exited"))
        self.assertEqual(exited.container_state("x"), "exited")

    def test_a_failing_engine_command_becomes_a_user_facing_error(self) -> None:
        docker = engine.detect(self.settings(CONTAINER_ENGINE="docker"))
        # The fake engine exits 1 for an invocation the wrapper never makes.
        with self.assertRaisesRegex(TokenCrateError, "docker bogus failed"):
            docker.command("bogus", capture=True)
        self.assertEqual(docker.command("bogus", capture=True, check=False).returncode, 1)

    def test_captured_compose_failures_keep_the_diagnostic(self) -> None:
        docker = engine.Engine("docker", self.settings())
        failure = subprocess.CompletedProcess([], 1, "", "invalid integer in services.llama.pids_limit")
        with patch.object(engine, "_run", return_value=failure):
            with self.assertRaisesRegex(TokenCrateError, "invalid integer in services.llama.pids_limit"):
                docker.compose("config", capture=True)

    def test_removal_tolerates_auto_removed_clients_but_reports_engine_errors(self) -> None:
        docker = engine.Engine("docker", self.settings())
        success = subprocess.CompletedProcess([], 0, "", "")
        missing = subprocess.CompletedProcess([], 1, "", "No such container: terminal")
        with patch.object(engine, "_run", side_effect=[success, missing]):
            docker.remove_containers([{"Id": "terminal"}])
        removing = subprocess.CompletedProcess(
            [], 1, "", "Error response from daemon: removal of container terminal is already in progress"
        )
        with (
            patch.object(engine, "_run", side_effect=[success, removing, missing]) as run,
            patch.object(engine.time, "sleep") as sleep,
        ):
            docker.remove_containers([{"Id": "terminal"}])
        self.assertEqual([call.args[0][1] for call in run.call_args_list], ["stop", "rm", "rm"])
        sleep.assert_called_once_with(0.1)
        with (
            patch.object(engine, "_run", side_effect=[success, removing]),
            patch.object(engine.time, "monotonic", side_effect=[0, 0, 31]),
            self.assertRaisesRegex(TokenCrateError, "rm failed: .*removal .* is already in progress"),
        ):
            docker.remove_containers([{"Id": "terminal"}])
        denied = subprocess.CompletedProcess([], 1, "", "permission denied")
        with patch.object(engine, "_run", return_value=denied):
            with self.assertRaisesRegex(TokenCrateError, "stop failed: permission denied"):
                docker.remove_containers([{"Id": "terminal"}])

    def test_fake_config_label_handles_missing_render_and_explicit_overrides(self) -> None:
        for rendered in (False, True):
            if rendered:
                self.scratch.render_fixture("fixture")
            config = self.scratch.root / "build/models.ini"
            expected = hashlib.sha256(config.read_bytes()).hexdigest() if rendered else ""
            for overrides, digest in (
                ({}, expected),
                ({"FAKE_ENGINE_CONFIG_SHA256": "explicit-digest"}, "explicit-digest"),
                ({"FAKE_ENGINE_CONFIG_SHA256": ""}, ""),
            ):
                with self.subTest(rendered=rendered, overrides=overrides):
                    selected = engine.detect(self.settings(FAKE_ENGINE_LLAMA_RUNNING="true", **overrides))
                    result = selected.command(
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "io.tokencrate.config-sha256"}}',
                        selected.running_llama_id(),
                        capture=True,
                    )
                    self.assertEqual(result.stdout, digest + "\n")
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
