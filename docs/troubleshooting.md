# Troubleshooting

Start with these two commands:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate logs
```

## `bin/tokencrate` reports that python3 was not found or is too old

The wrapper runs `python3` (or `python` when only that name exists) from
`PATH` and needs Python 3.11 or newer. Install it with your distribution's
package manager; the [README](../README.md#start-here) lists the other
host tools.

## `doctor` reports the Docker Compose plugin under Podman

`podman compose` is delegating to a `docker-compose` binary that ignores
the CDI `devices:` request. llama-server would start without the GPU.
Install your distribution's podman-compose package (Arch:
`pacman -S podman-compose`; elsewhere `pipx install podman-compose`) so that
`podman compose version` reports `podman-compose`. Run `doctor` again; the
`[fail]` line disappears.

## CUDA fails to initialize although `nvidia-smi` works

The log shows `no CUDA-capable device is detected`, a driver version
mismatch, or llama-server loads every layer on the CPU. The likely cause
is a stale CDI specification after a driver upgrade; under Podman,
`doctor` compares the driver version in `/etc/cdi/nvidia.yaml` with the
running driver.

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
bash bin/tokencrate doctor
bash bin/tokencrate up
```

## `up` refuses to start because the default preset is not loadable

The model set behind `LLM_DEFAULT_PRESET` has missing files. Plain `up`
checks their presence; `up --model-set`, `models fetch`, and `models status`
also verify checksums. `up` prints one line per preset, `loadable` or
`skipped`, before it refuses.

```bash
bash bin/tokencrate models status all
bash bin/tokencrate models fetch qwen3.8-27b-ud-q4-k-xl
```

Alternatively set `LLM_DEFAULT_PRESET` to a preset whose files exist.

## The running llama configuration differs from the rendered files

A failed `up` can leave generated model lists that differ from the running
router. Agent and UI starts refuse this mismatch. Resolve the earlier
startup error, then run
`bash bin/tokencrate up` before retrying the session.

## The agent starts but every request fails

The model is still loading, llama-server exited after the agent started,
or the request does not fit the preset's slot: llama-server answers
`400 ... exceeds the available context size`. oh-my-pi's
[first request](agents.md) fills much of a 32K slot, so on
`qwen3.8-27b-q4` start it with `--preset qwen3.8-27b-q4-long`.

```bash
bash bin/tokencrate status
bash bin/tokencrate logs
bash bin/tokencrate smoke --agent pi
```

The agent check must report the model endpoint as reachable. If it does not,
recreate the stack with `down` and `up`.

## `agent` refuses the project directory

The error names the violated rule; [`agent`](cli.md#agent) lists all path
rules. Symbolic links are resolved
before the check. For a path with a character a Compose mount cannot
express, rename or move the project.

## `agent` refuses to start because of a skill set

The message names the command that resolves it, for example
`skill set pocock-core is incomplete (missing: tdd); run: bash bin/tokencrate skills fetch pocock-core`.
Run that command, or remove the set from `LLM_SKILL_SETS`.

## The port is already in use

`doctor` reports a failure when another program holds `LLM_PORT`, and
`up` refuses to continue. The check stays silent while TokenCrate's own
llama container holds the port. Set a different host port in `.env`:

```dotenv
LLM_PORT=4307
```

## Paseo stays on "connecting" or shows the previous project

If the UI was restarted for another project, reload the page. If Paseo
stays on "connecting", clear the site's browser data (by default
`http://127.0.0.1:4250/`) or remove the host in Paseo's host picker, then
reload.

Paseo remembers the daemon identity associated with an address. TokenCrate
shares the identity in `data/agents/pi/paseo-identity/` across projects.
Deleting that directory or changing `LLM_AGENTS_DIR` can leave the browser
expecting an identity the daemon no longer uses.

## oh-my-pi forgets a setting after the container stops

oh-my-pi saves its settings to `~/.omp/agent/config.yml` in the agent
home, which is a tmpfs: a model chosen in the session applies, and the
next container starts from `config/agents/omp/config.yml` again. Pass
`--preset <id>` (or set `LLM_DEFAULT_PRESET`) to start on another model,
and change the repository file for a lasting setting. A few keys cannot
be changed in a session at all, because the same file is also an overlay
above the home copy; [Agent configuration](agents.md#agent-configuration)
lists them.

## The browser UI answers `403` with `refused a request for host`

The forwarder in front of a browser UI (`ui <set>`) refused the request's
`Host`, `Origin`, or `Sec-Fetch-Site` header; the response names the value.
Open the address printed by `ui <set>` directly, not through a page of
another site. A reverse proxy in front of
it must pass that `Host` value on and rewrite or drop the `Origin` and
`Sec-Fetch-Site` headers. [Privacy and
containment](privacy.md#defaults-and-their-limits) states the full rule.

## `up` or an agent session reports a gateway address on an internal network

On Docker, an `agents` or `ui` network created without
`compose.docker.yaml` can lack gateway mode `isolated` and retain a gateway
address. A direct Compose call can cause this; Compose preserves existing
network settings. Engine versions older than 28 fail in `doctor` before
this check.

```bash
bash bin/tokencrate down
bash bin/tokencrate up
bash bin/tokencrate smoke --agent pi
```

`down` removes the networks; `up` creates them with the options in
`compose.docker.yaml`.

## `ui` reports that the container stopped or did not answer

Run `bash bin/tokencrate ui logs <set>` for the failing UI. The UI uses
the same entrypoint as `agent pi`, so skill-set or settings errors appear
before the daemon starts. Lines from `paseo` or `pi-web` identify daemon
errors. The readiness check goes through the forwarder; a `502` during
the first seconds means the UI is still starting.

## Asking for help

Open a
[bug report](https://github.com/angelo-lesniak/token-crate/issues/new?template=bug-report.yml);
the form lists what to include. Remove host paths, prompts, project
content, and other private information before attaching logs or reports.
For security problems, follow [SECURITY.md](../SECURITY.md) instead of
opening a public issue.
