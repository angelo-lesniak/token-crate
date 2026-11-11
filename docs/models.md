# Models and presets

A **model set** is what you download: one GGUF quantization of one model
(one file, or the parts of a split file), pinned to a Hugging Face commit
with byte sizes and SHA-256 checksums. A **preset** is how llama-server runs
a model set: context size, slots, KV cache types, speculative decoding,
reasoning effort, sampling, and the host memory it needs. One set can serve
several presets. Every preset declares the GPU memory it needs in
`[requires] vram_gib`, and the system memory in `ram_gib` when it keeps
expert weights there (`n_cpu_moe`); `doctor --preset` compares both with
the host. The shipped presets declare 15 to 30 GiB; if none fits your
card, [write your own](#write-a-preset-for-another-card).

## Included model sets

The manifests under `config/model-sets/` hold each set's files and
sources; `bash bin/tokencrate models list` prints the sets and their
descriptions.

| Set | Download | Notes |
| --- | ---: | --- |
| `qwen3.8-27b-ud-q4-k-xl` | 17.6 GB | |
| `qwen3.8-27b-ud-q6-k-xl` | 25.3 GB | quality tier |
| `qwen3.8-27b-ud-q3-k-xl` | 13.1 GB | intended for a 16 GB card, not measured on one |
| `gpt-oss-20b-mxfp4` | 12.1 GB | |
| `qwen3.8-27b-huihui-abliterated-ud-q4-k-xl` | 17.4 GB | [uncensored](#uncensored-presets) |
| `glm-5.3-flash-ud-q2-k-xl` | 108.7 GB | [96 GB RAM tier](#the-96-gb-ram-tier) |
| `glm-5.3-flash-orcarouter-uncensored-q2-k` | 116.9 GB | uncensored; 96 GB RAM tier; [gated](#hugging-face-access-and-storage); [build gate](#build-gate) |
| `qwen3.8-flash-next-ud-q4-k-xl` | 111.3 GB | 96 GB RAM tier |
| `qwen3.8-flash-next-orcarouter-uncensored-q4-k-s` | 111.8 GB | uncensored; 96 GB RAM tier; gated |

`models fetch` prints every license and model card before it writes
files; review them yourself. The repository's MIT license does not
cover weights.

## Included presets

The preset files under `config/presets/` hold every setting; `bash
bin/tokencrate presets list` prints each preset's model set,
`[requires]`, build wait, and description.

| Preset | Context | Slots | `[requires]` | Generation (tokens/s) | Use it for |
| --- | ---: | ---: | ---: | ---: | --- |
| `qwen3.8-27b-q4-mtp` (default) | 64K | 1 | 24 GiB | ~140 | a single agent |
| `qwen3.8-27b-q4` | 64K total, 32K per slot | 2 | 24 GiB | ~80 | the built-in chat UI and an agent on one loaded model |
| `qwen3.8-27b-q4-mtp-long` | 128K | 1 | 28 GiB | ~140 | long agent sessions and clients with large tool schemas |
| `qwen3.8-27b-q6-quality` | 48K | 1 | 30 GiB | ~110 | the larger Q6 quantization |
| `gpt-oss-20b-fast` | 128K total, 64K per slot | 2 | 20 GiB | ~340 | fast chat and a tool-calling fallback |
| `gpt-oss-20b-small` | 32K | 1 | 15 GiB | ~340 | [smaller cards](#write-a-preset-for-another-card) |
| `qwen3.8-27b-q3-small` | 32K | 1 | 15 GiB | ~90 | smaller cards with the 27B; answer quality is not measured |
| `qwen3.8-27b-q4-mtp-f16kv` | 64K | 1 | 25 GiB | ~140 | the default with an unquantized KV cache, for long documents and tool calls |
| `qwen3.8-27b-q4-uncensored-mtp` | 64K | 1 | 24 GiB | ~140 | the default, [uncensored](#uncensored-presets) |
| `qwen3.8-27b-q4-uncensored-mtp-long` | 128K | 1 | 28 GiB | ~140 | the 128K preset, uncensored |
| `glm-5.3-flash-q2` | 128K | 1 | 30 GiB and 96 GiB RAM | ~20 | the [96 GB RAM tier](#the-96-gb-ram-tier) |
| `glm-5.3-flash-q2-uncensored` | 64K | 1 | 30 GiB and 96 GiB RAM | not measured | uncensored, no memory margin; waits behind the [build gate](#build-gate) |
| `qwen3.8-flash-next-q4` | 128K | 1 | 30 GiB and 96 GiB RAM | ~30 | the 96 GB RAM tier |
| `qwen3.8-flash-next-q4-uncensored` | 128K | 1 | 30 GiB and 96 GiB RAM | ~30 | the 96 GB RAM tier, uncensored |

The generation speeds are estimates from a short and a long prompt on
an RTX 5090, rounded to the nearest ten. A declared `[requires]` value
is a ceiling with a few GiB of headroom: llama-server allocates the KV cache when the preset loads,
so a full slot holds no more than an empty one.

The default preset gives a single agent one 64K slot instead of two 32K
slots: with an agent set and `xhigh` [reasoning](#reasoning-effort), the
largest request needs a full 32K slot; a second client waits for the
slot. One preset is loaded at a time: a request that names another
preset waits for the running request, then the router unloads the
loaded model and reads the other one's file from disk, so keep one
preset for a session.

Any OpenAI-compatible client on the host can use the running stack at
`http://127.0.0.1:4207/v1` (port `LLM_PORT`). Every request names a
preset id from `/v1/models` in its `model` field, and the router loads
that preset on first use. A client on the host is outside the
containment of the agent containers ([Privacy and
containment](privacy.md#defaults-and-their-limits)).

## Reasoning effort

Qwen3.8, gpt-oss, and GLM-5.3-Flash think before answering and read
their effort from the request. The effort is an instruction to the
model, not a token budget. Higher effort means longer turns, and the
Qwen template keeps earlier reasoning in the prompt, so a slot fills
sooner. A client that sends no effort gets the preset's default:
`xhigh` for Qwen, the default of the [model
card](https://huggingface.co/Qwen/Qwen3.8-27B), and `medium` for gpt-oss,
whose purpose is speed.

The presets declare these efforts: Qwen3.8 27B and Flash-Next `low`,
`medium`, and `xhigh`, with thinking switchable off; gpt-oss `low`,
`medium`, and `high`; GLM-5.3-Flash `low`, `high`, and `max`. Choose
another effort without reloading the model:

- **In pi and oh-my-pi**, use the thinking level: `/thinking low` in the
  session, `--thinking low` on the command line, or
  `defaultThinkingLevel` in the agent settings. Both agents start at
  `xhigh` and send the level with every request. pi offers only the
  declared levels, plus `off` where thinking can be switched off;
  oh-my-pi sends an undeclared level as the nearest declared effort,
  upward when one exists. On gpt-oss, pi's starting `xhigh` is not a
  declared level; the effort pi then sends is a [known
  gap](validation.md#known-gaps).
- **In any other client**, send `reasoning_effort` at the top level of
  the chat completion body, or `chat_template_kwargs` with
  `reasoning_effort` and, for Qwen, `enable_thinking`.

## Uncensored presets

The uncensored presets appear wherever the other presets do; their
descriptions carry the word "uncensored" and the method.

- `qwen3.8-27b-q4-uncensored-mtp` and
  `qwen3.8-27b-q4-uncensored-mtp-long` run
  [huihui-ai's abliteration](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF)
  of the default's file with the settings of `qwen3.8-27b-q4-mtp` and
  `qwen3.8-27b-q4-mtp-long`. Abliterated builds can loop in their
  reasoning; the `reply terminates` check of `smoke` shows such a loop
  (the reply ends with `length` instead of `stop`), and a 128K slot
  gives it more room before `n_predict` ends it.
- `qwen3.8-flash-next-q4-uncensored` and `glm-5.3-flash-q2-uncensored`
  run orcarouter's abliterations. The GLM files drop the MTP head, so
  that preset does not draft, and its plain 2-bit experts leave no
  memory margin on a 96 GB host: its first run decides whether the 64K
  slot fits, and if it does not, it is expected to swap through the
  memory map rather than crash.

## The 96 GB RAM tier

Qwen3.8-Flash-Next and GLM-5.3-Flash keep most of their expert weights
in system memory (`n_cpu_moe`) and the rest on the card, so their
presets need a host with 96 GB of RAM besides a 32 GB card.

The weights in system memory are memory-mapped, so the host counts them
as page cache, not as used memory. The first Flash-Next request after a
load waits for the page faults of the memory map before the first word,
an estimated 25 to 45 seconds on an RTX 5090 host. The preset comments
([Flash-Next](../config/presets/qwen3.8-flash-next-q4.toml),
[GLM](../config/presets/glm-5.3-flash-q2.toml)) break down the memory
on the card and in system memory, and say what `load-mode` does to each.

The orcarouter GLM set waits behind the [build gate](#build-gate) as
`unreleased`: its files declare the pre-release architecture name
`glm5next`, which no llama.cpp release loads; its preset is untested, a
[known gap](validation.md#known-gaps).

## Build gate

A model set whose architecture the pinned llama.cpp build does not know
declares `[requires] llama_build`: the first build that loads it, as
`pins.env` spells it (`b12200`), or `unreleased`. The gate compares that
build with the number at the end of `LLAMA_CPP_TAG`; an `unreleased` set
waits for every pin. While a set waits, each of its presets:

- is listed as waiting by `presets check` and `presets list` (`waits for
  llama.cpp build b12200 (pinned: b12182)`); `doctor --preset` warns,
  and `pins check` names the waiting set;
- stays out of the router preset file and the agent model lists that
  `up` renders;
- is refused, with the same reason, as `LLM_DEFAULT_PRESET` (by
  `presets check` and `up`), as `--preset` of `smoke`, `agent`, and
  `ui`, and in `--presets` of `bench`.

`models fetch` downloads a waiting set all the same. When a llama.cpp
release loads the model, write its build number into the set and raise
the pin to that build or later ([Upgrade a
pin](configuration.md#upgrade-a-pin)).

## The patched chat template

The template embedded in the Qwen GGUF files raises `System message must
be at the beginning.` for a system or developer message after the first
turn, which some clients send mid-conversation. The Qwen sets, the
Flash-Next and abliterated ones included, therefore use a copy under
`config/chat-templates/` that renders such a message as a normal system
turn and is otherwise identical; the header of [the template
file](../config/chat-templates/qwen3.8-27b-agent.jinja) names the
upstream source and the reasons. `smoke` checks it on the running
server.

## Add a model

1. Print a manifest draft for the GGUF file and save it under
   `config/model-sets/` with a `<set>` name that `models list` does not
   show:

   ```bash
   bash bin/tokencrate models draft hf:<owner>/<repository>:<file>.gguf \
     > config/model-sets/<set>.toml
   ```

   The draft pins the repository's current commit and fills sizes and
   checksums from the Hub. Replace the `TODO` markers, point the license
   `url` at the license file when the repository has one (the draft uses
   the pinned README), set `mtp`, and add `chat_template_file` when the
   model needs the patched template. A model the pinned llama.cpp build
   cannot load also gets `[requires] llama_build`.
   [Manifest keys](#manifest-keys) lists every key.

2. Copy the closest preset under `config/presets/`, point `model_set` at the
   new set, and adjust the context size and `[requires] vram_gib`. The
   preset id is the file name without `.toml`. Presets express
   llama-server settings through typed keys; the `[server.extra]` table
   passes a short list of further options through as `name = value`, and
   another option joins the list by a code change in
   `tokencrate/presets.py`. Run `presets check` after every edit; it
   names what it rejects, such as an unknown key, an option outside the
   list, an invalid combination (MTP with two slots), or a value the
   router would cut at a `;` or `#`.

3. Check, fetch, start, and measure:

   ```bash
   bash bin/tokencrate presets check                    # validates every manifest and preset
   bash bin/tokencrate doctor --preset <preset>         # compares [requires] with the host
   bash bin/tokencrate models fetch <set>               # downloads and verifies the set's files
   LLM_DEFAULT_PRESET=<preset> bash bin/tokencrate up   # starts the stack with the preset loaded
   bash bin/tokencrate smoke --preset <preset>          # checks the running preset, writes a report
   bash bin/tokencrate bench --presets <preset>         # measures speed, writes a report
   ```

Attach the `smoke` and `bench` reports to the change; a shipped preset
also gets its generation estimate in the [preset table](#included-presets),
as [Validation](validation.md#record-a-run) describes.

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
| `[requires] llama_build` | no | `b<N>` or `unreleased`; see [Build gate](#build-gate) |
| `[[license]] name`, `url` | yes, one or more | The license name and an immutable URL: a `blob/<commit>` path on huggingface.co or github.com, or `https://cdn.jsdelivr.net/gh/<owner>/<repository>@<commit>/<path>` |
| `[[file]] role` | yes | `weights` or `split` |
| `[[file]] repository`, `revision`, `source` | yes | The Hugging Face repository (owner and name, neither `.` nor `..`), its full 40-character commit, and the file's path in it; the library keeps the file at `<repository>/<source>` |
| `[[file]] size`, `sha256` | yes | The byte size and the lowercase SHA-256 of the file |

Exactly one file has the role `weights`. A weights file named
`*-00001-of-NNNNN.gguf` needs NNNNN−1 `split` rows with the same stem,
one for each of the parts `00002` to `NNNNN`; a `-00001-of-00001` file
needs none.

## Write a preset for another card

The smallest shipped presets, `gpt-oss-20b-small` and
`qwen3.8-27b-q3-small` at 15 GiB, are measured on a 32 GB card, not on a
16 GB one ([known gaps](validation.md#known-gaps)). `[requires]
vram_gib` is what `doctor --preset` compares with the card; nothing else
in TokenCrate is tied to a card size.

1. Copy the closest shipped preset under `config/presets/` and shrink
   the slot count (`parallel`) and the context (`ctx_size`) first, since
   the weights are fixed by the model set. If the set's download is
   larger than the card, nothing is left for the cache: add a smaller
   quantization with `models draft`.
2. Set `[requires] vram_gib` to the card's size for the first run, and
   name the memory class in the description, as the shipped ones do.
3. Check, start, and measure with the commands of [Add a
   model](#add-a-model), step 3.
4. Set `vram_gib` to what `nvidia-smi` shows llama-server holding after
   `smoke`, plus the few GiB of headroom the shipped presets keep, and
   attach the reports to the change.

## Hugging Face access and storage

Gated repositories need a read token. Accept the license on Hugging Face,
create a token, and add `HF_TOKEN=hf_...` to the uncommitted `.env`. The
wrapper keeps it out of every subprocess and sends it to huggingface.co
only ([What leaves the machine](privacy.md#what-leaves-the-machine)).

Files download into a hidden staging directory beside their destination
and become visible only after the size and checksum match. An
interrupted download resumes on the next run. `fetch` refuses to start
when the bytes still to download exceed the free space, naming both
figures. A file at the same destination with different content is never
overwritten, and a file another tool downloaded into the library layout
([Storage layout](configuration.md#storage-layout)) is reused when its
checksum matches. [`models`](cli.md#models) says how `models status`
verifies files without network access.
