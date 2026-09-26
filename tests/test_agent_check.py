"""The containment check (services/agents/agent-check.sh) run on the host
with stub commands on PATH, so every branch of the gateway probe runs
without an engine. The route probes read the host's own tables (a default
route through a gateway) and the interface count is the host's; the test
asserts the lines it drives."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import SOURCE_ROOT

CHECK = SOURCE_ROOT / "services" / "agents" / "agent-check.sh"
# `timeout 3 bash -c "exec 3<>/dev/tcp/<gateway>/1"`: the stub answers as the
# real connection attempt would, from FAKE_GATEWAY.
STUB_TIMEOUT = """#!/bin/sh
case "${FAKE_GATEWAY:-silent}" in
  refused) echo "bash: connect: Connection refused" >&2; exit 1 ;;
  open) exit 0 ;;
  *) exit 124 ;;
esac
"""


class AgentCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tokencrate-agent-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (
            ("timeout", STUB_TIMEOUT),
            # The model answers; nothing else does.
            ("curl", '#!/bin/sh\ncase "$*" in *llama:8080/health*) exit 0 ;; esac\nexit 7\n'),
            # Name resolution answers only for example.com, and only when asked.
            ("getent", '#!/bin/sh\ncase "$*" in *example.com*) [ -n "$FAKE_DNS" ] && exit 0 ;; esac\nexit 2\n'),
        ):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.home = self.tmp / "home"
        (self.home / ".agents" / "skills").mkdir(parents=True)

    def run_check(self, **extra: str) -> str:
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "TOKENCRATE_AGENT": "omp",
            "TOKENCRATE_PROJECT_DIR": str(self.tmp),
            "TOKENCRATE_UI_TARGETS": "agent-ui-custom:8504 10.89.1.20:8504",
        }
        env.update(extra)
        result = subprocess.run(["bash", str(CHECK)], env=env, capture_output=True, text=True, check=False)
        return result.stdout

    def test_the_gateway_on_docker(self) -> None:
        # No gateway: the isolated network. Any gateway: a failure, answering or not.
        lines = self.run_check(TOKENCRATE_ENGINE="docker", TOKENCRATE_AGENTS_GATEWAY="")
        self.assertIn("[ok] the agents network has no gateway address", lines)
        self.assertIn("[ok] model endpoint is reachable: http://llama:8080", lines)
        self.assertIn("[ok] browser UI agent-ui-custom:8504 is not reachable", lines)
        refused = self.run_check(
            TOKENCRATE_ENGINE="docker", TOKENCRATE_AGENTS_GATEWAY="172.18.0.1", FAKE_GATEWAY="refused"
        )
        self.assertIn("[fail] the bridge gateway 172.18.0.1 answers; host services bound to all interfaces", refused)
        silent = self.run_check(
            TOKENCRATE_ENGINE="docker", TOKENCRATE_AGENTS_GATEWAY="172.18.0.1", FAKE_GATEWAY="silent"
        )
        self.assertIn("[fail] the agents network has a gateway address (172.18.0.1)", silent)

    def test_ui_addresses_are_probed_even_without_dns(self) -> None:
        lines = self.run_check(FAKE_GATEWAY="open")
        self.assertIn("[fail] the container reached browser UI 10.89.1.20:8504", lines)
        self.assertIn("[fail] the container reached browser UI agent-ui-custom:8504", lines)

    def test_egress_inverts_the_route_findings_and_nothing_else(self) -> None:
        # The host has a default route through a gateway, so an egress run
        # accepts the route it asked for and an offline run refuses it. What
        # a session must never reach stays a failure, which is the only
        # reason to run the check with egress.
        lines = self.run_check(TOKENCRATE_EGRESS="1", FAKE_GATEWAY="open")
        self.assertIn("== TokenCrate agent container check (omp, --egress) ==", lines)
        self.assertIn("[ok] the routing table has a default route (expected with --egress)", lines)
        self.assertIn("[fail] the container reached browser UI 10.89.1.20:8504", lines)
        # An egress session is not on the agents network: the gateway probe
        # does not apply and no "no gateway" line is claimed for it.
        self.assertIn("[info] the session is on the default network, not the agents network", lines)
        self.assertNotIn("no gateway address", lines)
        self.assertNotIn("egress is NOT blocked", lines)
        # Without egress the same run reports the gateway route as the failure.
        plain = self.run_check(FAKE_GATEWAY="open")
        self.assertIn(
            "[fail] the routing table has a default route or a route through a gateway; egress is NOT blocked", plain
        )
        self.assertIn("[ok] no name resolution (example.com does not resolve)", plain)

    def test_a_ui_started_with_egress_is_reached_by_design_from_an_egress_session_only(self) -> None:
        # The wrapper marks the name and the default-network address of such
        # a UI; an egress check reports reaching them as information, an
        # offline check still as the failure it is. Unmarked targets of the
        # same run stay failures either way.
        targets = "egress:tokencrate-ui-x:8504 egress:10.89.1.7:8504 10.89.0.5:8504"
        reached = "the container reached browser UI"
        by_design = "; that UI was started with --egress or --cloud"
        egress = self.run_check(TOKENCRATE_EGRESS="1", FAKE_GATEWAY="open", FAKE_DNS="1", TOKENCRATE_UI_TARGETS=targets)
        self.assertIn(f"[info] {reached} tokencrate-ui-x:8504{by_design}", egress)
        self.assertIn(f"[info] {reached} 10.89.1.7:8504{by_design}", egress)
        self.assertIn(f"[fail] {reached} 10.89.0.5:8504", egress)
        self.assertNotIn(f"[fail] {reached} tokencrate-ui-x", egress)
        offline = self.run_check(FAKE_GATEWAY="open", TOKENCRATE_UI_TARGETS=targets)
        self.assertIn(f"[fail] {reached} tokencrate-ui-x:8504{by_design}", offline)
        self.assertNotIn(f"[info] {reached}", offline)

    def test_name_resolution_is_a_failure_offline_and_expected_with_egress(self) -> None:
        plain = self.run_check(FAKE_DNS="1")
        self.assertIn("[fail] the container resolved example.com; DNS egress is NOT blocked", plain)
        egress = self.run_check(FAKE_DNS="1", TOKENCRATE_EGRESS="1")
        self.assertIn("[ok] example.com resolves (expected with --egress)", egress)

    def test_the_interface_count_is_reported(self) -> None:
        # The host has whatever it has; the line names the count it judged.
        lines = self.run_check()
        self.assertRegex(lines, r"\[(ok|fail)\] the container has ")

    def test_the_report_says_when_no_ui_was_running(self) -> None:
        # An empty target list passes the UI probes vacuously; the report
        # must say so instead of reading as a tested boundary.
        lines = self.run_check(TOKENCRATE_UI_TARGETS="")
        self.assertIn("[warn] no browser UI running; UI isolation not tested", lines)
        self.assertNotIn("browser UI", lines.replace("no browser UI running", ""))
        self.assertNotIn("[warn] no browser UI", self.run_check())

    def test_each_rendered_set_check_reports_its_last_line(self) -> None:
        # One script per set, run in a scratch directory the script may use;
        # the last line it prints is the report, whether it passed or failed.
        checks = self.tmp / "checks"
        checks.mkdir()
        (checks / "good").write_text('echo "starting"\ntest -d "$CHECK_DIR"\necho "tool 1.0 answers --version"\n')
        (checks / "bad").write_text('echo "the tool is missing" >&2\nfalse\n')
        (checks / "silent").write_text("false\n")
        (self.home / ".pi" / "agent").mkdir(parents=True)
        (self.home / ".pi" / "agent" / "settings.json").write_text('{"packages": []}')
        lines = self.run_check(TOKENCRATE_AGENT="pi", TOKENCRATE_CHECKS_DIR=str(checks))
        self.assertIn("[ok] good: tool 1.0 answers --version", lines)
        self.assertIn("[fail] bad: the tool is missing", lines)
        self.assertIn("[fail] silent: the check script failed without output", lines)
        self.assertNotIn("starting", lines)
        # The set checks prove what a set does with no route out; an egress
        # run has one and skips them.
        egress = self.run_check(TOKENCRATE_AGENT="pi", TOKENCRATE_CHECKS_DIR=str(checks), TOKENCRATE_EGRESS="1")
        self.assertNotIn("good:", egress)

    def test_the_gateway_on_podman(self) -> None:
        lines = self.run_check(
            TOKENCRATE_ENGINE="podman", TOKENCRATE_AGENTS_GATEWAY="10.89.1.1", FAKE_GATEWAY="refused"
        )
        self.assertIn("[ok] the gateway 10.89.1.1 answers from the user's network namespace (rootless Podman)", lines)
        lines = self.run_check(TOKENCRATE_ENGINE="podman", TOKENCRATE_AGENTS_GATEWAY="10.89.1.1")
        self.assertIn("[ok] the gateway 10.89.1.1 does not answer", lines)


if __name__ == "__main__":
    unittest.main()
