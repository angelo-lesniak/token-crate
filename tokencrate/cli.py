"""Command-line dispatch: the command table, option parsing, and usage.

`COMMANDS` is the one description of the interface: each entry is a usage
line, the flags it accepts, and its handler. `USAGE` and every refusal of
a misplaced flag are generated from it. Usage and error text are part of
the documented interface (`docs/cli.md`), so a change here changes the
page."""

from __future__ import annotations

import contextlib
import io
import os
import re
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property, partial
from pathlib import Path
from typing import Any

from . import (
    PROJECT_ROOT,
    TokenCrateError,
    agenthome,
    agents,
    agentsets,
    checkpins,
    doctor,
    env,
    models,
    presets,
    probe,
    runtime,
    session,
    skills,
    stats,
    uis,
    warn,
)
from . import engine as engines
from .names import PRESET_NAME_RE, parse_list, select_sets
from .stats import page as statspage
from .stats import server as statsserver

POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")


@dataclass
class Context:
    """What every handler may need: the settings, and the pins and the
    model configuration read once, on first use. Commands that do not act
    on a preset never read the configuration, so a broken preset file
    cannot stop `init`, or `doctor` without a selected or default preset."""

    settings: env.Settings

    @cached_property
    def pinned(self) -> dict[str, str]:
        return env.load_pins(PROJECT_ROOT / "pins.env")

    @cached_property
    def configuration(self) -> presets.Configuration:
        return presets.load(self.settings.config_dir, env.pinned_llama_build(self.pinned))


Options = dict[str, Any]
Handler = Callable[[Context, Options, list[str]], int | None]


@dataclass(frozen=True)
class Flag:
    """One option. `what` names the value it carries (empty for a switch)
    and `valid` accepts that value."""

    what: str = ""
    valid: Callable[[str], object] = lambda raw: True


@dataclass(frozen=True)
class Command:
    """One usage line. `name` is the command and, after a space, either its
    subcommand (`models fetch`) or the flag that selects a mode of it
    (`stats --serve`); `synopsis` is the rest of the usage line; `arguments`
    bounds the positional arguments (None: unbounded)."""

    name: str
    synopsis: str
    summary: str
    flags: dict[str, Flag]
    handler: Handler
    arguments: tuple[int, int | None] = (0, 0)

    @property
    def family(self) -> str:
        return self.name.split()[0]

    @property
    def selector(self) -> str:
        words = self.name.split()
        return words[1] if len(words) > 1 and words[1].startswith("--") else ""

    @property
    def usage(self) -> str:
        return f"bin/tokencrate {self.name} {self.synopsis}".rstrip()


SWITCH = Flag()
PRESET = Flag("a preset id", PRESET_NAME_RE.fullmatch)
PRESETS = Flag("a comma-separated list of preset ids", bool)
MODEL_SETS = Flag("a comma-separated list of model set names", bool)
POSITIVE = Flag("a positive integer", POSITIVE_INTEGER_RE.fullmatch)
PORT = Flag("a port from 1 to 65535", partial(env.validate_port, label="--port"))
AGENT = Flag("pi or omp", agenthome.AGENTS.__contains__)
SETS = Flag("a comma-separated list of agent sets (or an empty string)")
DIRECTORY = Flag("a directory", bool)
SINCE = Flag("a duration (30m, 12h, 7d, 2w) or an ISO date or date-time")


# -- Parsing -------------------------------------------------------------------


def usage_error(name: str) -> TokenCrateError:
    return TokenCrateError(f"usage: {BY_NAME[name].usage}")


def names_for(flag: str, commands: list[Command]) -> str:
    """`a, b, or c` for the commands that accept `flag`: a family whose base
    command accepts it, or whose mode it selects, is named once, in the
    order of the usage text."""
    names: list[str] = []
    for command in commands:
        base = BY_NAME.get(command.family)
        name = command.family if command.selector == flag or base in commands else command.name
        if name not in names:
            names.append(name)
    if len(names) > 2:
        return ", ".join(names[:-1]) + ", or " + names[-1]
    return " or ".join(names)


def refusal(command: Command, flag: str) -> str:
    """Why `command` does not take `flag`: another command does, another
    mode of the same command does, or nothing does."""
    accepting = [entry for entry in COMMANDS if flag in entry.flags]
    related = [entry for entry in accepting if entry.family == command.family]
    if not accepting:
        return f"unknown option for {command.name}: {flag}"
    if not related:
        return f"{flag} is only valid with {names_for(flag, accepting)}"
    if command.selector and BY_NAME.get(command.family) in related:
        return f"{flag} is not valid with {command.selector}"
    return f"{flag} applies to {names_for(flag, related)}"


def resolve(argv: list[str]) -> tuple[Command, list[str]]:
    """The table entry `argv` names and the arguments left for it: the
    subcommand when the second word is one, else the mode whose selector
    appears, else the command itself."""
    word = argv[0]
    family = [entry for entry in COMMANDS if entry.family == word]
    if not family:
        sys.stderr.write(USAGE)
        raise TokenCrateError(f"unknown command: {word}")
    subcommand = BY_NAME.get(" ".join(argv[:2]))
    if subcommand is not None and not subcommand.selector:
        return subcommand, argv[2:]
    base = BY_NAME.get(word)
    if base is None:
        raise TokenCrateError(f"usage: bin/tokencrate {word} " + " | ".join(entry.name.split()[1] for entry in family))
    arguments = argv[1:]
    for mode in family:
        if mode.selector and mode.selector in arguments:
            return mode, arguments
    return base, arguments


def parse(command: Command, arguments: list[str]) -> tuple[Options, list[str]]:
    """The flags of `command` with their values (True for a switch, the rest
    of the line for `--`) and its positional arguments. A repeated flag is
    refused rather than resolved to one occurrence, so a typo in either
    stays visible."""
    options: Options = {}
    names: list[str] = []
    least, most = command.arguments
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--" and "--" in command.flags:
            options["--"] = arguments[index + 1 :]
            break
        if not argument.startswith("--"):
            if most == 0:
                raise TokenCrateError(f"unexpected argument for {command.name}: {argument}")
            names.append(argument)
            index += 1
            continue
        flag = command.flags.get(argument)
        if flag is None:
            raise TokenCrateError(refusal(command, argument))
        if argument in options:
            raise TokenCrateError(f"{argument} may be given once with {command.name}")
        if not flag.what:
            options[argument] = True
            index += 1
            continue
        if index + 1 >= len(arguments) or not flag.valid(arguments[index + 1]):
            raise TokenCrateError(f"{argument} requires {flag.what}")
        options[argument] = arguments[index + 1]
        index += 2
    if len(names) < least or (most is not None and len(names) > most):
        raise usage_error(command.name)
    return options, names


# -- Shared steps --------------------------------------------------------------


def print_set_list(catalog: dict) -> None:
    """One line per manifest with its description."""
    for name, entry in catalog.items():
        print(f"{name} - {entry.description}")


def run_model_sets(settings: env.Settings, action: str, names: list[str], verify: bool = False) -> int:
    catalog = models.catalog(settings.config_dir)
    selected = select_sets(catalog, names, "model set")
    models_dir = runtime.models_directory(settings)
    if action == "status":
        return models.status(selected, models_dir, verify=verify)
    with models.model_download_lock(models_dir):
        models.fetch(selected, models_dir, settings.hf_token)
    return 0


def save_report(settings: env.Settings, kind: str, text: str) -> Path:
    reports = settings.root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_probe(context: Context, kind: str, selected: list[str], options: Options) -> int:
    settings = context.settings
    engine = engines.detect(settings)
    configuration = context.configuration
    # The preset is judged before the stack is asked for, so a name that does
    # not exist is that message and not "the llama container is not running".
    selected = selected or [session.chosen_preset(settings, "")]
    for name in selected:
        configuration.require(name)
    engine.running_llama_id()
    url = settings.service_url
    if kind == "smoke":
        preset = selected[0]
        found = configuration.find(preset)
        efforts = found.reasoning_efforts if found else []
        patched = bool(found and configuration.model_sets[found.model_set].chat_template_file)
        results = probe.smoke(url, preset, basic="--basic" in options, efforts=efforts, patched_template=patched)
        text, status = probe.smoke_report(preset, url, results, probe.server_facts(url, preset))
        rows = None
    else:
        rows = probe.bench(url, selected, int(options.get("--iterations", 3)), "--long" in options)
        text, status = probe.bench_report(url, rows), 0
    print(text, end="")
    path = save_report(settings, kind, text)
    print(f"Saved {kind} report to {path}")
    if rows is not None:
        # The same stem as the Markdown report, so the pair stays together.
        samples = path.with_suffix(".json")
        samples.write_text(probe.bench_json(url, rows), encoding="utf-8")
        print(f"Saved bench samples to {samples}")
    if status != 0:
        warn(f"the {kind} run failed with status {status}")
    return status


def run_doctor(context: Context, preset: str, facts: doctor.HostFacts | None = None) -> int:
    """The host checks, with the named preset's requirements when one is
    named; the configuration is read only then, so a broken preset file does
    not stop the host checks."""
    settings = context.settings
    preset = preset or settings.default_preset or None
    vram = ram = wait = None
    if preset:
        configuration = context.configuration
        found = configuration.find(preset)
        if found is None:
            # The host checks are worth more than the preset requirements.
            warn(f"unknown preset {preset}, so its host requirements were not checked")
            preset = None
        else:
            vram = found.requires.get("vram_gib")
            ram = found.requires.get("ram_gib")
            wait = configuration.wait(preset) or None
    return doctor.run(
        settings,
        min_driver_major=int(context.pinned["CUDA_MIN_DRIVER_MAJOR"]),
        preset=preset,
        required_vram_gib=vram,
        required_ram_gib=ram,
        build_wait=wait,
        facts=facts,
    )


def stats_filter(options: Options) -> stats.Filter:
    """The cutoff is resolved once, so a served page shows what it says."""
    since = stats.since_cutoff(options["--since"]) if "--since" in options else None
    return stats.Filter(since=since, agent=options.get("--agent", ""))


# -- Handlers ------------------------------------------------------------------


def cmd_init(context: Context, _options: Options, _names: list[str]) -> None:
    runtime.init_project(context.settings)


def cmd_doctor(context: Context, options: Options, _names: list[str]) -> int:
    return run_doctor(context, options.get("--preset", ""))


def cmd_up(context: Context, options: Options, _names: list[str]) -> None:
    settings = context.settings
    model_sets = parse_list(options.get("--model-sets", ""), "model set")
    if "all" in model_sets:
        raise TokenCrateError("name the model sets of up individually; all is available through models fetch")
    if model_sets:
        select_sets(models.catalog(settings.config_dir), model_sets, "model set")
    # The host checks run before the download, so the check that matters
    # most (the card against the preset) cannot be skipped by starting; the
    # engine they probed is the one the stack starts on.
    facts = doctor.gather(settings)
    if run_doctor(context, "", facts) != 0:
        raise TokenCrateError("fix the [fail] lines above before starting (bash bin/tokencrate doctor repeats them)")
    loaded = context.configuration
    # A default preset that does not exist, or that the pinned build
    # cannot load, must fail before a download.
    if settings.default_preset:
        loaded.require(settings.default_preset)
    runtime.prepare_host_directories(settings)
    engine = engines.detect(settings, selection=facts.selection)
    # A Docker network that keeps a gateway address must refuse before a
    # download.
    runtime.require_isolated_networks(engine)
    if model_sets:
        run_model_sets(settings, "fetch", model_sets)
    runtime.start_stack(settings, engine, loaded, int(options.get("--timeout", 600)))


def cmd_down(context: Context, _options: Options, _names: list[str]) -> None:
    runtime.stop_stack(engines.detect(context.settings, launching=False))


def cmd_status(context: Context, _options: Options, _names: list[str]) -> None:
    engine = engines.detect(context.settings, launching=False)
    runtime.print_containers(context.settings, engine)
    uis.print_status(engine)
    runtime.print_models(context.settings, engine)


def cmd_logs(context: Context, _options: Options, _names: list[str]) -> int:
    engine = engines.detect(context.settings, launching=False)
    ids = engine.container_ids("llama", all_states=True)
    if len(ids) != 1:
        raise TokenCrateError("logs needs exactly one llama container in this Compose project")
    return engine.command("logs", "--follow", ids[0], check=False).returncode


def cmd_smoke(context: Context, options: Options, _names: list[str]) -> int:
    return run_probe(context, "smoke", [options["--preset"]] if "--preset" in options else [], options)


def cmd_agent_check(context: Context, options: Options, _names: list[str]) -> int:
    agent = options["--agent"]
    if "--sets" in options and agent != "pi":
        raise TokenCrateError(session.SETS_ARE_PI_ONLY)
    engine = engines.detect(context.settings)
    return agents.agent_check(
        context.settings,
        engine,
        context.configuration,
        agent,
        options.get("--preset", ""),
        ui_targets=uis.peer_targets(engine),
        sets=options.get("--sets"),
        egress="--egress" in options,
    )


def cmd_bench(context: Context, options: Options, _names: list[str]) -> int:
    return run_probe(context, "bench", parse_list(options.get("--presets", ""), "preset", PRESET_NAME_RE), options)


def cmd_stats(context: Context, options: Options, _names: list[str]) -> None:
    # Reads the retained transcripts on the host; no engine, stack, or
    # preset is needed, so the report works with everything down.
    settings = context.settings
    selection = stats_filter(options)
    sessions = stats.read_sessions(settings.agents_dir, selection)
    slots = presets.rendered_slots(settings.build_dir)
    text = stats.report(sessions, selection, slots)
    print(text, end="")
    path = save_report(settings, "stats", text)
    print(f"Saved stats report to {path}")
    page = path.with_suffix(".html")
    page.write_text(statspage.html(sessions, selection=selection, slots=slots), encoding="utf-8")
    print(f"Saved stats page to {page}")


def cmd_stats_serve(context: Context, options: Options, _names: list[str]) -> int:
    port = int(options.get("--port", statsserver.SERVE_PORT))
    return statsserver.serve(context.settings, port, stats_filter(options))


def cmd_agent(context: Context, options: Options, names: list[str]) -> int:
    [agent] = names
    if agent not in agenthome.AGENTS:
        raise TokenCrateError(f"unsupported agent: {agent} (choose pi or omp)")
    if "--sets" in options and agent != "pi":
        raise TokenCrateError(session.SETS_ARE_PI_ONLY)
    if "--cloud" in options and agent != "pi":
        raise TokenCrateError(session.CLOUD_IS_PI_ONLY)
    settings = context.settings
    return agents.run_agent(
        settings,
        engines.detect(settings),
        context.configuration,
        agent,
        preset=options.get("--preset", ""),
        project_dir=options.get("--dir") or os.getcwd(),
        egress="--egress" in options,
        arguments=options.get("--", []),
        sets=options.get("--sets"),
        cloud="--cloud" in options,
    )


def cmd_agent_sets_list(context: Context, _options: Options, _names: list[str]) -> None:
    settings = context.settings
    for name, entry in agentsets.catalog(settings.root).items():
        print(f"{name}{' [ui]' if entry.ui else ''} - {entry.description}")
    selected = settings.get("LLM_AGENT_SETS") or "none"
    print(f"Selected by LLM_AGENT_SETS ({selected}) or agent --sets; private sets go below local/agent-sets.")


def cmd_ui(context: Context, options: Options, names: list[str]) -> int:
    settings = context.settings
    return uis.start(
        settings,
        engines.detect(settings),
        context.configuration,
        names[0],
        options.get("--preset", ""),
        options.get("--dir") or os.getcwd(),
        options.get("--sets"),
        options.get("--port", ""),
        "--egress" in options,
        "--cloud" in options,
    )


def cmd_ui_action(action: str, context: Context, _options: Options, names: list[str]) -> int:
    engine = engines.detect(context.settings, launching=False)
    name = names[0] if names else ""
    return uis.stop(engine, name) if action == "stop" else uis.logs(engine, name)


def cmd_models_list(context: Context, _options: Options, _names: list[str]) -> None:
    print_set_list(models.catalog(context.settings.config_dir))
    print("Download with models fetch <set>; files go below LLM_MODELS_DIR.")


def cmd_model_sets(action: str, context: Context, options: Options, names: list[str]) -> int:
    return run_model_sets(context.settings, action, names, verify="--verify" in options)


def cmd_models_draft(context: Context, _options: Options, names: list[str]) -> None:
    sys.stdout.write(models.draft(names[0], context.settings.hf_token))


def cmd_presets_list(context: Context, _options: Options, _names: list[str]) -> None:
    loaded = context.configuration
    for preset in loaded.presets:
        wait = loaded.wait(preset.name)
        marks = preset.requirement_text() + (f"; {wait}" if wait else "")
        print(f"{preset.name} [{preset.model_set}] {marks} - {preset.description}")
    default = context.settings.default_preset or "unset"
    print(f"Selected by LLM_DEFAULT_PRESET ({default}) or --preset; a waiting preset stays out of the router.")


def cmd_presets_check(context: Context, _options: Options, _names: list[str]) -> None:
    presets.validate(context.configuration, default_preset=context.settings.default_preset)


def cmd_skills_list(context: Context, _options: Options, _names: list[str]) -> None:
    print_set_list(skills.catalog(context.settings.config_dir))
    print(f"Private skills go below {context.settings.local_skills_dir}.")


def cmd_skill_sets(action: str, context: Context, _options: Options, names: list[str]) -> int:
    settings = context.settings
    skills_dir = settings.skills_dir
    if not skills_dir.is_dir():
        raise TokenCrateError(f"skills directory does not exist: {skills_dir} (run: bash bin/tokencrate init)")
    selected = select_sets(skills.catalog(settings.config_dir), names, "skill set")
    return skills.fetch(selected, skills_dir.resolve(), verify_only=action == "status")


def cmd_pins(context: Context, _options: Options, _names: list[str]) -> None:
    # Through the validating loader, so a bad edit is a refusal.
    sys.stdout.write("".join(f"{key}={value}\n" for key, value in context.pinned.items()))


def cmd_pins_check(context: Context, _options: Options, names: list[str]) -> None:
    component = names[0] if names else "all"
    # Only the llama.cpp build gate reads the manifests, so a broken one
    # must not break `pins check pi`.
    waits = (
        presets.model_set_waits(models.catalog(context.settings.config_dir), env.pinned_llama_build(context.pinned))
        if component in ("all", "llama-cpp")
        else ()
    )
    try:
        sys.stdout.write(checkpins.check(component, context.pinned, waits=waits))
    except checkpins.LookupsFailed as failure:
        sys.stdout.write(failure.report)
        raise


# -- The table -----------------------------------------------------------------

COMMANDS = (
    Command("init", "", "Create .env and the host storage directories.", {}, cmd_init),
    Command(
        "doctor",
        "[--preset id]",
        "Check the host (engine, GPU, CDI, memory, directories, port) before starting.",
        {"--preset": PRESET},
        cmd_doctor,
    ),
    Command(
        "up",
        "[--model-sets names] [--timeout seconds]",
        "Check the host, fetch named model sets, render presets, build the image if needed, and start llama-server.",
        {"--model-sets": MODEL_SETS, "--timeout": POSITIVE},
        cmd_up,
    ),
    Command(
        "down",
        "",
        "Stop and remove the model, terminal agents, browser UIs, the dashboard, and Compose networks.",
        {},
        cmd_down,
    ),
    Command("status", "", "Show the service state and the load state of every rendered preset.", {}, cmd_status),
    Command("logs", "", "Follow the llama container logs.", {}, cmd_logs),
    Command(
        "smoke",
        "[--preset id] [--basic]",
        "Run API probes against the running stack and save a report "
        "(--basic skips the checks that need a capable model).",
        {"--preset": PRESET, "--basic": SWITCH},
        cmd_smoke,
    ),
    Command(
        "smoke --agent",
        "<pi|omp> [--preset id] [--sets names (pi only)] [--egress]",
        "Prove from inside an agent container what is reachable: only the model, or with --egress also the routes out.",
        {"--agent": AGENT, "--preset": PRESET, "--sets": SETS, "--egress": SWITCH},
        cmd_agent_check,
    ),
    Command(
        "bench",
        "[--presets ids] [--iterations n] [--long]",
        "Measure prompt-processing and generation speed per preset and save a report.",
        {"--presets": PRESETS, "--iterations": POSITIVE, "--long": SWITCH},
        cmd_bench,
    ),
    Command(
        "stats",
        "[--since when] [--agent <pi|omp>]",
        "Summarize token usage and context sizes from the retained agent transcripts and save a report.",
        {"--since": SINCE, "--agent": AGENT},
        cmd_stats,
    ),
    Command(
        "stats --serve",
        "[--port port] [--since when] [--agent <pi|omp>]",
        "Serve the stats page on loopback and re-read the transcripts on each refresh (Ctrl-C stops it).",
        {"--serve": SWITCH, "--port": PORT, "--since": SINCE, "--agent": AGENT},
        cmd_stats_serve,
    ),
    Command(
        "agent",
        "<pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [--cloud] [-- args]",
        "Open a coding agent in the current (or named) project directory; "
        "--cloud (pi only) mounts LLM_CLOUD_KEYS_FILE.",
        {
            "--preset": PRESET,
            "--sets": SETS,
            "--dir": DIRECTORY,
            "--egress": SWITCH,
            "--cloud": SWITCH,
            "--": SWITCH,
        },
        cmd_agent,
        arguments=(1, 1),
    ),
    Command(
        "agent-sets list", "", "List the agent sets that can be rendered into the pi image.", {}, cmd_agent_sets_list
    ),
    Command(
        "ui",
        "<set> [--preset id] [--sets names] [--dir path] [--port port] [--egress] [--cloud]",
        "Start a browser UI for pi from an agent set in the background; --cloud mounts LLM_CLOUD_KEYS_FILE into it.",
        {
            "--preset": PRESET,
            "--sets": SETS,
            "--dir": DIRECTORY,
            "--port": PORT,
            "--egress": SWITCH,
            "--cloud": SWITCH,
        },
        cmd_ui,
        arguments=(1, 1),
    ),
    Command(
        "ui stop",
        "[<set>]",
        "Stop and remove the named UI, or all UIs when no set is named.",
        {},
        partial(cmd_ui_action, "stop"),
        arguments=(0, 1),
    ),
    Command(
        "ui logs",
        "[<set>]",
        "Follow the named UI logs; omit the set only when one UI is present.",
        {},
        partial(cmd_ui_action, "logs"),
        arguments=(0, 1),
    ),
    Command("models list", "", "List the available pinned model sets.", {}, cmd_models_list),
    Command(
        "models fetch",
        "<set> [<set> ...] | all",
        "Download and verify one or more model sets from Hugging Face.",
        {},
        partial(cmd_model_sets, "fetch"),
        arguments=(1, None),
    ),
    Command(
        "models status",
        "[--verify] <set> [<set> ...] | all",
        "Verify the selected files already present in the models directory; --verify re-reads every file.",
        {"--verify": SWITCH},
        partial(cmd_model_sets, "status"),
        arguments=(1, None),
    ),
    Command(
        "models draft",
        "hf:<owner>/<repo>:<file.gguf>",
        "Print a model-set manifest draft for one Hugging Face file.",
        {},
        cmd_models_draft,
        arguments=(1, 1),
    ),
    Command("presets list", "", "List the available presets and their model sets.", {}, cmd_presets_list),
    Command(
        "presets check",
        "",
        "Validate every preset and model set; up renders them into build/.",
        {},
        cmd_presets_check,
    ),
    Command("skills list", "", "List the available skill sets.", {}, cmd_skills_list),
    Command(
        "skills fetch",
        "<set> [<set> ...] | all",
        "Fetch reviewed skills at their pinned commits.",
        {},
        partial(cmd_skill_sets, "fetch"),
        arguments=(1, None),
    ),
    Command(
        "skills status",
        "<set> [<set> ...] | all",
        "Verify fetched skills against their pinned tree digests.",
        {},
        partial(cmd_skill_sets, "status"),
        arguments=(1, None),
    ),
    Command("pins", "", "Show the pinned components (pins.env).", {}, cmd_pins),
    Command(
        "pins check",
        "[component|all]",
        "Print the latest eligible upstream pins next to the current ones; nothing is written.",
        {},
        cmd_pins_check,
        arguments=(0, 1),
    ),
)
BY_NAME = {command.name: command for command in COMMANDS}

USAGE = (
    "TokenCrate - pinned local-LLM and coding-agent containers for Docker and Podman\n\nUsage:\n"
    + "".join(f"  {command.usage}\n      {command.summary}\n" for command in COMMANDS)
    + "\nSet CONTAINER_ENGINE=docker or CONTAINER_ENGINE=podman to override detection.\n"
)


# -- Entry ---------------------------------------------------------------------


def dispatch(argv: list[str]) -> int:
    command, arguments = resolve(argv)
    options, names = parse(command, arguments)
    return command.handler(Context(env.load(PROJECT_ROOT)), options, names) or 0


def install_signal_handlers() -> None:
    """A hang-up or termination ends the wrapper the way an exception does,
    so its `with` and `try` blocks unwind: the Compose client is killed,
    and `agent` stops the session container it started (which the client
    alone would leave running). A disposition of SIG_IGN, which `nohup`
    and `setsid` leave behind, is respected: a backgrounded `up` or
    `models fetch` keeps running."""

    def raise_exit(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    for signum in (signal.SIGHUP, signal.SIGTERM):
        if signal.getsignal(signum) is not signal.SIG_IGN:
            signal.signal(signum, raise_exit)


def main(argv: list[str]) -> int:
    install_signal_handlers()
    try:
        if not argv or argv[0] in ("help", "--help", "-h"):
            sys.stdout.write(USAGE)
            status = 0
        else:
            status = dispatch(argv)
        # A listing fits the pipe buffer, so a reader that is gone is first
        # seen here; left to interpreter shutdown it is an "Exception
        # ignored" line and exit status 120.
        sys.stdout.flush()
        return status
    except TokenCrateError as error:
        warn(str(error))
        return 1
    except BrokenPipeError:
        # Before the OSError clause, of which this is a subclass: a reader
        # that closed the pipe (`| head`) is not a filesystem failure.
        with contextlib.suppress(OSError):
            sys.stdout = io.TextIOWrapper(open(1, "wb", closefd=False))
        return 1
    except OSError as error:
        warn(f"filesystem operation failed: {error}")
        return 1
    except KeyboardInterrupt:
        return 130
