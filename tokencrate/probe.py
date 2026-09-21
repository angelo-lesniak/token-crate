"""API smoke probes and benchmarks against the running llama-server router.

`smoke` proves the paths agents depend on: health, model listing, a plain chat
completion, a streamed tool call, and a system message in the middle of a
conversation (the case the stock Qwen3.8 template rejects). `bench` measures
prompt-processing and generation speed from llama-server's `timings` object.
The report functions return Markdown text; the CLI runs the probe on the host
against the published loopback port, prints the report, and saves it under
reports/.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import TokenCrateError
from .localhttp import OPENER

LOAD_TIMEOUT = 900  # seconds; the first request loads the model from disk
# A chat completion may be the first request, so it waits for the load, and
# then for up to ANSWER_TOKENS at the slowest shipped preset (a model with
# expert weights in system memory generates about 6 tokens per second, so a
# full answer budget alone takes about three minutes).
COMPLETION_TIMEOUT = 1500
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}


@dataclass
class Result:
    name: str
    passed: bool
    detail: str


def request(url: str, payload: dict | None = None, *, timeout: int = LOAD_TIMEOUT, stream: bool = False):
    data = None
    headers = {"User-Agent": "TokenCrate-probe/1"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        response = OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        with error:
            body = error.read().decode("utf-8", errors="replace")[:500]
        raise TokenCrateError(f"HTTP {error.code} from {url}: {body}") from error
    except (OSError, urllib.error.URLError) as error:
        raise TokenCrateError(f"could not reach {url}: {error}") from error
    if stream:
        return response
    with response:
        body = response.read().decode("utf-8", errors="replace")
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def chat(url: str, model: str, messages: list[dict], **extra) -> dict:
    payload = {"model": model, "messages": messages, "stream": False, **extra}
    started = time.monotonic()
    response = request(f"{url}/v1/chat/completions", payload, timeout=COMPLETION_TIMEOUT)
    elapsed = time.monotonic() - started
    if not isinstance(response, dict):
        raise TokenCrateError("chat completion did not return JSON")
    response["_elapsed"] = elapsed
    return response


def streamed_tool_call(url: str, model: str) -> dict:
    payload = {
        "model": model,
        "stream": True,
        "max_tokens": 256,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant. Use the available tool when a tool fits the request.",
            },
            {"role": "user", "content": "What is the weather in Paris right now? Use the get_weather tool."},
        ],
        "tools": [WEATHER_TOOL],
        "tool_choice": "auto",
    }
    response = request(f"{url}/v1/chat/completions", payload, stream=True)
    name_parts: list[str] = []
    argument_parts: list[str] = []
    content_parts: list[str] = []
    with response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                event = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
                for call in delta.get("tool_calls", []) or []:
                    function = call.get("function", {})
                    if function.get("name"):
                        name_parts.append(function["name"])
                    if function.get("arguments"):
                        argument_parts.append(function["arguments"])
    return {
        "name": "".join(name_parts),
        "arguments": "".join(argument_parts),
        "content": "".join(content_parts),
    }


def message_text(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


def finish_reason(response: dict) -> str:
    choices = response.get("choices") or []
    return str((choices[0] if choices else {}).get("finish_reason") or "")


# Enough for a thinking model's shortest reasoning plus the answer; the
# completion checks ask for the preset's lowest effort so the reasoning
# stays short, and judge the answer, not the reasoning.
ANSWER_TOKENS = 1024


def smoke(
    url: str,
    model: str,
    *,
    basic: bool = False,
    efforts: list[str] | None = None,
    patched_template: bool = True,
) -> list[Result]:
    """Run the probes. `basic` skips the checks that need a capable model
    (tool calling, and ending a reply on its own: a toy model never emits
    the end-of-turn token and always runs into the budget), so a tiny CI
    model can still prove the transport, the chat template, and the
    mid-conversation system message path. The
    render check applies only to a model set that ships the patched
    template (`patched_template`); the model's own template is not asked
    to keep a later system message."""
    results: list[Result] = []
    lowest_effort = {"chat_template_kwargs": {"reasoning_effort": efforts[0]}} if efforts else {}
    # The finish reason of every completion, judged once by reply_terminates.
    completions: dict[str, str] = {}

    def record(name: str, function):
        try:
            detail = function()
            results.append(Result(name, True, detail))
        except TokenCrateError as error:
            results.append(Result(name, False, str(error)))
        except Exception as error:  # report every failure in the table
            results.append(Result(name, False, f"{type(error).__name__}: {error}"))

    def models():
        body = request(f"{url}/v1/models", timeout=30)
        ids = [item.get("id") for item in (body or {}).get("data", [])]
        if model not in ids:
            raise TokenCrateError(f"{model} is not listed; available: {', '.join(map(str, ids))}")
        return f"{len(ids)} model(s) listed, including {model}"

    def completion():
        response = chat(
            url,
            model,
            [
                {"role": "system", "content": "Answer with one short sentence."},
                {"role": "user", "content": "Say hello and name one programming language."},
            ],
            max_tokens=ANSWER_TOKENS,
            **lowest_effort,
        )
        completions["chat completion"] = finish_reason(response)
        text = message_text(response)
        if not text:
            raise TokenCrateError("empty assistant message")
        timings = response.get("timings") or {}
        speed = timings.get("predicted_per_second")
        detail = f"{len(text)} characters in {response['_elapsed']:.1f}s"
        if speed:
            detail += f", {speed:.1f} tokens/s generation"
        return detail

    def tool_call():
        call = streamed_tool_call(url, model)
        if call["name"] != "get_weather":
            raise TokenCrateError(
                f"no get_weather tool call in the stream (name={call['name']!r}, content={call['content'][:120]!r})"
            )
        try:
            arguments = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError as error:
            raise TokenCrateError(f"tool call arguments are not valid JSON: {call['arguments']!r}") from error
        if "paris" not in str(arguments.get("city", "")).lower():
            raise TokenCrateError(f"tool call arguments do not name Paris: {arguments}")
        return f"streamed tool call get_weather({json.dumps(arguments)})"

    def mid_conversation_system():
        response = chat(
            url,
            model,
            [
                {"role": "system", "content": "You are a coding assistant."},
                {"role": "user", "content": "Remember the number 41."},
                {"role": "assistant", "content": "I will remember 41."},
                {"role": "system", "content": "The user now prefers answers in one word."},
                {"role": "user", "content": "What is the number plus one?"},
            ],
            max_tokens=ANSWER_TOKENS,
            **lowest_effort,
        )
        completions["mid-conversation system message"] = finish_reason(response)
        text = message_text(response)
        if not text:
            raise TokenCrateError("empty assistant message after a mid-conversation system message")
        return f"accepted a system message after position 0 (answer: {text[:40]!r})"

    def reply_terminates():
        # A model that loops in its reasoning (seen on abliterated Qwen3.8
        # builds) runs into the token budget and ends with `length`; a
        # reply that ends on its own says `stop`.
        if not completions:
            raise TokenCrateError("no completion to judge")
        truncated = [name for name, reason in completions.items() if reason != "stop"]
        if truncated:
            reasons = ", ".join(f"{name}: {completions[name] or 'none'}" for name in truncated)
            raise TokenCrateError(
                f"finish_reason is not stop ({reasons}); the reply ran into the {ANSWER_TOKENS}-token budget"
            )
        return f"finish_reason stop on {len(completions)} completion(s)"

    def effort_reaches_template():
        # Rendering the same prompt with two of the preset's declared efforts
        # through chat_template_kwargs (what the agents send per turn) must
        # give different prompts, or the template ignores the effort.
        chosen = list(efforts or [])[:2]
        if len(chosen) < 2:
            return "fewer than two efforts declared; nothing to compare"
        prompts = {}
        for effort in chosen:
            rendered = request(
                f"{url}/apply-template",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "Hello."}],
                    "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": effort},
                },
                timeout=120,
            )
            prompt = (rendered or {}).get("prompt") if isinstance(rendered, dict) else None
            if not isinstance(prompt, str) or not prompt:
                raise TokenCrateError(f"apply-template returned no prompt for effort {effort}")
            prompts[effort] = prompt
        first, second = chosen
        if prompts[first] == prompts[second]:
            raise TokenCrateError(f"the template renders efforts {first} and {second} identically")
        return f"efforts {first} and {second} render different prompts"

    def tokenize():
        body = request(f"{url}/tokenize", {"model": model, "content": "hello world"}, timeout=120)
        tokens = (body or {}).get("tokens")
        if not isinstance(tokens, list) or not tokens:
            raise TokenCrateError("tokenize returned no tokens")
        return f"{len(tokens)} tokens for 'hello world'"

    def template_render():
        # llama-server renders the chat template without generating, so this
        # proves the (patched) template accepts a system message after the
        # first turn and keeps it in the prompt.
        body = request(
            f"{url}/apply-template",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "First system message."},
                    {"role": "user", "content": "Hello."},
                    {"role": "assistant", "content": "Hi."},
                    {"role": "system", "content": "SECOND-SYSTEM-MARKER"},
                    {"role": "user", "content": "Continue."},
                ],
            },
            timeout=120,
        )
        prompt = (body or {}).get("prompt") if isinstance(body, dict) else None
        if not isinstance(prompt, str) or not prompt:
            raise TokenCrateError("apply-template returned no prompt")
        if "SECOND-SYSTEM-MARKER" not in prompt:
            raise TokenCrateError("the template dropped the mid-conversation system message")
        if "<|im_start|>system" in prompt and prompt.count("<|im_start|>system") < 2:
            raise TokenCrateError("the template merged the later system message into the first turn")
        return f"rendered {len(prompt)} characters including the later system message"

    record("model listing", models)
    record("chat completion", completion)
    if not basic:
        record("streamed tool call", tool_call)
    record("mid-conversation system message", mid_conversation_system)
    if not basic:
        record("reply terminates", reply_terminates)
    if patched_template:
        record("template keeps later system messages", template_render)
    record("reasoning effort reaches the template", effort_reaches_template)
    record("tokenize", tokenize)
    return results


def bench_prompt(tokens_target: int) -> str:
    base = (
        "You are reviewing a Python module that parses configuration files, validates "
        "the values, and renders a report. Summarize the risks in such a module. "
    )
    repeats = max(1, tokens_target // 40)
    return base * repeats


def bench(url: str, presets: list[str], iterations: int, long: bool) -> list[dict]:
    rows: list[dict] = []
    for preset in presets:
        chat(url, preset, [{"role": "user", "content": "Warm-up."}], max_tokens=8)
        runs: list[tuple[str, str]] = [("short", bench_prompt(300))]
        if long:
            runs.append(("long", bench_prompt(8000)))
        for label, prompt in runs:
            prompt_speeds: list[float] = []
            generation_speeds: list[float] = []
            prompt_tokens = 0
            generated_tokens = 0
            for _ in range(iterations):
                # cache_prompt=False makes every iteration process the whole
                # prompt again; otherwise llama-server reuses the cached prefix
                # and prompt_per_second measures one token.
                response = chat(
                    url,
                    preset,
                    [{"role": "user", "content": prompt}],
                    max_tokens=128,
                    temperature=0,
                    cache_prompt=False,
                )
                timings = response.get("timings") or {}
                if not timings:
                    raise TokenCrateError("the response has no timings object; is this llama-server?")
                prompt_speeds.append(float(timings.get("prompt_per_second") or 0))
                generation_speeds.append(float(timings.get("predicted_per_second") or 0))
                prompt_tokens = int(timings.get("prompt_n") or 0)
                generated_tokens = int(timings.get("predicted_n") or 0)
            rows.append(
                {
                    "preset": preset,
                    "run": label,
                    "prompt_tokens": prompt_tokens,
                    "generated_tokens": generated_tokens,
                    "prompt_tps": sum(prompt_speeds) / len(prompt_speeds),
                    "generation_tps": sum(generation_speeds) / len(generation_speeds),
                    "iterations": iterations,
                }
            )
    return rows


def server_facts(url: str, preset: str) -> dict:
    facts = {}
    try:
        props = request(f"{url}/props?model={urllib.parse.quote(preset, safe='')}", timeout=120)
        if isinstance(props, dict):
            facts["build"] = props.get("build_info")
            facts["model_path"] = props.get("model_path")
            defaults = props.get("default_generation_settings") or {}
            facts["n_ctx"] = defaults.get("n_ctx")
    except TokenCrateError as error:
        facts["error"] = str(error)
    return facts


def smoke_report(model: str, url: str, results: list[Result], facts: dict) -> tuple[str, int]:
    """The Markdown smoke report and the exit status (1 when a check failed)."""
    lines = ["# TokenCrate smoke report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- Preset: `{model}`")
    lines.append(f"- Endpoint: {url}")
    for key, value in facts.items():
        lines.append(f"- {key}: {value}")
    lines += ["", "| Check | Result | Detail |", "| --- | --- | --- |"]
    for result in results:
        lines.append(f"| {result.name} | {'pass' if result.passed else 'FAIL'} | {result.detail.replace('|', '/')} |")
    failed = [result for result in results if not result.passed]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)} check(s) failed.")
        return "\n".join(lines) + "\n", 1
    lines.append("All checks passed.")
    return "\n".join(lines) + "\n", 0


def bench_report(url: str, rows: list[dict], facts: dict) -> str:
    """The Markdown bench report."""
    lines = ["# TokenCrate bench report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- Endpoint: {url}")
    for key, value in facts.items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "| Preset | Run | Prompt tokens | Generated tokens | Prompt tokens/s | Generation tokens/s | Iterations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['preset']} | {row['run']} | {row['prompt_tokens']} | {row['generated_tokens']} | "
            f"{row['prompt_tps']:.1f} | {row['generation_tps']:.1f} | {row['iterations']} |"
        )
    lines += [
        "",
        "Speeds are averages of llama-server's per-request `timings` with prompt caching disabled for the request.",
    ]
    return "\n".join(lines) + "\n"
