"""Tests for the preset renderer against the shipped configuration and temporary inputs."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.support import shipped
from tokencrate import PROJECT_ROOT, TokenCrateError, agentmodels, models, presets

CONFIG = PROJECT_ROOT / "config"
GPT_OSS_20B_WEIGHTS = "ggml-org/gpt-oss-20b-GGUF/gpt-oss-20b-MXFP4.gguf"
SHIPPED_MODEL_SETS = shipped("model-sets")
SHIPPED_PRESETS = shipped("presets")
# A preset whose model set waits for a llama.cpp build no release carries
# (the GLM presets) never reaches the router. The tests pass the build
# number they compare against (10920) themselves.
_CONFIGURATION = presets.load(CONFIG, 10920)
_MODEL_SETS, _PRESETS = _CONFIGURATION.model_sets, _CONFIGURATION.presets
GATED_PRESETS = [p.name for p in _PRESETS if _MODEL_SETS[p.model_set].llama_build == models.UNRELEASED_BUILD]
LOADABLE_PRESETS = [name for name in SHIPPED_PRESETS if name not in GATED_PRESETS]
# Every preset of the gpt-oss set: the tests that gate that set or leave
# only its file on disk expect all of them, not one.
GPT_OSS_PRESETS = [p.name for p in _PRESETS if p.model_set == "gpt-oss-20b-mxfp4"]
UNRELEASED_WAIT = "waits for an unreleased llama.cpp build (pinned: b10920)"
VALIDATED = f"Validated {len(SHIPPED_PRESETS)} preset(s) against {len(SHIPPED_MODEL_SETS)} model set(s)."
# Every preset states the keys the renderer has no fallback for.
PRESET_HEAD = (
    'schema = 1\ndescription = "case"\nmodel_set = "qwen3.8-27b-ud-q4-k-xl"\n'
    "[server]\nctx_size = 8192\nn_predict = 16384\ngpu_layers = 99\n"
    'flash_attn = "auto"\ncache_type_k = "f16"\ncache_type_v = "f16"\n'
)


def replace_restated_keys(body: str) -> str:
    """A case appends its own line for a key PRESET_HEAD already sets; the
    later line wins, so the preset stays valid TOML."""
    lines = body.splitlines()
    last: dict[str, int] = {}
    for index, line in enumerate(lines):
        if "=" in line and not line.startswith("["):
            last[line.split("=", 1)[0].strip()] = index
    keep = set(last.values())
    return (
        "\n".join(line for index, line in enumerate(lines) if index in keep or "=" not in line or line.startswith("["))
        + "\n"
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_ini(path: Path) -> dict[str, dict[str, str]]:
    """The preset file as {section: {key: value}}, in file order."""
    sections: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            current = sections.setdefault(line[1:-1], {})
        elif line:
            key, _, value = line.partition(" = ")
            current[key] = value
    return sections


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_sets = models.available_sets(CONFIG / "model-sets")

    def workdir(self) -> Path:
        path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def render(self, config_dir: Path = CONFIG, **overrides):
        """Render into a temporary directory; return the rendered presets, stdout, and the output directory."""
        workdir = self.workdir()
        models_root = workdir / "models"
        models_root.mkdir()
        # Every shipped weight exists unless the test names the files itself.
        for relative in overrides.pop(
            "models", [file.destination for s in self.model_sets.values() for file in s.files]
        ):
            path = models_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"gguf")
        output = workdir / "build"
        arguments = {
            "output_dir": output,
            "models_root": models_root,
            "default_preset": "qwen3.8-27b-q4",
        }
        pinned_build = overrides.pop("pinned_build", 10920)
        # `check` selects the sibling that writes nothing, which takes
        # neither an output directory nor a models root.
        check = overrides.pop("check", False)
        arguments.update(overrides)
        configuration = presets.load(config_dir, pinned_build)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            if check:
                rendered = presets.validate(configuration, default_preset=arguments["default_preset"])
            else:
                rendered = presets.render(configuration, **arguments)
        return rendered, stdout.getvalue(), output

    def config_with_cases(self, **cases: str) -> Path:
        """A copy of the shipped configuration plus one preset per case."""
        config_dir = self.workdir() / "config"
        shutil.copytree(CONFIG, config_dir)
        for name, body in cases.items():
            (config_dir / "presets" / f"{name}.toml").write_text(replace_restated_keys(body), encoding="utf-8")
        return config_dir

    def test_every_shipped_preset_renders_and_the_router_file_keeps_its_shape(self):
        # The shipped values live in the preset files and are gated by the
        # bench rule; this proves the shape and what holds between presets.
        rendered, stdout, output = self.render()
        text = (output / "models.ini").read_text(encoding="utf-8")
        config = read_ini(output / "models.ini")
        self.assertEqual(list(config), ["*", *LOADABLE_PRESETS])
        # Every child inherits the shared section; the router adds host, port,
        # and alias itself, so no section names them.
        self.assertEqual(config["*"], {"jinja": "true", "ui-config-file": "/etc/tokencrate/ui-config.json"})
        for forbidden in ("host", "port", "alias"):
            self.assertNotIn(forbidden, text)
        # Only the default preset loads at start; the file is plain `key = value` lines.
        self.assertEqual(text.count("load-on-startup = true"), 1)
        self.assertIn("\n[qwen3.8-27b-q4]\nmodel = /models/", text)
        records = {item.preset.name: item for item in rendered}
        self.assertEqual(list(records), SHIPPED_PRESETS)
        for name in LOADABLE_PRESETS:
            self.assertTrue(records[name].loadable, name)
            self.assertEqual(records[name].missing, [], name)
            self.assertIn(f"{name}: loadable\n", stdout)
        for name in GATED_PRESETS:
            self.assertEqual((records[name].loadable, records[name].wait), (False, UNRELEASED_WAIT))
            self.assertIn(f"{name}: {UNRELEASED_WAIT}\n", stdout)
        self.assertIn(f"Rendered {len(LOADABLE_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into {output}.\n", stdout)
        self.assertEqual(presets.rendered_model_ids(output), set(LOADABLE_PRESETS))
        # The MTP variants differ from the default in one thing each: the
        # KV cache type, the model file (with the same patched template), and
        # the slot; the uncensored long preset is the long one on that file.
        variants = ("mtp", "mtp-f16kv", "uncensored-mtp", "mtp-long", "uncensored-mtp-long")
        mtp, f16kv, uncensored, mtp_long, uncensored_long = (config[f"qwen3.8-27b-q4-{name}"] for name in variants)
        self.assertEqual({key for key in mtp if mtp[key] != f16kv.get(key)}, {"cache-type-k", "cache-type-v"})
        self.assertEqual({key for key in mtp if mtp[key] != uncensored.get(key)}, {"model"})
        self.assertEqual({key for key in mtp if mtp[key] != mtp_long.get(key)}, {"ctx-size", "ctx-checkpoints"})
        self.assertEqual({key for key in mtp_long if mtp_long[key] != uncensored_long.get(key)}, {"model"})
        # The two 128K presets differ only in drafting.
        long = config["qwen3.8-27b-q4-long"]
        self.assertEqual({key for key in mtp_long if mtp_long[key] != long.get(key)}, {"spec-type", "spec-draft-n-max"})
        # The Flash-Next presets reuse the 27B's patched template, which
        # their file embeds, and never draft with MTP.
        flash = config["qwen3.8-flash-next-q4"]
        self.assertEqual(flash["chat-template-file"], config["qwen3.8-27b-q4"]["chat-template-file"])
        self.assertNotIn("spec-type", flash)
        # One entry per loadable preset in each agent's list, no per-effort
        # entries: the agents switch effort per turn.
        pi_models = read_json(output / "agents" / "pi" / "models.json")
        self.assertEqual(pi_models["providers"]["tokencrate"]["api"], "openai-completions")
        omp_models = read_json(output / "agents" / "omp" / "models.yml")
        self.assertEqual(omp_models["providers"]["tokencrate"]["baseUrl"], "http://llama:8080/v1")
        for document in (pi_models, omp_models):
            ids = [model["id"] for model in document["providers"]["tokencrate"]["models"]]
            self.assertEqual(ids, LOADABLE_PRESETS)

    def test_the_renderer_maps_every_preset_key_to_its_router_option(self):
        # One preset that sets every typed key: its section holds each key's
        # router spelling and value, the model set's file and template, and
        # no start-up load (it is not the default).
        case = PRESET_HEAD + (
            'parallel = 1\nspec_type = "draft-mtp"\nspec_draft_n_max = 3\nn_cpu_moe = 38\n'
            "batch_size = 2048\nubatch_size = 2048\nctx_checkpoints = 8\n"
            'reasoning_effort = "xhigh"\nreasoning_efforts = ["low", "xhigh"]\n'
            "[sampling]\ntemperature = 1.0\ntop_p = 0.95\ntop_k = 20\nmin_p = 0.0\npresence_penalty = 0.0\n"
            "[requires]\nvram_gib = 24\nram_gib = 96\n"
        )
        rendered, _, output = self.render(self.config_with_cases(case=case))
        config = read_ini(output / "models.ini")
        section = config["case"]
        sibling = config["qwen3.8-27b-q4"]
        self.assertEqual(
            (section["model"], section["chat-template-file"]), (sibling["model"], sibling["chat-template-file"])
        )
        self.assertNotIn("load-on-startup", section)
        for key, value in {
            "ctx-size": "8192",
            "n-predict": "16384",
            "parallel": "1",
            "gpu-layers": "99",
            "flash-attn": "auto",
            "cache-type-k": "f16",
            "cache-type-v": "f16",
            "spec-type": "draft-mtp",
            "spec-draft-n-max": "3",
            "n-cpu-moe": "38",
            "batch-size": "2048",
            "ubatch-size": "2048",
            "ctx-checkpoints": "8",
            "chat-template-kwargs": '{"reasoning_effort":"xhigh"}',
            "temperature": "1.0",
            "top-p": "0.95",
            "top-k": "20",
            "min-p": "0.0",
            "presence-penalty": "0.0",
        }.items():
            self.assertEqual(section.get(key), value, key)
        record = {item.preset.name: item for item in rendered}["case"]
        self.assertEqual(record.preset.requires, {"vram_gib": 24, "ram_gib": 96})
        self.assertEqual(record.preset.reasoning_efforts, ["low", "xhigh"])
        self.assertEqual(record.preset.description, "case")

    def test_the_model_list_dialects_follow_the_thinking_shape(self):
        # A preset whose template takes the thinking toggle and one that
        # switches it off: each agent's list spells the two shapes its own way.
        think = PRESET_HEAD + 'reasoning_effort = "xhigh"\nreasoning_efforts = ["low", "medium", "xhigh"]\n'
        plain = PRESET_HEAD.replace("qwen3.8-27b-ud-q4-k-xl", "gpt-oss-20b-mxfp4") + (
            'reasoning_effort = "medium"\nreasoning_efforts = ["low", "medium", "high"]\nthinking_toggle = false\n'
        )
        _, _, output = self.render(self.config_with_cases(think=think, plain=plain))
        pi_models = read_json(output / "agents" / "pi" / "models.json")
        pi_entries = {model["id"]: model for model in pi_models["providers"]["tokencrate"]["models"]}
        self.assertNotIn("think:low", pi_entries)
        think_entry = pi_entries["think"]
        self.assertEqual(think_entry["input"], ["text"])
        self.assertEqual(think_entry["compat"]["thinkingFormat"], "chat-template")
        self.assertEqual(think_entry["compat"]["chatTemplateKwargs"]["enable_thinking"], {"$var": "thinking.enabled"})
        self.assertEqual(
            think_entry["compat"]["chatTemplateKwargs"]["reasoning_effort"],
            {"$var": "thinking.effort", "omitWhenOff": True},
        )
        self.assertEqual(
            think_entry["thinkingLevelMap"], {"minimal": None, "high": None, "xhigh": "xhigh", "max": None}
        )
        plain_entry = pi_entries["plain"]
        self.assertNotIn("enable_thinking", plain_entry["compat"]["chatTemplateKwargs"])
        self.assertEqual(plain_entry["thinkingLevelMap"], {"off": None, "minimal": None, "xhigh": None, "max": None})
        # oh-my-pi reads models.yml as YAML; the file is JSON text.
        omp_models = read_json(output / "agents" / "omp" / "models.yml")
        omp_entries = {model["id"]: model for model in omp_models["providers"]["tokencrate"]["models"]}
        self.assertNotIn("think:low", omp_entries)
        self.assertEqual(omp_entries["think"]["compat"]["thinkingFormat"], "qwen-chat-template")
        self.assertEqual(
            omp_entries["think"]["thinking"],
            {"mode": "effort", "efforts": ["low", "medium", "high", "xhigh"], "requiresEffort": False},
        )
        self.assertEqual(omp_entries["think"]["compat"]["reasoningDisableMode"], "qwen-template-false")
        self.assertTrue(omp_entries["think"]["compat"]["qwenTemplateReasoningEffort"])
        self.assertEqual(
            omp_entries["think"]["compat"]["reasoningEffortMap"], {"minimal": "low", "high": "xhigh", "max": "xhigh"}
        )
        self.assertEqual(omp_entries["plain"]["thinking"], {"mode": "effort", "efforts": ["low", "medium", "high"]})
        self.assertNotIn("reasoningDisableMode", omp_entries["plain"]["compat"])
        self.assertNotIn("thinkingFormat", omp_entries["plain"]["compat"])
        self.assertEqual(
            omp_entries["plain"]["compat"]["reasoningEffortMap"], {"minimal": "low", "xhigh": "high", "max": "high"}
        )

    def test_require_files_skips_presets_whose_files_are_missing(self):
        rendered, stdout, output = self.render(models=[GPT_OSS_20B_WEIGHTS])
        config = read_ini(output / "models.ini")
        self.assertEqual(list(config), ["*", *GPT_OSS_PRESETS])
        self.assertNotIn("load-on-startup", (output / "models.ini").read_text(encoding="utf-8"))
        states = {item.preset.name: item for item in rendered}
        self.assertFalse(states["qwen3.8-27b-q4"].loadable)
        self.assertEqual(states["qwen3.8-27b-q4"].missing, ["unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_XL.gguf"])
        self.assertTrue(states["gpt-oss-20b-fast"].loadable)
        self.assertIn("qwen3.8-27b-q4: skipped (missing unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_XL.gguf)", stdout)
        self.assertIn(f"Rendered {len(GPT_OSS_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into", stdout)
        self.assertEqual(presets.rendered_model_ids(output), set(GPT_OSS_PRESETS))
        pi_models = read_json(output / "agents" / "pi" / "models.json")
        self.assertEqual([model["id"] for model in pi_models["providers"]["tokencrate"]["models"]], GPT_OSS_PRESETS)

    def test_check_mode_writes_nothing(self):
        rendered, stdout, output = self.render(check=True)
        self.assertFalse(output.exists())
        self.assertEqual(len(rendered), len(SHIPPED_PRESETS))
        self.assertIn(f"{VALIDATED}\n", stdout)
        self.assertEqual(presets.rendered_model_ids(output), set())

    def test_render_check_validates_the_shipped_configuration(self):
        output = self.workdir() / "build"
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            rendered = presets.validate(presets.load(CONFIG, 10920), default_preset="")
        lines = stdout.getvalue().splitlines()
        self.assertEqual(
            lines[:-1],
            [f"{name}: {UNRELEASED_WAIT if name in GATED_PRESETS else 'valid'}" for name in SHIPPED_PRESETS],
        )
        self.assertEqual(lines[-1], VALIDATED)
        self.assertEqual([item.preset.name for item in rendered], SHIPPED_PRESETS)
        self.assertFalse(output.exists())

    def test_load_reads_the_shipped_configuration(self):
        model_sets, loaded = _MODEL_SETS, _PRESETS
        self.assertEqual(sorted(model_sets), sorted(SHIPPED_MODEL_SETS))
        self.assertEqual([preset.name for preset in loaded], SHIPPED_PRESETS)
        for preset in loaded:
            self.assertIn(preset.model_set, model_sets)
        self.assertTrue(model_sets["qwen3.8-27b-ud-q4-k-xl"].mtp)
        glm = model_sets["glm-5.3-flash-ud-q2-k-xl"]
        self.assertEqual((glm.llama_build, len(glm.splits), glm.mtp), ("unreleased", 3, True))
        self.assertEqual(len(model_sets["glm-5.3-flash-orcarouter-uncensored-q2-k"].splits), 2)
        flash = model_sets["qwen3.8-flash-next-ud-q4-k-xl"]
        self.assertEqual(
            (flash.llama_build, flash.mtp, len(flash.splits), flash.chat_template_file),
            ("", False, 3, "qwen3.8-27b-agent.jinja"),
        )

    def test_glm_efforts_map_onto_the_agents_thinking_levels(self):
        # The GLM template takes low, high, and max with no thinking switch;
        # the presets are gated, so the maps are checked on the entries the
        # renderer would write once the gate opens.
        glm = next(preset for preset in _PRESETS if preset.name == "glm-5.3-flash-q2")
        self.assertEqual((glm.reasoning_efforts, glm.server["reasoning_effort"]), (["low", "high", "max"], "high"))
        [model] = presets.agent_models([presets.RenderedPreset(glm, True)])
        self.assertEqual((model["thinking_toggle"], model["reasoning"], model["context"]), (False, True, 131072))
        pi_entry = agentmodels.pi_model_entry(model)
        self.assertNotIn("enable_thinking", pi_entry["compat"]["chatTemplateKwargs"])
        self.assertEqual(
            pi_entry["thinkingLevelMap"], {"off": None, "minimal": None, "medium": None, "xhigh": None, "max": "max"}
        )
        omp_entry = agentmodels.omp_model_entry(model)
        self.assertEqual(
            omp_entry["thinking"], {"mode": "effort", "efforts": ["low", "medium", "high", "xhigh", "max"]}
        )
        self.assertEqual(
            omp_entry["compat"]["reasoningEffortMap"], {"minimal": "low", "medium": "high", "xhigh": "max"}
        )
        self.assertNotIn("reasoningDisableMode", omp_entry["compat"])

    def gated_config(self, llama_build: str) -> Path:
        """A copy of the shipped configuration whose gpt-oss set requires a build."""
        config_dir = self.workdir() / "config"
        shutil.copytree(CONFIG, config_dir)
        with (config_dir / "model-sets" / "gpt-oss-20b-mxfp4.toml").open("a", encoding="utf-8") as handle:
            handle.write(f'\n[requires]\nllama_build = "{llama_build}"\n')
        return config_dir

    def test_a_model_set_that_needs_a_newer_build_keeps_its_presets_out_of_the_router(self):
        # The pinned build cannot load the set: its preset is validated and
        # listed as waiting, and left out of the router and the agent lists
        # in both modes, so nothing can pick a preset that would crash the
        # child server on an unknown architecture.
        wait = "waits for an unreleased llama.cpp build (pinned: b10920)"
        config_dir = self.gated_config("unreleased")
        rendered, stdout, output = self.render(config_dir)
        states = {item.preset.name: item for item in rendered}
        self.assertEqual((states["gpt-oss-20b-fast"].loadable, states["gpt-oss-20b-fast"].wait), (False, wait))
        self.assertTrue(states["qwen3.8-27b-q4"].loadable)
        self.assertIn(f"gpt-oss-20b-fast: {wait}\n", stdout)
        self.assertIn(
            f"Rendered {len(LOADABLE_PRESETS) - len(GPT_OSS_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into",
            stdout,
        )
        self.assertNotIn("gpt-oss-20b-fast", presets.rendered_model_ids(output))
        pi_models = read_json(output / "agents" / "pi" / "models.json")
        self.assertNotIn("gpt-oss-20b-fast", [model["id"] for model in pi_models["providers"]["tokencrate"]["models"]])
        rendered, stdout, output = self.render(config_dir, check=True)
        self.assertFalse(output.exists())
        self.assertIn(f"gpt-oss-20b-fast: {wait}\n", stdout)
        self.assertIn(f"{VALIDATED}\n", stdout)
        # The default preset cannot be a waiting one.
        with self.assertRaises(TokenCrateError) as caught:
            self.render(config_dir, default_preset="gpt-oss-20b-fast")
        self.assertEqual(
            str(caught.exception),
            f"preset gpt-oss-20b-fast {wait}; bash bin/tokencrate presets list shows the loadable ones",
        )
        # A build number gates until the pin reaches it.
        gpt_oss = models.available_sets(self.gated_config("b10921") / "model-sets")["gpt-oss-20b-mxfp4"]
        self.assertEqual(presets.build_wait(gpt_oss, 10920), "waits for llama.cpp build b10921 (pinned: b10920)")
        self.assertEqual(presets.build_wait(gpt_oss, 10921), "")
        rendered, stdout, _ = self.render(self.gated_config("b10920"))
        self.assertTrue({item.preset.name: item for item in rendered}["gpt-oss-20b-fast"].loadable)
        self.assertIn(f"Rendered {len(LOADABLE_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into", stdout)
        self.assertEqual(presets.build_wait(self.model_sets["gpt-oss-20b-mxfp4"], 1), "")

    def test_load_rejects_a_missing_chat_template(self):
        config_dir = self.workdir() / "config"
        shutil.copytree(CONFIG / "model-sets", config_dir / "model-sets")
        shutil.copytree(CONFIG / "presets", config_dir / "presets")
        (config_dir / "chat-templates").mkdir()
        with self.assertRaises(TokenCrateError) as caught:
            presets.load(config_dir, 10920)
        self.assertIn("references a missing chat template: qwen3.8-27b-agent.jinja", str(caught.exception))

    def test_load_presets_requires_at_least_one_preset(self):
        empty = self.workdir()
        with self.assertRaises(TokenCrateError) as caught:
            presets.load_presets(empty, self.model_sets)
        self.assertEqual(str(caught.exception), f"no presets found in {empty}")

    def test_unknown_default_preset_is_rejected(self):
        with self.assertRaises(TokenCrateError) as caught:
            self.render(default_preset="nope")
        self.assertEqual(str(caught.exception), "unknown preset: nope (run: bash bin/tokencrate presets list)")

    def preset_error(self, body: str, message: str, filename: str = "case.toml"):
        path = self.workdir() / filename
        path.write_text(replace_restated_keys(body), encoding="utf-8")
        with self.assertRaises(TokenCrateError) as caught:
            presets.read_preset(path, self.model_sets)
        self.assertIn(message, str(caught.exception))

    def test_preset_validation_rules(self):
        head = PRESET_HEAD
        self.preset_error(head + 'parallel = 2\nspec_type = "draft-mtp"\n', "requires parallel = 1")
        self.preset_error(head + "cache_reuse = 256\n", "unknown [server] key(s): cache_reuse")
        self.preset_error(head + 'extra = ["--verbose"]\n', "must be a table")
        self.preset_error(head + "[server.extra]\nverbose = [1]\n", "must be a string, number, or boolean")
        # Only the listed options pass through: not the ones that tie a
        # preset to the container and the router, download model files,
        # run tools, proxy MCP servers, or spell a typed key, and not an
        # option the list does not know.
        for key in ("host", "m", "api-key", "ctx-size", "hf-repo", "docker-repo", "rpc", "tools", "agent", "min-p"):
            self.preset_error(head + f'[server.extra]\n{key} = "x"\n', f"cannot set {key}; the renderer passes through")
        self.preset_error(
            head.replace('flash_attn = "auto"', 'flash_attn = "off"').replace(
                'cache_type_v = "f16"', 'cache_type_v = "q8_0"'
            ),
            "quantized cache_type_v",
        )
        self.preset_error(head + 'reasoning_efforts = ["low"]\n', "needs a default reasoning_effort")
        self.preset_error(
            head + 'reasoning_effort = "brief"\nreasoning_efforts = ["brief"]\n', "agent thinking level names"
        )
        self.preset_error(head + 'reasoning_effort = "low"\nreasoning_efforts = ["low", "low"]\n', "must not repeat")
        self.preset_error(head.replace("ctx_size = 8192", "ctx_size = 1000"), "at least 1024")
        self.preset_error(head.replace("ctx_size = 8192\n", ""), "[server] ctx_size is required")
        self.preset_error(head + "parallel = 3\n", "divisible by parallel")
        self.preset_error(head + 'flash_attn = "maybe"\n', "flash_attn must be one of")
        self.preset_error(head + 'cache_type_k = "q4_0"\n', "cache_type_k must be one of f16, bf16, q8_0")
        self.preset_error(head + 'spec_type = "ngram-simple"\n', "spec_type must be one of none, draft-mtp")
        self.preset_error(head + "[sampling]\nrepeat_penalty = 1.1\n", "unknown [sampling] key(s): repeat_penalty")
        self.preset_error(head + "[sampling]\ntemperature = true\n", "temperature must be a number")
        self.preset_error(head + "[requires]\nvram_gib = 0\n", "vram_gib must be at least 1")
        self.preset_error(head + "[requires]\nram_gib = 0\n", "ram_gib must be at least 1")
        self.preset_error(head + "n_cpu_moe = -1\n", "n_cpu_moe must be at least 0")
        self.preset_error(head.replace("schema = 1", "schema = 2"), "schema must be 1")
        self.preset_error(head.replace('"case"', '"' + "x" * 121 + '"'), "description must be at most 120 characters")
        self.preset_error(head + "unexpected = 1\n", "unknown [server] key(s): unexpected")
        self.preset_error("extra = 1\n" + head, "unknown key(s): extra")
        self.preset_error(head, "unsafe preset filename", filename="Bad_Name.toml")
        self.preset_error(
            'schema = 1\ndescription = "case"\nmodel_set = "missing"\n[server]\nctx_size = 8192\n',
            "model_set must name",
        )
        gpt = PRESET_HEAD.replace('model_set = "qwen3.8-27b-ud-q4-k-xl"', 'model_set = "gpt-oss-20b-mxfp4"')
        self.preset_error(gpt + 'spec_type = "draft-mtp"\nspec_draft_n_max = 3\n', "mtp = true")

    def test_extra_options_become_ini_lines(self):
        # Booleans, numbers, and strings are written as the router reads them,
        # after the typed keys (the router keeps the last value of a key).
        path = self.workdir() / "extra.toml"
        path.write_text(
            PRESET_HEAD + 'reasoning_effort = "low"\nenable_thinking = false\n'
            '[server.extra]\nverbose = true\nload-mode = "none"\n'
            'override-kv = "a=int:1"\nlog-prompts-dir = "/tmp/prompts"\n',
            encoding="utf-8",
        )
        preset = presets.read_preset(path, self.model_sets)
        section = presets.preset_section(preset, self.model_sets["qwen3.8-27b-ud-q4-k-xl"], startup=False)
        self.assertEqual(section[0], "[extra]")
        self.assertEqual(
            section[-4:],
            ["verbose = true", "load-mode = none", "override-kv = a=int:1", "log-prompts-dir = /tmp/prompts"],
        )
        self.assertIn('chat-template-kwargs = {"enable_thinking":false,"reasoning_effort":"low"}', section)
        self.assertNotIn("load-on-startup = true", section)

    def test_expert_offload_and_system_memory_reach_the_preset_file_and_the_record(self):
        # The first N layers keep their expert weights in system memory; the
        # option is written only when set, and the RAM requirement travels
        # with the preset for doctor and presets list.
        path = self.workdir() / "offload.toml"
        path.write_text(PRESET_HEAD + "n_cpu_moe = 21\n[requires]\nvram_gib = 24\nram_gib = 64\n", encoding="utf-8")
        preset = presets.read_preset(path, self.model_sets)
        self.assertEqual(preset.requires, {"vram_gib": 24, "ram_gib": 64})
        section = presets.preset_section(preset, self.model_sets["qwen3.8-27b-ud-q4-k-xl"], startup=False)
        self.assertIn("n-cpu-moe = 21", section)
        path.write_text(PRESET_HEAD + "n_cpu_moe = 0\n", encoding="utf-8")
        preset = presets.read_preset(path, self.model_sets)
        section = presets.preset_section(preset, self.model_sets["qwen3.8-27b-ud-q4-k-xl"], startup=False)
        self.assertFalse(any(line.startswith("n-cpu-moe") for line in section))

    def test_values_the_router_would_truncate_are_refused(self):
        # The router reads a value up to the first ; or #, so a model file or
        # option value with either would silently load something else.
        for value in ("a;b", "x #1", "", "two\nlines"):
            with self.assertRaises(TokenCrateError) as caught:
                presets.ini_line("lora", value)
            self.assertIn("cannot be written to the preset file", str(caught.exception))
        self.assertEqual(presets.ini_line("fit", "off"), "fit = off")
        self.assertEqual(presets.ini_line("min-p", 1e-07), "min-p = 1e-07")
        config_dir = self.workdir() / "config"
        shutil.copytree(CONFIG, config_dir)
        # A model file name with such a character never reaches the renderer:
        # the manifest's path rule refuses it first.
        manifest = config_dir / "model-sets" / "qwen3.8-27b-ud-q4-k-xl.toml"
        manifest.write_text(
            manifest.read_text().replace("Qwen3.8-27B-UD-Q4_K_XL.gguf", "Qwen#1.gguf"), encoding="utf-8"
        )
        with self.assertRaises(TokenCrateError) as caught:
            self.render(config_dir, check=True)
        self.assertIn("source must be a relative path", str(caught.exception))

    def test_rendered_model_ids_reads_the_rendered_preset_file(self):
        output = self.workdir() / "build"
        self.assertEqual(presets.rendered_model_ids(output), set())
        path = output / "models.ini"
        path.parent.mkdir(parents=True)
        path.write_text(
            "[*]\njinja = true\n\n[a]\nmodel = /models/a.gguf\n\n[b]\nmodel = /models/b.gguf\n", encoding="utf-8"
        )
        self.assertEqual(presets.rendered_model_ids(output), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
