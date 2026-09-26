# TokenCrate

Local language models and coding agents for Docker and Podman.

TokenCrate runs llama.cpp and coding agents in containers on your computer.
It pins the llama.cpp build, agent versions, and model files, and verifies
model downloads by checksum. Containers do not update their software at
startup.

TokenCrate is built for a single NVIDIA graphics card. A preset is a
model with its llama.cpp settings and states the GPU memory it needs;
see [Scope and support](#scope-and-support).

Use it when you want to:

- run a [preset](docs/models.md#included-presets) that fits your card, for
  example Qwen3.8-27B at 4-bit quantization with a 128K context and
  multi-token prediction;
- run the pi or oh-my-pi coding agent on a project directory, with pinned
  skills and, by default, no internet access;
- add coding extensions, a debugger, a browser, or C#, Node/Vue, and Odin
  toolchains to pi by choosing [agent sets](docs/agent-sets.md), or write
  your own set;
- use pi in a browser with PI WEB or Paseo;
- switch reasoning effort per request without reloading the model;
- use a [cloud model](docs/agents.md#cloud-providers) beside the local one
  in a session or browser UI started with `--cloud`, with API keys from a
  file you keep.

## Start here

The example below downloads the Qwen3.8-27B Q4 model set and
the llama.cpp server image. The first `agent` or `smoke --agent` command
builds the agent image, which downloads a few hundred megabytes of
packages and takes several minutes. Allow tens of minutes, mostly for the
model download, and about 25 GB of disk.

Install these host tools:

- Bash, Git, and Python 3.11 or newer (the standard library is enough);
- [Docker Engine](https://docs.docker.com/engine/install/) 28 or newer
  with [Compose v2](https://docs.docker.com/compose/install/), or
  [rootless Podman](https://github.com/podman-container-tools/podman/blob/main/docs/tutorials/rootless_tutorial.md)
  6 or newer with `crun` and
  [podman-compose](https://github.com/containers/podman-compose), which
  `podman compose` must resolve to (rootless Podman needs
  `/etc/subuid` and `/etc/subgid` entries for your user);
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  (Arch package: `nvidia-container-toolkit`) with a driver of major version
  580 or newer (CUDA 13).

Generate the NVIDIA CDI configuration, and regenerate it after every driver
upgrade:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-ctk cdi list   # must list nvidia.com/gpu=all
```

Clone the repository and create the settings file:

```bash
git clone https://github.com/angelo-lesniak/token-crate.git tokencrate
cd tokencrate
bash bin/tokencrate init
```

`init` creates the storage directories and a settings file, `.env`,
that only you can read and that sets nothing yet. `.env.example` lists every setting with
its default; to change one, copy its line into `.env` and edit it. Set
`LLM_MODELS_DIR` to store models on another disk, and
`GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` for the commits the agent makes.

If both Docker and Podman are installed, TokenCrate uses Podman; set
`CONTAINER_ENGINE=docker` in `.env` to use Docker.

`up --model-set` prints the model's license and starts the download
without asking. Stop it with Ctrl+C if you do not accept the license.

Check the host, download the model, start the model server, and test
its API:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-set qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate smoke
```

`doctor` must finish without a `[fail]` line; read any warnings. `up`
prints the address when the default preset, `qwen3.8-27b-q4-mtp`, is loaded.
Every row of the `smoke` table must say `pass`.

Open <http://127.0.0.1:4207/> for the built-in chat UI. If the chat UI
is all you need, stop here; the rest of this section adds a coding agent.

Skills are instructions an agent loads when a task matches them. The
commands below fetch the two default skill sets from GitHub, which
`agent` needs before it starts, check that the agent container has no
route to the internet, and open pi in a project. Replace
`~/src/my-project` with an existing project directory:

```bash
bash bin/tokencrate skills fetch pocock-core skill-crate
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate agent pi --dir ~/src/my-project
```

The agent check must report no failures: the container reaches the
model and nothing else. pi starts with the default preset and the
skills loaded.

The project is mounted read-write at its host path. Apart from the
project, the agent can change only the directories under
`LLM_AGENTS_DIR` that keep its sessions. The project must lie below your home directory or a
directory listed in `LLM_PROJECT_ROOTS`; see [`agent`](docs/cli.md#agent)
for all path rules.

Press Ctrl+C to leave; sessions persist per project.
[Coding agents and skills](docs/agents.md#what-the-container-can-and-cannot-do)
says what the container can read, write, and reach.

Useful first commands:

```bash
bash bin/tokencrate status     # service state and loaded models
bash bin/tokencrate bench      # tokens per second for the default preset
bash bin/tokencrate logs       # follow llama-server output
bash bin/tokencrate down       # stop and remove the containers and networks
```

If a command fails, start with the
[troubleshooting guide](docs/troubleshooting.md).

## Choose what to do next

| Goal | Start here |
| --- | --- |
| Look up any command or flag | [CLI reference](docs/cli.md) |
| Fix a failing command or check | [Troubleshooting](docs/troubleshooting.md) |
| Measure tokens per second per preset | [`bench`](docs/cli.md#bench) |
| Run the built-in chat UI and an agent on one model, or pick another preset | [Models and presets](docs/models.md#included-presets) |
| Add a new GGUF model | [Adding a model](docs/models.md#adding-a-model) |
| Use oh-my-pi, private skills, or give an agent network access | [Coding agents and skills](docs/agents.md) |
| Set up pi for .NET and Vue in PI WEB, or for Odin with Claude beside the local model | [Common selections](docs/agent-sets.md#common-selections) |
| Add a toolchain, extensions, or packages to the pi image | [Agent sets](docs/agent-sets.md) |
| Use pi from a browser | [Browser UIs](docs/agents.md#browser-uis) |
| Understand what leaves the machine | [Privacy and containment](docs/privacy.md) |
| Change storage paths, ports, or pins | [Configuration](docs/configuration.md) |
| Update pinned versions | [Upgrading](docs/configuration.md#upgrading) |
| See what is validated, or validate a change | [Validation](docs/validation.md) |
| Contribute a change | [Contributing](CONTRIBUTING.md) |
| Report a security problem | [Security policy](SECURITY.md) |

## Scope and support

TokenCrate runs on x86-64 Linux with one NVIDIA GPU and is developed on
Arch Linux. It uses one inference server, llama.cpp's `llama-server`, and
runs agents only in containers. If you want a desktop application with a
model catalog, or a server for several users, other projects are simpler.

If no shipped preset fits your card, write your own with a smaller
context or quantization
([Presets for other cards](docs/models.md#presets-for-other-cards)).

| Platform and engine | Status |
| --- | --- |
| Linux with rootless Podman 6 or newer, `crun`, and podman-compose, or with Docker Engine 28 or newer and Compose v2 | Supported; [what is validated](docs/validation.md#status) |
| Windows 11 with WSL2, running Podman or Docker Engine inside the Linux distribution | Untested; `doctor` treats it as Linux on x86-64 |
| Native Windows containers, macOS, AMD GPUs, ARM64 | Not supported |

## Privacy

The API is published on `127.0.0.1` only; no setting exposes it elsewhere.
Agent containers have no route to the internet unless you enable access
for a session or a browser UI. TokenCrate turns off the telemetry
settings it knows of in the software it bundles.

These defaults reduce accidental exposure. They do not make an unreviewed
skill or model safe. Read [privacy and containment](docs/privacy.md) before
mounting a sensitive project.

## License

TokenCrate is available under the [MIT License](LICENSE). Container images
also include upstream software under its own licenses, and model weights and
skills are downloaded under their own licenses. Review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing images.

TokenCrate is an unofficial community project. It is not affiliated with the
llama.cpp, pi, Qwen, OpenAI, NVIDIA, Docker, or Podman projects.
It is the sibling of [LatentCrate](https://github.com/angelo-lesniak/latent-crate),
which does the same for ComfyUI.
