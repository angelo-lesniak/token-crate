"""UI ownership, ports, the launch through `compose run`, and lifecycle failures."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.support import Scratch, free_port
from tokencrate import TokenCrateError, agentsets, engine, env, uis


def container(name: str, role: int = 0, port: str = "4224", project: str = "tokencrate", access: str = "") -> dict:
    """One UI container as `inspect` shows it: role 0 is the UI, 1 its
    forwarder; `access` is `egress` or `cloud` on a UI started so."""
    service = ("agent-ui", "ui-forward")[role]
    labels = {engine.PROJECT_LABEL: project, engine.SERVICE_LABEL: service, uis.UI_LABEL: name}
    if access:
        labels[uis.EGRESS_LABEL] = "1"
    return {
        "Id": uis.container_names(name)[role],
        "Name": "/" + uis.container_names(name)[role],
        "Config": {
            "Labels": labels,
            "Env": ["TOKENCRATE_UI_PORT=8504"] + (["TOKENCRATE_CLOUD=1"] if access == "cloud" else []),
        },
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]} if role else {},
            "Networks": {"tokencrate_ui": {"IPAddress": "10.89.0.5"}}
            | ({"tokencrate_default": {"IPAddress": "10.89.1.7"}} if access and not role else {}),
        },
    }


class UiTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.settings = env.load(
            self.scratch.root, self.scratch.environment(LLM_DEFAULT_PRESET="qwen3.8-27b-q4-mtp-2x128k")
        )
        self.engine = engine.Engine("docker", self.settings)

    def test_the_host_port_is_the_manifests_unless_port_names_one(self):
        # --port for one launch, else the manifest's host_port; a set
        # without one needs --port. No setting takes part.
        entry = uis.ui_entry(self.settings, "pi-web")
        self.assertEqual(uis.host_port(entry, ""), "4224")
        self.assertEqual(uis.host_port(entry, "54224"), "54224")
        custom = dataclasses.replace(entry, name="custom", ui=dataclasses.replace(entry.ui, host_port=None))
        with self.assertRaisesRegex(TokenCrateError, "^UI set custom declares no host_port; pass --port$"):
            uis.host_port(custom, "")
        self.assertEqual(uis.host_port(custom, "4444"), "4444")
        with self.assertRaisesRegex(TokenCrateError, "agent set coding is not a UI set"):
            uis.ui_entry(self.settings, "coding")
        local = self.scratch.root / ".env"
        local.write_text("LLM_UI_PORT_PI_WEB=4444\n")
        local.chmod(0o600)
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            env.load(self.scratch.root, self.scratch.environment())
        self.assertIn("keys not listed in .env.example are ignored: LLM_UI_PORT_PI_WEB", stderr.getvalue())

    def test_occupied_port_belongs_only_to_its_actual_forwarder(self):
        port = str(free_port())
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", int(port)))
            with patch.object(self.engine, "containers", return_value=[]):
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    self.engine.require_port(uis.container_names("pi-web")[1], port)
            with patch.object(self.engine, "containers", return_value=[container("pi-web", 1, port)]):
                self.engine.require_port(uis.container_names("pi-web")[1], port)
                with self.assertRaisesRegex(TokenCrateError, "belongs to another container"):
                    self.engine.require_port(uis.container_names("custom")[1], port)
                # Owning another port never excuses a conflict on this port.
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    with patch.object(self.engine, "containers", return_value=[container("pi-web", 1, "1")]):
                        self.engine.require_port(uis.container_names("pi-web")[1], port)

    def test_port_preflight_allows_recently_closed_connections_but_not_live_listeners(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = str(server.getsockname()[1])
            with patch.object(self.engine, "containers", return_value=[]):
                with self.assertRaisesRegex(TokenCrateError, "cannot use host port"):
                    self.engine.require_port(uis.container_names("pi-web")[1], port)
            with socket.create_connection(("127.0.0.1", int(port))) as client:
                accepted, _ = server.accept()
                # The server closes first, leaving this port in TIME_WAIT.
                accepted.close()
                self.assertEqual(client.recv(1), b"")
        with patch.object(self.engine, "containers", return_value=[]):
            self.engine.require_port(uis.container_names("pi-web")[1], port)

    def test_port_permission_errors_keep_their_actual_cause(self):
        with (
            patch.object(self.engine, "containers", return_value=[]),
            patch.object(engine.socket, "socket") as socket_type,
        ):
            socket_type.return_value.__enter__.return_value.bind.side_effect = PermissionError(13, "Permission denied")
            with self.assertRaisesRegex(TokenCrateError, "cannot use host port 80: .*Permission denied"):
                self.engine.require_port(uis.container_names("pi-web")[1], "80")

    def test_status_reports_the_project_and_the_access_from_the_agent_container(self):
        owned = [container("pi-web", role) for role in (0, 1)]
        owned += [container("custom", role, "4444", access="cloud") for role in (0, 1)]
        owned[0]["Config"]["Env"].append("TOKENCRATE_PROJECT_DIR=/projects/selected")
        owned[1]["State"] = {"Status": "running"}
        with patch.object(uis, "containers", return_value=owned), contextlib.redirect_stdout(io.StringIO()) as output:
            uis.print_status(self.engine)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "UI custom: forwarder unknown http://127.0.0.1:4444/ project=unknown cloud")
        self.assertEqual(lines[1], "UI pi-web: forwarder running http://127.0.0.1:4224/ project=/projects/selected")
        self.assertEqual(uis.access(container("web", access="egress")), "egress")
        # A UI whose forwarder never started (the second `run` failed) still
        # holds its project and, with --cloud, the keys: it must show.
        orphan = [container("other", access="cloud")]
        with patch.object(uis, "containers", return_value=orphan), contextlib.redirect_stdout(io.StringIO()) as output:
            uis.print_status(self.engine)
        self.assertEqual(output.getvalue(), "UI other: forwarder missing project=unknown cloud\n")

    def test_label_discovery_keeps_the_ui_containers_of_the_project(self):
        # The engine lists the project's containers; the UI label picks the
        # UI pairs out of them.
        ours = container("pi-web")
        llama = {
            "Id": "llama",
            "Config": {"Labels": {engine.PROJECT_LABEL: "tokencrate", engine.SERVICE_LABEL: "llama"}},
        }
        self.engine.command = Mock(
            side_effect=[Mock(stdout="a b"), *[Mock(stdout=json.dumps(x), returncode=0) for x in (ours, llama)]]
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
        owned = [container(name, role) for name in ("pi-web", "custom") for role in (0, 1)]
        self.engine.command = Mock(return_value=Mock(returncode=0))
        with patch.object(uis, "containers", return_value=owned), contextlib.redirect_stdout(io.StringIO()):
            uis.stop(self.engine, "pi-web")
            self.assertEqual(
                [call.args[1] for call in self.engine.command.call_args_list if call.args[0] == "stop"],
                list(uis.container_names("pi-web")),
            )
            self.engine.command.reset_mock()
            with self.assertRaisesRegex(TokenCrateError, "several UIs"):
                uis.logs(self.engine)
            uis.logs(self.engine, "custom")
            ui_name = uis.container_names("custom")[0]
            self.engine.command.assert_called_once_with("logs", "--follow", ui_name, check=False)
            self.engine.command.reset_mock()
            uis.stop(self.engine)
            self.assertEqual(
                {call.args[1] for call in self.engine.command.call_args_list if call.args[0] == "stop"},
                {x["Id"] for x in owned},
            )
        with patch.object(uis, "containers", return_value=owned[:2]):
            self.assertEqual(uis.logs(self.engine), 0)

    def test_failed_build_does_not_start_containers_and_failed_start_keeps_them(self):
        running = [container("pi-web", role) for role in (0, 1)]
        sibling = [container("custom", role) for role in (0, 1)]
        with (
            patch.object(uis, "containers", return_value=running + sibling),
            patch.object(self.engine, "require_port"),
            patch.object(self.engine, "remove_containers") as removed,
            patch("tokencrate.session.prepare", return_value={}),
            patch.object(uis, "wait_for_ui", side_effect=TokenCrateError("failed readiness")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.engine.compose = Mock(side_effect=TokenCrateError("failed build"))
            with self.assertRaisesRegex(TokenCrateError, "failed build"):
                uis.start(self.settings, self.engine, None, "pi-web", "", str(self.scratch.project))
            self.assertEqual(len(self.engine.compose.call_args_list), 1)
            self.assertEqual(self.engine.compose.call_args.args[0], "build")
            removed.assert_not_called()
            self.engine.compose = Mock()
            with self.assertRaisesRegex(TokenCrateError, "failed readiness"):
                uis.start(self.settings, self.engine, None, "pi-web", "", str(self.scratch.project))
            # The set's own pair is replaced after the build; the UI and the
            # forwarder start under their fixed names, the UI alone under
            # the overlay when asked; a failed pair stays for logs.
            removed.assert_called_once_with(running)
            calls = self.engine.compose.call_args_list
            ui_name, forward_name = uis.container_names("pi-web")
            self.assertEqual(calls[1].args, ("run", "--detach", "--no-deps", "-T", "--name", ui_name, "agent-ui"))
            self.assertFalse(calls[1].kwargs["egress"])
            self.assertEqual(
                calls[2].args,
                ("run", "--detach", "--no-deps", "-T", "--service-ports", "--name", forward_name, "ui-forward"),
            )
            self.assertNotIn("egress", calls[2].kwargs)
            self.assertFalse(any("down" in call.args for call in calls))
            self.assertEqual(calls[1].kwargs["TOKENCRATE_UI_SET"], "pi-web")
            self.assertEqual(calls[2].kwargs["TOKENCRATE_UI_HOST_PORT"], "4224")
            self.assertEqual(agentsets.load_set(self.scratch.root, "pi-web").ui.host_port, 4224)

    def test_the_printed_address_opens_the_project(self):
        entry = uis.ui_entry(self.settings, "pi-web")
        self.assertEqual(
            uis.address(entry, "4224", Path("/srv/my project")), "http://127.0.0.1:4224/?cwd=%2Fsrv%2Fmy%20project"
        )
        # A path that is not UTF-8 is quoted byte by byte.
        undecodable = Path(os.fsdecode(b"/srv/caf\xe9"))
        self.assertEqual(uis.address(entry, "4224", undecodable), "http://127.0.0.1:4224/?cwd=%2Fsrv%2Fcaf%E9")
        plain = dataclasses.replace(entry, ui=dataclasses.replace(entry.ui, path="/"))
        self.assertEqual(uis.address(plain, "4224", Path("/srv/x")), "http://127.0.0.1:4224/")

    def test_a_name_held_by_another_checkout_is_refused_and_its_container_kept(self):
        # The fixed names are not project-scoped. This project owns no UI
        # of the set, yet another project's container holds the name: the
        # failed `run` would stop that UI in its unwind, so the launch
        # refuses before removing or running anything.
        ui_name = uis.container_names("pi-web")[0]
        other = json.dumps(container("pi-web", project="other-checkout"))
        self.engine.command = Mock(return_value=Mock(returncode=0, stdout=other))
        with (
            patch.object(uis, "containers", return_value=[]),
            patch.object(self.engine, "require_port"),
            patch.object(self.engine, "remove_containers") as removed,
            patch("tokencrate.session.prepare", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.engine.compose = Mock(
                side_effect=[Mock(), TokenCrateError(f'the container name "/{ui_name}" is already in use')]
            )
            with self.assertRaisesRegex(
                TokenCrateError,
                f"^the container {ui_name} belongs to another checkout's UI; "
                "free it there with: bash bin/tokencrate ui stop pi-web$",
            ):
                uis.start(self.settings, self.engine, None, "pi-web", "", str(self.scratch.project))
        self.assertEqual([call.args[0] for call in self.engine.compose.call_args_list], ["build"])
        self.assertEqual({call.args[0] for call in self.engine.command.call_args_list}, {"inspect"})
        removed.assert_not_called()
        # A name the engine does not know, and one of this project's, pass.
        self.engine.command = Mock(return_value=Mock(returncode=1, stdout="", stderr="No such container"))
        self.assertFalse(self.engine.foreign_container(ui_name))
        self.engine.command = Mock(return_value=Mock(returncode=0, stdout=json.dumps(container("pi-web"))))
        self.assertFalse(self.engine.foreign_container(ui_name))

    def test_readiness_checks_both_containers_by_name(self):
        self.engine.container_state = Mock(side_effect=["running", "exited"])
        with patch("tokencrate.uis.http_get", return_value="ok") as get:
            with self.assertRaisesRegex(TokenCrateError, "the container tokencrate-ui-forward-pi-web is exited"):
                uis.wait_for_ui(self.engine, "pi-web", "4224", 0)
            get.assert_not_called()
        self.assertEqual(
            [call.args for call in self.engine.container_state.call_args_list],
            [(name,) for name in uis.container_names("pi-web")],
        )

    def test_all_ui_names_and_addresses_are_containment_targets(self):
        # The UI of a set started with --egress or --cloud marks its name
        # and its default-network address for expected DNS resolution.
        # Every target must still refuse TCP connections.
        owned = [container("custom", access="egress"), container("custom", 1), container("other", 1)]
        with patch.object(self.engine, "containers", return_value=owned):
            targets = uis.peer_targets(self.engine).split()
        self.assertEqual(
            targets,
            [
                "egress:tokencrate-ui-custom:8504",
                "10.89.0.5:8504",
                "egress:10.89.1.7:8504",
                "tokencrate-ui-forward-custom:8080",
                "10.89.0.5:8080",
                "tokencrate-ui-forward-other:8080",
                "10.89.0.5:8080",
            ],
        )
