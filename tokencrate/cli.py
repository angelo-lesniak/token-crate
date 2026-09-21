"""Command-line dispatch: usage, option parsing, and the command table.

The parser is deliberately small and hand-written so that every error text
users and the documentation rely on stays exactly as it is."""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache

from . import (
    PROJECT_ROOT,
    TokenCrateError,
    agents,
    agentsets,
    checkpins,
    doctor,
    env,
    models,
    presets,
    probe,
    runtime,
    skills,
    uis,
    warn,
)
from . import engine as engines
from .names import SET_NAME_RE, UI_ACTIONS, preset_file, select_sets

USAGE = """\
TokenCrate - pinned local-LLM and coding-agent containers for Docker and Podman

Usage:
  bin/tokencrate init
      Create .env and the host data directories.
  bin/tokencrate doctor [--preset id]
      Check the host (engine, GPU, CDI, memory, directories, port) before starting.
  bin/tokencrate up [--model-set name]... [--timeout seconds]
      Check the host, fetch named model sets, render presets, build the image if needed, and start llama-server.
  bin/tokencrate down
      Stop and remove the model, terminal agents, browser UIs, and Compose networks.
  bin/tokencrate status
      Show the service state and the load state of every rendered preset.
  bin/tokencrate logs
      Follow the llama container logs.
  bin/tokencrate smoke [--preset id] [--basic]
      Run API probes against the running stack and save a report (--basic skips the checks that need a capable model).
  bin/tokencrate smoke --agent <pi|omp> [--preset id] [--sets names (pi only)]
      Prove from inside an agent container that only the model is reachable.
  bin/tokencrate bench [--preset id]... [--iterations n] [--long]
      Measure prompt-processing and generation speed per preset and save a report.
  bin/tokencrate agent <pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [-- args]
      Open a coding agent in the current (or named) project directory.
  bin/tokencrate agent-sets list
      List the agent sets that can be rendered into the pi image.
  bin/tokencrate ui <set> [--preset id] [--sets names] [--dir path] [--port port]
      Start a browser UI for pi from an agent set in the background and print its loopback address.
  bin/tokencrate ui stop [<set>]
      Stop and remove the named UI, or all UIs when no set is named.
  bin/tokencrate ui logs [<set>]
      Follow the named UI logs; omit the set only when one UI is present.
  bin/tokencrate models list
      List the available pinned model sets.
  bin/tokencrate models fetch <set> [<set> ...] | all
      Download and verify one or more model sets from Hugging Face.
  bin/tokencrate models status <set> [<set> ...] | all
      Verify the selected files already present in the models directory.
  bin/tokencrate models draft hf:<owner>/<repo>:<file.gguf>
      Print a model-set manifest draft for one Hugging Face file.
  bin/tokencrate presets list
      List the available presets and their model sets.
  bin/tokencrate presets render
      Validate every preset and model set; up renders them into build/.
  bin/tokencrate skills list
      List the available skill sets.
  bin/tokencrate skills fetch <set> [<set> ...] | all
      Fetch reviewed skills at their pinned commits.
  bin/tokencrate skills status <set> [<set> ...] | all
      Verify fetched skills against their pinned tree digests.
  bin/tokencrate pins
      Show the pinned components (pins.env).
  bin/tokencrate pins check [component|all]
      Print the latest eligible upstream pins next to the current ones; nothing is written.

Set CONTAINER_ENGINE=docker or CONTAINER_ENGINE=podman to override detection.
"""

POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
DRAFT_SPEC_RE = re.compile(r"^hf:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[^\s]+$")
# Which commands accept which flag, and how the refusal names them.
FLAG_COMMANDS = {
    "--long": (("bench",), "bench"),
    "--basic": (("smoke",), "smoke"),
    "--egress": (("agent",), "agent"),
    "--timeout": (("up",), "up"),
    "--iterations": (("bench",), "bench"),
    "--preset": (("doctor", "smoke", "bench", "agent", "ui"), "doctor, smoke, bench, agent, or ui"),
    "--model-set": (("up",), "up"),
    "--sets": (("agent", "smoke", "ui"), "agent, smoke --agent, or ui"),
    "--port": (("ui",), "ui"),
    "--dir": (("agent", "ui"), "agent or ui"),
    "--agent": (("smoke",), "smoke"),
}
# The flags that carry one value. `--preset` and `--model-set` repeat by
# design and have their own rules.
SINGLE_VALUE_FLAGS = ("--timeout", "--iterations", "--sets", "--port", "--dir", "--agent")


@dataclass
class Options:
    port: str = ""
    timeout: int = 600
    presets: list[str] = field(default_factory=list)
    model_sets: list[str] = field(default_factory=list)
    agent_dir: str = ""
    egress: bool = False
    agent_name: str = ""
    iterations: int = 3
    long: bool = False
    basic: bool = False
    sets: str | None = None
    agent_args: list[str] = field(default_factory=list)

    @property
    def preset(self) -> str:
        return self.presets[-1] if self.presets else ""


def parse_options(settings: env.Settings, command: str, arguments: list[str]) -> Options:
    options = Options()
    index = 0
    seen: set[str] = set()

    def value(flag: str, what: str) -> str:
        if index + 1 >= len(arguments):
            raise TokenCrateError(f"{flag} requires {what}")
        return arguments[index + 1]

    while index < len(arguments):
        argument = arguments[index]
        if argument in FLAG_COMMANDS and command not in FLAG_COMMANDS[argument][0]:
            raise TokenCrateError(f"{argument} is only valid with {FLAG_COMMANDS[argument][1]}")
        # A repeated single-valued flag used to take the last occurrence
        # silently, so a typo in the first one was invisible.
        if argument in SINGLE_VALUE_FLAGS:
            if argument in seen:
                raise TokenCrateError(f"{argument} may be given once with {command}")
            seen.add(argument)
        if argument == "--long":
            options.long = True
        elif argument == "--basic":
            options.basic = True
        elif argument == "--egress":
            options.egress = True
        elif argument == "--timeout":
            raw = value(argument, "a positive integer")
            if not POSITIVE_INTEGER_RE.fullmatch(raw):
                raise TokenCrateError("--timeout requires a positive integer")
            options.timeout = int(raw)
            index += 1
        elif argument == "--iterations":
            raw = value(argument, "a positive integer")
            if not POSITIVE_INTEGER_RE.fullmatch(raw):
                raise TokenCrateError("--iterations requires a positive integer")
            options.iterations = int(raw)
            index += 1
        elif argument == "--preset":
            name = value(argument, "a preset name")
            preset_file(settings.config_dir, name)
            if options.presets and command != "bench":
                raise TokenCrateError(f"--preset may be given once with {command}")
            if name in options.presets:
                raise TokenCrateError(f"--preset names {name} twice")
            options.presets.append(name)
            index += 1
        elif argument == "--model-set":
            name = value(argument, "a set name")
            if name == "all":
                raise TokenCrateError("use individual --model-set names with up; all is available through models fetch")
            select_sets(models.available_sets(settings.config_dir / "model-sets"), [name], "model set")
            options.model_sets.append(name)
            index += 1
        elif argument == "--sets":
            options.sets = value(argument, "a comma-separated list of agent sets (or an empty string)")
            index += 1
        elif argument == "--port":
            options.port = env.validate_port(value(argument, "a port from 1 to 65535"), argument)
            index += 1
        elif argument == "--dir":
            options.agent_dir = value(argument, "a directory")
            index += 1
        elif argument == "--agent":
            name = value(argument, "pi or omp")
            if name not in agents.AGENTS:
                raise TokenCrateError("--agent requires pi or omp")
            options.agent_name = name
            index += 1
        elif argument == "--":
            if command != "agent":
                raise TokenCrateError(f"unknown option for {command}: --")
            options.agent_args = arguments[index + 1 :]
            return options
        elif argument.startswith("--"):
            raise TokenCrateError(f"unknown option for {command}: {argument}")
        else:
            raise TokenCrateError(f"unexpected argument for {command}: {argument}")
        index += 1
    return options


def parse_names(arguments: list[str]) -> list[str]:
    """`models` and `skills` take set names without options."""
    for argument in arguments:
        if argument.startswith("--"):
            raise TokenCrateError(f"unknown option: {argument}")
    return list(arguments)


def skill_set_catalog(settings: env.Settings) -> dict:
    hosts = skills.load_allowed_hosts(settings.config_dir / "skill-sets" / "allowed-git-hosts.txt")
    return skills.available_sets(settings.config_dir / "skill-sets", hosts)


def requirement_text(preset: presets.Preset) -> str:
    """The `[requires]` of a preset as `presets list` prints it."""
    parts = []
    if "vram_gib" in preset.requires:
        parts.append(f"{preset.requires['vram_gib']} GiB GPU memory")
    if "ram_gib" in preset.requires:
        parts.append(f"{preset.requires['ram_gib']} GiB system memory")
    return "needs " + " and ".join(parts) if parts else "(no [requires])"


def print_set_list(catalog: dict) -> None:
    """One line per manifest with its description."""
    for name, entry in catalog.items():
        print(f"{name}{' - ' + entry.description if entry.description else ''}")


def run_model_sets(settings: env.Settings, action: str, names: list[str]) -> int:
    catalog = models.available_sets(settings.config_dir / "model-sets")
    selected = select_sets(catalog, names, "model set")
    models_dir = runtime.models_directory(settings)
    if action == "status":
        return models.status(selected, models_dir)
    with models.model_download_lock(models_dir):
        models.fetch(selected, models_dir, settings.hf_token)
    return 0


def run_skill_sets(settings: env.Settings, action: str, names: list[str]) -> int:
    skills_dir = settings.skills_dir
    if not skills_dir.is_dir():
        raise TokenCrateError(f"skills directory does not exist: {skills_dir} (run: bash bin/tokencrate init)")
    selected = select_sets(skill_set_catalog(settings), names, "skill set")
    return skills.fetch(selected, skills_dir.resolve(), verify_only=action == "status")


def refuse_waiting(configuration: presets.Configuration, preset: str) -> None:
    """The router has no section for a preset the pinned build cannot load."""
    wait = configuration.wait(preset)
    if wait:
        raise presets.wait_error(preset, wait)


def run_probe(
    settings: env.Settings,
    engine: engines.Engine,
    configuration: presets.Configuration,
    kind: str,
    options: Options,
) -> int:
    # The preset is judged before the stack is asked for, so a name that does
    # not exist is that message and not "the llama container is not running".
    selected = options.presets or ([settings.default_preset] if settings.default_preset else [])
    if not selected:
        raise TokenCrateError(f"{kind} needs --preset or LLM_DEFAULT_PRESET")
    for name in selected:
        preset_file(settings.config_dir, name)
        refuse_waiting(configuration, name)
    engine.running_llama_id()
    url = settings.service_url
    if kind == "smoke":
        preset = selected[0]
        found = configuration.find(preset)
        efforts = found.reasoning_efforts if found else []
        patched = bool(found and configuration.model_sets[found.model_set].chat_template_file)
        results = probe.smoke(url, preset, basic=options.basic, efforts=efforts, patched_template=patched)
        text, status = probe.smoke_report(preset, url, results, probe.server_facts(url, preset))
    else:
        rows = probe.bench(url, selected, options.iterations, options.long)
        text, status = probe.bench_report(url, rows, probe.server_facts(url, selected[0])), 0
    print(text, end="")
    path = runtime.save_report(settings, kind, text)
    print(f"Saved {kind} report to {path}")
    if status != 0:
        warn(f"the {kind} run failed with status {status}")
    return status


def model_set_waits(model_sets: dict, pinned: dict[str, str]) -> tuple[str, ...]:
    """One line per model set that waits for a newer llama.cpp build, for pins check."""
    build = env.pinned_llama_build(pinned)
    return tuple(
        f"model set {model_set.name} {wait}"
        for model_set in model_sets.values()
        if (wait := presets.build_wait(model_set, build))
    )


def run_doctor(
    settings: env.Settings,
    pinned: dict[str, str],
    read_configuration: Callable[[], presets.Configuration],
    options: Options,
) -> int:
    """The host checks, with the named preset's requirements when one is
    named; the configuration is read only then, so a broken preset file does
    not stop the host checks."""
    preset = options.preset or settings.default_preset or None
    vram = ram = wait = None
    if preset:
        configuration = read_configuration()
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
        min_driver_major=int(pinned["CUDA_MIN_DRIVER_MAJOR"]),
        preset=preset,
        required_vram_gib=vram,
        required_ram_gib=ram,
        build_wait=wait,
    )


def dispatch(command: str, arguments: list[str]) -> int:
    settings = env.load(PROJECT_ROOT)

    @cache
    def pinned() -> dict[str, str]:
        return env.load_pins(PROJECT_ROOT / "pins.env")

    @cache
    def configuration() -> presets.Configuration:
        """The model sets and presets of this command, read once. Commands
        that do not act on a preset never read them, so a broken preset file
        cannot stop `init`, or `doctor` without a selected or default preset."""
        return presets.load(settings.config_dir, env.pinned_llama_build(pinned()))

    if command == "init":
        parse_options(settings, command, arguments)
        runtime.init_project(settings)
    elif command == "doctor":
        options = parse_options(settings, command, arguments)
        return run_doctor(settings, pinned(), configuration, options)
    elif command == "up":
        options = parse_options(settings, command, arguments)
        # The host checks run before the download, so the check that matters
        # most (the card against the preset) cannot be skipped by starting.
        if run_doctor(settings, pinned(), configuration, options) != 0:
            raise TokenCrateError(
                "fix the [fail] lines above before starting (bash bin/tokencrate doctor repeats them)"
            )
        loaded = configuration()
        # A default preset that no longer exists, or that the pinned build
        # cannot load, must fail before a download.
        if settings.default_preset:
            preset_file(settings.config_dir, settings.default_preset)
            wait = loaded.wait(settings.default_preset)
            if wait:
                raise presets.default_wait_error(settings.default_preset, wait)
        runtime.prepare_host_directories(settings)
        engine = engines.detect(settings)
        # A Docker network that keeps a gateway address must refuse before a
        # download.
        runtime.require_isolated_networks(engine)
        if options.model_sets:
            run_model_sets(settings, "fetch", options.model_sets)
        runtime.start_stack(settings, engine, loaded, options.timeout)
    elif command == "down":
        parse_options(settings, command, arguments)
        runtime.stop_stack(engines.detect(settings, launching=False))
    elif command == "status":
        parse_options(settings, command, arguments)
        runtime.print_status(settings, engines.detect(settings, launching=False))
    elif command == "logs":
        parse_options(settings, command, arguments)
        engine = engines.detect(settings, launching=False)
        ids = engine.container_ids("llama", all_states=True)
        if len(ids) != 1:
            raise TokenCrateError("logs needs exactly one llama container in this Compose project")
        return engine.command("logs", "--follow", ids[0], check=False).returncode
    elif command == "smoke":
        options = parse_options(settings, command, arguments)
        if options.sets is not None and not options.agent_name:
            raise TokenCrateError("--sets applies to smoke --agent")
        if options.sets is not None and options.agent_name != "pi":
            raise TokenCrateError(agents.SETS_ARE_PI_ONLY)
        engine = engines.detect(settings)
        if options.agent_name:
            if options.basic:
                raise TokenCrateError("--basic is not valid with --agent")
            return agents.agent_check(
                settings, engine, configuration(), options.agent_name, options.preset, options.sets
            )
        return run_probe(settings, engine, configuration(), "smoke", options)
    elif command == "bench":
        options = parse_options(settings, command, arguments)
        return run_probe(settings, engines.detect(settings), configuration(), "bench", options)
    elif command == "agent":
        if not arguments:
            raise TokenCrateError(
                "usage: bin/tokencrate agent <pi|omp> [--preset id] [--sets names] [--dir path] [--egress] [-- args]"
            )
        agent, rest = arguments[0], arguments[1:]
        if agent not in agents.AGENTS:
            raise TokenCrateError(f"unsupported agent: {agent} (choose pi or omp)")
        options = parse_options(settings, command, rest)
        if options.sets is not None and agent != "pi":
            raise TokenCrateError(agents.SETS_ARE_PI_ONLY)
        project_dir = options.agent_dir or os.getcwd()
        engine = engines.detect(settings)
        return agents.run_agent(
            settings,
            engine,
            configuration(),
            agent,
            options.preset,
            project_dir,
            options.egress,
            options.agent_args,
            options.sets,
        )
    elif command == "ui":
        if not arguments:
            raise TokenCrateError(
                "usage: bin/tokencrate ui <set> [--preset id] [--sets names] [--dir path] [--port port] | stop | logs"
            )
        target, rest = arguments[0], arguments[1:]
        if target in UI_ACTIONS:
            if len(rest) > 1 or (rest and not SET_NAME_RE.fullmatch(rest[0])):
                raise TokenCrateError(f"usage: bin/tokencrate ui {target} [<set>]")
            engine = engines.detect(settings, launching=False)
            name = rest[0] if rest else ""
            return uis.stop(engine, name) if target == "stop" else uis.logs(engine, name)
        if not SET_NAME_RE.fullmatch(target):
            raise TokenCrateError(f"unsafe agent set name: {target}")
        options = parse_options(settings, command, rest)
        project_dir = options.agent_dir or os.getcwd()
        return agents.run_ui(
            settings,
            engines.detect(settings),
            configuration(),
            target,
            options.preset,
            project_dir,
            options.sets,
            options.port,
        )
    elif command == "models":
        action, rest = (arguments[0], arguments[1:]) if arguments else ("", [])
        if action == "list":
            if rest:
                raise TokenCrateError("usage: bin/tokencrate models list")
            print_set_list(models.available_sets(settings.config_dir / "model-sets"))
            print("Download with models fetch <set>; files go below LLM_MODELS_DIR.")
        elif action in ("fetch", "status"):
            return run_model_sets(settings, action, parse_names(rest))
        elif action == "draft":
            names = parse_names(rest)
            if len(names) != 1:
                raise TokenCrateError("usage: bin/tokencrate models draft hf:<owner>/<repo>:<file.gguf>")
            if not DRAFT_SPEC_RE.fullmatch(names[0]):
                raise TokenCrateError("model draft needs hf:<owner>/<repository>:<file.gguf>")
            sys.stdout.write(models.draft(names[0], settings.hf_token))
        else:
            raise TokenCrateError("usage: bin/tokencrate models list | fetch | status | draft")
    elif command == "presets":
        action, rest = (arguments[0], arguments[1:]) if arguments else ("", [])
        if action == "list":
            if rest:
                raise TokenCrateError("usage: bin/tokencrate presets list")
            loaded = configuration()
            for preset in loaded.presets:
                wait = loaded.wait(preset.name)
                marks = requirement_text(preset) + (f"; {wait}" if wait else "")
                print(f"{preset.name} [{preset.model_set}] {marks} - {preset.description}")
            default = settings.default_preset or "unset"
            print(f"Selected by LLM_DEFAULT_PRESET ({default}) or --preset; a waiting preset stays out of the router.")
        elif action == "render":
            parse_options(settings, "render", rest)
            presets.validate(configuration(), default_preset=settings.default_preset)
        else:
            raise TokenCrateError("usage: bin/tokencrate presets list | render")
    elif command == "agent-sets":
        if arguments != ["list"]:
            raise TokenCrateError("usage: bin/tokencrate agent-sets list")
        for name, entry in agentsets.catalog(settings.root).items():
            print(f"{name}{' [ui]' if entry.ui else ''} - {entry.description}")
        selected = settings.get("LLM_AGENT_SETS") or "none"
        print(f"Selected by LLM_AGENT_SETS ({selected}) or agent --sets; private sets go below local/agent-sets.")
    elif command == "skills":
        action, rest = (arguments[0], arguments[1:]) if arguments else ("", [])
        if action == "list":
            if rest:
                raise TokenCrateError("usage: bin/tokencrate skills list")
            print_set_list(skill_set_catalog(settings))
            print(
                "Repository skills under config/skills are always available; "
                f"private skills go below {settings.local_skills_dir}."
            )
        elif action in ("fetch", "status"):
            return run_skill_sets(settings, action, parse_names(rest))
        else:
            raise TokenCrateError("usage: bin/tokencrate skills list | fetch | status")
    elif command == "pins":
        if arguments[:1] == ["check"]:
            if len(arguments) > 2:
                raise TokenCrateError("usage: bin/tokencrate pins check [component|all]")
            component = arguments[1] if len(arguments) == 2 else "all"
            # Only the llama.cpp build gate reads the manifests, so a broken
            # one must not break `pins check pi`.
            waits = (
                model_set_waits(models.available_sets(settings.config_dir / "model-sets"), pinned())
                if component in ("all", "llama-cpp")
                else ()
            )
            sys.stdout.write(checkpins.check(component, pinned(), waits=waits))
        else:
            if arguments:
                raise TokenCrateError("usage: bin/tokencrate pins [check [component|all]]")
            pinned()
            sys.stdout.write(env.pinned_lines(PROJECT_ROOT / "pins.env"))
    else:
        sys.stderr.write(USAGE)
        raise TokenCrateError(f"unknown command: {command}")
    return 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "help"
    if command in ("help", "--help", "-h"):
        sys.stdout.write(USAGE)
        return 0
    try:
        return dispatch(command, argv[1:])
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
