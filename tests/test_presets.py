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
_MODEL_SETS, _PRESETS = presets.load_all(CONFIG)
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

    def test_shipped_presets_render_a_complete_configuration(self):
        rendered, stdout, output = self.render()
        text = (output / "models.ini").read_text(encoding="utf-8")
        config = read_ini(output / "models.ini")
        self.assertEqual(list(config), ["*", *LOADABLE_PRESETS])
        # Every child inherits the shared section; the router adds host, port,
        # and alias itself, so no section names them.
        self.assertEqual(config["*"], {"jinja": "true", "ui-config-file": "/etc/tokencrate/ui-config.json"})
        self.assertNotIn("host", text)
        self.assertNotIn("port", text)
        self.assertNotIn("alias", text)
        qwen = config["qwen3.8-27b-q4"]
        self.assertEqual(
            qwen,
            {
                "model": "/models/unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_XL.gguf",
                "chat-template-file": "/etc/tokencrate/chat-templates/qwen3.8-27b-agent.jinja",
                "load-on-startup": "true",
                "ctx-size": "65536",
                "n-predict": "16384",
                "parallel": "2",
                "gpu-layers": "99",
                "flash-attn": "auto",
                "cache-type-k": "q8_0",
                "cache-type-v": "q8_0",
                "ctx-checkpoints": "8",
                "chat-template-kwargs": '{"reasoning_effort":"xhigh"}',
                "fit": "off",
                "temperature": "1.0",
                "top-p": "0.95",
                "top-k": "20",
                "min-p": "0.0",
                "presence-penalty": "0.0",
            },
        )
        # Only the default preset loads at start; the file is plain `key = value` lines.
        self.assertEqual(text.count("load-on-startup = true"), 1)
        self.assertIn("\n[qwen3.8-27b-q4]\nmodel = /models/unsloth/", text)
        gpt_oss = config["gpt-oss-20b-fast"]
        self.assertNotIn("load-on-startup", gpt_oss)
        self.assertNotIn("chat-template-file", gpt_oss)
        self.assertEqual((gpt_oss["batch-size"], gpt_oss["ubatch-size"]), ("2048", "2048"))
        # The returned records carry the loadable state, the efforts, and the
        # host requirements.
        records = {item.preset.name: item for item in rendered}
        self.assertEqual(list(records), SHIPPED_PRESETS)
        qwen_record = records["qwen3.8-27b-q4"]
        self.assertTrue(qwen_record.loadable)
        self.assertEqual(qwen_record.missing, [])
        self.assertEqual(qwen_record.preset.reasoning_efforts, ["low", "medium", "xhigh"])
        self.assertEqual(qwen_record.preset.requires, {"vram_gib": 24})
        self.assertTrue(qwen_record.preset.description.startswith("Qwen3.8-27B Q4"))
        self.assertEqual(records["gpt-oss-20b-fast"].preset.reasoning_efforts, ["low", "medium", "high"])
        self.assertIn("qwen3.8-27b-q4: loadable\n", stdout)
        self.assertIn(f"Rendered {len(LOADABLE_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into {output}.\n", stdout)
        # The Flash-Next presets keep most expert layers in system memory and
        # reuse the 27B's patched template, which their file embeds.
        flash = config["qwen3.8-flash-next-q4"]
        self.assertEqual((flash["n-cpu-moe"], flash["ctx-size"], flash["ctx-checkpoints"]), ("38", "131072", "16"))
        self.assertEqual((flash["batch-size"], flash["ubatch-size"]), ("2048", "2048"))
        self.assertEqual(flash["chat-template-file"], qwen["chat-template-file"])
        self.assertNotIn("spec-type", flash)
        self.assertEqual(records["qwen3.8-flash-next-q4"].preset.requires, {"vram_gib": 30, "ram_gib": 96})
        self.assertEqual(presets.rendered_model_ids(output), set(LOADABLE_PRESETS))
        for name in GATED_PRESETS:
            self.assertEqual((records[name].loadable, records[name].wait), (False, UNRELEASED_WAIT))
            self.assertIn(f"{name}: {UNRELEASED_WAIT}\n", stdout)
            self.assertEqual(records[name].preset.requires, {"vram_gib": 30, "ram_gib": 96})
        mtp = config["qwen3.8-27b-q4-mtp"]
        self.assertEqual((mtp["spec-type"], mtp["spec-draft-n-max"], mtp["parallel"]), ("draft-mtp", "3", "1"))
        # The two MTP variants differ from the default in one thing each: the
        # KV cache type, and the model file (with the same patched template).
        f16kv = config["qwen3.8-27b-q4-mtp-f16kv"]
        self.assertEqual({key for key in mtp if mtp[key] != f16kv.get(key)}, {"cache-type-k", "cache-type-v"})
        self.assertEqual((f16kv["cache-type-k"], f16kv["cache-type-v"]), ("f16", "f16"))
        uncensored = config["qwen3.8-27b-q4-mtp-uncensored"]
        self.assertEqual({key for key in mtp if mtp[key] != uncensored.get(key)}, {"model"})
        self.assertEqual(uncensored["chat-template-file"], mtp["chat-template-file"])
        self.assertIn(
            "uncensored (abliterated by huihui-ai)", records["qwen3.8-27b-q4-mtp-uncensored"].preset.description
        )
        pi_models = read_json(output / "agents" / "pi" / "models.json")
        pi_entries = {model["id"]: model for model in pi_models["providers"]["tokencrate"]["models"]}
        self.assertIn("qwen3.8-27b-q4", pi_entries)
        # The agents switch effort per turn; no per-effort model entries exist.
        self.assertNotIn("qwen3.8-27b-q4:low", pi_entries)
        self.assertEqual(pi_models["providers"]["tokencrate"]["api"], "openai-completions")
        qwen = pi_entries["qwen3.8-27b-q4"]
        self.assertEqual(qwen["input"], ["text"])
        self.assertEqual(qwen["compat"]["thinkingFormat"], "chat-template")
        self.assertEqual(qwen["compat"]["chatTemplateKwargs"]["enable_thinking"], {"$var": "thinking.enabled"})
        self.assertEqual(
            qwen["compat"]["chatTemplateKwargs"]["reasoning_effort"], {"$var": "thinking.effort", "omitWhenOff": True}
        )
        self.assertEqual(qwen["thinkingLevelMap"], {"minimal": None, "high": None, "xhigh": "xhigh", "max": None})
        gpt_oss = pi_entries["gpt-oss-20b-fast"]
        self.assertNotIn("enable_thinking", gpt_oss["compat"]["chatTemplateKwargs"])
        self.assertEqual(gpt_oss["thinkingLevelMap"], {"off": None, "minimal": None, "xhigh": None, "max": None})
        # oh-my-pi reads models.yml as YAML; the file is JSON text.
        omp_models = read_json(output / "agents" / "omp" / "models.yml")
        self.assertEqual(omp_models["providers"]["tokencrate"]["baseUrl"], "http://llama:8080/v1")
        omp_entries = {model["id"]: model for model in omp_models["providers"]["tokencrate"]["models"]}
        self.assertNotIn("qwen3.8-27b-q4:low", omp_entries)
        self.assertEqual(omp_entries["qwen3.8-27b-q4"]["compat"]["thinkingFormat"], "qwen-chat-template")
        self.assertEqual(
            omp_entries["qwen3.8-27b-q4"]["thinking"],
            {"mode": "effort", "efforts": ["low", "medium", "high", "xhigh"], "requiresEffort": False},
        )
        self.assertEqual(omp_entries["qwen3.8-27b-q4"]["compat"]["reasoningDisableMode"], "qwen-template-false")
        self.assertEqual(
            omp_entries["gpt-oss-20b-fast"]["thinking"], {"mode": "effort", "efforts": ["low", "medium", "high"]}
        )
        self.assertNotIn("reasoningDisableMode", omp_entries["gpt-oss-20b-fast"]["compat"])
        self.assertTrue(omp_entries["qwen3.8-27b-q4"]["compat"]["qwenTemplateReasoningEffort"])
        self.assertEqual(
            omp_entries["qwen3.8-27b-q4"]["compat"]["reasoningEffortMap"],
            {"minimal": "low", "high": "xhigh", "max": "xhigh"},
        )
        self.assertNotIn("thinkingFormat", omp_entries["gpt-oss-20b-fast"]["compat"])
        self.assertEqual(
            omp_entries["gpt-oss-20b-fast"]["compat"]["reasoningEffortMap"],
            {"minimal": "low", "xhigh": "high", "max": "high"},
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

    def test_load_all_reads_the_shipped_configuration(self):
        model_sets, loaded = presets.load_all(CONFIG)
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
        _, loaded = presets.load_all(CONFIG)
        glm = next(preset for preset in loaded if preset.name == "glm-5.3-flash-q2")
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
            f"the default preset gpt-oss-20b-fast {wait}; set LLM_DEFAULT_PRESET to a preset the pinned build loads",
        )
        # A build number gates until the pin reaches it.
        gpt_oss = models.available_sets(self.gated_config("b10921") / "model-sets")["gpt-oss-20b-mxfp4"]
        self.assertEqual(presets.build_wait(gpt_oss, 10920), "waits for llama.cpp build b10921 (pinned: b10920)")
        self.assertEqual(presets.build_wait(gpt_oss, 10921), "")
        rendered, stdout, _ = self.render(self.gated_config("b10920"))
        self.assertTrue({item.preset.name: item for item in rendered}["gpt-oss-20b-fast"].loadable)
        self.assertIn(f"Rendered {len(LOADABLE_PRESETS)} of {len(SHIPPED_PRESETS)} preset(s) into", stdout)
        self.assertEqual(presets.build_wait(self.model_sets["gpt-oss-20b-mxfp4"], 1), "")

    def test_load_all_rejects_a_missing_chat_template(self):
        config_dir = self.workdir() / "config"
        shutil.copytree(CONFIG / "model-sets", config_dir / "model-sets")
        shutil.copytree(CONFIG / "presets", config_dir / "presets")
        (config_dir / "chat-templates").mkdir()
        with self.assertRaises(TokenCrateError) as caught:
            presets.load_all(config_dir)
        self.assertIn("references a missing chat template: qwen3.8-27b-agent.jinja", str(caught.exception))

    def test_load_presets_requires_at_least_one_preset(self):
        empty = self.workdir()
        with self.assertRaises(TokenCrateError) as caught:
            presets.load_presets(empty, self.model_sets)
        self.assertEqual(str(caught.exception), f"no presets found in {empty}")

    def test_unknown_default_preset_is_rejected(self):
        with self.assertRaises(TokenCrateError) as caught:
            self.render(default_preset="nope")
        self.assertEqual(str(caught.exception), "the default preset does not exist: nope")

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
        self.preset_error(head + "[server.extra]\nBad_Flag = 1\n", "is not a llama-server option name")
        self.preset_error(head + "[server.extra]\nlora = [1]\n", "must be a string, number, or boolean")
        # The renderer owns the options that tie a preset to the container and
        # the router, and the ones that download model files past the
        # manifests (by long name or short form, including the Docker Hub
        # option that offline mode does not stop); the router's own models-*
        # options are refused with them.
        for key in ("host", "port", "m", "alias", "api-key", "ctx-size", "np", "mmproj", "load-on-startup", "fit"):
            self.preset_error(head + f'[server.extra]\n{key} = "x"\n', f"must not set {key};")
        for key in ("hf", "hf-repo", "model-url", "mmu", "docker-repo", "dr", "spec-draft-hf", "models-max", "rpc"):
            self.preset_error(head + f'[server.extra]\n{key} = "x"\n', f"must not set {key};")
        # A typed setting has one spelling: the typed key.
        for key, typed in (("min-p", "min_p"), ("n-predict", "n_predict"), ("flash-attn", "flash_attn")):
            self.preset_error(head + f'[server.extra]\n{key} = "x"\n', f"must not set {key}; use the typed key {typed}")
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
        self.preset_error("extra = 1\n" + head, "unknown field(s): extra")
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
            "[server.extra]\nverbose = true\nseed = -1\nlv = 2\ndry-multiplier = 0.8\n"
            'override-kv = "a=int:1"\nno-webui = false\n',
            encoding="utf-8",
        )
        preset = presets.read_preset(path, self.model_sets)
        section = presets.preset_section(preset, self.model_sets["qwen3.8-27b-ud-q4-k-xl"], startup=False)
        self.assertEqual(section[0], "[extra]")
        self.assertEqual(
            section[-6:],
            [
                "verbose = true",
                "seed = -1",
                "lv = 2",
                "dry-multiplier = 0.8",
                "override-kv = a=int:1",
                "no-webui = false",
            ],
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
        manifest = config_dir / "model-sets" / "qwen3.8-27b-ud-q4-k-xl.toml"
        manifest.write_text(
            manifest.read_text().replace("Qwen3.8-27B-UD-Q4_K_XL.gguf", "Qwen#1.gguf"), encoding="utf-8"
        )
        with self.assertRaises(TokenCrateError) as caught:
            self.render(config_dir, check=True)
        self.assertIn("cannot be written to the preset file", str(caught.exception))

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
