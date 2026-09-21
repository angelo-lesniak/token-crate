#!/usr/bin/env python3
"""End-to-end check of TokenCrate with real containers and the fixture models.

The setup copies the fixture model sets and presets into config/, fetches
the two default skill sets, and runs `up` (which waits for the default
preset). The checks run the smoke and bench probes (which swap the loaded
model between the two fixture presets), the agent check and a prompt for
each agent (pi for every shipped toolchain selection), the thinking-level
check, and the home lifecycle of both agents and both browser UIs on the
images the run builds. `down` and the removal of everything the run
created follow. It needs a container engine and network access (the
pinned images, 0.4 GB of model files on the first run, github.com for the
skill sets) and takes several minutes. With LLM_GPU=false (the default
here) the models run on the CPU; LLM_GPU=true uses the GPU path on an
NVIDIA host. Requires PyYAML.

Usage: python3 tests/integration.py [-k pattern]   (the unittest options;
CONTAINER_ENGINE selects the engine, PROMPT_TIMEOUT bounds every agent
prompt in seconds). The module name keeps it out of the `test_*`
discovery of the static gate.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tokencrate import agents, agentsets, env  # noqa: E402
from tokencrate import engine as engines  # noqa: E402

FIXTURES = ROOT / "tests/fixtures"
MODEL_SETS = ("ci-tiny", "ci-small")
PRESETS = ("ci-tiny", "ci-small", "ci-think")
SKILL_SETS = ("pocock-core", "skill-crate")
# Every shipped agent-set selection: the agent check and a prompt run for each.
SELECTIONS = ("coding", "coding,debug,dotnet,web,browser", "coding,debug,odin")
# A prompt the agent never answers has nothing to wake it: a lost model
# response leaves the process in its event loop with no request open, and
# the agent has no timeout of its own. The bound is generous because the
# fixture model runs on the CPU and oh-my-pi's first request is about
# 19,000 tokens: one turn is most of a minute there, and a stuck agent
# idles for many minutes, so the two are far apart.
PROMPT_TIMEOUT = float(os.environ.get("PROMPT_TIMEOUT", "600"))
HOME = agents.HOME_IN_CONTAINER
README_TEXT = "# Integration project\n\nA scratch project for the agent checks.\n"


def tokencrate(*arguments: str, capture: bool = False, check: bool = True, timeout: float | None = None):
    """Run the shim from the checkout with a closed stdin. A captured run
    echoes its output afterwards, so the log holds every command."""
    result = subprocess.run(
        ["bash", "bin/tokencrate", *arguments],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
        check=check,
        timeout=timeout,
    )
    if capture:
        print(result.stdout, end="", flush=True)
    return result


class IntegrationTests(unittest.TestCase):
    settings: env.Settings
    engine: engines.Engine
    scratch: Path
    project: Path
    reports: list[str] = []

    @classmethod
    def setUpClass(cls) -> None:
        for kind, names in (("model-sets", MODEL_SETS), ("presets", PRESETS)):
            for name in names:
                if (ROOT / "config" / kind / f"{name}.toml").exists():
                    raise RuntimeError(f"config/{kind}/{name}.toml already exists; remove it first")
        cls.scratch = Path(tempfile.mkdtemp(prefix="tokencrate-integration-"))
        cls.addClassCleanup(cls.cleanup)
        cls.project = cls.scratch / "project"
        cls.project.mkdir()
        (cls.scratch / "skills").mkdir()
        (cls.project / "README.md").write_text(README_TEXT, encoding="utf-8")
        # The environment set here wins over .env for every wrapper command.
        os.environ.setdefault("LLM_GPU", "false")
        os.environ.update(
            LLM_DEFAULT_PRESET="ci-small",
            LLM_SKILL_SETS=",".join(SKILL_SETS),
            LLM_SKILLS_DIR=str(cls.scratch / "skills"),
            LLM_PROJECT_ROOTS=os.path.realpath(tempfile.gettempdir()),
        )
        os.environ.pop("HF_TOKEN", None)
        if not (ROOT / ".env").is_file():
            tokencrate("init")
        cls.settings = env.load(ROOT)
        cls.engine = engines.detect(cls.settings)
        print(f"engine {cls.engine.name}, LLM_GPU={os.environ['LLM_GPU']}", flush=True)
        for kind, names in (("model-sets", MODEL_SETS), ("presets", PRESETS)):
            for name in names:
                shutil.copy(FIXTURES / kind / f"{name}.toml", ROOT / "config" / kind / f"{name}.toml")
        tokencrate("skills", "fetch", *SKILL_SETS)
        tokencrate("skills", "status", *SKILL_SETS)
        cls.addClassCleanup(tokencrate, "down", capture=True, check=False)
        tokencrate("up", "--model-set", "ci-small", "--model-set", "ci-tiny")
        if "  ci-small: loaded" not in tokencrate("status", capture=True).stdout.splitlines():
            raise AssertionError("up did not leave the default preset loaded")

    @classmethod
    def cleanup(cls) -> None:
        for kind, names in (("model-sets", MODEL_SETS), ("presets", PRESETS)):
            for name in names:
                (ROOT / "config" / kind / f"{name}.toml").unlink(missing_ok=True)
        for report in cls.reports:
            Path(report).unlink(missing_ok=True)
        if hasattr(cls, "settings"):
            for agent in agents.AGENTS:
                shutil.rmtree(agents.agent_home_directory(cls.settings, agent, cls.project), ignore_errors=True)
        shutil.rmtree(cls.scratch, ignore_errors=True)

    # --- Helpers ---------------------------------------------------------

    def expect_status(self, line: str) -> None:
        """`status` prints one line per rendered preset with the router's state."""
        self.assertIn(f"  {line}", tokencrate("status", capture=True).stdout.splitlines(), f"status lacks '{line}'")

    def probe(self, *arguments: str) -> str:
        output = tokencrate(*arguments, capture=True).stdout
        self.reports.extend(re.findall(r"^Saved [a-z]+ report to (.+)$", output, re.MULTILINE))
        return output

    def prompt(self, what: str, *arguments: str) -> subprocess.CompletedProcess:
        """A batch prompt through `agent`; its stdin is closed, so the agent
        cannot wait for a terminal."""
        try:
            return tokencrate("agent", *arguments, capture=True, check=False, timeout=PROMPT_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.fail(f"{what} did not answer within {PROMPT_TIMEOUT:g}s (PROMPT_TIMEOUT)")

    def assert_project_untouched(self) -> None:
        self.assertEqual([p.name for p in self.project.rglob("*") if p.is_file()], ["README.md"])
        self.assertEqual((self.project / "README.md").read_bytes(), README_TEXT.encode("utf-8"))

    # --- Checks ------------------------------------------------------------

    def test_concurrent_clients(self) -> None:
        from tests.concurrent_clients import run

        # Fresh state is part of this test: retained Paseo provider settings
        # must not silently select a different effective model.
        project = self.scratch / "concurrent-project"
        project.mkdir()
        identity = agents.ui_identity_store(self.settings, "paseo")
        had_identity = identity.exists()
        try:
            run(ROOT, project)
        finally:
            for directory in (project, project.with_name(project.name + "-peer")):
                for agent in agents.AGENTS:
                    shutil.rmtree(agents.agent_home_directory(self.settings, agent, directory), ignore_errors=True)
            if not had_identity:
                shutil.rmtree(identity, ignore_errors=True)

    def test_probes_swap_the_loaded_model(self) -> None:
        self.probe("smoke", "--preset", "ci-small")
        self.expect_status("ci-small: loaded")
        self.expect_status("ci-tiny: unloaded")
        self.probe("smoke", "--basic", "--preset", "ci-tiny")
        self.expect_status("ci-tiny: loaded")
        self.expect_status("ci-small: unloaded")
        output = self.probe("bench", "--preset", "ci-small", "--iterations", "2")
        self.assertRegex(
            output, r"(?m)^\| ci-small \| short \| [0-9]{2,} \|", "bench did not measure a multi-token prompt"
        )

    def test_agent_checks_pass(self) -> None:
        for sets in SELECTIONS:
            with self.subTest(agent="pi", sets=sets):
                tokencrate("smoke", "--agent", "pi", "--sets", sets)
        with self.subTest(agent="omp"):
            tokencrate("smoke", "--agent", "omp")

    def test_pi_runs_each_selection(self) -> None:
        for sets in SELECTIONS:
            with self.subTest(sets=sets):
                result = self.prompt(
                    f"pi ({sets})",
                    "pi",
                    "--sets",
                    sets,
                    "--dir",
                    str(self.project),
                    "--",
                    "-p",
                    "Read README.md in the current directory and reply with its first heading, nothing else.",
                )
                self.assertEqual(result.returncode, 0)
                # This checks command output; the wrapper's banner alone can satisfy it.
                self.assertTrue(result.stdout.strip(), "pi command produced no output")
                # An extension that fails to load is reported before the answer.
                self.assertNotRegex(result.stdout, r"(?i)failed to load|error loading")
        self.assert_project_untouched()

    def test_omp_answers(self) -> None:
        result = self.prompt(
            "oh-my-pi", "omp", "--dir", str(self.project), "--", "-p", "Reply with the single word hello."
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout.lower())
        self.assert_project_untouched()

    def test_thinking_level_reaches_the_template(self) -> None:
        """The ci-think server writes every formatted prompt below /tmp/prompts
        in the llama container; the prompt that carries the marker must render
        the low-effort sentence and not the preset's default (medium), which
        is what a request without a usable level would render. The toy model
        never closes its think block, so the agent's exit status is not checked."""
        llama = self.engine.running_llama_id()
        for agent in agents.AGENTS:
            with self.subTest(agent=agent):
                marker = f"TOKENCRATE-THINK-{agent}-{os.getpid()}"
                self.prompt(
                    f"{agent} --thinking low",
                    agent,
                    "--preset",
                    "ci-think",
                    "--dir",
                    str(self.project),
                    "--",
                    "--thinking",
                    "low",
                    "-p",
                    marker,
                )
                found = self.engine.command(
                    "exec", llama, "grep", "-rlF", marker, "/tmp/prompts", capture=True, check=False
                )
                prompts = found.stdout.split()
                self.assertTrue(prompts, f"no prompt carrying {marker} reached the ci-think server")
                for prompt in prompts:
                    text = self.engine.command("exec", llama, "cat", prompt, capture=True).stdout
                    self.assertIn("Reasoning effort is set to low", text, prompt)
                    self.assertNotIn("Reasoning effort is set to medium", text, prompt)
        self.assert_project_untouched()

    def test_home_lifecycle_pi(self) -> None:
        self.home_lifecycle("pi")

    def test_home_lifecycle_omp(self) -> None:
        self.home_lifecycle("omp")

    def test_home_lifecycle_pi_web(self) -> None:
        self.home_lifecycle("pi", ui="pi-web")

    def test_home_lifecycle_paseo(self) -> None:
        self.home_lifecycle("pi", ui="paseo")

    def home_lifecycle(self, agent: str, ui: str | None = None) -> None:
        """The agent home without a model: the production service rendered
        through the wrapper's Compose invocation (its tmpfs, hardening, user
        mapping, and retained mounts), run from the image the run builds with
        networking disabled in a disposable Compose project with scratch
        retained directories. A terminal container runs `sleep`; a UI
        container runs its launcher and daemon."""
        settings, engine = self.settings, self.engine
        scratch = Path(tempfile.mkdtemp(prefix=f"home-lifecycle-{ui or agent}-", dir=self.scratch))
        home, project = scratch / "home", scratch / "project"
        project.mkdir()
        agents.prepare_mountpoints(home, agent, ui=bool(ui))
        # Host files outside the retained directories stay on disk and never enter the home.
        (home / "host-unlisted").write_text("host data")
        (home / f".{agent}/agent/host-marker").write_text("host data")
        retained = agents.persistent_directories(agent, ui=bool(ui))
        extra = {
            "LLM_AGENT_PROJECT_DIR": str(project),
            "TOKENCRATE_AGENT_HOME": str(home),
            "TOKENCRATE_PRESET": "ci-small",
        }
        if ui:
            sets, entry = agents.ui_selection(settings, None, ui)
            tag = agentsets.render(ROOT, settings.build_dir, sets)
            extra.update(
                TOKENCRATE_AGENT_SETS_TAG=tag,
                TOKENCRATE_UI_COMMAND=entry.ui["command"],
                TOKENCRATE_UI_PORT=str(entry.ui["port"]),
            )
            service_name, profiles, port = "agent-ui", ("ui",), entry.ui["port"]
        else:
            extra.update(agents.render_image(settings, agent, None))
            service_name, profiles, port = f"agent-{agent}", (f"agent-{agent}",), None
        engine.compose("build", service_name, profiles=profiles, **extra)
        rendered = engine.compose("config", profiles=profiles, capture=True, **extra)
        service = yaml.safe_load(rendered.stdout)["services"][service_name]
        for key in ("build", "profiles", "networks", "depends_on"):
            service.pop(key, None)
        service.update(pull_policy="never", network_mode="none", stop_grace_period="2s")
        service["command"] = [extra["TOKENCRATE_UI_COMMAND"]] if ui else ["sleep", "600"]
        for mount in service["volumes"]:
            if mount.get("type") == "bind":
                mount["source"] = str((ROOT / mount["source"]).resolve())
        # Terminal and UI containers share transcript storage, never live settings.
        peer = copy.deepcopy(service)
        peer["command"] = ["sleep", "600"]
        peer["volumes"] = [m for m in peer["volumes"] if m["target"] not in (f"{HOME}/.pi-web", f"{HOME}/.paseo")]
        compose_file = scratch / "compose.json"
        compose_file.write_text(json.dumps({"services": {"first": service, "peer": peer}}))
        name = scratch.name

        def run(*words: str, **kwargs) -> str:
            result = subprocess.run(
                [engine.name, *words], check=True, text=True, stdout=subprocess.PIPE, env=engine.env, **kwargs
            )
            return result.stdout.strip()

        def compose(*words: str) -> str:
            return run("compose", "--project-name", name, "--file", str(compose_file), *words)

        def container(service: str) -> str:
            return run(
                "ps",
                "-q",
                "--filter",
                f"label={engines.PROJECT_LABEL}={name}",
                "--filter",
                f"label={engines.SERVICE_LABEL}={service}",
            )

        def execute(cid: str, script: str) -> str:
            return run("exec", cid, "bash", "-ec", script)

        def fixture(cid: str) -> None:
            runtime = ["bun", "run", "-"] if agent == "omp" else ["node", "--input-type=module"]
            print(
                run(
                    "exec",
                    "-i",
                    cid,
                    *runtime,
                    input=(FIXTURES / "home-lifecycle/sessions.mjs").read_text(),
                    timeout=90,
                ),
                flush=True,
            )

        def ready(cid: str) -> None:
            """The entrypoint has written the model list and the UI answers."""
            script = f"test -f {HOME}/.{agent}/agent/models.{'json' if agent == 'pi' else 'yml'}"
            if ui:
                script += f" && curl -sf -o /dev/null http://127.0.0.1:{port}/" + (
                    "api/health" if ui == "paseo" else ""
                )
            deadline = time.monotonic() + 65
            quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            while subprocess.call([engine.name, "exec", cid, "sh", "-c", script], env=engine.env, **quiet) != 0:
                self.assertLess(time.monotonic(), deadline, "the entrypoint or the UI did not become ready")
                time.sleep(0.5)

        def absent(cid: str, *paths: str) -> None:
            execute(cid, "; ".join(f"test ! -e {HOME}/{path}" for path in paths))

        def settings_json(cid: str) -> str:
            return execute(cid, f"cat {HOME}/.pi/agent/settings.json")

        def check(cid: str) -> None:
            ready(cid)
            absent(cid, "host-unlisted", f".{agent}/agent/host-marker", "planted")
            execute(cid, f"test -L {HOME}/.agents/skills")
            for relative in agents.home_tmpfs_directories(agent):
                target = str(Path(HOME) / relative)
                self.assertEqual(
                    execute(cid, f"stat -c '%u:%g:%a' {target}"), f"{os.getuid()}:{os.getgid()}:750", target
                )
                execute(cid, f"touch {target}/owned-check; rm {target}/owned-check")
            fixture(cid)
            for relative in retained:
                execute(cid, f"test -w {HOME}/{relative}")

        try:
            compose("up", "--no-build", "--detach", "first")
            first = container("first")
            check(first)
            if ui == "paseo":
                # The workspace registration follows the daemon's health response.
                deadline = time.monotonic() + 30
                while str(project) not in execute(first, "paseo workspace ls --json"):
                    self.assertLess(time.monotonic(), deadline, "Paseo did not register the workspace")
                    time.sleep(0.5)
            identity = {
                p.name: p.read_bytes()
                for p in (home / ".paseo").glob("*")
                if p.name in ("server-id", "daemon-keypair.json")
            }
            if ui == "paseo":
                self.assertEqual(len(identity), 2, "Paseo did not create its identity")
            print(execute(first, f"du -sk {HOME}"), flush=True)
            execute(first, f"touch {HOME}/planted; mkdir -p {HOME}/.cache; touch {HOME}/.cache/unlisted")
            if agent == "pi":
                execute(
                    first,
                    f"node -e \"const fs=require('fs'),p='{HOME}/.pi/agent/settings.json',"
                    "s=JSON.parse(fs.readFileSync(p));s.lifecycleMarker=true;"
                    'fs.writeFileSync(p,JSON.stringify(s));"',
                )
            for relative in retained:
                execute(first, f"echo retained > {HOME}/{relative}/lifecycle-marker")
            compose("up", "--no-build", "--detach", "peer")
            other = container("peer")
            # The peer runs no UI launcher, so it only needs the generated config.
            execute(other, f"for i in {{1..100}}; do test -f {HOME}/.{agent}/agent/models.* && break; sleep .1; done")
            absent(other, "planted", ".pi-web/lifecycle-marker", ".paseo/lifecycle-marker")
            fixture(other)
            if agent == "pi":
                self.assertNotIn("lifecycleMarker", settings_json(other))
                self.assertIn("lifecycleMarker", settings_json(first))
            run("stop", "--time", "2", other)
            for action in ("restart", "recreate"):
                if action == "restart":
                    run("stop", "--time", "2", first)
                    run("start", first)
                else:
                    compose("up", "--no-build", "--detach", "--force-recreate", "first")
                    first = container("first")
                check(first)
                absent(first, ".cache/unlisted")
                if agent == "pi":
                    self.assertNotIn("lifecycleMarker", settings_json(first))
                for relative in retained:
                    self.assertEqual(
                        execute(first, f"cat {HOME}/{relative}/lifecycle-marker"), "retained", (action, relative)
                    )
                for filename, data in identity.items():
                    self.assertEqual((home / ".paseo" / filename).read_bytes(), data, (action, filename))
            self.assertEqual((home / "host-unlisted").read_text(), "host data")
        except BaseException:
            print(compose("logs", "--no-color"), flush=True)
            raise
        finally:
            compose("down", "--timeout", "2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
