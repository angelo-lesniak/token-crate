"""Tests for the API probe against a canned router-shaped HTTP server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from tokencrate import TokenCrateError, localhttp, probe


class FakeRouter(BaseHTTPRequestHandler):
    """Answers like llama-server in router mode: the listing endpoints are its
    own, everything else is routed by the `model` field of the body or the
    `model` query parameter, and a request without a known model is a 400.
    Behavior is switched through class attributes so one server serves
    several test cases."""

    MODELS = ("fixture-preset", "other")
    reject_mid_system = False
    tool_call = True
    ignore_effort = False
    finish_reason = "stop"
    requests: list[dict] = []

    def log_message(self, *_args):  # silence the default logger
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self, model: object) -> bool:
        """The router's answer for a missing or unknown model: a 400."""
        if not isinstance(model, str) or not model:
            self.send_json({"error": {"code": 400, "message": "model name is missing from the request"}}, 400)
            return False
        if model not in self.MODELS:
            self.send_json({"error": {"code": 400, "message": f"model '{model}' not found"}}, 400)
            return False
        return True

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/health":
            self.send_json({"status": "ok"})
        elif path in ("/models", "/v1/models"):
            self.send_json({"data": [{"id": name, "status": {"value": "loaded"}} for name in self.MODELS]})
        elif path == "/props":
            if self.route(urllib.parse.parse_qs(query).get("model", [None])[0]):
                self.send_json(
                    {
                        "build_info": "b10920",
                        "model_path": "/models/x.gguf",
                        "default_generation_settings": {"n_ctx": 4096},
                    }
                )
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append({"path": self.path, "payload": payload})
        if not self.route(payload.get("model")):
            return
        if self.path == "/tokenize":
            self.send_json({"tokens": [1, 2]})
            return
        if self.path == "/apply-template":
            messages = payload.get("messages", [])
            if self.reject_mid_system and any(message["role"] == "system" for message in messages[1:]):
                self.send_json({"error": {"message": "System message must be at the beginning."}}, 500)
                return
            rendered = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
            effort = (payload.get("chat_template_kwargs") or {}).get("reasoning_effort")
            if effort and not self.ignore_effort:
                rendered = f"<|im_start|>system\nReasoning effort is set to {effort}.<|im_end|>\n" + rendered
            self.send_json({"prompt": rendered})
            return
        if self.path != "/v1/chat/completions":
            self.send_json({"error": "not found"}, 404)
            return
        messages = payload.get("messages", [])
        if self.reject_mid_system and any(message["role"] == "system" for message in messages[1:]):
            self.send_json({"error": {"message": "System message must be at the beginning."}}, 500)
            return
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if self.tool_call and payload.get("tools"):
                chunks = [
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [{"index": 0, "function": {"name": "get_weather", "arguments": ""}}]
                                }
                            }
                        ]
                    },
                    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"city": "Pa'}}]}}]},
                    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ris"}'}}]}}]},
                ]
            else:
                chunks = [{"choices": [{"delta": {"content": "I cannot call tools."}}]}]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self.send_json(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hello from Python."},
                        "finish_reason": self.finish_reason,
                    }
                ],
                "timings": {"prompt_n": 12, "predicted_n": 8, "prompt_per_second": 500.0, "predicted_per_second": 42.0},
            }
        )


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeRouter)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeRouter.reject_mid_system = False
        FakeRouter.tool_call = True
        FakeRouter.ignore_effort = False
        FakeRouter.finish_reason = "stop"
        FakeRouter.requests = []

    def test_local_clients_bypass_proxies_without_changing_external_transport(self):
        proxy_requests = []

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                proxy_requests.append(self.path)
                self.send_error(502, "unexpected proxy request")

            do_POST = do_GET

        proxy = HTTPServer(("127.0.0.1", 0), Proxy)
        self.addCleanup(proxy.server_close)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(proxy.shutdown)
        environment = {key: value for key, value in os.environ.items() if not key.lower().endswith("_proxy")}
        environment["http_proxy"] = f"http://127.0.0.1:{proxy.server_address[1]}"
        # Import in a fresh process with the proxy already configured: an
        # opener created before the environment changes could hide the bug.
        script = """
import json
import sys
import urllib.error
import urllib.request
from tokencrate import probe, runtime

url = sys.argv[1]
assert json.loads(runtime.http_get(url + '/health')) == {'status': 'ok'}
assert runtime.http_post(url + '/tokenize', {'model': 'fixture-preset'}) == ''
assert runtime.http_post(url + '/tokenize', {'model': 'missing'}) == 'HTTP 400'
assert probe.request(url + '/health') == {'status': 'ok'}
answer = probe.chat(url, 'fixture-preset', [{'role': 'user', 'content': 'hello'}])
assert probe.message_text(answer) == 'Hello from Python.'
assert probe.streamed_tool_call(url, 'fixture-preset')['name'] == 'get_weather'
# The ordinary urllib transport still honors the proxy for other callers.
try:
    urllib.request.urlopen(url + '/proxy-check', timeout=5)
except urllib.error.HTTPError as error:
    assert error.code == 502
else:
    raise AssertionError('the default transport bypassed the proxy')
"""
        result = subprocess.run(
            [sys.executable, "-c", script, self.url],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(proxy_requests, [f"{self.url}/proxy-check"])

    def test_smoke_and_bench_pass_against_a_healthy_server(self):
        results = probe.smoke(self.url, "fixture-preset", efforts=["low", "xhigh"])
        self.assertTrue(all(result.passed for result in results), [r.detail for r in results if not r.passed])
        # Every proxied request names the model in its body, as the router requires.
        self.assertTrue(all(request["payload"].get("model") == "fixture-preset" for request in FakeRouter.requests))
        self.assertEqual(
            {request["path"] for request in FakeRouter.requests},
            {"/v1/chat/completions", "/apply-template", "/tokenize"},
        )
        names = [result.name for result in results]
        self.assertIn("streamed tool call", names)
        self.assertIn("mid-conversation system message", names)
        self.assertIn("reply terminates", names)
        self.assertIn("template keeps later system messages", names)
        self.assertIn("reasoning effort reaches the template", names)
        by_name = {result.name: result for result in results}
        self.assertEqual(by_name["reply terminates"].detail, "finish_reason stop on 2 completion(s)")
        basic = [result.name for result in probe.smoke(self.url, "fixture-preset", basic=True)]
        self.assertNotIn("streamed tool call", basic)
        # A toy model never emits the end-of-turn token, so judging
        # termination on it would always fail.
        self.assertNotIn("reply terminates", basic)
        self.assertIn("template keeps later system messages", basic)
        facts = probe.server_facts(self.url, "fixture-preset")
        self.assertEqual(facts["build"], "b10920")
        text, status = probe.smoke_report("fixture-preset", self.url, results, facts)
        self.assertEqual(status, 0)
        self.assertTrue(text.startswith("# TokenCrate smoke report\n\n- Date: "), text)
        self.assertIn("- Preset: `fixture-preset`\n", text)
        self.assertIn(f"- Endpoint: {self.url}\n", text)
        self.assertIn("- build: b10920\n- model_path: /models/x.gguf\n- n_ctx: 4096\n", text)
        self.assertIn("\n| Check | Result | Detail |\n| --- | --- | --- |\n| model listing | pass |", text)
        self.assertIn("| streamed tool call | pass |", text)
        self.assertTrue(text.endswith("|\n\nAll checks passed.\n"), text)

        FakeRouter.requests = []
        rows = probe.bench(self.url, ["fixture-preset"], iterations=2, long=True)
        self.assertEqual([row["run"] for row in rows], ["short", "long"])
        self.assertEqual(rows[0]["generation_tps"], 42.0)
        self.assertEqual(rows[0]["iterations"], 2)
        bench_requests = [request for request in FakeRouter.requests if request["path"] == "/v1/chat/completions"]
        self.assertEqual(len(bench_requests), 1 + 2 * 2)
        # Every iteration must process the whole prompt again, or the prompt
        # speed measures one cached token.
        self.assertEqual(bench_requests[1]["payload"]["temperature"], 0)
        self.assertIs(bench_requests[1]["payload"]["cache_prompt"], False)
        text = probe.bench_report(self.url, rows, {"build": "b10920"})
        self.assertTrue(text.startswith("# TokenCrate bench report\n\n- Date: "), text)
        self.assertIn(f"- Endpoint: {self.url}\n- build: b10920\n\n| Preset | Run |", text)
        self.assertIn("| fixture-preset | short | 12 | 8 | 500.0 | 42.0 | 2 |", text)
        self.assertTrue(text.endswith("prompt caching disabled for the request.\n"), text)

    def test_completion_checks_ask_for_the_lowest_effort_and_room_for_an_answer(self):
        FakeRouter.requests.clear()
        results = {r.name: r for r in probe.smoke(self.url, "fixture-preset", basic=True, efforts=["low", "xhigh"])}
        self.assertTrue(results["chat completion"].passed)
        completions = [r["payload"] for r in FakeRouter.requests if r["path"] == "/v1/chat/completions"]
        self.assertEqual(len(completions), 2)
        for payload in completions:
            self.assertEqual(payload["max_tokens"], probe.ANSWER_TOKENS)
            self.assertEqual(payload["chat_template_kwargs"], {"reasoning_effort": "low"})
        # A set that uses the model's own template is not asked to keep a
        # later system message.
        names = [
            r.name for r in probe.smoke(self.url, "fixture-preset", basic=True, efforts=[], patched_template=False)
        ]
        self.assertNotIn("template keeps later system messages", names)
        self.assertIn("mid-conversation system message", names)

    def test_smoke_reports_failures(self):
        # The stock template rejects a later system message, the model calls
        # no tool, and the template ignores the effort.
        FakeRouter.reject_mid_system = True
        FakeRouter.tool_call = False
        FakeRouter.ignore_effort = True
        results = {r.name: r for r in probe.smoke(self.url, "fixture-preset", efforts=["low", "xhigh"])}
        self.assertFalse(results["mid-conversation system message"].passed)
        self.assertIn("HTTP 500", results["mid-conversation system message"].detail)
        self.assertFalse(results["template keeps later system messages"].passed)
        self.assertFalse(results["streamed tool call"].passed)
        self.assertFalse(results["reasoning effort reaches the template"].passed)
        self.assertIn("identically", results["reasoning effort reaches the template"].detail)
        self.assertTrue(results["chat completion"].passed)
        text, status = probe.smoke_report("fixture-preset", self.url, list(results.values()), {})
        self.assertEqual(status, 1)
        self.assertIn("| mid-conversation system message | FAIL | HTTP 500 from", text)
        self.assertIn("| chat completion | pass |", text)
        self.assertTrue(text.endswith("|\n\n4 check(s) failed.\n"), text)

        # A preset with fewer than two efforts skips the comparison; a preset
        # the router does not know fails the listing and every routed request.
        FakeRouter.ignore_effort = False
        results = {r.name: r for r in probe.smoke(self.url, "fixture-preset", basic=True, efforts=["low"])}
        self.assertTrue(results["reasoning effort reaches the template"].passed)
        self.assertIn("nothing to compare", results["reasoning effort reaches the template"].detail)
        results = {result.name: result for result in probe.smoke(self.url, "missing-preset")}
        self.assertFalse(results["model listing"].passed)
        self.assertIn("missing-preset is not listed", results["model listing"].detail)
        self.assertIn("HTTP 400", results["tokenize"].detail)
        self.assertIn("HTTP 400", probe.server_facts(self.url, "missing-preset")["error"])

    def test_a_reply_that_runs_into_the_token_budget_fails_the_termination_check(self):
        # A thinking loop ends with finish_reason length; the answer itself
        # may still look fine, so the completion check alone would pass.
        FakeRouter.finish_reason = "length"
        results = {r.name: r for r in probe.smoke(self.url, "fixture-preset")}
        self.assertTrue(results["chat completion"].passed)
        self.assertFalse(results["reply terminates"].passed)
        self.assertIn(
            "chat completion: length, mid-conversation system message: length", results["reply terminates"].detail
        )
        self.assertIn(f"ran into the {probe.ANSWER_TOKENS}-token budget", results["reply terminates"].detail)
        # Without any completion there is nothing to judge.
        FakeRouter.finish_reason = "stop"
        results = {r.name: r for r in probe.smoke(f"{self.url}/nope", "fixture-preset")}
        self.assertFalse(results["reply terminates"].passed)
        self.assertEqual(results["reply terminates"].detail, "no completion to judge")
        # The completions wait longer than the other probes: the first one
        # loads the model, and the answer budget at a slow preset takes minutes.
        self.assertGreater(probe.COMPLETION_TIMEOUT, localhttp.LOAD_TIMEOUT)

    def test_request_failures_are_user_facing_errors(self):
        with self.assertRaises(TokenCrateError) as caught:
            probe.request(f"{self.url}/nope", timeout=5)
        self.assertIn("HTTP 404 from", str(caught.exception))
        # The fake answers any model name, so an unknown path stands in for a
        # server that rejects the request.
        with self.assertRaises(TokenCrateError) as caught:
            probe.bench(f"{self.url}/nope", ["fixture-preset"], iterations=1, long=False)
        self.assertIn("HTTP 404 from", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
