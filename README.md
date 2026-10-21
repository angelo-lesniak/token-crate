# TokenCrate

TokenCrate runs llama.cpp and the pi or oh-my-pi coding agent in
containers using Docker or Podman. It pins software
versions and model files, verifies model downloads by checksum, and gives
agents no internet access by default.

It is built for x86-64 Linux with one NVIDIA GPU. Choose a
[preset](docs/models.md#included-presets) for your card, then use the
built-in chat UI or open a coding agent in your project. Agent
[sets](docs/agent-sets.md) add toolchains and browser UIs to pi.

## Start here

The example below downloads the Qwen3.8-27B Q4 model set and the
llama.cpp server image. Allow tens of minutes, mostly for the model
download, and about 25 GB of disk. The default preset requires 24 GiB
of GPU memory; a smaller-card option is given below.

Install these host tools:

- Bash, Git, and Python 3.11 or newer (the standard library is enough);
- [Docker Engine](https://docs.docker.com/engine/install/) 28 or newer
  with [Compose v2](https://docs.docker.com/compose/install/), or
  [rootless Podman](https://github.com/podman-container-tools/podman/blob/main/docs/tutorials/rootless_tutorial.md)
  6 or newer with `crun` and
  [podman-compose](https://github.com/containers/podman-compose), which
  `podman compose` must resolve to;
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  (Arch package: `nvidia-container-toolkit`) with a driver whose major
  version is at least `CUDA_MIN_DRIVER_MAJOR` in [`pins.env`](pins.env)
  `doctor` checks it.

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
`CONTAINER_ENGINE=docker` in `.env` selects Docker. On a 16 GB card,
set `LLM_DEFAULT_PRESET=qwen3.8-27b-q3-small` and pass
`--model-sets qwen3.8-27b-ud-q3-k-xl` below.

Check the host, download the model, start the model server, and test
its API. `up --model-sets` prints the model's license and starts the
download without asking; stop it with Ctrl+C if you do not accept the
license:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
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

The agent check must report no failures. pi starts with the default preset and the
skills loaded. The project is mounted read-write at its host path.
[Coding agents and skills](docs/agents.md#what-the-container-can-and-cannot-do)
explains the container's access to your files. Press Ctrl+C to
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
| Use a cloud model with pi | [Cloud providers](docs/agents.md#cloud-providers) |
| Choose a pi toolchain | [Common selections](docs/agent-sets.md#common-selections) |
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
records the environments checked and the remaining gaps. TokenCrate does not run in
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
