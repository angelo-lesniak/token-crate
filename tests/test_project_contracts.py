"""Repository contracts that need no container engine.

Every test parses the artifact it inspects (Compose YAML, JSON, TOML, the
Dockerfiles, the Markdown pages) and fails with the rule it enforces.
Behavior is proven elsewhere: the package by the other unit tests, the
images and the running stack by tests/integration.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError(
        "the repository contracts need PyYAML: python3 -m pip install -r requirements-dev.txt "
        "(a silent skip would hollow out the gate, so the dependency is mandatory)"
    ) from None

from tests.support import home_tmpfs_directories
from tokencrate import PROJECT_ROOT, agentsets, env, presets, session, uis
from tokencrate.cli import USAGE
from tokencrate.env import PIN_KEYS

# The pinned keys come from the package; none may grow a duplicate default
# in a Dockerfile or Compose file. Host-side inputs are not image build inputs.
BUILD_PIN_KEYS = set(PIN_KEYS) - {"CUDA_MIN_DRIVER_MAJOR"}
AGENT_SERVICES = ("agent-pi", "agent-omp")
# The browser-UI service is the pi image with another command; the forwarder publishes it.
UI_SERVICES = ("agent-ui", "ui-forward")
# oh-my-pi reads its global context file from the home, so the repository's
# copy is bound there read-only. Both agents take their settings from
# /etc/tokencrate through the entrypoint, which writes them into the home.
CONFIGURATION_FILES = {
    "pi": {},
    "omp": {".omp/agent/AGENTS.md": "./config/agents/omp/AGENTS.md"},
}
COMPOSE_FILES = (
    "compose.yaml",
    "compose.gpu.yaml",
    "compose.podman.yaml",
    "compose.docker.yaml",
    "compose.agent-egress.yaml",
)
# The internal networks: agents and the model; the browser UI, the model, and
# the forwarder. ui-publish carries the forwarder's published port alone.
INTERNAL_NETWORKS = ("agents", "ui")
HOME_TMPFS_OPTIONS = (
    "rw,exec,nosuid,nodev,mode=0750,${TOKENCRATE_HOME_OWNER:?set per engine by bin/tokencrate},size=256m"
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<target>[^)]+)\)")
COMPOSE_FALLBACK_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):-([^}]*)\}")
# Every base image is pulled by the pinned digest, never by the tag alone.
PINNED_FROM_RE = re.compile(r":\$\{[A-Z_]+_TAG\}@sha256:\$\{[A-Z_]+_DIGEST\}")


def read_text(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


class ComposeLoader(yaml.SafeLoader):
    """The Compose merge tags an overlay may carry; `!override` replaces the
    base value instead of merging into it (both Compose parsers honour it)."""


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
ComposeLoader.add_constructor("!reset", lambda loader, node: None)


def load_yaml(relative: str) -> dict:
    document = yaml.load(read_text(relative), Loader=ComposeLoader)
    if not isinstance(document, dict):
        raise AssertionError(f"{relative} did not parse to a YAML mapping")
    return document


def markdown_pages() -> list[Path]:
    """The tracked Markdown files: what ships, not a reviewer's notes or a
    report left in the checkout. A `git archive` extract has no work tree
    (the gate runs there too), so it scans the directory instead."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"], cwd=PROJECT_ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        skipped = {".git", "data", "local", "build", "reports"}
        return sorted(path for path in PROJECT_ROOT.rglob("*.md") if not skipped & set(path.parts))
    return sorted(path for path in (PROJECT_ROOT / p for p in listed.decode().split("\0") if p) if path.is_file())


def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(key)
            yield from walk_strings(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk_strings(item)


def find_mount(service: dict, target: str) -> dict | None:
    for mount in service.get("volumes") or []:
        if isinstance(mount, dict) and mount.get("target") == target:
            return mount
    return None


def heading_anchors(text: str) -> set[str]:
    """The anchors GitHub derives from a page's headings."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        base = "".join(character for character in title.lower() if character.isalnum() or character in " -_")
        base = base.replace(" ", "-")
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


class ProjectContractTests(unittest.TestCase):
    def service(self, compose: dict, name: str) -> dict:
        service = compose.get("services", {}).get(name)
        self.assertIsInstance(service, dict, f"compose.yaml must define the {name} service")
        return service

    def assert_hardened(self, name: str, service: dict) -> None:
        self.assertIs(service.get("read_only"), True, f"service {name} must set read_only: true")
        self.assertIn("ALL", service.get("cap_drop") or [], f"service {name} must drop all Linux capabilities")
        self.assertIn(
            "no-new-privileges:true",
            service.get("security_opt") or [],
            f"service {name} must set security_opt no-new-privileges:true",
        )
        self.assertTrue(service.get("pids_limit"), f"service {name} must set pids_limit")

    def assert_mount(self, name: str, service: dict, target: str, source: str, *, read_only: bool) -> None:
        mount = find_mount(service, target)
        how = "read-only" if read_only else "read-write"
        self.assertIsNotNone(mount, f"service {name} must mount {source} at {target} {how}")
        self.assertEqual(mount.get("source"), source, f"service {name} must mount {target} from {source}")
        self.assertEqual(bool(mount.get("read_only")), read_only, f"service {name} must mount {target} {how}")

    def test_yaml_mappings_have_no_duplicate_keys(self) -> None:
        # A duplicate key in a literal YAML mapping silently overwrites the
        # earlier one, so a hardening line could vanish without a diff hunk
        # that says so.
        def walk(node: yaml.Node, relative: Path, path: tuple[str, ...] = ()) -> None:
            if isinstance(node, yaml.MappingNode):
                seen: set[str] = set()
                for key_node, value_node in node.value:
                    key = key_node.value if isinstance(key_node, yaml.ScalarNode) else "<complex>"
                    self.assertFalse(
                        key != "<<" and key in seen, f"duplicate YAML key in {relative}: {'.'.join((*path, key))}"
                    )
                    seen.add(key)
                    walk(value_node, relative, (*path, key))
            elif isinstance(node, yaml.SequenceNode):
                for index, item in enumerate(node.value):
                    walk(item, relative, (*path, str(index)))

        paths = sorted(PROJECT_ROOT.glob("compose*.yaml"))
        paths.extend(sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")))
        for path in paths:
            node = yaml.compose(path.read_text(encoding="utf-8"))
            if node is not None:
                walk(node, path.relative_to(PROJECT_ROOT))

    def test_the_llama_image_boots_the_rendered_configuration(self) -> None:
        self.assertIn(
            f"/etc/tokencrate/{presets.CONFIG_FILE_NAME}",
            read_text("services/llama/Dockerfile"),
            f"services/llama/Dockerfile must boot /etc/tokencrate/{presets.CONFIG_FILE_NAME}",
        )

    def test_pins_env_is_the_only_place_a_pinned_value_lives(self) -> None:
        for dockerfile in ("services/llama/Dockerfile", "services/agents/Dockerfile"):
            text = read_text(dockerfile)
            for key in sorted(BUILD_PIN_KEYS):
                default = re.search(rf"^ARG {re.escape(key)}=.*$", text, re.MULTILINE)
                self.assertIsNone(default, f"pinned ARG {key} has a duplicate default in {dockerfile}")
            for line in text.splitlines():
                if line.startswith("FROM "):
                    self.assertRegex(line, PINNED_FROM_RE, f"{dockerfile} must pin the base image by tag and digest")
        compose_strings = list(walk_strings(load_yaml("compose.yaml")))
        for key in sorted(BUILD_PIN_KEYS):
            pattern = re.compile(rf"\$\{{{re.escape(key)}:-([^}}]*)\}}")
            for value in compose_strings:
                for match in pattern.finditer(value):
                    self.assertFalse(match.group(1), f"pinned value {key} has a duplicate Compose default ({value})")

    def test_the_llama_service_publishes_on_loopback_with_read_only_mounts(self) -> None:
        compose = load_yaml("compose.yaml")
        llama = self.service(compose, "llama")
        self.assert_hardened("llama", llama)
        self.assertNotIn(
            "devices", llama, "the GPU device request belongs in compose.gpu.yaml so CPU-only checks can run"
        )
        ports = [str(port) for port in llama.get("ports") or []]
        self.assertTrue(
            ports and ports[0].startswith("127.0.0.1:"), f"the llama port must publish on 127.0.0.1: {ports}"
        )
        for target, source in (
            ("/models", "${LLM_MODELS_DIR:-./data/models}"),
            (f"/etc/tokencrate/{presets.CONFIG_FILE_NAME}", f"./build/{presets.CONFIG_FILE_NAME}"),
            ("/etc/tokencrate/chat-templates", "./config/chat-templates"),
            ("/etc/tokencrate/ui-config.json", "./config/llama/ui-config.json"),
        ):
            self.assert_mount("llama", llama, target, source, read_only=True)
        environment = llama.get("environment") or {}
        self.assertEqual(
            environment.get("NVIDIA_VISIBLE_DEVICES"),
            "void",
            "the llama service must set NVIDIA_VISIBLE_DEVICES=void so CDI is the only device source",
        )
        self.assertEqual(
            environment.get("LLAMA_ARG_OFFLINE"),
            "1",
            "the llama service must set LLAMA_ARG_OFFLINE=1 so no model server downloads files at start",
        )
        devices = load_yaml("compose.gpu.yaml").get("services", {}).get("llama", {}).get("devices")
        self.assertEqual(
            devices,
            ["${GPU_DEVICE:-nvidia.com/gpu=all}"],
            "compose.gpu.yaml must request the CDI device ${GPU_DEVICE:-nvidia.com/gpu=all} for llama",
        )

    def test_the_networks_are_internal_and_the_services_are_exactly_the_documented_ones(self) -> None:
        compose = load_yaml("compose.yaml")
        networks = compose.get("networks") or {}
        self.assertEqual(
            set(networks),
            {"default", *INTERNAL_NETWORKS, "ui-publish"},
            "compose.yaml must define exactly the default, agents, ui, and ui-publish networks",
        )
        for name in INTERNAL_NETWORKS:
            self.assertIs((networks.get(name) or {}).get("internal"), True, f"the {name} network must be internal")
        self.assertFalse(
            (networks.get("ui-publish") or {}).get("internal"),
            "the ui-publish network must not be internal; it carries the forwarder's published port",
        )
        docker = load_yaml("compose.docker.yaml")
        self.assertEqual(
            {key for key in docker if not key.startswith("x-")},
            {"networks"},
            "compose.docker.yaml must set network options and nothing else",
        )
        self.assertEqual(
            set(docker["networks"]), set(INTERNAL_NETWORKS), "compose.docker.yaml must cover the internal networks"
        )
        for name, network in docker["networks"].items():
            options = (network or {}).get("driver_opts") or {}
            for key in ("com.docker.network.bridge.gateway_mode_ipv4", "com.docker.network.bridge.gateway_mode_ipv6"):
                self.assertEqual(
                    options.get(key), "isolated", f"compose.docker.yaml must set {key}: isolated on the {name} network"
                )
        self.assertEqual(
            set(compose.get("services") or {}),
            {"llama", *AGENT_SERVICES, *UI_SERVICES},
            "compose.yaml must define exactly the llama, agent, and UI services; helpers run in-process",
        )

    def test_agent_services_run_hardened_on_the_internal_network_with_a_tmpfs_home(self) -> None:
        compose = load_yaml("compose.yaml")
        dockerfile = read_text("services/agents/Dockerfile")
        for name in (*AGENT_SERVICES, "agent-ui"):
            with self.subTest(service=name):
                self.assert_agent_service(name, self.service(compose, name), dockerfile)

    def assert_agent_service(self, name: str, service: dict, dockerfile: str) -> None:
        self.assert_hardened(name, service)
        for target in (
            "/opt/tokencrate/skills",
            "/opt/tokencrate/skills-local",
            "/etc/tokencrate/agent",
        ):
            mount = find_mount(service, target)
            self.assertTrue(mount is not None and mount.get("read_only") is True, f"{name}: {target} must be read-only")
        self.assert_mount(
            name,
            service,
            "${LLM_AGENT_PROJECT_DIR:-/workspace}",
            "${LLM_AGENT_PROJECT_DIR:-./local/project}",
            read_only=False,
        )
        # The service name and the agent name the entrypoint sees are the
        # same thing; the pi image is rendered from the agent sets, so its
        # service builds the rendered Dockerfile's `agent` stage on top of
        # the static `pi` stage.
        agent = "pi" if name == "agent-ui" else name.removeprefix("agent-")
        filename = "models.json" if agent == "pi" else "models.yml"
        generated = find_mount(service, f"/etc/tokencrate/agent-generated/{filename}")
        self.assertIsNotNone(generated)
        self.assertTrue(generated["read_only"])
        self.assertTrue(generated["source"].endswith(f"/build/agents/{agent}/{filename}"))
        self.assertIsNone(find_mount(service, "/etc/tokencrate/agent-generated"))
        self.assertIn(agent, session.AGENTS, f"{name} is not an agent of session.AGENTS")
        # The home is a per-container tmpfs. The retained directories and the
        # configuration files are its only binds, and every ancestor of a
        # bind has an owned tmpfs of its own.
        home = session.HOME_IN_CONTAINER
        # The UI state directory is the set's own; compose.yaml carries the
        # variable, whose fallback only lets a render without the wrapper resolve.
        state = "${TOKENCRATE_UI_STATE:-.ui-state}" if name == "agent-ui" else None
        retained = session.persistent_directories(agent, state)
        configuration = CONFIGURATION_FILES[agent]
        home_mounts = {
            mount["target"]: mount
            for mount in service.get("volumes") or []
            if isinstance(mount, dict) and (mount["target"] == home or mount["target"].startswith(home + "/"))
        }
        self.assertEqual(
            set(home_mounts),
            {f"{home}/{relative}" for relative in (*retained, *configuration)},
            f"{name} must bind exactly the retained home directories and the configuration files",
        )
        for relative in retained:
            source = f"${{TOKENCRATE_AGENT_HOME:-./data/agents/{agent}}}/{relative}"
            self.assert_mount(name, service, f"{home}/{relative}", source, read_only=False)
        for relative, source in configuration.items():
            self.assert_mount(name, service, f"{home}/{relative}", source, read_only=True)
        home_tmpfs = dict(
            item.split(":", 1)
            for item in service.get("tmpfs") or []
            if item.startswith(home + ":") or item.startswith(home + "/")
        )
        self.assertEqual(
            set(home_tmpfs),
            {str(Path(home) / relative) for relative in home_tmpfs_directories(agent)},
            f"{name} must provide a tmpfs for the home and every ancestor of a home bind, nothing else",
        )
        for target, options in home_tmpfs.items():
            self.assertEqual(options, HOME_TMPFS_OPTIONS, f"{name} must mount the tmpfs {target} owned and executable")
        for target in home_mounts:
            for parent in Path(target).parents:
                if parent.is_relative_to(home):
                    self.assertIn(str(parent), home_tmpfs, f"{name} mounts {target} below {parent} without a tmpfs")
        build = service.get("build") or {}
        rendered = "build/agents/pi/${TOKENCRATE_AGENT_SETS_TAG:-unrendered}/Dockerfile"
        expected = (rendered, "agent") if agent == "pi" else ("services/agents/Dockerfile", agent)
        built = (build.get("dockerfile"), build.get("target"))
        self.assertEqual(built, expected, f"{name} must build {expected[1]} from {expected[0]}")
        self.assertIn(f" AS {agent}\n", dockerfile, f"services/agents/Dockerfile must define the stage {agent}")
        environment = service.get("environment") or {}
        self.assertEqual(environment.get("TOKENCRATE_AGENT"), agent, f"{name} must set TOKENCRATE_AGENT={agent}")
        # Without it oh-my-pi runs its bash tool as a login shell, which
        # executes a ~/.profile written into the home during the session.
        self.assertEqual(str(environment.get("PI_BASH_NO_LOGIN")), "1", f"{name} must set PI_BASH_NO_LOGIN=1")

    def test_every_service_sits_on_exactly_its_networks(self) -> None:
        # The placement the privacy model rests on: terminal agents on the
        # internal agents network alone, a browser UI on the internal ui
        # network alone, the forwarder on ui and its published ui-publish,
        # llama on all three of default, agents, and ui. tests/podman-compose.sh
        # proves the same from the rendered `run` arguments.
        compose = load_yaml("compose.yaml")
        expected = {
            "llama": ["default", "agents", "ui"],
            "agent-pi": ["agents"],
            "agent-omp": ["agents"],
            "agent-ui": ["ui"],
            "ui-forward": ["ui-publish", "ui"],
        }
        for name, networks in expected.items():
            self.assertEqual(self.service(compose, name).get("networks"), networks, f"{name} must sit on {networks}")

    def test_only_the_egress_overlay_moves_a_session_to_the_default_network(self) -> None:
        # The overlay replaces the network list (`!override`, which the
        # loader honours): an egress session is on the default network only,
        # so it shares none with offline sessions and cannot relay for them.
        egress = load_yaml("compose.agent-egress.yaml").get("services", {})
        for name in AGENT_SERVICES:
            self.assertEqual(
                egress.get(name, {}).get("networks"),
                ["default"],
                f"compose.agent-egress.yaml must put {name} on the default network only",
            )
        # A browser UI keeps the ui network for its forwarder and joins the
        # default network; the overlay marks it for status and the check.
        ui = egress.get("agent-ui", {})
        self.assertEqual(ui.get("networks"), ["ui", "default"], "compose.agent-egress.yaml must add default to the UI")
        self.assertEqual(ui.get("labels"), {uis.EGRESS_LABEL: "1"}, "the overlay must label an egress UI")
        self.assertNotIn("ui-forward", egress, "the forwarder never gets a route out")

    def test_no_compose_file_carries_the_cloud_keys(self) -> None:
        # The keys reach a container only as the file the `run -v` of
        # `agent --cloud` binds read-only and the entrypoint exports; no
        # Compose file names the file, its setting, or its mount target, so
        # no other service can receive it.
        self.assertIn(session.KEYS_MOUNT_TARGET, read_text("services/agents/entrypoint.sh"))
        for relative in COMPOSE_FILES:
            text = read_text(relative)
            for needle in (session.KEYS_MOUNT_TARGET, "LLM_CLOUD_KEYS_FILE", "TOKENCRATE_CLOUD"):
                self.assertNotIn(needle, text, f"{relative} names {needle}; the keys travel only as the run's mount")
        self.assertIn("LLM_CLOUD_KEYS_FILE", env.documented_keys(PROJECT_ROOT / ".env.example"))

    def test_the_ui_services_publish_the_selected_ui_on_loopback_through_the_forwarder(self) -> None:
        compose = load_yaml("compose.yaml")
        ui = self.service(compose, "agent-ui")
        self.assertEqual(
            ui.get("environment", {}).get("TOKENCRATE_UI_PORT"),
            "${TOKENCRATE_UI_PORT:-}",
            "the agent-ui service must pass the selected UI manifest port to its launcher",
        )
        self.assertEqual(ui.get("profiles"), ["ui"], "the agent-ui service must be in the ui profile")
        for name in UI_SERVICES:
            self.assertEqual(
                self.service(compose, name).get("labels"),
                {uis.UI_LABEL: "${TOKENCRATE_UI_SET:-}"},
                f"{name} must carry the UI set label the wrapper finds its containers by",
            )
        self.assertTrue(
            str(ui.get("command", [""])[0]).startswith("${TOKENCRATE_UI_COMMAND"),
            "the agent-ui service must run the wrapper's TOKENCRATE_UI_COMMAND",
        )
        forward = self.service(compose, "ui-forward")
        self.assert_hardened("ui-forward", forward)
        self.assertEqual(forward.get("profiles"), ["ui"], "the ui-forward service must be in the ui profile")
        ports = [str(port) for port in forward.get("ports") or []]
        self.assertTrue(
            ports and ports[0].startswith("127.0.0.1:${TOKENCRATE_UI_HOST_PORT"),
            f"the ui-forward port must publish TOKENCRATE_UI_HOST_PORT on 127.0.0.1: {ports}",
        )
        self.assert_mount(
            "ui-forward",
            forward,
            "/etc/tokencrate/ui-forward.js",
            "${TOKENCRATE_ROOT:?set by bin/tokencrate}/services/agents/ui-forward.js",
            read_only=True,
        )
        self.assertNotIn("depends_on", forward, "the template must not start a generic UI dependency")
        self.assertEqual(forward.get("command", [None])[0], "node", "the ui-forward service must run node")

    def test_every_service_runs_as_the_host_user(self) -> None:
        # Podman additionally keeps the id mapping.
        compose = load_yaml("compose.yaml")
        podman = load_yaml("compose.podman.yaml").get("services", {})
        for name, service in compose.get("services", {}).items():
            with self.subTest(service=name):
                user = str(service.get("user", ""))
                self.assertTrue(user.startswith("${HOST_UID"), f"compose.yaml must set the host user for {name}")
                self.assertTrue(
                    str(podman.get(name, {}).get("userns_mode", "")).startswith("keep-id:"),
                    f"compose.podman.yaml must use keep-id for {name}",
                )

    def test_the_token_never_reaches_compose(self) -> None:
        for relative in COMPOSE_FILES:
            self.assertNotIn("HF_TOKEN", read_text(relative), f"HF_TOKEN must stay in the wrapper, not in {relative}")

    def test_the_agent_settings_switch_telemetry_off(self) -> None:
        # The switches docs/privacy.md lists.
        pi_settings = json.loads(read_text("config/agents/pi/settings.json"))
        for key in ("enableInstallTelemetry", "enableAnalytics"):
            self.assertIs(pi_settings.get(key), False, f"config/agents/pi/settings.json must set {key} to false")
        self.assertEqual(
            pi_settings.get("defaultProjectTrust"), "ask", "config/agents/pi/settings.json must set defaultProjectTrust"
        )
        autolearn = load_yaml("config/agents/omp/config.yml").get("autolearn") or {}
        self.assertIs(autolearn.get("enabled"), False, "config/agents/omp/config.yml must disable autolearn")

    def test_the_agent_images_switch_install_telemetry_off_before_installing(self) -> None:
        dockerfile = read_text("services/agents/Dockerfile")
        for stage, install in (("pi", "npm install --global --ignore-scripts"), ("omp", "bun install --global")):
            section = dockerfile.split(f" AS {stage}\n", 1)[1].split("\nFROM ", 1)[0]
            telemetry = section.find("PI_TELEMETRY=0")
            installer = section.find(install)
            self.assertTrue(
                0 <= telemetry < installer, f"the {stage} image must set PI_TELEMETRY=0 before its package install"
            )

    def test_a_ui_set_declares_its_port_once(self) -> None:
        # The wrapper passes the manifest port to the launcher and to the
        # forwarder; a launcher that writes the number itself could drift
        # from the manifest, and the mismatch would show only as the `ui`
        # start timeout.
        for entry in agentsets.catalog(PROJECT_ROOT).values():
            if entry.ui is None:
                continue
            launcher = entry.directory / entry.ui["command"]
            self.assertTrue(launcher.is_file(), f"{entry.name} must ship its launcher {entry.ui['command']}")
            self.assertNotIn(
                str(entry.ui["port"]),
                launcher.read_text(encoding="utf-8"),
                f"{launcher.relative_to(PROJECT_ROOT)} writes the port that {entry.name}'s manifest declares",
            )

    def test_compose_fallbacks_agree_with_the_documented_defaults(self) -> None:
        # The wrapper exports every key it defaults with its effective value,
        # so a Compose `${KEY:-fallback}` for such a key is never used; a
        # fallback that differs from the wrapper's default would still
        # mislead a reader and a direct Compose call.
        defaults = env.parse_env_file(PROJECT_ROOT / ".env.example")
        for relative in COMPOSE_FILES:
            for key, fallback in COMPOSE_FALLBACK_RE.findall(read_text(relative)):
                if key in defaults and fallback:
                    self.assertEqual(
                        fallback, defaults[key], f"{relative} falls back to {key}={fallback!r}; .env.example differs"
                    )

    def test_the_ui_forward_fallback_port_is_the_pi_web_host_port(self) -> None:
        # TOKENCRATE_UI_HOST_PORT is set per launch, so it has no line in
        # .env.example and the fallback test above cannot reach it; the
        # fallback still copies the pi-web manifest's host_port and would
        # mislead a reader if it differed.
        expected = str(agentsets.load_set(PROJECT_ROOT, "pi-web").ui["host_port"])
        fallbacks = {
            fallback
            for key, fallback in COMPOSE_FALLBACK_RE.findall(read_text("compose.yaml"))
            if key == "TOKENCRATE_UI_HOST_PORT"
        }
        self.assertEqual(
            fallbacks,
            {expected},
            "compose.yaml must fall back to the pi-web manifest's host_port for the forwarder port",
        )

    def test_the_shipped_ui_ports_are_documented_as_the_setting_pattern(self) -> None:
        # The setting is one key per UI set; .env.example shows the two
        # shipped ones, commented out, with the manifest's host_port.
        documented = env.documented_keys(PROJECT_ROOT / ".env.example")
        for name in ("pi-web", "paseo"):
            key = env.ui_port_key(name)
            self.assertIn(key, documented, f".env.example must show {key}")
            self.assertIn(
                f"# {key}={agentsets.load_set(PROJECT_ROOT, name).ui['host_port']}\n", read_text(".env.example")
            )

    def test_every_npm_agent_set_gets_security_updates(self) -> None:
        # A set whose package.json is not listed gets no advisory, and nothing
        # else in the tree would say so.
        listed = {
            str(directory).strip("/")
            for entry in yaml.safe_load(read_text(".github/dependabot.yml"))["updates"]
            if entry.get("package-ecosystem") == "npm"
            for directory in entry.get("directories") or ([entry["directory"]] if entry.get("directory") else [])
        }
        present = {
            f"config/agent-sets/{path.parent.name}"
            for path in (PROJECT_ROOT / "config/agent-sets").glob("*/package.json")
        }
        self.assertEqual(listed, present, ".github/dependabot.yml must list every agent set with a package.json")

    def test_every_shipped_item_is_named_on_its_owner_page(self) -> None:
        # CONTRIBUTING.md asks a maintainer to add the row; this names the
        # page a forgotten one belongs on.
        config = PROJECT_ROOT / "config"
        agent_sets = sorted(path.name for path in (config / "agent-sets").iterdir() if path.is_dir())
        owners = (
            ("agent set", agent_sets, "agent-sets"),
            ("model set", sorted(path.stem for path in (config / "model-sets").glob("*.toml")), "models"),
            ("preset", sorted(path.stem for path in (config / "presets").glob("*.toml")), "models"),
            ("setting", sorted(env.parse_env_file(PROJECT_ROOT / ".env.example")), "configuration"),
        )
        for kind, names, page in owners:
            text = read_text(f"docs/{page}.md")
            for name in names:
                self.assertIn(f"`{name}`", text, f"{kind} {name} is not named in docs/{page}.md")

    def test_the_cloud_keys_template_holds_no_value(self) -> None:
        # Every line is a comment: a copy exports nothing until edited, and
        # the names are pi's, spelled the way the entrypoint accepts them.
        for line in read_text("cloud-keys.env.example").splitlines():
            self.assertTrue(not line.strip() or line.startswith("#"), f"cloud-keys.env.example line: {line}")
        names = re.findall(r"^# ([A-Z][A-Z0-9_]*)=", read_text("cloud-keys.env.example"), re.MULTILINE)
        self.assertIn("ANTHROPIC_API_KEY", names)

    def test_the_validation_environment_names_the_pinned_versions(self) -> None:
        # The records are measurements of the pins under test; a raised pin
        # without a new record would otherwise keep the old line.
        text = read_text("docs/validation.md")
        for key, value in env.load_pins(PROJECT_ROOT / "pins.env").items():
            if key not in env.DIGEST_KEYS:
                self.assertIn(f"`{key}={value}`", text, f"docs/validation.md#environment must name {key}={value}")

    def test_the_documentation_links_resolve_and_index_every_page_and_usage_line(self) -> None:
        pages = {path: path.read_text(encoding="utf-8") for path in markdown_pages()}
        for path, text in pages.items():
            for match in MARKDOWN_LINK_RE.finditer(text):
                raw_target = match.group("target").strip().strip("<>")
                target, _, fragment = raw_target.partition("#")
                if "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (path.parent / target).resolve() if target else path
                self.assertTrue(
                    resolved.exists(), f"broken Markdown link in {path.relative_to(PROJECT_ROOT)}: {raw_target}"
                )
                if fragment and resolved.suffix == ".md":
                    anchors = heading_anchors(pages.get(resolved, resolved.read_text(encoding="utf-8")))
                    self.assertIn(
                        fragment, anchors, f"broken heading anchor in {path.relative_to(PROJECT_ROOT)}: {raw_target}"
                    )
        readme = pages[PROJECT_ROOT / "README.md"]
        index = readme.split("## Choose what to do next", 1)[1].split("\n## ", 1)[0]
        docs = PROJECT_ROOT / "docs"
        for page in [*sorted(docs.glob("*.md")), PROJECT_ROOT / "CONTRIBUTING.md", PROJECT_ROOT / "SECURITY.md"]:
            relative = page.relative_to(PROJECT_ROOT)
            self.assertTrue(
                f"({relative})" in index or f"({relative}#" in index,
                f'README\'s "Choose what to do next" table must link {relative}',
            )
        cli_page = pages[docs / "cli.md"]
        for line in USAGE.splitlines():
            if line.startswith("  bin/tokencrate "):
                self.assertIn(line.strip(), cli_page, f"docs/cli.md must show the usage line verbatim: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
