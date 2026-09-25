# Models and presets

A **model set** is what you download: one GGUF quantization of one model
(one file, or the parts of a split file), pinned to a Hugging Face commit
with byte sizes and SHA-256 checksums. A **preset** is how llama-server runs
a model set: context size, slots, KV cache types, speculative decoding,
reasoning effort, sampling, and the host memory it needs. One set can serve
several presets. Every preset declares the GPU memory it needs in
`[requires] vram_gib`, and the system memory in `ram_gib` when it keeps
expert weights there (`n_cpu_moe`). `presets list` prints both, and
`doctor --preset` compares them with the host. The shipped presets
declare 15 to 30 GiB; if none fits your card, [write your
own](#presets-for-other-cards).

## Included model sets

| Set | Download | Notes |
| --- | ---: | --- |
| `qwen3.8-27b-ud-q4-k-xl` | 17.6 GB | Qwen3.8-27B, Unsloth UD-Q4_K_XL, Apache-2.0; MTP heads; hybrid attention |
| `qwen3.8-27b-ud-q6-k-xl` | 25.3 GB | The same model at UD-Q6_K_XL for the quality tier |
| `qwen3.8-27b-ud-q3-k-xl` | 13.1 GB | The same model at UD-Q3_K_XL for a 16 GB card, MTP heads included |
| `gpt-oss-20b-mxfp4` | 12.1 GB | gpt-oss-20b in its native MXFP4 quantization, Apache-2.0 |
| `qwen3.8-27b-huihui-abliterated-ud-q4-k-xl` | 17.4 GB | Qwen3.8-27B uncensored: huihui-ai's abliteration of the UD-Q4_K_XL file, the same layout, MTP heads, and template as the original, Apache-2.0 |
| `glm-5.3-flash-ud-q2-k-xl` | 108.7 GB | GLM-5.3-Flash (320B total, 18B active), Unsloth UD-Q2_K_XL in 4 parts, MIT; needs a llama.cpp build with `glm5next` |
| `glm-5.3-flash-orcarouter-uncensored-q2-k` | 116.9 GB | GLM-5.3-Flash uncensored (orcarouter), plain Q2_K in 3 parts, MIT, [gated repository](#hugging-face-access-and-storage); needs the same build |
| `qwen3.8-flash-next-ud-q4-k-xl` | 111.3 GB | Qwen3.8-Flash-Next (125B total, 6B active, plus a 51B n-gram table), Unsloth UD-Q4_K_XL in 4 parts, Qwen Community License |
| `qwen3.8-flash-next-orcarouter-uncensored-q4-k-s` | 111.8 GB | Qwen3.8-Flash-Next uncensored (orcarouter), plain Q4_K_S in 3 parts, Qwen Community License, [gated repository](#hugging-face-access-and-storage) |

List sets and their descriptions with `bash bin/tokencrate models list`.
`models fetch` prints every license and model card before writing files;
review them yourself. The repository's MIT license does not cover weights.

## Included presets

| Preset | Set | Context | Slots | Speculative | `[requires]` | Generation | Use it for |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `qwen3.8-27b-q4-mtp` (default) | Qwen3.8 Q4 | 64K | 1 | MTP, 3 draft tokens | 24 GiB | 138 to 154 tokens/s | a single agent; a second client waits for the slot instead of sharing it |
| `qwen3.8-27b-q4` | Qwen3.8 Q4 | 64K total, 32K per slot | 2 | none | 24 GiB | 74 to 75 tokens/s | the built-in chat UI and an agent at the same time on one loaded model |
| `qwen3.8-27b-q4-long` | Qwen3.8 Q4 | 128K | 1 | none | 28 GiB | 75 to 76 tokens/s | oh-my-pi, whose [first request](agents.md) is large, and long agent sessions |
| `qwen3.8-27b-q4-mtp-long` | Qwen3.8 Q4 | 128K | 1 | MTP, 3 draft tokens | 28 GiB | 138 to 154 tokens/s | oh-my-pi and long agent sessions at the default's speed |
| `qwen3.8-27b-q6-quality` | Qwen3.8 Q6 | 48K | 1 | MTP, 2 draft tokens | 30 GiB | 100 to 113 tokens/s | the quality tier |
| `gpt-oss-20b-fast` | gpt-oss-20b | 128K total, 64K per slot | 2 | none | 20 GiB | 246 to 264 tokens/s | fast chat and a tool-calling fallback |
| `gpt-oss-20b-small` | gpt-oss-20b | 32K | 1 | none | 15 GiB | 244 to 260 tokens/s | a 16 GB card: the tested path of the two |
| `qwen3.8-27b-q3-small` | Qwen3.8 Q3 | 32K | 1 | none | 15 GiB | 89 to 91 tokens/s | a 16 GB card with the 27B; what three bits cost it on agent work is not measured |
| `qwen3.8-27b-q4-mtp-f16kv` | Qwen3.8 Q4 | 64K | 1 | MTP, 3 draft tokens | 25 GiB | 143 to 144 tokens/s | the default's settings with an unquantized KV cache, for long documents and tool calls |
| `qwen3.8-27b-q4-uncensored-mtp` | Qwen3.8 Q4 abliterated | 64K | 1 | MTP, 3 draft tokens | 24 GiB | 143 to 151 tokens/s | uncensored (abliterated), refusals removed at the weight level |
| `qwen3.8-27b-q4-uncensored-mtp-long` | Qwen3.8 Q4 abliterated | 128K | 1 | MTP, 3 draft tokens | 28 GiB | 142 to 147 tokens/s | uncensored (abliterated) with the 128K slot |
| `glm-5.3-flash-q2` | GLM-5.3-Flash Q2 | 128K | 1 | MTP, 2 draft tokens | 30 GiB and 96 GiB RAM | not loadable | the [96 GB RAM tier](#the-96-gb-ram-tier) |
| `glm-5.3-flash-q2-uncensored` | GLM-5.3-Flash Q2 uncensored | 64K | 1 | none (its files drop the MTP head) | 30 GiB and 96 GiB RAM | not loadable | uncensored (orcarouter), 2-bit, no memory margin |
| `qwen3.8-flash-next-q4` | Flash-Next Q4 | 128K | 1 | none | 30 GiB and 96 GiB RAM | 31 to 32 tokens/s | the [96 GB RAM tier](#the-96-gb-ram-tier) that the pinned build loads: 125B parameters, 6B active, experts in system memory |
| `qwen3.8-flash-next-q4-uncensored` | Flash-Next Q4 uncensored | 128K | 1 | none | 30 GiB and 96 GiB RAM | 34 to 35 tokens/s | uncensored (orcarouter), the same settings with two more expert layers on the card |

The `[requires]` values are the preset files' own, which `bash
bin/tokencrate presets list` prints. The generation speeds are for a
short and a long prompt on an RTX 5090, from
[the preset record](validation.md#the-llama-api-and-the-presets) on
llama.cpp build b11028, except `qwen3.8-flash-next-q4-uncensored`, whose
figure is from [the 96 GB tier
record](validation.md#the-settings-of-the-96-gb-ram-tier) on build
b10920, the two 16 GB presets, which are from [their own
record](validation.md#the-16-gb-presets), and the two 128K MTP presets,
from [theirs](validation.md#the-128k-mtp-presets). The presets measured
on the 32 GB card held 3 to 7 GiB less GPU memory than they declare and
the 16 GB pair 1.5 to 2.3 GiB less; the two GLM presets have no GPU
record.

The default preset, `qwen3.8-27b-q4-mtp`, gives a single agent one 64K
slot instead of two 32K slots: an agent's first request is 8,000 to
19,000 tokens ([Coding agents and skills](agents.md) has the figures per
agent), and `xhigh` reasoning grows the prompt quickly
([reasoning effort](#reasoning-effort)). Two requests issued together take
twice as long as one, at the same generation speed, because the second
waits for the slot. In a recorded pi session of 12 turns, pi compacted its
prompt at about 52,000 tokens and continued; at turn 12 the slot was full,
the overflow compaction failed, and the agent stopped accepting prompts
([the record](validation.md#four-clients-long-sessions-and-the-tools)).

One preset is loaded at a time: a request that names another preset waits
for the running request, then the router unloads the loaded model and
reads the other one's full file from disk. Keep one preset for a session;
switching between the two Flash-Next presets replaces one 111 GB file in
the page cache with the other.

## Reasoning effort

Qwen3.8 and gpt-oss think before answering and read their effort from the
request. The effort is an instruction to the model, not a token budget: the
Qwen template adds a system line that asks for careful or brief thinking,
and the model decides how long it thinks. The Qwen presets default to
`xhigh`, the default of the
[model card](https://huggingface.co/Qwen/Qwen3.8-27B), which also notes
that in multi-turn agentic tasks lower effort can cause failures and
retries that cost more in total. The gpt-oss presets stay at `medium`
because speed is their purpose. These defaults apply to clients that send
no effort; the agents always send their thinking level. Higher effort
means longer turns, and the template keeps earlier reasoning in the
prompt, so a slot fills sooner.

Two ways to choose another effort without reloading the model:

- **In pi and oh-my-pi**, use the thinking level: `/thinking low` inside
  the session, `--thinking low` on the command line, or
  `defaultThinkingLevel` in the agent settings. Both agents start at
  `xhigh` and send the level with every request. The generated model
  lists map the agents' levels onto the efforts a preset declares: pi's
  map hides a level the template lacks, and oh-my-pi's map sends such a
  level as the nearest effort the template accepts, upward when one
  exists.

  | Presets | Efforts declared | pi offers |
  | --- | --- | --- |
  | Qwen3.8 27B and Flash-Next | `low`, `medium`, `xhigh`; thinking can be switched off | `off`, `low`, `medium`, `xhigh` |
  | gpt-oss | `low`, `medium`, `high` (the harmony template cannot switch thinking off) | `low`, `medium`, `high` |
  | GLM-5.3-Flash | `low`, `high`, `max` (no thinking switch) | `low`, `high`, `max` |

  What pi sends at its seeded `xhigh` on gpt-oss is `high` by the map;
  [Validation](validation.md#status) says which rows a run has confirmed.
- **In any other client**, send the effort with the request:
  `reasoning_effort` at the top level of the chat completion body (`low`,
  `medium`, or `xhigh`; for gpt-oss `low`, `medium`, or `high`), or
  `chat_template_kwargs` with `reasoning_effort` and, for Qwen,
  `enable_thinking`, which is what the agents send. A request without
  either uses the preset's default.

## Uncensored presets

The uncensored presets appear wherever the other presets do; their
descriptions carry the word "uncensored" and the method.

- `qwen3.8-27b-q4-uncensored-mtp` runs
  [huihui-ai's abliteration](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF)
  of the default preset's file with the default preset's settings. In a
  [benchmark of eight uncensored Qwen3.8-27B builds](https://nathan.sapwell.net/posts/qwen38-27b-abliteration/)
  huihui's placed third (76 percent compliance, KL about 0.07 against the
  original) and every build looped in its reasoning in 30 to 45 percent
  of runs. The `reply terminates` check of `smoke` shows such a loop (the
  reply ends with `length` instead of `stop`).
  `qwen3.8-27b-q4-uncensored-mtp-long` is the same file with the settings
  of `qwen3.8-27b-q4-mtp-long`, a 128K slot that gives such a loop more
  room before `n_predict` ends it.
- `qwen3.8-flash-next-q4-uncensored` runs orcarouter's abliteration of
  Qwen3.8-Flash-Next, with the settings of `qwen3.8-flash-next-q4` and two
  more expert layers on the card, which its smaller file leaves room for.
- `glm-5.3-flash-q2-uncensored` runs orcarouter's abliteration of
  GLM-5.3-Flash, chosen because that method placed first in the same
  benchmark (82 percent compliance, KL about 0.04) on the 27B; nobody has
  measured it on GLM. Its files drop the MTP head, so the preset does not
  draft, and its only quant is a plain 2-bit Q2_K that sits below the
  tier's own quant. Its experts occupy 87.2 GiB of the 93.35 GiB a 96 GB
  host reports (39 of the 45 layers, against 38 for the Unsloth file),
  which leaves no margin: the preset uses a 64K slot, and its first run
  decides whether it fits. If it does not, it is expected to swap through
  the memory map rather than crash.

## The 96 GB RAM tier

Two models keep most of their expert weights in system memory
(`n_cpu_moe`) and the rest on the card. Both need a host with 96 GB of
RAM, which `doctor` compares with `[requires] ram_gib`. The figures are
for the Unsloth file of each model; the uncensored variants differ in
their quant and layer split.

| Property | Qwen3.8-Flash-Next | GLM-5.3-Flash |
| --- | --- | --- |
| Parameters | 125B total, 6B active, plus a 51B n-gram table | 320B total, 18B active |
| Quant and download | UD-Q4_K_XL, 111.3 GB (KL 0.047 in [Unsloth's table](https://unsloth.ai/docs/models/qwen3.8-next)) | UD-Q2_K_XL, 108.7 GB (78 percent top-1 agreement with the full model) |
| Expert layers in system memory | 38 of 48 (about 60 GiB mapped) | 38 of 45 (about 78 GiB) |
| Held on the card | 26.2 GiB (declares 30) | not measured (declares 30) |
| Generation | 31 to 32 tokens/s | 6 to 7 tokens/s in one consumer report on an RTX 3090 |
| Prompt processing | 98 tokens/s short, 660 for a 6K prompt | 60 to 70 tokens/s in that same report |
| Loads on the pinned build | yes | no; waits for a llama.cpp release with `glm5next` |

Flash-Next is the tier's loadable model. Its prompt processing is a
quarter of the 27B's, so a pi session's first request (about 8,000
tokens, [Coding agents and skills](agents.md)) takes about 12 seconds
before the first word at 660 tokens per second. That figure is computed; the recorded agent session ran at the
default micro-batch and took 43 seconds.

The weights in system memory are memory-mapped, so the host counts them
as page cache, not as used memory: a system monitor shows a few GiB in
use while `free` shows 86 GiB of cache.

The Flash-Next presets use a 2048 micro-batch, which holds 2.2 GiB more
of the card than the default 512 and more than doubles the long-prompt
speed.
`load-mode = "none"` would double prompt processing again but reads the
experts into memory the kernel cannot reclaim (the record measured 5 GiB
of available memory left with 32 GiB of swap in use); the presets do not
set it, and the preset comment says how to try it. Neither uses MTP:
on the pinned build the model's MTP layer needs an open llama.cpp pull
request (28243) and separate draft files.

No llama.cpp release carries GLM-5.3-Flash's architecture (`glm5next`),
so its model sets declare `[requires] llama_build = "unreleased"` and
`up`, `presets list`, and `doctor` mark both presets as waiting
([Adding a model](#adding-a-model) describes the gate). The model ships
because it is expected to beat the 27B on knowledge, going by the
Artificial Analysis scores of the full models (checked 2026-09-20):

| Score | GLM-5.3-Flash | Qwen3.8-27B |
| --- | ---: | ---: |
| Omniscience | +7 | −10 |
| Intelligence Index | 42 | 34 |
| HLE | 40 percent | 34 percent |

The 2-bit quant that fits keeps 78 percent top-1 agreement with its
full model, so the edge over the 27B is
expected, not measured; [Validation](validation.md#status) says what a
run has confirmed, and
[the settled decision](../CONTRIBUTING.md#settled-decisions) says why the
two models of this tier are these two.

The two GLM presets take their settings from
[pull request 27754](https://github.com/ggml-org/llama.cpp/pull/27754)
and the model discussion, with a fallback ladder in the preset comments
for the first run; they need tuning after every llama.cpp update. The
llama container sets `NVIDIA_TF32_OVERRIDE=0` for every preset
(`compose.yaml`), because that pull request names it as required for
correct GLM output; the other presets are unaffected. No vision
projector is mounted, so the vision tower is unused.

## KV cache and context checkpoints

The Qwen presets keep the KV cache in `q8_0`. `qwen3.8-27b-q4-mtp-f16kv`
keeps it unquantized: only the 16 full-attention layers of the 64 hold a
KV cache, so f16 cost about 2 GiB more and 7 percent of generation speed
after a 6K-token prompt on the RTX 5090, and bf16 gained nothing over
it. A KL benchmark on the same architecture put the `q8_0` cache at a
mean KL of 0.024, worst on long documents and tool calls; the preset
comment has the source.

The Qwen presets use context checkpoints (8, or 16 for the 128K presets),
which is how llama-server reuses earlier prompt work on a hybrid-attention
model: one more turn on a 6K-token conversation re-processed 39 tokens on
Flash-Next.

## The patched chat template

The Qwen sets, the Flash-Next ones included, ship with a patched chat
template: the template embedded in the GGUF raises `System message must
be at the beginning.` for any system or developer message after the first
turn, which clients such as Claude Code and Codex send mid-conversation.
The copy under `config/chat-templates/` renders such a message as a
normal system turn and is otherwise identical (one block differs);
`smoke` proves it on the running server, and the header of
[the template file](../config/chat-templates/qwen3.8-27b-agent.jinja)
names the upstream source and the discussions behind the change.

## Adding a model

1. Print a manifest draft for the GGUF file and save it under
   `config/model-sets/`:

   ```bash
   bash bin/tokencrate models draft hf:<owner>/<repository>:<file>.gguf \
     > config/model-sets/<set>.toml
   ```

   Choose a `<set>` name that `models list` does not show.

   The draft pins the repository's current commit and fills sizes and
   checksums from the Hub. Replace the `TODO` markers (description and
   license link), set `mtp` (true when the GGUF contains
   multi-token-prediction heads), and add `chat_template_file` when the
   model needs the patched template. The parts of a split file are listed
   as `split` rows.

   A model whose architecture the pinned llama.cpp build does not know
   gets a `[requires]` table with `llama_build`: the first build that
   loads it, as `pins.env` spells it (`llama_build = "b11100"`), or
   `"unreleased"` while no release carries the support. Its presets
   validate, are listed as waiting (`waits for llama.cpp build b11100
   (pinned: b11028)`), and stay out of the router and the agent model
   lists until the pin reaches that build; `LLM_DEFAULT_PRESET` cannot
   name one. When a release carries the support, write its build number
   into the set and raise the pin past it
   ([Upgrading](configuration.md#upgrading)).

2. Copy the closest preset under `config/presets/`, point `model_set` at the
   new set, and adjust the context size and `[requires] vram_gib`. The
   preset id is the file name without `.toml`.

   Presets express llama-server settings through typed keys, which
   `tokencrate/presets.py` defines with their types and limits. The
   `[server.extra]` table passes a short list of further options through
   unchanged, as `name = value` with the option's long name without the
   leading dashes. The list is `override-kv`, `load-mode`,
   `log-prompts-dir`, and `verbose` (`EXTRA_KEYS` in
   `tokencrate/presets.py`). Add another option to that list after
   reading its `llama-server --help` entry. The list is short because
   llama-server also takes options that run tools, proxy MCP servers,
   serve files, or fetch models, and each release adds some. Run
   `presets render` after every edit; it names what it rejects:

   - an unknown key, and an extra option outside the list, a typed
     setting's own spelling included;
   - an invalid combination, for example MTP with two slots or a
     quantized V cache without flash attention;
   - a value the router would cut at a `;` or `#`.

   The container runs llama.cpp in offline mode (`LLAMA_ARG_OFFLINE` in
   `compose.yaml`), which is what keeps a model server from downloading
   files at start; the renderer's list is a review aid for the shipped
   presets, not a sandbox for untrusted ones, and accepting an option
   does not establish that the pinned build supports it.

3. Fetch, render, start, and measure:

   ```bash
   bash bin/tokencrate models fetch <set>
   bash bin/tokencrate presets render
   LLM_DEFAULT_PRESET=<preset> bash bin/tokencrate up
   bash bin/tokencrate smoke --preset <preset>
   bash bin/tokencrate bench --preset <preset>
   ```

Attach the `smoke` and `bench` reports to the change; a shipped preset
also gets a dated record in [Validation](validation.md#records).

## Presets for other cards

The smallest shipped presets are `gpt-oss-20b-small` and
`qwen3.8-27b-q3-small` at 15 GiB, measured in [their
record](validation.md#the-16-gb-presets) but not on a 16 GB card. If
none of the shipped presets fits your card, write one: a preset is a TOML
file, and its `[requires] vram_gib` is what `doctor --preset` compares
with the card; nothing else in TokenCrate is tied to a card size.

1. Copy the closest shipped preset under `config/presets/`. For a 24 GB
   card, copy `qwen3.8-27b-q4.toml` and set `parallel = 1` and
   `ctx_size = 32768`. Below 16 GB the weights decide: a set whose file
   is larger than the card leaves nothing for the cache, so start from
   the download column of the [set table](#included-model-sets), add a
   smaller quantization with `models draft` if none fits, and give it one
   short slot.
2. Set `[requires] vram_gib` to the card's size for the first run, and
   name the memory class in the description, as the shipped ones do.
3. Render, start, and measure. A new model set needs its files first;
   the 24 GB path reuses the downloaded Q4 set and skips the `fetch`:

   ```bash
   bash bin/tokencrate presets render
   bash bin/tokencrate doctor --preset <preset>
   bash bin/tokencrate models fetch <set>
   LLM_DEFAULT_PRESET=<preset> bash bin/tokencrate up
   bash bin/tokencrate smoke --preset <preset>
   bash bin/tokencrate bench --preset <preset>
   ```

4. Set `vram_gib` to what `nvidia-smi` shows llama-server holding after
   `smoke`, rounded up by the few GiB of headroom the shipped presets keep,
   and attach the reports to the change.

## Hugging Face access and storage

Gated repositories need a read token. Accept the license on Hugging Face,
create a token, and add `HF_TOKEN=hf_...` to the uncommitted `.env`. The
wrapper reads it in-process and removes it from the environment of every
subprocess; it is not placed in command arguments, image layers, or
container environment metadata. The downloader sends the token to
`huggingface.co` only and drops it when the download is redirected to a
CDN host.

Files download into a hidden staging directory beside their destination and
become visible only after the size and checksum match; an interrupted
download resumes on the next run with an HTTP range request, and `fetch`
refuses to start when the bytes still to download exceed the free space. A
file at the same destination with different content is never overwritten.
`models status <set>` verifies files already on disk without network
access. The layout is `LLM_MODELS_DIR/<owner>/<repository>/<source>`,
where `<source>` is the manifest's path inside the repository (a file
name, or a quant directory and a file name for a split set), so a file
downloaded by another tool into that layout is reused when its checksum
matches.
