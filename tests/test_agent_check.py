"""The containment check (services/agents/agent-check.sh) run on the host
with stub commands on PATH, so every branch of the gateway probe runs
without an engine. The route probes read the host's own tables and are
expected to fail here; the test asserts the lines it drives."""

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
            ("curl", '#!/bin/sh\ncase "$*" in *llama:8080/health*) exit 0 ;; *) exit 7 ;; esac\n'),
            ("getent", "#!/bin/sh\nexit 2\n"),
            ("dotnet", '#!/bin/sh\ntouch "$HOME/dotnet-called"\nexit 1\n'),
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
        self.assertFalse((self.home / "dotnet-called").exists(), "OMP must not run pi's toolchain probes")
        return result.stdout

    def test_the_gateway_on_docker(self) -> None:
        # No gateway: the isolated network. Any gateway: a failure, answering or not.
        lines = self.run_check(TOKENCRATE_ENGINE="docker", TOKENCRATE_AGENTS_GATEWAY="")
        self.assertIn("[ok] the agents network has no gateway address; no host address is reachable", lines)
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

    def test_the_gateway_on_podman(self) -> None:
        lines = self.run_check(
            TOKENCRATE_ENGINE="podman", TOKENCRATE_AGENTS_GATEWAY="10.89.1.1", FAKE_GATEWAY="refused"
        )
        self.assertIn("[ok] the gateway 10.89.1.1 answers from the user's network namespace (rootless Podman)", lines)
        lines = self.run_check(TOKENCRATE_ENGINE="podman", TOKENCRATE_AGENTS_GATEWAY="10.89.1.1")
        self.assertIn("[ok] the gateway 10.89.1.1 does not answer", lines)


if __name__ == "__main__":
    unittest.main()
