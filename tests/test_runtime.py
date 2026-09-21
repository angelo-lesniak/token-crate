"""The readiness wait behind `up`, `init`, and `status`, with the engine and
HTTP stubbed."""

from __future__ import annotations

import json
import stat
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from tests.support import Scratch
from tokencrate import TokenCrateError, env, runtime
from tokencrate.engine import Engine


class FakeEngine:
    def __init__(self, states: list[str]) -> None:
        self.states = states

    def running_llama_id(self) -> str:
        return "llama-1"

    def container_state(self, container_id: str) -> str:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def http(responses: dict[str, str | None]):
    def get(url: str, timeout: float = 5) -> str | None:
        return responses.get(url.rsplit("/", 1)[1])

    return get


def listing(**states: str) -> str:
    """A GET /models body with one entry per model and its status."""
    return json.dumps({"data": [{"id": name, "status": {"value": value}} for name, value in states.items()]})


class WaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)
        self.clock = 0.0

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(LLM_PORT="4208", **overrides))

    def tick(self, seconds: float) -> None:
        self.clock += seconds

    def wait(self, settings, engine, responses, timeout=10) -> str:
        with (
            mock.patch.object(runtime, "http_get", http(responses)),
            mock.patch("builtins.print") as printed,
            mock.patch.object(runtime.uis, "containers", return_value=[]),
        ):
            runtime.wait_until_ready(settings, engine, timeout, sleep=self.tick, clock=lambda: self.clock)
        return "\n".join(str(call.args[0]) for call in printed.call_args_list)

    def test_an_exited_container_fails_immediately(self) -> None:
        with self.assertRaisesRegex(TokenCrateError, "container is exited before it was ready"):
            self.wait(self.settings(), FakeEngine(["exited"]), {"models": listing()})

    def test_a_removed_container_fails_immediately(self) -> None:
        # `removed` is what Engine.container_state reports when inspect fails.
        with self.assertRaisesRegex(TokenCrateError, "container is removed before it was ready"):
            self.wait(self.settings(), FakeEngine(["running", "removed"]), {"models": None})

    def test_healthy_without_a_default_preset_returns(self) -> None:
        output = self.wait(self.settings(LLM_DEFAULT_PRESET=""), FakeEngine(["running"]), {"models": listing()})
        self.assertIn("TokenCrate is healthy at http://127.0.0.1:4208/", output)

    def test_waits_for_the_default_preset_to_be_loaded(self) -> None:
        output = self.wait(
            self.settings(LLM_DEFAULT_PRESET="qwen3.8-27b-q4"),
            FakeEngine(["running"]),
            {"models": listing(**{"qwen3.8-27b-q4": "loaded", "gpt-oss-20b-fast": "unloaded"})},
        )
        self.assertIn("TokenCrate is ready at http://127.0.0.1:4208/ with preset qwen3.8-27b-q4 loaded", output)

    def test_times_out_while_the_preset_is_loading(self) -> None:
        with self.assertRaisesRegex(TokenCrateError, "did not become ready within 5s"):
            self.wait(
                self.settings(LLM_DEFAULT_PRESET="qwen3.8-27b-q4"),
                FakeEngine(["running"]),
                {"models": listing(**{"qwen3.8-27b-q4": "loading"})},
                timeout=5,
            )

    def wait_through(self, settings, bodies: list[str], post=None) -> str:
        """Wait with one GET /models body per poll and a stubbed POST."""
        answers = iter(bodies)
        with (
            mock.patch.object(runtime, "http_get", lambda url, timeout=5: next(answers)),
            mock.patch.object(runtime, "http_post", post or mock.Mock()),
            mock.patch("builtins.print") as printed,
            mock.patch.object(runtime.uis, "containers", return_value=[]),
        ):
            runtime.wait_until_ready(settings, FakeEngine(["running"]), 10, sleep=self.tick, clock=lambda: self.clock)
        return "\n".join(str(call.args[0]) for call in printed.call_args_list)

    def test_a_preset_whose_server_exited_fails_immediately(self) -> None:
        # `loading` then `unloaded` is the router's report of a model server
        # that exited; a preset the router does not list was never rendered.
        settings = self.settings(LLM_DEFAULT_PRESET="qwen3.8-27b-q4")
        with self.assertRaisesRegex(TokenCrateError, "preset qwen3.8-27b-q4 is unloaded instead of loaded"):
            self.wait_through(
                settings, [listing(**{"qwen3.8-27b-q4": "loading"}), listing(**{"qwen3.8-27b-q4": "unloaded"})]
            )
        with self.assertRaisesRegex(TokenCrateError, "preset qwen3.8-27b-q4 is not listed instead of loaded"):
            self.wait(settings, FakeEngine(["running"]), {"models": listing()})

    def test_a_kept_container_with_another_preset_loaded_is_reported_as_running(self) -> None:
        # Compose keeps a running container; after a swap the default preset
        # is `unloaded` while another holds the slot, and the router loads
        # the default on its first request. A sleeping preset counts as loaded.
        settings = self.settings(LLM_DEFAULT_PRESET="qwen3.8-27b-q4")
        output = self.wait_through(settings, [listing(**{"qwen3.8-27b-q4": "unloaded", "gpt-oss-20b-fast": "loaded"})])
        self.assertIn("with preset gpt-oss-20b-fast loaded; preset qwen3.8-27b-q4 loads on its first request", output)
        output = self.wait_through(settings, [listing(**{"qwen3.8-27b-q4": "sleeping"})])
        self.assertIn("with preset qwen3.8-27b-q4 loaded", output)

    def test_a_kept_container_with_nothing_loaded_is_asked_to_load_the_preset(self) -> None:
        # Nothing loaded and nothing loading: an earlier load failed, so `up`
        # asks the router once and then judges the load it started.
        settings = self.settings(LLM_DEFAULT_PRESET="qwen3.8-27b-q4")
        post = mock.Mock()
        states = [listing(**{"qwen3.8-27b-q4": value}) for value in ("unloaded", "loading", "loaded")]
        output = self.wait_through(settings, states, post)
        post.assert_called_once_with("http://127.0.0.1:4208/models/load", {"model": "qwen3.8-27b-q4"})
        self.assertIn("with preset qwen3.8-27b-q4 loaded", output)
        with self.assertRaisesRegex(TokenCrateError, "is unloaded instead of loaded"):
            self.wait_through(settings, [listing(**{"qwen3.8-27b-q4": value}) for value in ("unloaded", "unloaded")])
        # A refused load says so: the state alone cannot tell a rejected
        # request from one the router accepted and then failed.
        refusing = mock.Mock(return_value="HTTP 500")
        with self.assertRaisesRegex(TokenCrateError, r"refused: HTTP 500"):
            self.wait_through(
                settings, [listing(**{"qwen3.8-27b-q4": value}) for value in ("unloaded", "unloaded")], refusing
            )

    def test_model_listing_is_parsed_as_json(self) -> None:
        with mock.patch.object(runtime, "http_get", http({"models": "not json"})):
            self.assertIsNone(runtime.model_states(self.settings()))
        with mock.patch.object(runtime, "http_get", http({"models": json.dumps({"data": []})})):
            self.assertEqual(runtime.model_states(self.settings()), {})
        with mock.patch.object(runtime, "http_get", http({"models": listing(a="loaded", b="unloaded")})):
            self.assertEqual(runtime.model_states(self.settings()), {"a": "loaded", "b": "unloaded"})


class InitAndListingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def settings(self, **overrides: str) -> env.Settings:
        return env.load(self.scratch.root, self.scratch.environment(LLM_PORT="4208", **overrides))

    def test_init_creates_a_private_env_from_the_example(self) -> None:
        settings = self.settings()
        with mock.patch("builtins.print"):
            runtime.init_project(settings)
        env_file = self.scratch.root / ".env"
        self.assertEqual(env_file.read_text(), (self.scratch.root / ".env.example").read_text())
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        for path in (
            settings.models_dir,
            settings.agents_dir / "pi",
            settings.build_dir / "agents" / "omp",
            self.scratch.root / "reports",
        ):
            self.assertTrue(path.is_dir())
        env_file.chmod(0o644)
        with mock.patch("builtins.print"):
            runtime.init_project(settings)
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)

    def test_status_prints_one_line_per_model(self) -> None:
        settings = self.settings()
        engine = mock.MagicMock()
        engine.llama_container_ids.return_value = ["llama-1"]
        with (
            mock.patch.object(runtime, "http_get", http({"models": listing(a="loaded", b="unloaded")})),
            mock.patch("builtins.print") as printed,
            mock.patch.object(runtime.uis, "containers", return_value=[]),
        ):
            runtime.print_status(settings, engine)
        engine.command.assert_called_once_with("ps", "--all", "--filter", "label=com.docker.compose.project=tokencrate")
        output = "\n".join(str(call.args[0]) if call.args else "" for call in printed.call_args_list)
        self.assertIn("Models (GET /models):\n  a: loaded\n  b: unloaded", output)

    def test_shutdown_removes_terminal_legacy_and_current_ui_containers_before_networks(self) -> None:
        engine = Engine("docker", self.settings())
        names = ["llama", "terminal-one-off", "agent-ui", "ui-forward", "current-ui"]
        engine.containers = mock.Mock(return_value=[{"Id": name} for name in names])
        engine.command = mock.Mock(return_value=mock.Mock(returncode=0, stdout="network-id\n"))
        runtime.stop_stack(engine)
        calls = [call.args for call in engine.command.call_args_list]
        self.assertEqual(calls[:10], [(action, name) for name in names for action in ("stop", "rm")])
        self.assertEqual(calls[-1], ("network", "rm", "network-id"))
        engine.command.reset_mock()
        engine.containers.return_value = []
        engine.command.return_value.stdout = ""
        runtime.stop_stack(engine)
        self.assertEqual(len(engine.command.call_args_list), 1)

    def test_shutdown_waits_for_an_in_progress_model_start(self) -> None:
        settings = self.settings(LLM_DEFAULT_PRESET="")
        engine = Engine("docker", settings)
        engine.containers = mock.Mock(return_value=[])
        engine.command = mock.Mock(return_value=mock.Mock(stdout=""))
        building, finish_build, stopping, stopped = (threading.Event() for _ in range(4))
        trace = []

        def compose(*args, **kwargs):
            trace.append(args[0])
            if args[0] == "build":
                building.set()
                if not finish_build.wait(5):
                    raise AssertionError("build was not released")

        def stop():
            stopping.set()
            runtime.stop_stack(engine)
            trace.append("down")
            stopped.set()

        engine.compose = compose
        with (
            mock.patch.object(engine, "require_port"),
            mock.patch.object(runtime, "render", return_value=[]),
            mock.patch.object(runtime, "config_digest", return_value="digest"),
            mock.patch.object(runtime, "wait_until_ready"),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            start = pool.submit(runtime.start_stack, settings, engine, None, 1)
            self.assertTrue(building.wait(2))
            shutdown = pool.submit(stop)
            try:
                self.assertTrue(stopping.wait(2))
                self.assertFalse(stopped.wait(0.05))
            finally:
                finish_build.set()
            start.result(timeout=3)
            shutdown.result(timeout=3)
        self.assertEqual(trace, ["build", "up", "down"])


if __name__ == "__main__":
    unittest.main()
