"""Real sequential prompts with live clients, plus independent UI lifecycle.

Called by integration.py; terminal binaries stay alive in RPC mode. pi-web
uses its browser HTTP API. TOKENCRATE_CONCURRENT_AGENTS
selects the terminal clients (default "pi,omp"); CI sets "pi" to skip omp's
cold prompt. Browser rendering and terminal screen interaction are separate
manual checks, not claimed by this test.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tokencrate import engine, env, runtime, session, uis

# omp's first prompt here is a cold prompt: on a 4-vCPU CI runner it took
# six to eleven minutes.
RPC_TIMEOUT = float(os.environ.get("RPC_TIMEOUT", "1200"))
MARKERS = {"pi": "hello", "omp": "welcome"}
AGENTS = os.environ.get("TOKENCRATE_CONCURRENT_AGENTS", "pi,omp").split(",")


def request(url: str, body: dict | None = None, **headers) -> object:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


def until(probe, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("acceptance condition did not complete before its timeout")


def assistant_text(message: dict) -> str:
    if message.get("role") != "assistant":
        return ""
    return "".join(part.get("text", "") for part in message.get("content", []) if part.get("type") == "text").strip()


class RpcClient:
    def __init__(self, root: Path, name: str, project: Path):
        self.events = queue.Queue()
        self.output = []
        args = ["bash", "bin/tokencrate", "agent", name, "--preset", "ci-small", "--dir", str(project)]
        if name == "pi":
            args += ["--sets", ""]
        args += ["--", "--mode", "rpc"]
        self.process = subprocess.Popen(
            args,
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        def read():
            for line in self.process.stdout:
                self.output.append(line)
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    pass

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def receive(self, predicate):
        deadline = time.monotonic() + RPC_TIMEOUT
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=1)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise AssertionError("RPC process exited: " + "".join(self.output)[-5000:]) from None
                continue
            if predicate(event):
                return event
        raise AssertionError(f"RPC response timeout ({RPC_TIMEOUT:g}s, RPC_TIMEOUT): " + "".join(self.output)[-5000:])

    def prompt(self, marker: str):
        self.send({"type": "get_state", "id": "state"})
        state = self.receive(lambda event: event.get("id") == "state" and event.get("type") == "response")
        assert state.get("success"), state
        assert state["data"]["model"]["id"] == "ci-small", state
        self.send({"type": "prompt", "message": f"Reply with the single word {marker}. Do not use tools."})
        message = self.receive(
            lambda event: event.get("type") == "message_end" and assistant_text(event.get("message", {}))
        )["message"]
        assert message.get("model") == "ci-small", message
        assert assistant_text(message), message
        self.receive(lambda event: event.get("type") == "agent_end")
        print(f"RPC assistant: {assistant_text(message)!r}, model={message['model']}", flush=True)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            # The caller's isolated stack cleanup owns any leftover container.
            import signal

            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=20)
        self.reader.join(timeout=2)
        self.process.stdout.close()


def run(root: Path, project: Path) -> None:
    settings = env.load(root)
    selected = engine.detect(settings)

    def cli(*args, check=True):
        result = subprocess.run(
            ["bash", "bin/tokencrate", *args],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if check and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def identity():
        cid = selected.running_llama_id()
        # PID plus kernel start time for every router/model process, inside
        # the stable PID namespace. Neither a reused PID nor only a router ID
        # can hide a model reload.
        script = "for p in /proc/[0-9]*; do case $(cat $p/comm 2>/dev/null) in llama-server) cat $p/stat;; esac; done"
        return cid, selected.command("exec", cid, "sh", "-c", script, capture=True).stdout.splitlines()

    def stable_identity():
        cid, stats = identity()
        return cid, sorted((line.split()[0], line.split()[21]) for line in stats)

    def ui_ids(name):
        return tuple(
            selected.command("inspect", "--format", "{{.Id}}", n, capture=True).stdout.strip()
            for n in uis.container_names(name)
        )

    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return str(sock.getsockname()[1])

    port = free_port()
    before = stable_identity()
    assert len(before[1]) == 2, before
    cli("ui", "pi-web", "--sets", "", "--dir", str(project), "--port", port)
    first = ui_ids("pi-web")
    assert before == stable_identity()
    print(f"client start: agents={AGENTS}, router/processes={before}, pi-web={first}, port={port}", flush=True)
    # The forwarder refuses another loopback origin as well as foreign hosts.
    for headers in (
        {"Origin": "http://evil.example.com"},
        {"Host": f"evil.example.com:{port}"},
        {"Origin": f"http://127.0.0.1:{free_port()}"},
    ):
        try:
            request(f"http://127.0.0.1:{port}/", **headers)
        except urllib.error.HTTPError as error:
            assert error.code == 403, error
            error.close()
        else:
            raise AssertionError(f"pi-web accepted foreign Host/Origin {headers}")
    clients = []
    try:
        clients = [RpcClient(root, name, project) for name in AGENTS]
        for client, name in zip(clients, AGENTS, strict=True):
            client.prompt(MARKERS[name])
        base = f"http://127.0.0.1:{port}"
        prompt = {"type": "prompt", "message": "Reply with the single word hello. Do not use tools."}
        created = request(base + "/api/agent/new", {"cwd": str(project), **prompt})
        print("pi-web session:", created, flush=True)
        assert created["model"] == {"provider": "tokencrate", "modelId": "ci-small"}, created
        sid = created["sessionId"]
        agent = f"{base}/api/agent/{urllib.parse.quote(sid)}"

        def web_answers():
            page = request(f"{base}/api/sessions/{urllib.parse.quote(sid)}")
            return [m for m in page["context"]["messages"] if assistant_text(m)]

        answer = until(web_answers)[0]
        print("pi-web assistant:", answer, flush=True)
        assert answer.get("model") == "ci-small", answer
        until(lambda: not request(agent, {"type": "get_state"})["data"]["isStreaming"])
        # The sidebar state (here a pin) is the one pi-web file the set retains.
        state = request(base + "/api/sessions/ui-state", {"action": "set", "ids": [sid], "pinned": True})
        assert state["state"]["sessions"][sid]["pinnedAt"], state
        clients[0].prompt("hello")
        assert all(c.process.poll() is None for c in clients), "a terminal client stopped"
        assert first == ui_ids("pi-web")
        assert before == stable_identity(), (before, stable_identity())
        assert runtime.model_states(settings)["ci-small"] == "loaded"
        print(f"{len(clients) + 1} clients answered with the same router/model process identity", flush=True)
        targets = uis.peer_targets(selected)
        assert targets, "no UI peers discovered for containment"
        probe_script = r"""
fail=0
for target in $TOKENCRATE_UI_TARGETS; do
    peer=${target%:*}; port=${target##*:}
    case "$peer" in
        *[a-zA-Z]*) if getent hosts "$peer" >/dev/null; then echo "resolved $peer"; fail=1; fi;;
    esac
    if timeout 2 bash -c 'exec 3<>/dev/tcp/"$1"/"$2"' _ "$peer" "$port" 2>/dev/null; then
        echo "reached $target"; fail=1
    fi
done
exit "$fail"
"""
        other = project.with_name(project.name + "-peer")
        other.mkdir(exist_ok=True)
        for name in ("pi", "omp"):
            peer_home = session.agent_home_directory(settings, name, other)
            session.prepare_mountpoints(peer_home, name)
            extra = session.session_variables(other, peer_home, "ci-small")
            if name == "pi":
                extra.update(session.render_image(settings, []))
            for egress in (False, True):
                selected.compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "-e",
                    f"TOKENCRATE_UI_TARGETS={targets}",
                    f"agent-{name}",
                    "bash",
                    "-c",
                    probe_script,
                    profiles=(f"agent-{name}",),
                    egress=egress,
                    capture=True,
                    **extra,
                )
                print(f"containment: {name}, egress={egress}, targets={targets}", flush=True)
        assert before == stable_identity()
        # A failed custom UI launch leaves the running UI available.
        failing = root / "local/agent-sets/concurrent-failure"
        failing.mkdir(parents=True)
        try:
            (failing / "set.toml").write_text(
                'schema = 1\ndescription = "Failure fixture"\n[ui]\ncommand = "false"\nport = 15555\n'
                'state = ".concurrent-failure"\n'
            )
            failed = cli(
                "ui", "concurrent-failure", "--sets", "", "--dir", str(other), "--port", free_port(), check=False
            )
            stopped = f"the container {uis.container_names('concurrent-failure')[0]} is exited before it answered"
            assert failed.returncode and stopped in failed.stderr, failed
            assert first == ui_ids("pi-web")
            logs = selected.command("logs", uis.container_names("concurrent-failure")[0], capture=True)
            assert logs.returncode == 0
            cli("ui", "stop", "concurrent-failure")
            # Another UI on a held port is refused before anything starts.
            refused = cli("ui", "concurrent-failure", "--sets", "", "--dir", str(other), "--port", port, check=False)
            assert refused.returncode and "another container" in refused.stderr, refused
            assert first == ui_ids("pi-web")
        finally:
            import shutil

            shutil.rmtree(failing)
        assert before == stable_identity()
        # Stop and restart pi-web alone: the model stays, and the saved
        # session and its pin are retained and the session answers again.
        cli("ui", "stop", "pi-web")
        assert selected.container_state(uis.container_names("pi-web")[0]) == "removed"
        assert before == stable_identity()
        cli("ui", "pi-web", "--sets", "", "--dir", str(project), "--port", port)
        assert web_answers(), "pi-web transcript was not retained"
        assert request(base + "/api/sessions/ui-state")["state"]["sessions"][sid]["pinnedAt"], (
            "the pin was not retained"
        )
        assert before == stable_identity()
        request(agent, prompt)
        # The fast fixture may have completed before the first poll; the
        # recorded transcript itself supplies the count of completed answers.
        until(lambda: len(web_answers()) >= 2)
        # A different project, selection and port apply to the replaced UI
        # and leave the model alone.
        cli("ui", "pi-web", "--sets", "coding", "--dir", str(other), "--port", free_port())
        assert before == stable_identity()
        changed = json.loads(
            selected.command("inspect", "--format", "{{json .}}", ui_ids("pi-web")[0], capture=True).stdout
        )
        assert f"TOKENCRATE_PROJECT_DIR={other}" in changed["Config"]["Env"]
        assert "TOKENCRATE_PRESET=ci-small" in changed["Config"]["Env"]
        cli("ui", "stop")
        assert not uis.containers(selected)
        assert before == stable_identity()
        print("UI lifecycle, retained state, and failed launches passed", flush=True)
        # Both terminal run --rm containers are still alive. Whole-stack
        # shutdown must remove them before removing their networks.
        cli("down")
        assert not selected.containers(), "down left project containers behind"
        networks = selected.command(
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label={engine.PROJECT_LABEL}={settings.project_name}",
            capture=True,
        ).stdout.strip()
        assert not networks, "down left project networks behind"
        cli("up")
        print("whole-stack shutdown with live terminal clients passed", flush=True)
    finally:
        for client in clients:
            client.close()
        cli("ui", "stop", check=False)


if __name__ == "__main__":
    import sys

    run(Path.cwd(), Path(sys.argv[1]))
