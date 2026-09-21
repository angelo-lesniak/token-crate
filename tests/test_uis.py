"""UI ownership, temporary launch definitions, ports and lifecycle failures."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from tests.support import SOURCE_ROOT, Scratch, free_port
from tokencrate import TokenCrateError, agents, agentsets, engine, env, uis


def container(name: str, role: int = 0, port: str = "4224", project: str = "tokencrate") -> dict:
    service = uis.services(name)[role]
    return {
        "Id": service,
        "Config": {
            "Labels": {
                engine.PROJECT_LABEL: project,
                engine.SERVICE_LABEL: service,
                uis.UI_LABEL: name,
            },
            "Env": ["TOKENCRATE_UI_PORT=8504"],
        },
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]} if role else {},
            "Networks": {"ui": {"IPAddress": "10.89.0.5"}},
        },
    }


class UiTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.settings = env.load(self.scratch.root, self.scratch.environment(LLM_DEFAULT_PRESET="qwen3.8-27b-q4"))
        self.engine = engine.Engine("docker", self.settings)

    def test_defaults_and_overrides(self):
        fresh = env.load(self.scratch.root, self.scratch.environment(LLM_PORT=None))
        self.assertEqual(fresh.port, "4207")
        self.assertEqual(fresh.ui_port("pi-web"), "4224")
        self.assertEqual(fresh.ui_port("paseo"), "4250")
        self.assertEqual(fresh.ui_port("custom", "54224"), "54224")
        with self.assertRaisesRegex(TokenCrateError, "explicit --port"):
            fresh.ui_port("custom")
        local = self.scratch.root / ".env"
        local.write_text("LLM_PI_WEB_PORT=4444\nLLM_PASEO_PORT=4445\n")
        configured = env.load(self.scratch.root, self.scratch.environment())
        self.assertEqual(configured.ui_port("pi-web"), "4444")
        self.assertEqual(configured.ui_port("paseo"), "4445")
        for name in ("pi-web", "paseo"):
            self.assertEqual(configured.ui_port(name, "5555"), "5555")
        self.assertEqual(local.read_text(), "LLM_PI_WEB_PORT=4444\nLLM_PASEO_PORT=4445\n")
        for invalid in ("", "0", "65536", "-1", "localhost:4224", "1.5", " 4224"):
            with self.assertRaises(TokenCrateError):
                env.validate_port(invalid, "--port")

    def test_occupied_port_belongs_only_to_its_actual_forwarder(self):
        port = str(free_port())
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", int(port)))
            with patch.object(self.engine, "containers", return_value=[]):
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    self.engine.require_port(uis.services("pi-web")[1], port)
            with patch.object(self.engine, "containers", return_value=[container("pi-web", 1, port)]):
                self.engine.require_port(uis.services("pi-web")[1], port)
                with self.assertRaisesRegex(TokenCrateError, "belongs to another container"):
                    self.engine.require_port(uis.services("paseo")[1], port)
                # Owning another port never excuses a conflict on this port.
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    with patch.object(self.engine, "containers", return_value=[container("pi-web", 1, "1")]):
                        self.engine.require_port(uis.services("pi-web")[1], port)

    def test_port_preflight_allows_recently_closed_connections_but_not_live_listeners(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = str(server.getsockname()[1])
            with patch.object(self.engine, "containers", return_value=[]):
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    self.engine.require_port(uis.services("pi-web")[1], port)
            with socket.create_connection(("127.0.0.1", int(port))) as client:
                accepted, _ = server.accept()
                # The server closes first, leaving this port in TIME_WAIT.
                accepted.close()
                self.assertEqual(client.recv(1), b"")
        with patch.object(self.engine, "containers", return_value=[]):
            self.engine.require_port(uis.services("pi-web")[1], port)

    def test_port_permission_errors_keep_their_actual_cause(self):
        with (
            patch.object(self.engine, "containers", return_value=[]),
            patch.object(engine.socket, "socket") as socket_type,
        ):
            socket_type.return_value.__enter__.return_value.bind.side_effect = PermissionError(13, "Permission denied")
            with self.assertRaisesRegex(TokenCrateError, "cannot use host port 80: .*Permission denied"):
                self.engine.require_port(uis.services("pi-web")[1], "80")

    def test_status_reports_the_project_from_the_agent_container(self):
        owned = [container("pi-web", role) for role in (0, 1)]
        owned[0]["Config"]["Env"].append("TOKENCRATE_PROJECT_DIR=/projects/selected")
        with patch.object(uis, "containers", return_value=owned), contextlib.redirect_stdout(io.StringIO()) as output:
            uis.print_status(self.engine)
        self.assertIn("project=/projects/selected", output.getvalue())

    def test_label_discovery_preserves_unrelated_containers(self):
        ours = container("pi-web")
        unrelated = container("paseo", project="other")
        llama = {
            "Id": "llama",
            "Config": {"Labels": {engine.PROJECT_LABEL: "tokencrate", engine.SERVICE_LABEL: "llama"}},
        }
        self.engine.command = Mock(
            side_effect=[
                Mock(stdout="a b c"),
                *[Mock(stdout=json.dumps(x), returncode=0) for x in (ours, unrelated, llama)],
            ]
        )
        self.assertEqual(uis.containers(self.engine), [ours])

    def test_disappearing_terminal_does_not_abort_ui_discovery(self):
        owned = container("pi-web")
        self.engine.command = Mock(
            side_effect=[
                Mock(stdout="terminal ui"),
                Mock(returncode=1, stderr="Error: No such container: terminal"),
                Mock(returncode=0, stdout=json.dumps(owned)),
            ]
        )
        self.assertEqual(uis.containers(self.engine), [owned])
        for message in ("permission denied", "dial unix /run/docker.sock: connect: no such file or directory"):
            self.engine.command = Mock(side_effect=[Mock(stdout="ui"), Mock(returncode=1, stderr=message)])
            with self.assertRaisesRegex(TokenCrateError, "could not inspect"):
                uis.containers(self.engine)

    def test_targeted_stop_stop_all_and_logs_need_no_manifest_or_launch_environment(self):
        owned = [container(name, role) for name in ("pi-web", "paseo") for role in (0, 1)]
        self.engine.command = Mock(return_value=Mock(returncode=0))
        with patch.object(uis, "containers", return_value=owned):
            uis.stop(self.engine, "pi-web")
            self.assertEqual(
                [call.args[1] for call in self.engine.command.call_args_list if call.args[0] == "stop"],
                list(uis.services("pi-web")),
            )
            self.engine.command.reset_mock()
            with self.assertRaisesRegex(TokenCrateError, "several UIs"):
                uis.logs(self.engine)
            uis.logs(self.engine, "paseo")
            self.engine.command.assert_called_once_with("logs", "--follow", uis.services("paseo")[0], check=False)
            self.engine.command.reset_mock()
            uis.stop(self.engine)
            self.assertEqual(
                {call.args[1] for call in self.engine.command.call_args_list if call.args[0] == "stop"},
                {x["Id"] for x in owned},
            )
        with patch.object(uis, "containers", return_value=owned[:2]):
            self.assertEqual(uis.logs(self.engine), 0)

    def test_failed_build_does_not_start_containers_and_failed_start_keeps_them(self):
        candidate = self.scratch.tmp / "candidate.json"
        with (
            patch.object(uis, "containers", return_value=[]),
            patch.object(self.engine, "require_port"),
            patch.object(agents, "prepare_session", return_value={}),
            patch.object(agents, "wait_for_ui", side_effect=TokenCrateError("failed readiness")),
            patch.object(uis, "snapshot", side_effect=lambda *_: contextlib.nullcontext(candidate)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.engine.compose = Mock(side_effect=TokenCrateError("failed build"))
            with self.assertRaisesRegex(TokenCrateError, "failed build"):
                agents.run_ui(self.settings, self.engine, None, "paseo", "", str(self.scratch.project))
            self.assertEqual(len(self.engine.compose.call_args_list), 1)
            self.assertEqual(self.engine.compose.call_args.args[0], "build")
            self.engine.compose = Mock()
            with self.assertRaisesRegex(TokenCrateError, "failed readiness"):
                agents.run_ui(self.settings, self.engine, None, "paseo", "", str(self.scratch.project))
            calls = self.engine.compose.call_args_list
            self.assertEqual(calls[1].args, ("up", "--no-build", "--detach", "--no-deps", *uis.services("paseo")))
            self.assertFalse(any("down" in call.args for call in calls))

    def test_launch_files_are_removed_on_success_and_failure(self):
        self.engine.compose = Mock(return_value=Mock(stdout="services: {}\n"))
        for fail in (False, True):
            with self.subTest(fail=fail):
                try:
                    with uis.snapshot(self.engine, "pi-web", {}) as candidate:
                        self.assertTrue(candidate.is_file())
                        self.assertEqual(candidate.parent.stat().st_mode & 0o777, 0o700)
                        frozen = json.loads(candidate.read_text())["services"][uis.services("pi-web")[0]]["extends"][
                            "file"
                        ]
                        self.assertTrue(Path(frozen).is_file())
                        if fail:
                            raise RuntimeError("launch failed")
                except RuntimeError:
                    pass
                self.assertFalse(candidate.parent.exists())

    def test_readiness_checks_both_containers(self):
        self.engine.container_ids = Mock(side_effect=[["ui"], ["forward"]])
        self.engine.container_state = Mock(side_effect=["running", "exited"])
        with patch("tokencrate.runtime.http_get", return_value="ok") as get:
            with self.assertRaisesRegex(TokenCrateError, "container is exited"):
                agents.wait_for_ui(self.engine, "pi-web", "4224", 0)
            get.assert_not_called()

    def test_lock_serializes_close_launches_and_scopes_engine_project(self):
        entered = threading.Event()
        finished = threading.Event()

        def other():
            entered.set()
            with self.engine.lock():
                finished.set()

        with self.engine.lock():
            thread = threading.Thread(target=other)
            thread.start()
            entered.wait(2)
            self.assertFalse(finished.wait(0.05))
        thread.join(2)
        self.assertTrue(finished.is_set())
        self.assertNotEqual(self.engine.lock_file, engine.Engine("podman", self.settings).lock_file)

    def test_all_ui_names_and_addresses_are_containment_targets(self):
        with patch.object(self.engine, "containers", return_value=[container("custom.UI"), container("paseo", 1)]):
            targets = uis.peer_targets(self.engine)
        for target in (
            f"{uis.services('custom.UI')[0]}:8504",
            f"{uis.services('paseo')[1]}:8080",
            "10.89.0.5:8504",
            "10.89.0.5:8080",
        ):
            self.assertIn(target, targets)


class ProviderTests(unittest.TestCase):
    """Exercise actual parsers; fake only Podman's host probes, never Compose."""

    def setUp(self):
        UiTests.setUp(self)
        # The checkout is not a mounted project: its path can contain dollars.
        renamed = self.scratch.root.with_name("checkout$LITERAL")
        self.scratch.root.rename(renamed)
        self.scratch.root = renamed

    @unittest.skipUnless(shutil.which("podman-compose"), "podman-compose parser is not installed")
    def test_podman_frozen_ui_definitions(self):
        self.check_provider("podman")

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI is not installed")
    def test_docker_frozen_ui_definitions(self):
        if subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode:
            self.skipTest("Docker Compose is not installed")
        self.check_provider("docker")

    def check_provider(self, provider):
        real_run = engine._run
        settings = env.load(
            self.scratch.root,
            {**os.environ, **self.scratch.environment(), "PATH": os.environ["PATH"], "LLM_GPU": "false"},
        )
        selected = engine.Engine(provider, settings)

        def run(cmd, environ, provider=provider, **kwargs):
            if provider == "podman":
                cmd = [
                    "podman-compose",
                    "--podman-path",
                    str(SOURCE_ROOT / "tests/fixtures/podman-compose-bin/podman"),
                    *cmd[2:],
                ]
            return real_run(cmd, environ, **kwargs)

        with patch("tokencrate.engine._run", side_effect=run), selected.lock():
            tag = agentsets.render(settings.root, settings.build_dir, [])
            for name, port, internal in (("pi-web", "4224", "8504"), ("custom.UI", "4250", "6767")):
                extra = {
                    "TOKENCRATE_AGENT_SETS_TAG": tag,
                    "TOKENCRATE_UI_HOST_PORT": port,
                    "TOKENCRATE_UI_PORT": internal,
                    "TOKENCRATE_UI_SERVICE": uis.services(name)[0],
                    "TOKENCRATE_PRESET": name,
                    "TOKENCRATE_AGENT_HOME": str(self.scratch.storage / name),
                    "LLM_AGENT_PROJECT_DIR": str(self.scratch.project),
                    "GIT_AUTHOR_NAME": "literal $DOLLAR ${NO_EXPANSION}",
                }
                with uis.snapshot(selected, name, extra) as candidate:
                    if provider == "docker":
                        rendered = yaml.safe_load(
                            selected.compose("config", profiles=("ui",), files_extra=(candidate,), capture=True).stdout
                        )
                        service = rendered["services"][uis.services(name)[0]]
                        self.assertEqual(set(service["networks"]), {"ui"})
                        self.assertEqual(service["environment"]["TOKENCRATE_PRESET"], name)
                        self.assertIn("$$DOLLAR", service["environment"]["GIT_AUTHOR_NAME"])
                        self.assertTrue(service["read_only"])
                        self.assertTrue(
                            all(Path(v["source"]).is_relative_to(self.scratch.tmp) for v in service["volumes"])
                        )
                    else:
                        log = self.scratch.tmp / f"{name}.log"
                        selected.compose(
                            "run",
                            "--rm",
                            "--no-deps",
                            "-T",
                            uis.services(name)[0],
                            profiles=("ui",),
                            FAKE_PODMAN_LOG=str(log),
                            files_extra=(candidate,),
                            capture=True,
                        )
                        trace = log.read_text()
                        self.assertIn("--network=tokencrate_ui", trace)
                        self.assertNotIn("--network=tokencrate_agents", trace)
                        self.assertIn("keep-id", trace)
                        self.assertIn(f"TOKENCRATE_PRESET={name}", trace)
                        self.assertIn("$DOLLAR", trace)
                self.assertFalse(candidate.parent.exists())
