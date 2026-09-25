"""Real sequential prompts with four live clients, plus independent UI lifecycle.

Called by integration.py; terminal binaries stay alive in RPC mode. PI WEB
uses its browser HTTP API, Paseo its daemon CLI. Browser rendering and terminal
screen interaction are separate manual checks, not claimed by this test.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import queue
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tokencrate import engine, env, runtime, session, uis

# The first omp prompt here is a cold prefill of about 16,000 tokens on the
# CI runner's CPU: it took over six minutes in passing runs and over ten in
# a slower one. A stuck client still fails well inside the job's hour.
RPC_TIMEOUT = float(os.environ.get("RPC_TIMEOUT", "1200"))


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

    ports = {name: free_port() for name in ("pi-web", "paseo")}
    before = stable_identity()
    assert len(before[1]) == 2, before
    cli("ui", "pi-web", "--sets", "", "--dir", str(project), "--port", ports["pi-web"])
    first = ui_ids("pi-web")
    cli("ui", "paseo", "--sets", "", "--dir", str(project), "--port", ports["paseo"])
    second = ui_ids("paseo")
    assert first == ui_ids("pi-web")
    assert before == stable_identity()
    print(f"four-client start: router/processes={before}, pi-web={first}, paseo={second}, ports={ports}", flush=True)
    home = session.agent_home_directory(settings, "pi", project)
    config = json.loads((home / ".paseo/config.json").read_text())
    assert config["agents"]["providers"]["pi"]["additionalModels"][0]["id"] == "tokencrate/ci-small", config
    # Each HTTP forwarder refuses the sibling origin as well as foreign hosts.
    for name, port in ports.items():
        for headers in (
            {"Origin": "http://evil.example.com"},
            {"Host": f"evil.example.com:{port}"},
            {"Origin": f"http://127.0.0.1:{ports['paseo' if name == 'pi-web' else 'pi-web']}"},
        ):
            try:
                request(f"http://127.0.0.1:{port}/", **headers)
            except urllib.error.HTTPError as error:
                assert error.code == 403, error
                error.close()
            else:
                raise AssertionError(f"{name} accepted foreign Host/Origin")
    clients = []
    try:
        clients = [RpcClient(root, name, project) for name in ("pi", "omp")]
        for client, marker in zip(clients, ("hello", "welcome"), strict=True):
            client.prompt(marker)
        base = f"http://127.0.0.1:{ports['pi-web']}"
        created = request(base + "/api/sessions", {"cwd": str(project)})
        print("PI WEB session:", created, flush=True)
        sid = created["id"]
        route = f"/api/sessions/{urllib.parse.quote(sid)}"
        query = "?" + urllib.parse.urlencode({"cwd": str(project)})
        request(
            base + route + "/prompt",
            {"cwd": str(project), "text": "Reply with the single word hello. Do not use tools."},
        )

        def web_answer():
            page = request(base + route + "/messages" + query)
            messages = page.get("messages", []) if isinstance(page, dict) else page
            return next((m for m in messages if assistant_text(m)), None)

        answer = until(web_answer)
        print("PI WEB assistant:", answer, flush=True)
        assert answer.get("model") == "ci-small", answer
        # Title generation uses a separate request, outside isStreaming.
        # The pinned UI assigns a name only when it finishes (or falls back).
        until(lambda: any(s["id"] == sid and s.get("name") for s in request(base + "/api/sessions" + query)))
        until(lambda: not request(base + route + "/status" + query)["isStreaming"])
        paseo = selected.command(
            "exec",
            second[0],
            "paseo",
            "run",
            "--provider",
            "pi",
            "--model",
            "tokencrate/ci-small",
            "--thinking",
            "off",
            "Reply with the single word welcome. Do not use tools.",
            capture=True,
        )
        print("Paseo run:", paseo.stdout, flush=True)
        agent_id = re.search(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", paseo.stdout).group()
        records = list((home / ".paseo/agents").rglob(f"{agent_id}.json"))
        assert len(records) == 1, "Paseo did not save the agent record from this run"
        record = json.loads(records[0].read_text())
        assert record["config"]["model"] == "tokencrate/ci-small", record
        assert record["runtimeInfo"]["model"] == "tokencrate/ci-small", record
        relative = Path(record["persistence"]["nativeHandle"]).relative_to("/home/agent")
        answers = [json.loads(line).get("message", {}) for line in (home / relative).read_text().splitlines()]
        answer = next((m for m in answers if assistant_text(m)), None)
        assert answer and answer.get("model") == "ci-small", answers
        print(
            f"Paseo assistant: {assistant_text(answer)!r}, model={answer['model']}, session={relative.name}", flush=True
        )
        clients[0].prompt("hello")
        assert all(c.process.poll() is None for c in clients), "a terminal client stopped"
        assert first == ui_ids("pi-web") and second == ui_ids("paseo")
        assert before == stable_identity(), (before, stable_identity())
        assert runtime.model_states(settings)["ci-small"] == "loaded"
        print("all four clients answered with the same router/model process identity", flush=True)
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
        # A failed custom UI launch leaves both running siblings available.
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
            assert first == ui_ids("pi-web") and second == ui_ids("paseo")
            logs = selected.command("logs", uis.container_names("concurrent-failure")[0], capture=True)
            assert logs.returncode == 0
            cli("ui", "stop", "concurrent-failure")
        finally:
            import shutil

            shutil.rmtree(failing)
        assert before == stable_identity()
        # Collision must preserve all running container identities.
        refused = cli("ui", "paseo", "--sets", "", "--dir", str(project), "--port", ports["pi-web"], check=False)
        assert refused.returncode and "another container" in refused.stderr, refused
        assert first == ui_ids("pi-web") and second == ui_ids("paseo")
        assert before == stable_identity()
        cli("ui", "stop", "pi-web")
        assert selected.container_state(uis.container_names("pi-web")[0]) == "removed"
        assert second == ui_ids("paseo") and before == stable_identity()
        cli("ui", "pi-web", "--sets", "", "--dir", str(project), "--port", ports["pi-web"])
        assert request(base + route + "/messages" + query), "PI WEB transcript was not retained"
        assert second == ui_ids("paseo") and before == stable_identity()
        # Stop/restart Paseo independently and retain its provider settings
        # and daemon identity. PI WEB must continue answering the saved session.
        first = ui_ids("pi-web")
        retained = {
            name: (home / ".paseo" / name).read_bytes() for name in ("config.json", "server-id", "daemon-keypair.json")
        }
        cli("ui", "stop", "paseo")
        assert first == ui_ids("pi-web") and before == stable_identity()
        request(
            base + route + "/prompt",
            {"cwd": str(project), "text": "Reply with the single word hello. Do not use tools."},
        )

        # The fast fixture may have completed before the first poll; the
        # recorded transcript itself supplies the count of completed answers.
        def web_repeat():
            page = request(base + route + "/messages" + query)
            return len([m for m in page["messages"] if assistant_text(m)]) >= 2

        until(web_repeat)
        cli("ui", "paseo", "--sets", "", "--dir", str(project), "--port", ports["paseo"])
        assert first == ui_ids("pi-web") and before == stable_identity()
        assert all((home / ".paseo" / name).read_bytes() == value for name, value in retained.items())
        second = ui_ids("paseo")
        # A different project, selection and port apply only to the target UI.
        changed_port = free_port()
        cli("ui", "pi-web", "--sets", "coding", "--dir", str(other), "--port", changed_port)
        assert second == ui_ids("paseo") and before == stable_identity()
        changed = json.loads(
            selected.command("inspect", "--format", "{{json .}}", ui_ids("pi-web")[0], capture=True).stdout
        )
        assert f"TOKENCRATE_PROJECT_DIR={other}" in changed["Config"]["Env"]
        assert "TOKENCRATE_PRESET=ci-small" in changed["Config"]["Env"]
        # Starts issued close together must each publish their own launch
        # definition. Both targets change, while the model identity stays put.
        commands = [
            ["ui", "pi-web", "--sets", "", "--dir", str(project), "--port", ports["pi-web"]],
            ["ui", "paseo", "--sets", "coding", "--dir", str(other), "--port", ports["paseo"]],
        ]
        # Drain both builds while they run: sequential communicate() calls
        # can fill the second launch's output pipe while it holds the lock.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            starting = [pool.submit(cli, *args) for args in commands]
            for future in starting:
                future.result()
        for name, expected in (("pi-web", project), ("paseo", other)):
            current = json.loads(
                selected.command("inspect", "--format", "{{json .}}", ui_ids(name)[0], capture=True).stdout
            )
            assert f"TOKENCRATE_PROJECT_DIR={expected}" in current["Config"]["Env"]
        assert before == stable_identity()
        cli("ui", "stop")
        assert not uis.containers(selected)
        assert before == stable_identity()
        assert (home / ".paseo/config.json").exists()
        print("independent UI lifecycle, retained state, failed launches and close starts passed", flush=True)
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
