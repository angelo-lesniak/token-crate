"""Engine detection and the Compose invocation, against the fake engine."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import socket
import subprocess
import threading
import unittest
from unittest.mock import patch

from tests.support import Scratch
from tokencrate import TokenCrateError, engine, env


class FailingWrite:
    """An opened file whose write fails, as it does on a full disk."""

    def __init__(self, handle) -> None:
        self.handle = handle

    def write(self, text: str) -> int:
        raise OSError("disk full")

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.handle.close()


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

    def test_the_stack_record_decides_the_engine_and_refuses_a_disagreeing_setting(self) -> None:
        # Podman is usable, so detection would pick it; a stack recorded on
        # Docker keeps `down` and `status` on Docker until it is forgotten.
        engine.Engine("docker", self.settings()).record_stack()
        self.assertEqual(
            json.loads((self.scratch.root / "build" / "stack.json").read_text()),
            {"engine": "docker", "project": "tokencrate"},
        )
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE=""), launching=False).name, "docker")
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="docker")).name, "docker")
        refusal = (
            "the stack runs on docker, not podman (build/stack.json); "
            "run: CONTAINER_ENGINE=docker bash bin/tokencrate down"
        )
        with self.assertRaisesRegex(TokenCrateError, re.escape(refusal)):
            engine.detect(self.settings(CONTAINER_ENGINE="podman"), launching=False)
        # `up` passes what doctor gathered; a selection that disagrees with
        # the record is refused the same way, and a consistent one is used
        # without another probe.
        probed = engine.select(self.settings(CONTAINER_ENGINE="docker").subprocess_env(), "docker")
        with patch.object(engine, "select") as select:
            self.assertEqual(engine.detect(self.settings(), selection=probed).name, "docker")
        select.assert_not_called()
        other = engine.select(self.settings().subprocess_env(), "podman")
        with self.assertRaisesRegex(TokenCrateError, "the stack runs on docker, not podman"):
            engine.detect(self.settings(), selection=other)
        # Another project's record, and no record, leave detection alone.
        engine.Engine("docker", self.settings(COMPOSE_PROJECT_NAME="other")).record_stack()
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="")).name, "podman")
        engine.Engine("docker", self.settings()).forget_stack()
        self.assertEqual(engine.detect(self.settings(CONTAINER_ENGINE="")).name, "podman")
        engine.Engine("docker", self.settings()).forget_stack()
        (self.scratch.root / "build" / "stack.json").write_text("{")
        with self.assertRaisesRegex(TokenCrateError, "cannot read the stack record .*stack.json: .*; remove it"):
            engine.detect(self.settings(CONTAINER_ENGINE=""))

    def test_the_stack_record_is_written_whole_or_not_at_all(self) -> None:
        # The remedy for an unreadable record deletes it, so a write that
        # fails midway (a full disk) must leave the previous record intact.
        settings = self.settings()
        docker = engine.Engine("docker", settings)
        docker.record_stack()
        failing = patch.object(io, "open", lambda *args, **kwargs: FailingWrite(open(*args, **kwargs)))
        with failing, self.assertRaisesRegex(OSError, "disk full"):
            engine.Engine("podman", settings).record_stack()
        self.assertEqual(engine.recorded_engine(settings), "docker")
        self.assertEqual([path.name for path in docker.stack_record.parent.iterdir()], ["stack.json"])

    def test_the_lock_is_per_project_and_names_its_holder_while_it_waits(self) -> None:
        settings = self.settings()
        docker, podman = engine.Engine("docker", settings), engine.Engine("podman", settings)
        self.assertEqual(docker.lock_file, self.scratch.root / "build" / "locks" / "tokencrate.lock")
        self.assertEqual(docker.lock_file, podman.lock_file)
        entered, finished = threading.Event(), threading.Event()

        def other():
            entered.set()
            with podman.lock("down"):
                finished.set()

        with docker.lock("up"), patch.object(engine, "warn") as warn:
            self.assertEqual(docker.lock_file.read_text(), f"{os.getpid()} up\n")
            thread = threading.Thread(target=other)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(finished.wait(0.1))
        thread.join(2)
        self.assertTrue(finished.is_set())
        warn.assert_called_once_with(f"waiting for `up` (pid {os.getpid()}) to finish")
        self.assertEqual(docker.lock_file.read_text(), f"{os.getpid()} down\n")
        # A caller that names no command is still serialized and reported.
        with docker.lock():
            self.assertEqual(docker.lock_file.read_text(), f"{os.getpid()}\n")

    def test_the_port_check_is_one_bind_for_doctor_and_the_start(self) -> None:
        docker = engine.Engine("docker", self.settings())
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = str(listener.getsockname()[1])
            self.assertIn("in use", engine.loopback_bind_error(port))
            with self.assertRaisesRegex(TokenCrateError, f"cannot use host port {port}: "):
                docker.require_port("llama", port)
        self.assertEqual(engine.loopback_bind_error(port), "")
        docker.require_port("llama", port)

    def test_bridge_forwarding_reads_the_flag_in_the_rootless_namespace(self) -> None:
        for flag, expected in (("0", ("0", "")), ("1", ("1", ""))):
            podman = engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_ENGINE_FORWARDING=flag))
            self.assertEqual(podman.bridge_forwarding("podman1"), expected)
        podman = engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_ENGINE_FORWARDING="missing"))
        self.assertEqual(
            podman.bridge_forwarding("podman1"),
            ("", "cat: /proc/sys/net/ipv4/conf/podman1/forwarding: No such file or directory"),
        )
        podman = engine.detect(self.settings(CONTAINER_ENGINE="podman", FAKE_ENGINE_FORWARDING="fail"))
        self.assertEqual(podman.bridge_forwarding("podman1"), ("", "Error: cannot join the rootless network namespace"))

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
