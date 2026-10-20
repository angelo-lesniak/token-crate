"""API smoke probes and benchmarks against the running llama-server router.

`smoke` proves the paths agents depend on: health, model listing, a plain chat
completion, a streamed tool call, and a system message in the middle of a
conversation (the case the stock Qwen3.8 template rejects). `bench` measures
prompt-processing and generation speed from llama-server's `timings` object.
The report functions return Markdown text (`bench_json` the machine-readable
side of the bench); the CLI runs the probe on the host against the published
loopback port, prints the report, and saves it under reports/.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import TokenCrateError, stats
from .localhttp import LOAD_TIMEOUT, request
from .names import PRESET_NAME_RE

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


@dataclass(frozen=True)
class Smoke:
    """What the smoke checks share: the router, the preset, its declared
    efforts (the completions ask for the lowest), and the finish reason of
    every completion, judged once by `check_reply_terminates`."""

    url: str
    model: str
    efforts: tuple[str, ...]
    completions: dict[str, str] = field(default_factory=dict)

    def completion(self, name: str, messages: list[dict]) -> dict:
        """A completion with room for an answer at the lowest effort; its
        finish reason is kept under `name`."""
        effort = {"chat_template_kwargs": {"reasoning_effort": self.efforts[0]}} if self.efforts else {}
        response = chat(self.url, self.model, messages, max_tokens=ANSWER_TOKENS, **effort)
        self.completions[name] = finish_reason(response)
        return response

    def rendered_prompt(self, messages: list[dict], **extra) -> str:
        """The prompt llama-server renders for `messages` without generating."""
        body = request(f"{self.url}/apply-template", {"model": self.model, "messages": messages, **extra}, timeout=120)
        prompt = (body or {}).get("prompt") if isinstance(body, dict) else None
        return prompt if isinstance(prompt, str) else ""


def check_models(smoke: Smoke) -> str:
    body = request(f"{smoke.url}/v1/models", timeout=30)
    ids = [item.get("id") for item in (body or {}).get("data", [])]
    if smoke.model not in ids:
        raise TokenCrateError(f"{smoke.model} is not listed; available: {', '.join(map(str, ids))}")
    return f"{len(ids)} model(s) listed, including {smoke.model}"


def check_completion(smoke: Smoke) -> str:
    response = smoke.completion(
        "chat completion",
        [
            {"role": "system", "content": "Answer with one short sentence."},
            {"role": "user", "content": "Say hello and name one programming language."},
        ],
    )
    text = message_text(response)
    if not text:
        raise TokenCrateError("empty assistant message")
    timings = response.get("timings") or {}
    speed = timings.get("predicted_per_second")
    detail = f"{len(text)} characters in {response['_elapsed']:.1f}s"
    if speed:
        detail += f", {speed:.1f} tokens/s generation"
    return detail


def check_tool_call(smoke: Smoke) -> str:
    call = streamed_tool_call(smoke.url, smoke.model)
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


def check_mid_conversation_system(smoke: Smoke) -> str:
    response = smoke.completion(
        "mid-conversation system message",
        [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "Remember the number 41."},
            {"role": "assistant", "content": "I will remember 41."},
            {"role": "system", "content": "The user now prefers answers in one word."},
            {"role": "user", "content": "What is the number plus one?"},
        ],
    )
    text = message_text(response)
    if not text:
        raise TokenCrateError("empty assistant message after a mid-conversation system message")
    return f"accepted a system message after position 0 (answer: {text[:40]!r})"


def check_reply_terminates(smoke: Smoke) -> str:
    # A model that loops in its reasoning (seen on abliterated Qwen3.8
    # builds) runs into the token budget and ends with `length`; a
    # reply that ends on its own says `stop`.
    completions = smoke.completions
    if not completions:
        raise TokenCrateError("no completion to judge")
    truncated = [name for name, reason in completions.items() if reason != "stop"]
    if truncated:
        reasons = ", ".join(f"{name}: {completions[name] or 'none'}" for name in truncated)
        raise TokenCrateError(
            f"finish_reason is not stop ({reasons}); the reply ran into the {ANSWER_TOKENS}-token budget"
        )
    return f"finish_reason stop on {len(completions)} completion(s)"


def check_template_render(smoke: Smoke) -> str:
    # llama-server renders the chat template without generating, so this
    # proves the (patched) template accepts a system message after the
    # first turn and keeps it in the prompt.
    prompt = smoke.rendered_prompt(
        [
            {"role": "system", "content": "First system message."},
            {"role": "user", "content": "Hello."},
            {"role": "assistant", "content": "Hi."},
            {"role": "system", "content": "SECOND-SYSTEM-MARKER"},
            {"role": "user", "content": "Continue."},
        ]
    )
    if not prompt:
        raise TokenCrateError("apply-template returned no prompt")
    if "SECOND-SYSTEM-MARKER" not in prompt:
        raise TokenCrateError("the template dropped the mid-conversation system message")
    if "<|im_start|>system" in prompt and prompt.count("<|im_start|>system") < 2:
        raise TokenCrateError("the template merged the later system message into the first turn")
    return f"rendered {len(prompt)} characters including the later system message"


def check_effort_reaches_template(smoke: Smoke) -> str:
    # Rendering the same prompt with two of the preset's declared efforts
    # through chat_template_kwargs (what the agents send per turn) must
    # give different prompts, or the template ignores the effort.
    chosen = smoke.efforts[:2]
    if len(chosen) < 2:
        return "fewer than two efforts declared; nothing to compare"
    prompts = {}
    for effort in chosen:
        prompt = smoke.rendered_prompt(
            [{"role": "user", "content": "Hello."}],
            chat_template_kwargs={"enable_thinking": True, "reasoning_effort": effort},
        )
        if not prompt:
            raise TokenCrateError(f"apply-template returned no prompt for effort {effort}")
        prompts[effort] = prompt
    first, second = chosen
    if prompts[first] == prompts[second]:
        raise TokenCrateError(f"the template renders efforts {first} and {second} identically")
    return f"efforts {first} and {second} render different prompts"


def check_tokenize(smoke: Smoke) -> str:
    body = request(f"{smoke.url}/tokenize", {"model": smoke.model, "content": "hello world"}, timeout=120)
    tokens = (body or {}).get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise TokenCrateError("tokenize returned no tokens")
    return f"{len(tokens)} tokens for 'hello world'"


def check_metrics_counters(smoke: Smoke) -> str:
    # The renderer turns the counters on for every child ([*] metrics);
    # this proves the pinned build serves them for the probed preset.
    body = request(f"{smoke.url}/metrics?model={urllib.parse.quote(smoke.model, safe='')}", timeout=120)
    if not isinstance(body, str):
        raise TokenCrateError("the /metrics response is not Prometheus text")
    names = sorted({line.split("{")[0].split(" ")[0] for line in body.splitlines() if line.startswith("llamacpp:")})
    if not names:
        raise TokenCrateError("no llamacpp counters in the /metrics response")
    return f"{len(names)} llamacpp metric(s), including {names[0]}"


def run_check(name: str, check: Callable[[Smoke], str], smoke: Smoke) -> Result:
    """The check's detail as a passed row, or its failure as a failed one:
    every exception reaches the table instead of ending the run."""
    try:
        return Result(name, True, check(smoke))
    except TokenCrateError as error:
        return Result(name, False, str(error))
    except Exception as error:
        return Result(name, False, f"{type(error).__name__}: {error}")


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
    checks = (
        ("model listing", check_models, True),
        ("chat completion", check_completion, True),
        ("streamed tool call", check_tool_call, not basic),
        ("mid-conversation system message", check_mid_conversation_system, True),
        ("reply terminates", check_reply_terminates, not basic),
        ("template keeps later system messages", check_template_render, patched_template),
        ("reasoning effort reaches the template", check_effort_reaches_template, True),
        ("tokenize", check_tokenize, True),
        ("metrics counters", check_metrics_counters, True),
    )
    target = Smoke(url, model, tuple(efforts or ()))
    return [run_check(name, check, target) for name, check, wanted in checks if wanted]


def bench_prompt(tokens_target: int) -> str:
    base = (
        "You are reviewing a Python module that parses configuration files, validates "
        "the values, and renders a report. Summarize the risks in such a module. "
    )
    repeats = max(1, tokens_target // 40)
    return base * repeats


@dataclass(frozen=True)
class BenchRow:
    """One measured run of `bench`: the preset's facts, the last iteration's
    token counts, the average speeds, and every iteration's six `timings`
    values. `dataclasses.asdict` of it is a row of the schema-2 JSON, so the
    field order is the keys' order there."""

    preset: str
    run: str
    n_ctx: int | None
    build: str | None
    model_path: str | None
    prompt_tokens: int
    generated_tokens: int
    prompt_tps: float
    generation_tps: float
    iterations: int
    samples: list[dict]


def bench(url: str, presets: list[str], iterations: int, long: bool) -> list[BenchRow]:
    """The measured rows, each carrying its preset's `n_ctx`, build, and
    model path: read right after the preset's warm-up, so the facts are
    the loaded preset's and no extra load happens."""
    rows: list[BenchRow] = []
    for preset in presets:
        chat(url, preset, [{"role": "user", "content": "Warm-up."}], max_tokens=8)
        facts = server_facts(url, preset)
        runs: list[tuple[str, str]] = [("short", bench_prompt(300))]
        if long:
            runs.append(("long", bench_prompt(8000)))
        for label, prompt in runs:
            samples = [bench_sample(url, preset, prompt) for _ in range(iterations)]
            rows.append(
                BenchRow(
                    preset=preset,
                    run=label,
                    n_ctx=facts.get("n_ctx"),
                    build=facts.get("build"),
                    model_path=facts.get("model_path"),
                    prompt_tokens=samples[-1]["prompt_n"],
                    generated_tokens=samples[-1]["predicted_n"],
                    prompt_tps=sum(sample["prompt_per_second"] for sample in samples) / len(samples),
                    generation_tps=sum(sample["predicted_per_second"] for sample in samples) / len(samples),
                    iterations=iterations,
                    samples=samples,
                )
            )
    return rows


def bench_sample(url: str, preset: str, prompt: str) -> dict:
    """One iteration's `timings`: `prompt_ms` is the wait before the first
    token of this request."""
    # cache_prompt=False makes every iteration process the whole prompt
    # again; otherwise llama-server reuses the cached prefix and
    # prompt_per_second measures one token.
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
    return {
        "prompt_n": int(timings.get("prompt_n") or 0),
        "predicted_n": int(timings.get("predicted_n") or 0),
        "prompt_ms": float(timings.get("prompt_ms") or 0),
        "predicted_ms": float(timings.get("predicted_ms") or 0),
        "prompt_per_second": float(timings.get("prompt_per_second") or 0),
        "predicted_per_second": float(timings.get("predicted_per_second") or 0),
    }


def server_facts(url: str, preset: str) -> dict:
    """The preset's build, model path, and `n_ctx` from `/props`, which
    loads the preset when it is not loaded, so the request waits like a load."""
    facts = {}
    try:
        props = request(f"{url}/props?model={urllib.parse.quote(preset, safe='')}", timeout=LOAD_TIMEOUT)
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


def document_build(rows: list[BenchRow]) -> str | None:
    """The one build every row reports, or None when the rows disagree."""
    builds = {row.build for row in rows}
    return builds.pop() if len(builds) == 1 else None


def bench_report(url: str, rows: list[BenchRow]) -> str:
    """The Markdown bench report: one line per preset with its facts, then
    the table of the measured runs."""
    lines = ["# TokenCrate bench report", ""]
    lines.append(f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"- Endpoint: {url}")
    for preset, row in {row.preset: row for row in rows}.items():
        lines.append(f"- {preset}: n_ctx {row.n_ctx}, build {row.build}, {row.model_path}")
    lines += [
        "",
        "| Preset | Run | Prompt tokens | Generated tokens | Prompt tokens/s | Generation tokens/s | Iterations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.preset} | {row.run} | {row.prompt_tokens} | {row.generated_tokens} | "
            f"{row.prompt_tps:.1f} | {row.generation_tps:.1f} | {row.iterations} |"
        )
    lines += [
        "",
        "Speeds are averages of llama-server's per-request `timings` with prompt caching disabled for the request.",
    ]
    return "\n".join(lines) + "\n"


def bench_json(url: str, rows: list[BenchRow]) -> str:
    """The bench measurements as JSON, saved next to the Markdown report:
    six `timings` values per iteration for every preset and run, each row
    with its preset's `n_ctx`, build, and model path (schema 2; schema 1
    carried one `build` and `n_ctx` for the whole file). The document's
    `build` stays for a reader that wants one, when every row agrees."""
    document = {
        "schema": 2,
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": url,
        "build": document_build(rows),
        "rows": [asdict(row) for row in rows],
    }
    return json.dumps(document, indent=2) + "\n"


# --- bench --history ---------------------------------------------------------

# The files `bench` saves: the stem is the wrapper's own timestamp, which
# dates and orders the history; the JSON's own `date` is not read.
BENCH_FILE_RE = re.compile(r"bench-(\d{8})-(\d{6})\.json")
BENCH_FILE_LIMIT = 1024 * 1024
BUILD_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
BENCH_RUNS = ("short", "long")
HISTORY_HEADER = (
    "| Preset | Run | Date | n_ctx | Build | Prompt tokens | Prompt tokens/s | Generation tokens/s "
    "| Δ generation | Iterations |",
    "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
)
NO_HISTORY = (
    "No bench history: `bench` writes reports/bench-<timestamp>.json next to its report, and the history is "
    "this machine's (reports/ is not tracked)."
)


def bench_history_rows(reports_dir: Path) -> list[str]:
    """One Markdown row per measured run of every `bench` JSON under
    `reports_dir`, grouped by preset and run, oldest first within a group,
    with the change in generation speed against the previous row of the
    group when both ran at the same `n_ctx`. The build and `n_ctx` are the
    row's own (schema 2) or the file's (schema 1). A file that is not a
    bench document is skipped whole, a row that is not a measurement is
    skipped, and nothing but the build, `n_ctx`, the preset, the run label,
    and the numbers reaches the table, in the shapes the writer above
    produces. The rows stay dicts: the files are untrusted input (any
    key may be missing or of the wrong type), so every value is checked
    here instead of being trusted into a `BenchRow`."""

    def facts(source: dict) -> tuple[int | None, str]:
        n_ctx, build = source.get("n_ctx"), source.get("build")
        return (
            n_ctx if isinstance(n_ctx, int) and not isinstance(n_ctx, bool) and n_ctx >= 0 else None,
            build if isinstance(build, str) and BUILD_RE.fullmatch(build) else "?",
        )

    measured = []
    for path in sorted(reports_dir.glob("bench-*.json")):
        match = BENCH_FILE_RE.fullmatch(path.name)
        if match is None:
            continue
        try:
            if not path.is_file() or path.stat().st_size > BENCH_FILE_LIMIT:
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # gone, unreadable, malformed, or an integer past the digit limit
            continue
        if (
            not isinstance(document, dict)
            or (schema := document.get("schema")) not in (1, 2)
            or not isinstance(document.get("rows"), list)
        ):
            continue
        day, clock = match.group(1), match.group(2)
        date = f"{day[:4]}-{day[4:6]}-{day[6:]} {clock[:2]}:{clock[2:4]}"
        for row in document["rows"]:
            if not isinstance(row, dict):
                continue
            n_ctx, build = facts(row if schema == 2 else document)
            preset, run = row.get("preset"), row.get("run")
            prompt_tps, generation_tps = (
                stats.duration(row.get("prompt_tps")),
                stats.duration(row.get("generation_tps")),
            )
            if (
                not isinstance(preset, str)
                or not PRESET_NAME_RE.fullmatch(preset)
                or len(preset) > 64
                or run not in BENCH_RUNS
                or prompt_tps is None
                or generation_tps is None
                or min(prompt_tps, generation_tps) < 0
            ):
                continue
            measured.append((preset, BENCH_RUNS.index(run), date, n_ctx, build, row, prompt_tps, generation_tps))
    rows = []
    previous = None
    for preset, run_index, date, n_ctx, build, row, prompt_tps, generation_tps in sorted(
        measured, key=lambda item: item[:3]
    ):
        same_group = (
            previous is not None and previous[:2] == (preset, run_index) and n_ctx is not None and previous[2] == n_ctx
        )
        delta = f"{round(generation_tps - previous[3], 1) + 0.0:+.1f}" if same_group else ""
        previous = (preset, run_index, n_ctx, generation_tps)
        rows.append(
            f"| {preset} | {BENCH_RUNS[run_index]} | {date} | {n_ctx if n_ctx is not None else '?'} | {build} | "
            f"{stats.integer(row.get('prompt_tokens'))} | {prompt_tps:.1f} | {generation_tps:.1f} | {delta} | "
            f"{stats.integer(row.get('iterations'))} |"
        )
    return rows


def bench_history(reports_dir: Path) -> str:
    """The Markdown bench history: the measurements of every saved run, so
    a llama.cpp pin bump or a preset change shows next to what came before."""
    lines = ["# TokenCrate bench history", ""]
    rows = bench_history_rows(reports_dir)
    if not rows:
        lines.append(NO_HISTORY)
    else:
        lines += [*HISTORY_HEADER, *rows]
    lines += [
        "",
        "One row per measured run of every reports/bench-<timestamp>.json, grouped by preset and run, oldest "
        "first within a group; the numbers are the report's averages over its iterations. Δ generation is the "
        "change in generation tokens/s against the row above when both ran at the same n_ctx.",
    ]
    return "\n".join(lines) + "\n"
