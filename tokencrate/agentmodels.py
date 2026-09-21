"""How the two coding agents spell a model list.

pi reads `models.json` and oh-my-pi reads `models.yml`; both name the
router, the context, and the thinking levels, and each spells them its
own way, with its own `compat` flags. The renderer builds one plain model
list (`presets.agent_models`) and this module turns it into each agent's
file, so a change to either dialect -- or the removal of one agent --
stays here.
"""

from __future__ import annotations

# The router as the agent containers reach it, on the internal network.
LLAMA_URL_FOR_AGENTS = "http://llama:8080"
# The thinking levels pi and oh-my-pi know, in order; presets declare their
# efforts with these names so the agents can map levels onto them, and
# presets.py validates a preset's declared efforts against them.
AGENT_THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def thinking_level_map(model: dict, *, hide_unsupported: bool) -> dict:
    """Map the agents' thinking levels onto the template's efforts.

    With hide_unsupported (pi), a level the template does not know maps to
    null, which removes it from pi's picker. Otherwise (oh-my-pi) each such
    level maps to the nearest effort the template accepts, because oh-my-pi
    sends unmapped levels through unchanged and the template would reject
    them."""
    efforts = list(model["efforts"])
    if not efforts:
        return {}
    mapping: dict = {}
    for level in AGENT_THINKING_LEVELS:
        if level == "off":
            if not model["thinking_toggle"] and hide_unsupported:
                mapping["off"] = None
            continue
        if level in efforts:
            # pi lists xhigh and max only when the map names them explicitly.
            if hide_unsupported and level in ("xhigh", "max"):
                mapping[level] = level
            continue
        if hide_unsupported:
            mapping[level] = None
            continue
        ordered = [item for item in AGENT_THINKING_LEVELS[1:] if item in efforts]
        position = AGENT_THINKING_LEVELS.index(level)
        lower = [item for item in ordered if AGENT_THINKING_LEVELS.index(item) < position]
        higher = [item for item in ordered if AGENT_THINKING_LEVELS.index(item) > position]
        mapping[level] = higher[0] if higher else lower[-1]
    return mapping


def pi_models_json(models_list: list[dict]) -> dict:
    return {
        "providers": {
            "tokencrate": {
                "baseUrl": f"{LLAMA_URL_FOR_AGENTS}/v1",
                "api": "openai-completions",
                "apiKey": "tokencrate",
                "models": [pi_model_entry(model) for model in models_list],
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                    "maxTokensField": "max_tokens",
                },
            }
        }
    }


def pi_model_entry(model: dict) -> dict:
    entry = {
        "id": model["id"],
        "name": model["name"],
        "reasoning": model["reasoning"],
        "input": ["text"],
        "contextWindow": model["context"],
        "maxTokens": model["max_tokens"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }
    if model["reasoning"] and model["efforts"]:
        # pi's chat-template thinking format sends the selected level as
        # chat_template_kwargs.reasoning_effort (omitted when thinking is
        # off) and, for templates with a switch, enable_thinking.
        kwargs: dict = {}
        if model["thinking_toggle"]:
            kwargs["enable_thinking"] = {"$var": "thinking.enabled"}
        kwargs["reasoning_effort"] = {"$var": "thinking.effort", "omitWhenOff": True}
        entry["compat"] = {"thinkingFormat": "chat-template", "chatTemplateKwargs": kwargs}
        entry["thinkingLevelMap"] = thinking_level_map(model, hide_unsupported=True)
    return entry


def omp_model_entry(model: dict) -> dict:
    entry = {
        "id": model["id"],
        "name": model["name"],
        "contextWindow": model["context"],
        "maxTokens": model["max_tokens"],
        "reasoning": model["reasoning"],
        "input": ["text"],
    }
    if model["reasoning"] and model["efforts"]:
        # oh-my-pi sends reasoning_effort at the top level (which llama-server
        # maps into the template) and, for the Qwen dialect, also inside
        # chat_template_kwargs together with the thinking switch.
        compat: dict = {"supportsReasoningEffort": True}
        if model["thinking_toggle"]:
            # The qwen-chat-template dialect carries enable_thinking and the
            # effort inside chat_template_kwargs, which llama-server maps into
            # the template; the plain qwen dialect would add top-level fields.
            # The disable mode must be named, or oh-my-pi encodes "off" as the
            # lowest effort with thinking still on.
            compat["thinkingFormat"] = "qwen-chat-template"
            compat["qwenTemplateReasoningEffort"] = True
            compat["reasoningDisableMode"] = "qwen-template-false"
        mapping = thinking_level_map(model, hide_unsupported=False)
        if mapping:
            compat["reasoningEffortMap"] = mapping
        entry["compat"] = compat
        # oh-my-pi clamps a level that the model does not list to the nearest
        # listed one before the map applies, so a level that maps upward
        # (high -> xhigh) must be listed too; levels outside the declared
        # range clamp to the nearest end, which is what the map would do.
        ordered = [level for level in AGENT_THINKING_LEVELS[1:] if level in model["efforts"]]
        low_index = AGENT_THINKING_LEVELS.index(ordered[0])
        high_index = AGENT_THINKING_LEVELS.index(ordered[-1])
        entry["thinking"] = {
            "mode": "effort",
            "efforts": [level for index, level in enumerate(AGENT_THINKING_LEVELS) if low_index <= index <= high_index],
        }
        if model["thinking_toggle"]:
            # Without this, oh-my-pi turns "off" into the lowest effort with
            # thinking still on instead of sending enable_thinking=false.
            entry["thinking"]["requiresEffort"] = False
    return entry


def omp_models(models_list: list[dict]) -> dict:
    return {
        "providers": {
            "tokencrate": {
                "baseUrl": f"{LLAMA_URL_FOR_AGENTS}/v1",
                "api": "openai-completions",
                "auth": "none",
                "models": [omp_model_entry(model) for model in models_list],
            }
        }
    }
