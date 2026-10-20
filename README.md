# TokenCrate

Local language models and coding agents for Docker and Podman.

TokenCrate runs llama.cpp and coding agents in containers on your computer.
It pins the llama.cpp build, agent versions, and model files, and verifies
model downloads by checksum. Containers do not update their software at
startup.

TokenCrate is built for a single NVIDIA graphics card. A preset is a
model with its llama.cpp settings and the GPU memory it needs. The shipped
presets declare 15 to 30 GiB;
[Presets for other cards](docs/models.md#presets-for-other-cards) covers
smaller cards. See [Scope and support](#scope-and-support).

Use it when you want to:

- run a [preset](docs/models.md#included-presets) that fits your card, for
  example Qwen3.8-27B at 4-bit quantization with a 64K context and
  multi-token prediction;
- run the pi or oh-my-pi coding agent on a project directory, in a
  terminal or in a browser (PI WEB, Paseo), with pinned skills and, by
  default, no internet access;
- add coding extensions, a debugger, a browser, or C#, Node/Vue, and Odin
  toolchains to pi by choosing [agent sets](docs/agent-sets.md), or write
  your own set;
- switch reasoning effort per request without reloading the model.

## Start here

The example below downloads the Qwen3.8-27B Q4 model set and the
llama.cpp server image. Allow tens of minutes, mostly for the model
download, and about 25 GB of disk.

Install these host tools:

- Bash, Git, and Python 3.11 or newer (the standard library is enough);
- [Docker Engine](https://docs.docker.com/engine/install/) 28 or newer
  with [Compose v2](https://docs.docker.com/compose/install/), or
  [rootless Podman](https://github.com/podman-container-tools/podman/blob/main/docs/tutorials/rootless_tutorial.md)
  6 or newer with `crun` and
  [podman-compose](https://github.com/containers/podman-compose), which
  `podman compose` must resolve to;
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

`init` creates the storage directories and an empty settings file,
`.env`, readable by your user only. `.env.example` lists every setting
with its default. Set `LLM_MODELS_DIR` to store models on another disk.
If both Docker and Podman are installed, TokenCrate uses Podman;
`CONTAINER_ENGINE=docker` in `.env` selects Docker.

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
commands below fetch the two default skill sets from GitHub, check that
the agent container has no route to the internet, and open pi in a
project. `agent` refuses to start until the skill sets are fetched. The
first `smoke --agent` or `agent` command builds the agent image, which
downloads a few hundred megabytes of packages and takes several minutes.
Replace `~/src/my-project` with an existing project directory; it must
lie below your home directory or a directory listed in
`LLM_PROJECT_ROOTS`:

```bash
bash bin/tokencrate skills fetch pocock-core skill-crate
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate agent pi --dir ~/src/my-project
```

The agent check must report no failures: the container reaches the
model and nothing else. pi starts with the default preset and the
skills loaded. The project is mounted read-write at its host path;
[`agent`](docs/cli.md#agent) has all path rules.
[Coding agents and skills](docs/agents.md#what-the-container-can-and-cannot-do)
says what the container can read, write, and reach. Press Ctrl+C to
leave; sessions persist per project.

`down` stops and removes the containers and networks. If a command fails,
start with [Troubleshooting](docs/troubleshooting.md).

## Choose what to do next

| Goal | Start here |
| --- | --- |
| Look up any command or flag | [CLI reference](docs/cli.md) |
| Fix a failing command or check | [Troubleshooting](docs/troubleshooting.md) |
| Measure tokens per second per preset | [`bench`](docs/cli.md#bench) |
| See token usage and context sizes across past agent sessions | [`stats`](docs/cli.md#stats) |
| Watch the model server over weeks in Grafana | [Dashboard](docs/configuration.md#dashboard) |
| Run the built-in chat UI and an agent on one model, or pick another preset | [Models and presets](docs/models.md#included-presets) |
| Add a new GGUF model | [Adding a model](docs/models.md#adding-a-model) |
| Use oh-my-pi, private skills, or give an agent network access | [Coding agents and skills](docs/agents.md) |
| Use a cloud model beside the local one, with API keys from a file you keep | [Cloud providers](docs/agents.md#cloud-providers) |
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

TokenCrate runs on x86-64 Linux with one NVIDIA GPU, with the engines
[Start here](#start-here) lists. [Validation](docs/validation.md#status)
says what is validated on which engine; no run covers Windows 11 with
WSL2 (`doctor` treats it as Linux on x86-64). TokenCrate does not run in
native Windows containers or on macOS, AMD GPUs, or ARM64. It uses one
inference server, llama.cpp's `llama-server`, and runs agents only in
containers. If you want a desktop application with a model catalogue, or
a server for several users, other projects are simpler.

## Privacy

Every published port is on `127.0.0.1`. Agent containers have no route to
the internet unless you enable it for a session or a browser UI. The
telemetry switches of the bundled software are off. These defaults do not
make an unreviewed skill or model safe; read
[Privacy and containment](docs/privacy.md) before mounting a sensitive
project.

## License

TokenCrate is available under the [MIT License](LICENSE). Container images
also include upstream software under its own licenses, and model weights and
skills are downloaded under their own licenses. Review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing images.

TokenCrate is an unofficial community project. It is not affiliated with the
llama.cpp, pi, Qwen, OpenAI, NVIDIA, Docker, or Podman projects.
