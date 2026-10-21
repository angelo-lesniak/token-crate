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
| `qwen3.8-27b-q4-mtp-long` | Qwen3.8 Q4 | 128K | 1 | MTP, 3 draft tokens | 28 GiB | 138 to 154 tokens/s | oh-my-pi, whose [first request](agents.md) is large, and long agent sessions at the default's speed |
| `qwen3.8-27b-q6-quality` | Qwen3.8 Q6 | 48K | 1 | MTP, 2 draft tokens | 30 GiB | 100 to 113 tokens/s | the quality tier |
| `gpt-oss-20b-fast` | gpt-oss-20b | 128K total, 64K per slot | 2 | none | 20 GiB | 246 to 264 tokens/s | fast chat and a tool-calling fallback |
| `gpt-oss-20b-small` | gpt-oss-20b | 32K | 1 | none | 15 GiB | 244 to 260 tokens/s | a 16 GB card |
| `qwen3.8-27b-q3-small` | Qwen3.8 Q3 | 32K | 1 | none | 15 GiB | 89 to 91 tokens/s | a 16 GB card with the 27B; what three bits cost it on agent work is not measured |
| `qwen3.8-27b-q4-mtp-f16kv` | Qwen3.8 Q4 | 64K | 1 | MTP, 3 draft tokens | 25 GiB | 143 to 144 tokens/s | the default's settings with an unquantized KV cache, for long documents and tool calls |
| `qwen3.8-27b-q4-uncensored-mtp` | Qwen3.8 Q4 abliterated | 64K | 1 | MTP, 3 draft tokens | 24 GiB | 143 to 151 tokens/s | uncensored (abliterated), refusals removed at the weight level |
| `qwen3.8-27b-q4-uncensored-mtp-long` | Qwen3.8 Q4 abliterated | 128K | 1 | MTP, 3 draft tokens | 28 GiB | 142 to 147 tokens/s | uncensored (abliterated) with the 128K slot |
| `glm-5.3-flash-q2` | GLM-5.3-Flash Q2 | 128K | 1 | MTP, 2 draft tokens | 30 GiB and 96 GiB RAM | not loadable | the [96 GB RAM tier](#the-96-gb-ram-tier) |
| `glm-5.3-flash-q2-uncensored` | GLM-5.3-Flash Q2 uncensored | 64K | 1 | none (its files drop the MTP head) | 30 GiB and 96 GiB RAM | not loadable | uncensored (orcarouter), 2-bit, no memory margin |
| `qwen3.8-flash-next-q4` | Flash-Next Q4 | 128K | 1 | none | 30 GiB and 96 GiB RAM | 31 to 32 tokens/s | the [96 GB RAM tier](#the-96-gb-ram-tier) that the pinned build loads: 125B parameters, 6B active, experts in system memory |
| `qwen3.8-flash-next-q4-uncensored` | Flash-Next Q4 uncensored | 128K | 1 | none | 30 GiB and 96 GiB RAM | 36 to 37 tokens/s | uncensored (orcarouter), the same settings with two more expert layers on the card |

The `[requires]` values are the preset files' own, which `bash
bin/tokencrate presets list` prints. The generation speeds are for a
short and a long prompt on an RTX 5090 with llama.cpp build b11028,
except the `qwen3.8-flash-next-q4-uncensored` row, measured on b10920;
[Validation](validation.md#status) says when the baseline last passed.
The presets measured on the 32 GB card held 3 to 7 GiB less GPU memory
than they declare; the 16 GB pair held 1.5 to 2.3 GiB less. A full slot
holds no more than an empty one, because llama-server allocates the KV
cache when the preset loads (measured with 119,009 tokens in a 128K
slot), and MTP drafting adds about 1.5 GiB to a 128K slot. The two GLM
presets have no GPU record.

The default preset gives a single agent one 64K slot instead of two 32K
slots. An agent's first request is 8,000 to 19,000 tokens ([Coding
agents and skills](agents.md) has the figures per agent), and `xhigh`
reasoning grows the prompt quickly ([reasoning
effort](#reasoning-effort)). Two requests issued together take twice as
long as one, because the second waits for the slot. One preset is loaded
at a time. A request that names another preset waits for the running
request; then the router unloads the loaded model and reads the other
one's full file from disk. Keep one preset for a session.

Any OpenAI-compatible client on the host can use the running stack at
`http://127.0.0.1:4207/v1` (port `LLM_PORT`) with a model name listed by
`http://127.0.0.1:4207/v1/models` (the rendered preset ids). Every
request must name the preset in its `model` field: the router loads that
preset on first use. A client that runs on the host is outside the
containment of the agent containers ([Privacy and
containment](privacy.md#defaults-and-their-limits)).

## Reasoning effort

Qwen3.8 and gpt-oss think before answering and read their effort from the
request. The effort is an instruction to the model, not a token budget: the
Qwen template adds a system line that asks for careful or brief thinking,
and the model decides how long it thinks: on a task that needs
reasoning, the 27B generated 258, 503, 573, and 714 tokens per turn at
`low`, `medium`, `high`, and `xhigh`, and on a one-line answer the level
made no difference. The Qwen presets default to
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
  lists map the agents' levels onto the efforts a preset declares. pi's
  map lists only the levels the preset declares and hides the others;
  oh-my-pi's map sends a level the preset lacks as the nearest effort
  the template accepts, upward when one exists.

  | Presets | Efforts declared | pi offers |
  | --- | --- | --- |
  | Qwen3.8 27B and Flash-Next | `low`, `medium`, `xhigh`; thinking can be switched off | `off`, `low`, `medium`, `xhigh` |
  | gpt-oss | `low`, `medium`, `high` (the harmony template cannot switch thinking off) | `low`, `medium`, `high` |
  | GLM-5.3-Flash | `low`, `high`, `max` (no thinking switch) | `low`, `high`, `max` |

  On gpt-oss, pi's seeded `xhigh` is a hidden level. The GLM row and the
  effort pi sends on gpt-oss under its hidden `xhigh` are [known
  gaps](validation.md#known-gaps).
- **In any other client**, send the effort with the request:
  `reasoning_effort` at the top level of the chat completion body (`low`,
  `medium`, or `xhigh`; for gpt-oss `low`, `medium`, or `high`), or
  `chat_template_kwargs` with `reasoning_effort` and, for Qwen,
  `enable_thinking`. The agents send the second form. A request without
  either uses the preset's default.

## Uncensored presets

The uncensored presets appear wherever the other presets do; their
descriptions carry the word "uncensored" and the method.

- `qwen3.8-27b-q4-uncensored-mtp` runs
  [huihui-ai's abliteration](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF)
  of the default preset's file with the default preset's settings;
  `qwen3.8-27b-q4-uncensored-mtp-long` is the same file with the settings
  of `qwen3.8-27b-q4-mtp-long`. Abliterated builds loop in their
  reasoning in a share of runs. The `reply terminates` check of `smoke`
  shows such a loop (the reply ends with `length` instead of `stop`),
  and a 128K slot gives it more room before `n_predict` ends it. In the
  recorded runs (six long completions at `xhigh` and a six-turn agent
  session) the abliterated 27B ended its replies as the default preset
  did.
- `qwen3.8-flash-next-q4-uncensored` runs orcarouter's abliteration of
  Qwen3.8-Flash-Next with the settings of `qwen3.8-flash-next-q4` and two
  more expert layers on the card, which its smaller file leaves room for.
- `glm-5.3-flash-q2-uncensored` runs orcarouter's abliteration of
  GLM-5.3-Flash. Its files drop the MTP head, so the preset does not
  draft. Its only quant is a plain 2-bit Q2_K whose experts leave no
  memory margin on a 96 GB host: the preset uses a 64K slot, and its
  first run decides whether it fits. If it does not, it is expected to
  swap through the memory map rather than crash.

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

Flash-Next is the tier's loadable model. The first request after a load
is slow: the first completion takes 23 to 38 seconds (the page faults
of the memory map), and a pi session's first request took 43 seconds
before the first word, because the model's prompt processing is a
quarter of the 27B's. The weights in system memory are memory-mapped,
so the host counts them as page cache, not as used memory: a system
monitor shows a few GiB in use while `free` shows 86 GiB of cache. The
preset comments say what else was tried and how to try `load-mode`.

No llama.cpp release carries GLM-5.3-Flash's architecture (`glm5next`),
so its model sets declare `[requires] llama_build = "unreleased"` and
`up`, `presets list`, and `doctor` mark both presets as waiting
([Adding a model](#adding-a-model) describes the gate). The model ships
because it is expected to beat the 27B on knowledge; [the settled
decision](../CONTRIBUTING.md#settled-decisions) gives the scores behind
that expectation. The presets are a [known
gap](validation.md#known-gaps). The GLM presets take their settings from
[pull request 27754](https://github.com/ggml-org/llama.cpp/pull/27754),
with a fallback ladder in the preset comments for the first run.

## KV cache and context checkpoints

The Qwen presets keep the KV cache in `q8_0`. `qwen3.8-27b-q4-mtp-f16kv`
keeps it unquantized, which cost about 2 GiB more and 7 percent of
generation speed after a 6K-token prompt on the RTX 5090; the preset
comment cites the KL benchmark behind the choice. A `bf16` cache held as
much as `f16` and was no faster on the pinned build, so no preset uses
it. The Qwen presets use
context checkpoints (8, or 16 for the 128K presets), which is how
llama-server reuses earlier prompt work on a hybrid-attention model.

## The patched chat template

The Qwen sets, the Flash-Next ones included, ship with a patched chat
template: the template embedded in the GGUF raises `System message must
be at the beginning.` for any system or developer message after the first
turn, which some clients send mid-conversation. The copy under
`config/chat-templates/` renders such a message as a normal system turn
and is otherwise identical (one block differs). `smoke` proves it on the
running server; the header of
[the template file](../config/chat-templates/qwen3.8-27b-agent.jinja)
names the upstream source and the discussions behind the change.
huihui-ai's abliterated 27B embeds the same template as Unsloth's file
(the same SHA-256), so the patch applies to it; orcarouter's Flash-Next
file embeds a different one, which the patched copy replaces.

## Adding a model

1. Print a manifest draft for the GGUF file and save it under
   `config/model-sets/`:

   ```bash
   bash bin/tokencrate models draft hf:<owner>/<repository>:<file>.gguf \
     > config/model-sets/<set>.toml
   ```

   Choose a `<set>` name that `models list` does not show.

   The draft pins the repository's current commit and fills sizes and
   checksums from the Hub. Replace the `TODO` markers (the description
   and the license name); the draft fills the license `url` with the
   pinned README, so point it at the license file when the repository
   has one. Set `mtp` (true when the GGUF contains multi-token-prediction
   heads), and add `chat_template_file` when the model needs the patched
   template. The parts of a split file are listed as `split` rows.
   [Manifest keys](#manifest-keys) lists every key and the rules
   `presets check` enforces.

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
   leading dashes: `override-kv`, `load-mode`, `log-prompts-dir`, and
   `verbose` (`EXTRA_KEYS` in `tokencrate/presets.py`). Another option
   joins the list by a code change, after reading its `llama-server
   --help` entry. Run `presets check` after every edit; it names what it
   rejects:

   - an unknown key, and an extra option outside the list, a typed
     setting's own spelling included;
   - an invalid combination, for example MTP with two slots or a
     quantized V cache without flash attention;
   - a value the router would cut at a `;` or `#`.

3. Fetch, render, start, and measure:

   ```bash
   bash bin/tokencrate models fetch <set>
   bash bin/tokencrate presets check
   LLM_DEFAULT_PRESET=<preset> bash bin/tokencrate up
   bash bin/tokencrate smoke --preset <preset>
   bash bin/tokencrate bench --presets <preset>
   ```

Attach the `smoke` and `bench` reports to the change; a shipped preset
also gets its measured columns in the [preset table](#included-presets),
as [Validation](validation.md#recording-a-run) describes.

### Manifest keys

A model set is `config/model-sets/<set>.toml`; `presets check` refuses
any key not listed here.

| Key | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `description` | yes | One line; `models list` prints it |
| `model_card` | yes | The README of the Hugging Face repository at a commit: `https://huggingface.co/<owner>/<repository>/blob/<commit>/README.md` |
| `upstream_model` | no | The `owner/repository` the quantization or abliteration derives from |
| `mtp` | no | `true` when the GGUF has multi-token-prediction heads (default `false`) |
| `chat_template_file` | no | A `<name>.jinja` under `config/chat-templates/` that replaces the template embedded in the GGUF |
| `[requires] llama_build` | no | The first llama.cpp build that loads the set, as `pins.env` spells it (`b11100`), or `unreleased` |
| `[[license]] name`, `url` | yes, one or more | The license name and an immutable URL: a `blob/<commit>` path on huggingface.co or github.com, or `https://cdn.jsdelivr.net/gh/<owner>/<repository>@<commit>/<path>` |
| `[[file]] role` | yes | `weights` or `split` |
| `[[file]] repository`, `revision`, `source` | yes | The Hugging Face repository, its full 40-character commit, and the file's path in it; the library keeps the file at `<repository>/<source>` |
| `[[file]] size`, `sha256` | yes | The byte size and the lowercase SHA-256 of the file |

Exactly one file has the role `weights`. A weights file named
`*-00001-of-NNNNN.gguf` needs NNNNN−1 `split` rows with the same stem,
one for each of the parts `00002` to `NNNNN`; a `-00001-of-00001` file
needs none.

## Presets for other cards

The smallest shipped presets are `gpt-oss-20b-small` and
`qwen3.8-27b-q3-small` at 15 GiB, measured on a 32 GB card, not on a
16 GB one ([known gaps](validation.md#known-gaps)). If none of the
shipped presets fits
your card, write one. A preset is a TOML file, and its `[requires]
vram_gib` is what `doctor --preset` compares with the card; nothing else
in TokenCrate is tied to a card size.

1. Copy the closest shipped preset under `config/presets/` and shrink
   what the card cannot hold: the slot count (`parallel`) and the context
   (`ctx_size`) first, since the weights are fixed by the model set. If
   the set's file is larger than the card, nothing is left for the cache:
   start from the download column of the [set table](#included-model-sets)
   and add a smaller quantization with `models draft`.
2. Set `[requires] vram_gib` to the card's size for the first run, and
   name the memory class in the description, as the shipped ones do.
3. Render, start, and measure (a new model set needs its files first):

   ```bash
   bash bin/tokencrate presets check
   bash bin/tokencrate doctor --preset <preset>
   bash bin/tokencrate models fetch <set>
   LLM_DEFAULT_PRESET=<preset> bash bin/tokencrate up
   bash bin/tokencrate smoke --preset <preset>
   bash bin/tokencrate bench --presets <preset>
   ```

4. Set `vram_gib` to what `nvidia-smi` shows llama-server holding after
   `smoke`, rounded up by the few GiB of headroom the shipped presets keep,
   and attach the reports to the change.

## Hugging Face access and storage

Gated repositories need a read token. Accept the license on Hugging Face,
create a token, and add `HF_TOKEN=hf_...` to the uncommitted `.env`. The
wrapper keeps it out of every subprocess and sends it to huggingface.co
only ([What leaves the machine](privacy.md#what-leaves-the-machine)).

Files download into a hidden staging directory beside their destination and
become visible only after the size and checksum match. An interrupted
download resumes on the next run with an HTTP range request. `fetch`
refuses to start when the bytes still to download exceed the free space,
naming both figures; make room or fetch fewer sets. A
file at the same destination with different content is never overwritten,
and a file another tool downloaded into the library layout ([Storage
layout](configuration.md#storage-layout)) is reused when its checksum
matches. `models status <set>` verifies files already on disk without
network access; [`models`](cli.md#models) says when a file is re-read.
