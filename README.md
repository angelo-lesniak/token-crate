# TokenCrate

TokenCrate runs llama.cpp and the pi or oh-my-pi coding agent in Docker
or Podman containers on x86-64 Linux with one NVIDIA GPU. It pins
software versions and model files, verifies model downloads by checksum,
and gives agents no route to the internet by default.

## Start here

The example below downloads a 17.6 GB model set and the llama.cpp server
image: allow about 25 GB of disk and tens of minutes. The default preset
needs 24 GiB of GPU memory; a 16 GB card option follows.

Install these host tools:

- Bash, Git, and Python 3.11 or newer (the standard library is enough);
- [Docker Engine](https://docs.docker.com/engine/install/) 28 or newer
  with [Compose v2](https://docs.docker.com/compose/install/), or
  [rootless Podman](https://github.com/podman-container-tools/podman/blob/main/docs/tutorials/rootless_tutorial.md)
  6 or newer with `crun` and
  [podman-compose](https://github.com/containers/podman-compose), which
  `podman compose` must resolve to;
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  with a driver whose major version is at least `CUDA_MIN_DRIVER_MAJOR`
  in [`pins.env`](pins.env); `doctor` checks it.

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

`init` creates the storage directories and the settings file `.env`; to
change a setting, copy its line from `.env.example` into `.env`. Set
`LLM_MODELS_DIR` to store models on another disk. If both engines are
installed, TokenCrate uses Podman; `CONTAINER_ENGINE=docker` selects
Docker. On a 16 GB card, set `LLM_DEFAULT_PRESET=qwen3.8-27b-q3-small`
and pass `--model-sets qwen3.8-27b-ud-q3-k-xl` below; that preset is
untested on a 16 GB card ([Known gaps](docs/validation.md#known-gaps)).

Check the host, then download and start the model and test its API.
`up --model-sets` prints the model's license and starts the download
without asking; stop it with Ctrl+C if you do not accept the license:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate up --model-sets qwen3.8-27b-ud-q4-k-xl
bash bin/tokencrate smoke
```

`doctor` must finish without a `[fail]` line; read any warnings. `up`
prints the address once the default preset is loaded. Every row of the
`smoke` table must say `pass`.

Open <http://127.0.0.1:4207/> for the built-in chat UI. If the chat UI
is all you need, stop here; the rest of this section adds a coding agent.

The commands below fetch the two default skill sets from GitHub, check
that the agent container has no route to the internet, and open pi in a
project. The first `smoke --agent` or `agent` command builds the agent
image, which downloads a few hundred megabytes and takes several
minutes. The agent can read and change every file in the project
directory. Replace `~/src/my-project` with an existing project
directory below your home directory or a directory listed in
`LLM_PROJECT_ROOTS`:

```bash
bash bin/tokencrate skills fetch pocock-core skill-crate
bash bin/tokencrate smoke --agent pi
bash bin/tokencrate agent pi --dir ~/src/my-project
```

The agent check must report no failures. Press Ctrl+C to leave pi; the
session is kept per project. [Coding agents and
skills](docs/agents.md#what-the-container-can-and-cannot-do) states what
else the container can reach and which files it writes can run on your
host later.

`bash bin/tokencrate down` removes the containers and networks and keeps
models, sessions, and images. If a command fails, start with
[Troubleshooting](docs/troubleshooting.md).

## Choose what to do next

| Goal | Start here |
| --- | --- |
| Look up any command or flag | [CLI reference](docs/cli.md) |
| Fix a failing command or check | [Troubleshooting](docs/troubleshooting.md) |
| Measure tokens per second, or token usage across agent sessions | [`bench`](docs/cli.md#bench), [`stats`](docs/cli.md#stats) |
| Watch the model server over weeks in Grafana | [Dashboard](docs/configuration.md#dashboard) |
| Pick another preset, write one for another card, or add a GGUF model | [Models and presets](docs/models.md) |
| Use oh-my-pi, a cloud model, a browser UI, private skills, or network access | [Coding agents and skills](docs/agents.md) |
| Choose or write a pi toolchain | [Agent sets](docs/agent-sets.md) |
| Understand what leaves the machine | [Privacy and containment](docs/privacy.md) |
| Change a setting, a storage path, or a port, or update pins | [Configuration](docs/configuration.md) |
| See what is validated, or validate a change | [Validation](docs/validation.md) |
| Contribute a change | [Contributing](CONTRIBUTING.md) |
| Report a security problem | [Security policy](SECURITY.md) |

## Scope and support

TokenCrate does not run in native Windows containers or on macOS, AMD
GPUs, or ARM64. It uses one inference server, llama.cpp's
`llama-server`, and runs agents only in containers. If you want a
desktop application with a model catalogue, or a server for several
users, other projects are simpler. [Validation](docs/validation.md#status)
records the environments checked.

## Privacy

The privacy defaults do not make an unreviewed skill or model safe.
Before mounting a sensitive project, read [Privacy and
containment](docs/privacy.md) for what leaves the machine and the limits
of each default.

## License

TokenCrate is available under the [MIT License](LICENSE). Upstream
software in the images, model weights, and skills have their own
licenses; review [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before
redistributing images.

TokenCrate is an unofficial community project. It is not affiliated with the
llama.cpp, pi, Qwen, OpenAI, NVIDIA, Docker, or Podman projects.
