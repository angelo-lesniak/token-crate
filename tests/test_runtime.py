"""The readiness wait behind `up`, `init`, and `status`, with the engine and
HTTP stubbed."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.support import SOURCE_ROOT, Scratch
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
        post = mock.Mock(return_value="")
        states = [listing(**{"qwen3.8-27b-q4": value}) for value in ("unloaded", "loading", "loaded")]
        output = self.wait_through(settings, states, post)
        post.assert_called_once_with("http://127.0.0.1:4208/models/load", {"model": "qwen3.8-27b-q4"})
        self.assertIn("with preset qwen3.8-27b-q4 loaded", output)
        # The router answers the load request before its model server is
        # spawned, so the listing may still read unloaded for a few polls;
        # a load that never begins within that grace has failed.
        unloaded = listing(**{"qwen3.8-27b-q4": "unloaded"})
        post = mock.Mock(return_value="")
        output = self.wait_through(settings, [unloaded] * (runtime.LOAD_GRACE_POLLS + 1) + states[1:], post)
        post.assert_called_once()
        self.assertIn("with preset qwen3.8-27b-q4 loaded", output)
        with self.assertRaisesRegex(TokenCrateError, "is unloaded instead of loaded"):
            self.wait_through(settings, [unloaded] * (runtime.LOAD_GRACE_POLLS + 2))
        # A refused load says so, on the next poll: the state alone cannot
        # tell a rejected request from one the router accepted and then failed.
        refusing = mock.Mock(return_value="HTTP 500")
        with self.assertRaisesRegex(TokenCrateError, r"refused: HTTP 500"):
            self.wait_through(settings, [unloaded, unloaded], refusing)

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
        # Comments only: every default stays in .env.example, so a line is
        # copied only to change it and nothing is frozen at its old default.
        self.assertEqual(env_file.read_text(), runtime.ENV_HEADER)
        self.assertEqual(env.parse_env_file(env_file), {})
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        # Every storage entry init owns, and the two agent homes below the
        # agents directory.
        root = self.scratch.root
        for path in (
            settings.models_dir,
            settings.agents_dir / "pi",
            settings.agents_dir / "omp",
            settings.skills_dir,
            settings.local_skills_dir,
            root / "reports",
            root / "data" / "dashboard" / "victoria",
        ):
            self.assertTrue(path.is_dir(), path)
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
        ):
            runtime.print_containers(settings, engine)
            runtime.print_models(settings, engine)
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

    def test_shutdown_waits_for_the_compose_up_but_not_for_the_build(self) -> None:
        # The lock covers the Compose `up` and the stack record; a `down`
        # during the image build goes first (the build is content-addressed
        # and may take long), one during `up` waits for it.
        settings = self.settings(LLM_DEFAULT_PRESET="")
        engine = Engine("docker", settings)
        engine.containers = mock.Mock(return_value=[])
        engine.command = mock.Mock(return_value=mock.Mock(stdout=""))
        building, finish_build, starting, finish_start = (threading.Event() for _ in range(4))
        trace = []

        def compose(*args, **kwargs):
            trace.append(args[0])
            step, release = (building, finish_build) if args[0] == "build" else (starting, finish_start)
            step.set()
            if not release.wait(5):
                raise AssertionError(f"{args[0]} was not released")

        def stop():
            runtime.stop_stack(engine)
            trace.append("down")

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
            pool.submit(stop).result(timeout=3)
            finish_build.set()
            self.assertTrue(starting.wait(2))
            # The wait notice is the one observable sign that `down` is
            # blocked on the lock; releasing `up` any earlier would let
            # `down` acquire the lock without contention on a slow run.
            waiting = threading.Event()
            with mock.patch("tokencrate.engine.warn", side_effect=lambda *_: waiting.set()) as warn:
                shutdown = pool.submit(stop)
                try:
                    self.assertTrue(waiting.wait(2))
                    self.assertFalse(shutdown.done())
                finally:
                    finish_start.set()
                start.result(timeout=3)
                shutdown.result(timeout=3)
            warn.assert_called_once_with(f"waiting for `up` (pid {os.getpid()}) to finish")
        self.assertEqual(trace, ["build", "down", "up", "down"])
        self.assertFalse(engine.stack_record.exists())

    def test_up_records_the_engine_and_down_forgets_it(self) -> None:
        settings = self.settings(LLM_DEFAULT_PRESET="")
        engine = Engine("docker", settings)
        engine.containers = mock.Mock(return_value=[])
        engine.command = mock.Mock(return_value=mock.Mock(stdout=""))
        engine.compose = mock.Mock()
        with (
            mock.patch.object(engine, "require_port"),
            mock.patch.object(runtime, "render", return_value=[]),
            mock.patch.object(runtime, "config_digest", return_value="digest"),
            mock.patch.object(runtime, "wait_until_ready"),
        ):
            runtime.start_stack(settings, engine, None, 1)
        self.assertEqual(json.loads(engine.stack_record.read_text()), {"engine": "docker", "project": "tokencrate"})
        runtime.stop_stack(engine)
        self.assertFalse(engine.stack_record.exists())


class IsolatedNetworkTests(unittest.TestCase):
    """The per-bridge forwarding check of rootless Podman, against the fake
    engine; the Docker gateway check is covered by the CLI tests."""

    def setUp(self) -> None:
        self.scratch = Scratch()
        self.addCleanup(self.scratch.close)

    def engine(self, **overrides: str) -> Engine:
        from tokencrate import engine

        return engine.detect(env.load(self.scratch.root, self.scratch.environment(**overrides)))

    BRIDGED = json.dumps(
        {
            "subnets": [{"subnet": "10.89.0.0/24", "gateway": "10.89.0.1"}],
            "internal": True,
            "network_interface": "podman1",
            "labels": {"com.docker.compose.project": "tokencrate"},
        }
    )

    def test_a_forwarding_bridge_is_refused_with_the_recreate_remedy(self) -> None:
        with self.assertRaisesRegex(
            TokenCrateError,
            "the agents network's bridge podman1 forwards IPv4 traffic, so a session on another network "
            "can reach it. Run: bash bin/tokencrate down, then up",
        ):
            runtime.require_isolated_networks(
                self.engine(CONTAINER_ENGINE="podman", FAKE_ENGINE_NETWORK=self.BRIDGED, FAKE_ENGINE_FORWARDING="1")
            )

    def test_a_bridge_with_forwarding_off_passes_silently(self) -> None:
        with mock.patch.object(runtime, "warn") as warn:
            runtime.require_isolated_networks(
                self.engine(CONTAINER_ENGINE="podman", FAKE_ENGINE_NETWORK=self.BRIDGED, FAKE_ENGINE_FORWARDING="0")
            )
            # No bridge exists until a container uses the network: nothing to judge.
            runtime.require_isolated_networks(
                self.engine(
                    CONTAINER_ENGINE="podman", FAKE_ENGINE_NETWORK=self.BRIDGED, FAKE_ENGINE_FORWARDING="missing"
                )
            )
            # The fake's Podman document names no interface; Docker is not asked.
            runtime.require_isolated_networks(self.engine(CONTAINER_ENGINE="podman", FAKE_ENGINE_FORWARDING="1"))
            runtime.require_isolated_networks(self.engine(CONTAINER_ENGINE="docker", FAKE_ENGINE_FORWARDING="1"))
        warn.assert_not_called()

    def test_a_flag_that_cannot_be_read_warns_and_does_not_refuse(self) -> None:
        with mock.patch.object(runtime, "warn") as warn:
            runtime.require_isolated_networks(
                self.engine(
                    CONTAINER_ENGINE="podman",
                    FAKE_ENGINE_NETWORK_AGENTS=self.BRIDGED,
                    FAKE_ENGINE_NETWORK_UI="missing",
                    FAKE_ENGINE_NETWORK_DASHBOARD="missing",
                    FAKE_ENGINE_FORWARDING="fail",
                )
            )
        warn.assert_called_once_with(
            "could not read the forwarding flag of bridge podman1: Error: cannot join the rootless network namespace"
        )


if __name__ == "__main__":
    unittest.main()


class DashboardStartTests(unittest.TestCase):
    """The dashboard profile's services are started by name, and the GPU
    exporter's profile follows the GPU setting (the CLI test covers the
    CPU path through the fake engine; the doctor refuses a GPU `up` there)."""

    def start(self, gpu: str) -> list[tuple]:
        import tempfile

        calls: list[tuple] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text((SOURCE_ROOT / ".env.example").read_text())
            settings = env.load(root, {"LLM_DASHBOARD": "true", "LLM_GPU": gpu})
            engine = type("Engine", (), {"compose": lambda self, *args, **kwargs: calls.append((args, kwargs))})()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                runtime.start_dashboard(settings, engine)
            # The samples directory is init's (the storage map), not the start's.
            self.assertFalse((root / "data" / "dashboard" / "victoria").exists())
        self.assertIn("Dashboard at http://127.0.0.1:4211/", out.getvalue())
        return calls

    def test_the_gpu_exporter_follows_the_gpu_setting(self) -> None:
        self.assertEqual(
            self.start("false"),
            [
                (
                    ("up", "--no-build", "--detach", "llama-exporter", "victoriametrics", "grafana"),
                    {"profiles": ("dashboard",)},
                )
            ],
        )
        self.assertEqual(
            self.start("true"),
            [
                (
                    ("up", "--no-build", "--detach", "llama-exporter", "victoriametrics", "grafana", "gpu-exporter"),
                    {"profiles": ("dashboard", "dashboard-gpu")},
                )
            ],
        )
