# Third-party software

TokenCrate's own source code is MIT licensed; the vendored chart library
below carries its own license. Built images are aggregates that contain
upstream software under its own licenses:

- the runtime image adds a layer to the official llama.cpp server image,
  which contains llama.cpp (MIT) on an NVIDIA CUDA base image subject to the
  NVIDIA CUDA end-user license;
- the agent images contain Node.js or Bun, Debian packages, pi
  (`@earendil-works/pi-coding-agent`, MIT) or oh-my-pi
  (`@oh-my-pi/pi-coding-agent`, MIT with vendored components under their own
  licenses);
- the pi image adds what its selected agent sets pin, listed below; a
  private set under `local/agent-sets` is the user's own.

| Set | Software | License |
| --- | --- | --- |
| `coding` | pi-lens | MIT, with bundled tree-sitter grammars and ast-grep under their own licenses |
| `coding` | `@narumitw/pi-plan-mode`, `@juicesharp/rpiv-advisor`, and the dependencies the lockfile names | MIT |
| `debug` | The PieX `extensions/dap` source at a pinned commit, installed as `piex-dap` | MIT |
| `browser` | `@narumitw/pi-chrome-devtools` and the dependencies the lockfile names | MIT |
| `browser` | Debian's Chromium | BSD-3-Clause with bundled components under their own licenses |
| `dotnet` | .NET SDK | MIT, with the .NET library license for its runtime packs |
| `dotnet` | csharp-ls, netcoredbg | MIT |
| `dotnet` | NuGet packages of the warmed cache | Their own licenses |
| `web` | TypeScript, typescript-language-server | Apache-2.0 |
| `web` | Vue language tools | MIT |
| `odin` | Odin compiler and its vendor libraries | zlib and the vendor libraries' own licenses |
| `odin` | OLS | MIT |
| `odin` | Debian's LLVM, SDL2, Vulkan, and shaderc packages | Their own licenses |
| `pi-web` | pi-web (`@agegr/pi-web`), Next.js, React, xterm.js, node-pty, and the dependencies the lockfile names | MIT (dependencies also MPL-2.0 for web-push and Next.js's bundled `@vercel/og`, Apache-2.0 for sharp with libvips under LGPL-3.0-or-later, CC-BY-4.0, PSF-2.0, BlueOak-1.0.0, BSD-3-Clause, 0BSD) |
| `guard` | `pi-warden`, `pi-typesafe`, `@typesafe-ai/sdk`, and the dependencies the lockfile names | MIT |
| `guard` | A loop guard with detectors reimplemented from oh-my-pi, OpenHands, `@wkqco33/pi-loop-guard`, pi-warden, and Qwen Code | MIT; Apache-2.0 for the parts from Qwen Code |
| `judge` | An extension whose questions and output masking follow pi-warden and Gemini CLI | MIT; Apache-2.0 for the parts from Gemini CLI |
| `todo` | `@juicesharp/rpiv-todo` and the dependencies the lockfile names | MIT |
| `search` | `pi-web-access` and the dependencies the lockfile names | MIT (dependencies MIT, ISC, BSD-2-Clause, BSD-3-Clause, Apache-2.0) |
| `memory` | `pi-memory` | MIT |
| `hindsight` | `@vectorize-io/hindsight-coding-agents`, a bundle with its dependencies inlined | MIT (the Hindsight repository's; the package names none), bundled dependencies under their own licenses |
| `roles` | `pi-subagents` and the dependencies the lockfile names | MIT (dependencies MIT, ISC, Apache-2.0) |

Anyone redistributing an image is responsible for preserving required notices
and reviewing the licenses introduced by the pinned packages.

Model-set manifests refer to model weights under their upstream licenses. Those
weights are downloaded to user-controlled storage and are not distributed
under TokenCrate's MIT license. Users must review and accept each model
license; `models fetch` prints them before writing files.

The repository vendors uPlot 1.6.32 under `tokencrate/stats/pages/vendor/`
(`uPlot.iife.js` and `uPlot.min.css`; MIT; <https://github.com/leeoniya/uPlot>):
byte-for-byte the files of the published npm artifact
`https://registry.npmjs.org/uplot/-/uplot-1.6.32.tgz`, hash-pinned by
`tests/test_statspage.py`. The `stats` command inlines both files into every
saved or served stats page, so sharing a page redistributes uPlot; its
license header opens `uPlot.iife.js` and therefore every page's copy.

The [dashboard](docs/configuration.md#dashboard) profile runs two
upstream images as pinned in `pins.env`, without modifying or
redistributing them: VictoriaMetrics (`victoriametrics/victoria-metrics`,
Apache-2.0; <https://github.com/VictoriaMetrics/VictoriaMetrics>) and
Grafana (`grafana/grafana`, AGPL-3.0; <https://github.com/grafana/grafana>),
and with the GPU a third, NVIDIA's DCGM exporter
(`nvcr.io/nvidia/k8s/dcgm-exporter`, Apache-2.0;
<https://github.com/NVIDIA/dcgm-exporter>, whose image also carries
DCGM under NVIDIA's own license). The provisioned dashboard and
datasource files under `config/dashboard/` are TokenCrate's own.

The memory server (`LLM_MEMORY_SERVER=true`) runs Hindsight's API image
as pinned in `pins.env`, without modifying or redistributing it
(`ghcr.io/vectorize-io/hindsight-api`, MIT;
<https://github.com/vectorize-io/hindsight>). The image carries the
embedding model BAAI/bge-small-en-v1.5 (MIT), the reranker
hindsight-ai/hs-rerank-1 (MIT), and an embedded PostgreSQL (pg0, MIT)
with PostgreSQL and pgvector (PostgreSQL License).

The shipped chat template under `config/chat-templates/` is a modified copy of
the template embedded in the Qwen3.8 GGUF files (Apache License 2.0).

Skill sets refer to third-party Agent Skills under their own licenses; the
license identifier is recorded next to each pin.
