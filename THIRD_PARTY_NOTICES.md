# Third-party software

TokenCrate's source code is MIT licensed. Built images are aggregates that
contain upstream software under its own licenses:

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
| `coding` | pi-hashline-edit-pro, `@narumitw/pi-plan-mode`, `@juicesharp/rpiv-advisor`, and the dependencies the lockfile names | MIT |
| `debug` | The PieX `extensions/dap` source at a pinned commit, installed as `piex-dap` | MIT |
| `browser` | `@narumitw/pi-chrome-devtools` and the dependencies the lockfile names | MIT |
| `browser` | Debian's Chromium | BSD-3-Clause with bundled components under their own licenses |
| `dotnet` | .NET SDK | MIT, with the .NET library license for its runtime packs |
| `dotnet` | csharp-ls, netcoredbg | MIT |
| `dotnet` | NuGet packages of the warmed cache | Their own licenses |
| `web` | TypeScript, typescript-language-server | Apache-2.0 |
| `web` | Vue language tools, js-debug | MIT |
| `odin` | Odin compiler and its vendor libraries | zlib and the vendor libraries' own licenses |
| `odin` | OLS | MIT |
| `odin` | Debian's LLVM, SDL2, Vulkan, and shaderc packages | Their own licenses |
| `pi-web` | PI WEB (`@jmfederico/pi-web`), node-pty, and the dependencies the lockfile names | MIT |
| `paseo` | Paseo (`@getpaseo/cli` and its `@getpaseo/*` packages) | No license field on npm; the upstream repository's LICENSE is Apache-2.0 with carve-outs |
| `paseo` | Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`) | "SEE LICENSE IN README.md" on npm |
| `paseo` | OpenAI SDK | Apache-2.0 |
| `paseo` | MCP SDK, Express, and the other dependencies the lockfile names | MIT and their own licenses |

TokenCrate runs none of the Paseo dependencies below `@getpaseo/*`; whether
the Claude Agent SDK's terms allow its presence in a locally built, never
redistributed image was not reviewed.

Anyone redistributing an image is responsible for preserving required notices
and reviewing the licenses introduced by the pinned packages.

Model-set manifests refer to model weights under their upstream licenses. Those
weights are downloaded to user-controlled storage and are not distributed
under TokenCrate's MIT license. Users must review and accept each model
license; `models fetch` prints them before writing files.

The shipped chat template under `config/chat-templates/` is a modified copy of
the template embedded in the Qwen3.8 GGUF files (Apache License 2.0).

Skill sets refer to third-party Agent Skills under their own licenses; the
license identifier is recorded next to each pin. `config/skills/` contains
skills authored in this repository (MIT).
