"""Render reviewed presets and model sets into the router preset file.

Inputs are the TOML files under config/presets and config/model-sets. Outputs
are build/models.ini, the preset file llama-server reads in router mode (a
`[*]` section of shared keys and one section per loadable preset, keyed by
the long flag names without dashes), and the agent model lists under
build/agents (pi/models.json and omp/models.yml, both JSON text; oh-my-pi
reads JSON as YAML). The renderer owns the keys that tie a preset to the
container layout (model paths, chat template, context, slots) and the ones
the router sets for every child (host, port, alias); presets express
everything else through typed keys.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import TokenCrateError, models
from .agentmodels import AGENT_THINKING_LEVELS, omp_models, pi_models_json
from .names import PRESET_NAME_RE, load_catalog, read_toml
from .names import description as read_description

# The rendered router preset file; services/llama/Dockerfile boots it.
CONFIG_FILE_NAME = "models.ini"
MODELS_ROOT_IN_CONTAINER = "/models"
CHAT_TEMPLATES_IN_CONTAINER = "/etc/tokencrate/chat-templates"
UI_CONFIG_IN_CONTAINER = "/etc/tokencrate/ui-config.json"
# The [*] section, which every child server inherits: the Jinja template
# engine (tool calls and chat_template_kwargs) and the UI defaults (the
# router loads the same file for the UI at the root; the UI reads whichever
# /props it fetched last).
SHARED_KEYS = (("jinja", "true"), ("ui-config-file", UI_CONFIG_IN_CONTAINER))
SECTION_RE = re.compile(r"^\[([^\]]+)\]$", re.MULTILINE)
# The choices are the values the shipped presets use or a validation
# record has measured; a value llama-server accepts but no preset has run
# with is added together with the preset that runs it.
FLASH_ATTN_VALUES = ("on", "off", "auto")
CACHE_TYPES = ("f16", "bf16", "q8_0")
SPEC_TYPES = ("none", "draft-mtp")
REASONING_EFFORT_RE = re.compile(r"^[a-z]+$")
# The typed [server] keys: integers with their minimum, booleans, choices; the
# word, list, and table keys (reasoning_effort, reasoning_efforts, extra) are
# validated in read_preset.
INT_KEYS = {
    "ctx_size": 1024,
    "n_predict": -1,
    "parallel": 1,
    "gpu_layers": 0,
    "spec_draft_n_max": 1,
    "ctx_checkpoints": 0,
    "batch_size": 1,
    "ubatch_size": 1,
    # Expert weights of the first N layers stay in system memory (a MoE
    # model larger than the card); 0 keeps everything on the GPU.
    "n_cpu_moe": 0,
}
BOOL_KEYS = ("enable_thinking", "thinking_toggle")
CHOICE_KEYS = {
    "flash_attn": FLASH_ATTN_VALUES,
    "cache_type_k": CACHE_TYPES,
    "cache_type_v": CACHE_TYPES,
    "spec_type": SPEC_TYPES,
}
SERVER_KEYS = {*INT_KEYS, *BOOL_KEYS, *CHOICE_KEYS, "reasoning_effort", "reasoning_efforts", "extra"}
# Every preset states these; the renderer has no fallback for them, so a
# preset file is the only place the value is written.
REQUIRED_SERVER_KEYS = ("ctx_size", "n_predict", "gpu_layers", "flash_attn", "cache_type_k", "cache_type_v")
SAMPLING_KEYS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty")
# The host memory a preset declares: GPU memory always, system memory for
# a preset that keeps expert weights there (n_cpu_moe).
REQUIRES_KEYS = {"vram_gib", "ram_gib"}
# The agents show the description as the model name, and presets list
# prints it after the name, the set, and the requirements.
DESCRIPTION_MAX = 120
# The options [server.extra] passes through to the router, by long name:
# what the shipped presets, the fixtures, and the documentation use. Every
# other option is refused, the typed keys' own spellings included, so a
# preset cannot set one option twice. llama-server also takes options that
# run tools, proxy MCP servers, serve files, or fetch models, and each
# release adds some; a new option is added here after reading its help.
EXTRA_KEYS = ("override-kv", "load-mode", "log-prompts-dir", "verbose")


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    model_set: str
    server: dict
    sampling: dict
    requires: dict

    @property
    def parallel(self) -> int:
        return int(self.server.get("parallel", 1))

    @property
    def ctx_size(self) -> int:
        return int(self.server["ctx_size"])

    @property
    def context_per_slot(self) -> int:
        return self.ctx_size // self.parallel

    @property
    def reasoning_efforts(self) -> list[str]:
        return list(self.server.get("reasoning_efforts", []))


@dataclass
class RenderedPreset:
    preset: Preset
    loadable: bool
    missing: list[str] = field(default_factory=list)
    # Why the pinned llama.cpp build cannot load the preset ("" when it can).
    wait: str = ""


def expect_int(table: dict, key: str, context: str, *, minimum: int | None = None) -> int | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TokenCrateError(f"{context}: {key} must be an integer")
    if minimum is not None and value < minimum:
        raise TokenCrateError(f"{context}: {key} must be at least {minimum}")
    return value


def expect_number(table: dict, key: str, context: str) -> float | None:
    if key not in table:
        return None
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TokenCrateError(f"{context}: {key} must be a number")
    return value


def read_preset(path: Path, model_sets: dict) -> Preset:
    name = path.stem
    if not PRESET_NAME_RE.fullmatch(name):
        raise TokenCrateError(f"unsafe preset filename: {path.name} (use lowercase letters, digits, dots, and dashes)")
    context = f"preset {name}"
    document = read_toml(path, {"schema", "description", "model_set", "server", "sampling", "requires"}, context)
    description = read_description(document, context)
    if len(description) > DESCRIPTION_MAX:
        raise TokenCrateError(
            f"{context}: description must be at most {DESCRIPTION_MAX} characters "
            "(the agents show it as the model name); the preset comments take the rest"
        )
    model_set = document.get("model_set")
    if not isinstance(model_set, str) or model_set not in model_sets:
        raise TokenCrateError(f"{context}: model_set must name a file under config/model-sets (got {model_set!r})")
    server = document.get("server", {})
    sampling = document.get("sampling", {})
    requires = document.get("requires", {})
    for table, allowed, label in (
        (server, SERVER_KEYS, "server"),
        (sampling, SAMPLING_KEYS, "sampling"),
        (requires, REQUIRES_KEYS, "requires"),
    ):
        if not isinstance(table, dict):
            raise TokenCrateError(f"{context}: [{label}] must be a table")
        unknown = set(table) - set(allowed)
        if unknown:
            raise TokenCrateError(f"{context}: unknown [{label}] key(s): {', '.join(sorted(unknown))}")

    for key, minimum in INT_KEYS.items():
        expect_int(server, key, context, minimum=minimum)
    for key in BOOL_KEYS:
        if key in server and not isinstance(server[key], bool):
            raise TokenCrateError(f"{context}: {key} must be true or false")
    for key, choices in CHOICE_KEYS.items():
        if key in server and server[key] not in choices:
            raise TokenCrateError(f"{context}: {key} must be one of {', '.join(choices)}")
    for key in REQUIRED_SERVER_KEYS:
        if key not in server:
            raise TokenCrateError(f"{context}: [server] {key} is required")
    # n_predict = 0 would pass the -1 minimum, cap the server at nothing,
    # and still advertise the 8192 fallback to the agents.
    if server["n_predict"] == 0:
        raise TokenCrateError(f"{context}: n_predict must be -1 (unlimited) or a positive integer")
    if server["ctx_size"] % server.get("parallel", 1) != 0:
        raise TokenCrateError(f"{context}: ctx_size must be divisible by parallel")
    effort = server.get("reasoning_effort")
    if effort is not None and (not isinstance(effort, str) or not REASONING_EFFORT_RE.fullmatch(effort)):
        raise TokenCrateError(f"{context}: reasoning_effort must be a lowercase word")
    efforts = server.get("reasoning_efforts", [])
    if not isinstance(efforts, list) or any(
        not isinstance(item, str) or not REASONING_EFFORT_RE.fullmatch(item) for item in efforts
    ):
        raise TokenCrateError(f"{context}: reasoning_efforts must be a list of lowercase words")
    if len(set(efforts)) != len(efforts):
        raise TokenCrateError(f"{context}: reasoning_efforts must not repeat values")
    unknown = [item for item in efforts if item not in AGENT_THINKING_LEVELS[1:]]
    if unknown:
        raise TokenCrateError(
            f"{context}: reasoning_efforts must use the agent thinking level names "
            f"({', '.join(AGENT_THINKING_LEVELS[1:])}); unknown: {', '.join(unknown)}"
        )
    if efforts and effort is None:
        raise TokenCrateError(f"{context}: reasoning_efforts needs a default reasoning_effort")
    extra = server.get("extra", {})
    if not isinstance(extra, dict):
        raise TokenCrateError(f"{context}: [server.extra] must be a table of llama-server options")
    for key, value in extra.items():
        if key not in EXTRA_KEYS:
            raise TokenCrateError(
                f"{context}: [server.extra] cannot set {key}; the renderer passes through {', '.join(EXTRA_KEYS)}"
            )
        if not isinstance(value, (str, int, float, bool)):
            raise TokenCrateError(f"{context}: [server.extra] {key} must be a string, number, or boolean")
    for key in SAMPLING_KEYS:
        expect_number(sampling, key, context)
    expect_int(requires, "vram_gib", context, minimum=1)
    expect_int(requires, "ram_gib", context, minimum=1)

    if server.get("spec_type", "none") == "draft-mtp":
        if not model_sets[model_set].mtp:
            raise TokenCrateError(f"{context}: draft-mtp needs a model set with mtp = true")
        if server.get("parallel", 1) != 1:
            raise TokenCrateError(f"{context}: draft-mtp requires parallel = 1")
    if (server.get("spec_type", "none") != "none") and "spec_draft_n_max" not in server:
        raise TokenCrateError(f"{context}: a spec_type other than none needs spec_draft_n_max")
    if server.get("cache_type_v") not in (None, "f16", "bf16") and server.get("flash_attn") == "off":
        raise TokenCrateError(f"{context}: a quantized cache_type_v needs flash_attn on or auto")
    return Preset(name, description, model_set, server, sampling, requires)


def load_presets(presets_dir: Path, model_sets: dict) -> list[Preset]:
    """Every preset under presets_dir, in preset-name order."""
    return list(load_catalog(presets_dir, lambda path: read_preset(path, model_sets), "preset").values())


def model_path(destination: str) -> str:
    return f"{MODELS_ROOT_IN_CONTAINER}/{destination}"


def template_kwargs(preset: Preset) -> dict:
    kwargs: dict = {}
    if preset.server.get("enable_thinking") is False:
        kwargs["enable_thinking"] = False
    if preset.server.get("reasoning_effort") is not None:
        kwargs["reasoning_effort"] = preset.server["reasoning_effort"]
    return kwargs


def ini_line(key: str, value: object) -> str:
    """One `key = value` line of the router's preset file. The router reads a
    value up to the first `;` or `#` (the rest is a comment) and one line at
    a time, so those characters are refused rather than silently truncated."""
    text = ("true" if value else "false") if isinstance(value, bool) else str(value)
    if not text or any(character in text for character in ";#\n\r"):
        raise TokenCrateError(
            f"{key} = {text!r} cannot be written to the preset file (empty, or contains ; # or a line break)"
        )
    return f"{key} = {text}"


def preset_section(preset: Preset, model_set, *, startup: bool) -> list[str]:
    """The INI section of one preset: the model and its template first, the
    typed [server] keys, the sampling keys, then [server.extra], which
    read_preset keeps free of the typed keys' spellings."""
    server = preset.server
    pairs: list[tuple[str, object]] = [("model", model_path(model_set.weights.destination))]
    if model_set.chat_template_file:
        pairs.append(("chat-template-file", f"{CHAT_TEMPLATES_IN_CONTAINER}/{model_set.chat_template_file}"))
    if startup:
        pairs.append(("load-on-startup", True))
    pairs += [
        ("ctx-size", preset.ctx_size),
        ("n-predict", server["n_predict"]),
        ("parallel", preset.parallel),
        ("gpu-layers", server["gpu_layers"]),
        ("flash-attn", server["flash_attn"]),
        ("cache-type-k", server["cache_type_k"]),
        ("cache-type-v", server["cache_type_v"]),
    ]
    spec_type = server.get("spec_type", "none")
    if spec_type != "none":
        pairs += [("spec-type", spec_type), ("spec-draft-n-max", server["spec_draft_n_max"])]
    for key in ("ctx_checkpoints", "batch_size", "ubatch_size"):
        if key in server:
            pairs.append((key.replace("_", "-"), server[key]))
    if server.get("n_cpu_moe", 0) > 0:
        pairs.append(("n-cpu-moe", server["n_cpu_moe"]))
    kwargs = template_kwargs(preset)
    if kwargs:
        pairs.append(("chat-template-kwargs", json.dumps(kwargs, separators=(",", ":"))))
    # llama-server's --fit would shrink the context or move layers off the
    # card to fit the free memory; a preset states its memory in [requires]
    # and gets what it declares.
    pairs.append(("fit", "off"))
    pairs += [(key.replace("_", "-"), preset.sampling[key]) for key in SAMPLING_KEYS if key in preset.sampling]
    pairs += list(server.get("extra", {}).items())
    return [f"[{preset.name}]", *(ini_line(key, value) for key, value in pairs)]


def build_wait(model_set, pinned_build: int) -> str:
    """The reason the pinned llama.cpp build cannot load the model set, as the
    preset lines print it, or "" when it can: a set may require a build the
    pin has not reached, or one that no release carries yet."""
    required = model_set.llama_build
    if not required:
        return ""
    if required == models.UNRELEASED_BUILD:
        return f"waits for an unreleased llama.cpp build (pinned: b{pinned_build})"
    if int(required[1:]) <= pinned_build:
        return ""
    return f"waits for llama.cpp build {required} (pinned: b{pinned_build})"


@dataclass(frozen=True)
class Configuration:
    """The model sets, the presets, and the build that pins.env pins, read
    once for the command that acts on them. Every question of the form
    "which preset is this, and can the pinned build load it" is answered
    from here, so no caller re-reads config_dir or pins.env to ask it."""

    model_sets: dict
    presets: tuple[Preset, ...]
    pinned_build: int

    def find(self, name: str) -> Preset | None:
        return next((preset for preset in self.presets if preset.name == name), None)

    def wait(self, name: str) -> str:
        """build_wait for the named preset's model set; "" for an unknown
        name. For a listing or a report; a command about to use the preset
        calls `require`."""
        found = self.find(name)
        return build_wait(self.model_sets[found.model_set], self.pinned_build) if found else ""

    def require(self, name: str) -> Preset:
        """The named preset, which the pinned build can load: the one refusal
        of a preset a command is about to use, for `--preset` and for
        LLM_DEFAULT_PRESET alike."""
        found = self.find(name)
        if found is None:
            raise TokenCrateError(f"unknown preset: {name} (run: bash bin/tokencrate presets list)")
        wait = build_wait(self.model_sets[found.model_set], self.pinned_build)
        if wait:
            raise TokenCrateError(f"preset {name} {wait}; bash bin/tokencrate presets list shows the loadable ones")
        return found


def load(config_dir: Path, pinned_build: int) -> Configuration:
    """The model sets and presets below config_dir. Every chat template a
    model set references must exist under config_dir/chat-templates,
    because llama-server would only fail at load time otherwise."""
    model_sets = models.available_sets(config_dir / "model-sets")
    chat_templates_dir = config_dir / "chat-templates"
    for model_set in model_sets.values():
        if model_set.chat_template_file and not (chat_templates_dir / model_set.chat_template_file).is_file():
            raise TokenCrateError(
                f"model set {model_set.name} references a missing chat template: {model_set.chat_template_file}"
            )
    return Configuration(model_sets, tuple(load_presets(config_dir / "presets", model_sets)), pinned_build)


def missing_files(model_set, models_root: Path | None) -> list[str]:
    if models_root is None:
        return []
    return [
        model_file.destination
        for model_file in model_set.files
        if not (models_root / Path(*PurePosixPath(model_file.destination).parts)).is_file()
    ]


def build_config(rendered: list[RenderedPreset], model_sets: dict, default_preset: str) -> str:
    """The router preset file: the shared [*] section, then one section per
    loadable preset; the default preset loads at start."""
    lines = ["[*]", *(ini_line(key, value) for key, value in SHARED_KEYS)]
    for item in rendered:
        if item.loadable:
            section = preset_section(
                item.preset, model_sets[item.preset.model_set], startup=item.preset.name == default_preset
            )
            lines += ["", *section]
    return "\n".join(lines) + "\n"


def agent_models(rendered: list[RenderedPreset]) -> list[dict]:
    models_list = []
    for item in rendered:
        if not item.loadable:
            continue
        preset = item.preset
        models_list.append(
            {
                "id": preset.name,
                "name": preset.description,
                "context": preset.context_per_slot,
                "max_tokens": n_predict if (n_predict := preset.server["n_predict"]) > 0 else 8192,
                "reasoning": preset.server.get("enable_thinking", True) is not False,
                # Effort levels the chat template accepts; the agents map their
                # thinking levels onto them per turn.
                "efforts": preset.reasoning_efforts,
                # Whether the template honors enable_thinking=false (Qwen) or
                # always thinks (gpt-oss harmony).
                "thinking_toggle": preset.server.get("thinking_toggle", True) is not False,
            }
        )
    return models_list


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def evaluate(configuration: Configuration, default_preset: str, models_root: Path | None) -> tuple[list, str]:
    """Judge every preset, print one line each, and build the router preset
    file's text, which is where a value the router would truncate is
    refused; the caller decides whether to write it.

    A preset whose model set needs a newer llama.cpp build than the pinned
    one is reported as waiting and is not loadable. With a models_root, a
    preset whose model files are missing below it is reported as skipped;
    without one, no file is looked at and every other preset counts as
    loadable."""
    model_sets, presets, pinned_build = configuration.model_sets, configuration.presets, configuration.pinned_build
    if default_preset:
        configuration.require(default_preset)
    rendered = []
    for preset in presets:
        wait = build_wait(model_sets[preset.model_set], pinned_build)
        missing = [] if wait else missing_files(model_sets[preset.model_set], models_root)
        rendered.append(RenderedPreset(preset, not (wait or missing), missing, wait))
    for item in rendered:
        if item.wait:
            state = item.wait
        elif item.loadable:
            state = "valid" if models_root is None else "loadable"
        else:
            state = f"skipped (missing {', '.join(item.missing)})"
        print(f"{item.preset.name}: {state}")
    return rendered, build_config(rendered, model_sets, default_preset)


def validate(configuration: Configuration, *, default_preset: str) -> list[RenderedPreset]:
    """Judge the configuration and write nothing; model files are not looked
    at, so this needs no storage."""
    rendered, _ = evaluate(configuration, default_preset, None)
    print(f"Validated {len(rendered)} preset(s) against {len(configuration.model_sets)} model set(s).")
    return rendered


def render(
    configuration: Configuration, *, output_dir: Path, models_root: Path, default_preset: str
) -> list[RenderedPreset]:
    """Write the router preset file and the two agent model lists for every
    preset whose model files are present below models_root."""
    rendered, config = evaluate(configuration, default_preset, models_root)
    models_list = agent_models(rendered)
    write_atomic(output_dir / CONFIG_FILE_NAME, config)
    write_atomic(output_dir / "agents" / "pi" / "models.json", json.dumps(pi_models_json(models_list), indent=2) + "\n")
    # oh-my-pi looks for models.yml; JSON is valid YAML, so the name stays.
    write_atomic(output_dir / "agents" / "omp" / "models.yml", json.dumps(omp_models(models_list), indent=2) + "\n")
    loadable = sum(1 for item in rendered if item.loadable)
    print(f"Rendered {loadable} of {len(rendered)} preset(s) into {output_dir}.")
    return rendered


def rendered_model_ids(output_dir: Path) -> set[str]:
    """The model ids (section names) in the rendered router preset file;
    empty when nothing has been rendered into output_dir yet."""
    try:
        text = (output_dir / CONFIG_FILE_NAME).read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    return set(SECTION_RE.findall(text)) - {"*"}
