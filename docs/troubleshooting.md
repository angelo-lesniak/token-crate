# Troubleshooting

Start with these two commands:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate logs
```

## `bin/tokencrate` reports that python3 was not found or is too old

The wrapper needs Python 3.11 or newer as `python3` (or `python`) on
`PATH`. Install it with your distribution's package manager; the
[README](../README.md#start-here) lists the other host tools.

## `doctor` reports the Docker Compose plugin under Podman

`podman compose` delegates to the Docker Compose plugin, which drops the
CDI GPU device request, so llama-server would start without the GPU.
Install podman-compose (Arch: `pacman -S podman-compose`; elsewhere
`pipx install podman-compose`) so that `podman compose version` reports
`podman-compose`, then run `doctor` again. For CPU-only checks, set
`LLM_GPU=false` instead.

## CUDA fails to initialize although `nvidia-smi` works

The log shows `no CUDA-capable device is detected` or a driver version
mismatch, or llama-server loads every layer on the CPU. The likely cause
is a CDI specification left stale by a driver upgrade; under Podman,
`doctor` warns when the specification names another driver version.
Regenerate it:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
bash bin/tokencrate doctor
bash bin/tokencrate up
```

## `up` refuses to start because the default preset is not loadable

The model set behind `LLM_DEFAULT_PRESET` has missing files; `up` lists
each preset as `loadable` or `skipped` before it refuses. Plain `up` only
checks that the files exist; `models status` also verifies checksums.
Fetch the set, or set `LLM_DEFAULT_PRESET` to a loadable preset:

```bash
bash bin/tokencrate models status all
bash bin/tokencrate models fetch qwen3.8-27b-ud-q4-k-xl
```

## The running llama configuration differs from the rendered files

A failed `up` can leave generated model lists that differ from the
running router, and agent and UI starts refuse the mismatch. Fix the
earlier startup error, run `bash bin/tokencrate up`, and retry.

## The agent starts but every request fails

The model is still loading, llama-server exited after the agent started,
or the request does not fit the preset's slot, and llama-server answers
`400 ... exceeds the available context size`. oh-my-pi's
[first request](agents.md) fills much of a 32K slot; instead of
`qwen3.8-27b-q4`, start it with `--preset qwen3.8-27b-q4-long`.

```bash
bash bin/tokencrate status
bash bin/tokencrate logs
bash bin/tokencrate smoke --agent pi
```

If the agent check reports `model endpoint is not reachable`, run `down`
and `up`.

## `agent` refuses the project directory

The error names the violated rule; [`agent`](cli.md#agent) lists the
path rules, which apply after symbolic links are resolved. If the path
has a character a Compose mount cannot express, rename or move the
project.

## `agent` refuses to start because of a skill set

The message names the command that resolves it, for example
`skill set pocock-core is incomplete (missing: tdd); run: bash bin/tokencrate skills fetch pocock-core`.
Run that command, or remove the set from `LLM_SKILL_SETS`.

## The port is already in use

`doctor` reports `host port ... is already in use` when another program
holds `LLM_PORT`, and `up` refuses to start. Set another port in `.env`:

```dotenv
LLM_PORT=4307
```

## Paseo stays on "connecting" or shows the previous project

If the UI was restarted for another project, reload the page. If Paseo
stays on "connecting", clear the site's browser data (by default for
`http://127.0.0.1:4250/`) or remove the host in Paseo's host picker, then
reload. Paseo remembers the daemon identity of each address; deleting
`LLM_AGENTS_DIR/pi/paseo-identity/` or changing `LLM_AGENTS_DIR` gives
the daemon a new identity that the browser does not expect.

## oh-my-pi forgets a setting after the container stops

oh-my-pi saves settings to `~/.omp/agent/config.yml` on the tmpfs home,
so the next container starts from `config/agents/omp/config.yml` again.
Pass `--preset <id>` (or set `LLM_DEFAULT_PRESET`) to start on another
model, and change the repository file for a lasting setting. Some keys
cannot be changed in a session at all, because the repository file is
also an overlay above the home copy;
[Agent configuration](agents.md#agent-configuration) lists them.

## The browser UI answers `403` with `refused a request for host`

The forwarder in front of a browser UI (`ui <set>`) refused the request's
`Host`, `Origin`, or `Sec-Fetch-Site` header; the response names the value.
Open the address that `ui <set>` prints directly, not through a page of
another site. A reverse proxy in front of it must pass that `Host` value
on and rewrite or drop the `Origin` and `Sec-Fetch-Site` headers.
[Privacy and containment](privacy.md#defaults-and-their-limits) states
the full rule.

## `up` or an agent session reports a gateway address on an internal network

The message is `the agents network keeps a host gateway address` (or
`ui`). On Docker, a network created without `compose.docker.yaml`, for
example by a direct Compose call, lacks gateway mode `isolated`, and
Compose keeps an existing network's settings. Recreate the networks:

```bash
bash bin/tokencrate down
bash bin/tokencrate up
bash bin/tokencrate smoke --agent pi
```

## `ui` reports that the container stopped or did not answer

Run `bash bin/tokencrate ui logs <set>`. Skill-set and settings errors
from the shared `agent pi` entrypoint appear before the daemon starts;
lines from `paseo` or `pi-web` are daemon errors. A `502` in the first
seconds means the UI is still starting.

## Asking for help

Open a
[bug report](https://github.com/angelo-lesniak/token-crate/issues/new?template=bug-report.yml).
Remove host paths, prompts, project content, and other private
information from logs and reports first. For security problems, follow
[SECURITY.md](../SECURITY.md) instead.
