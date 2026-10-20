# Troubleshooting

Each section is one failure observed in a run of the shipped tree: the
message, its cause, and the remedy. Most refusals name their remedy;
when one does not, start with these two commands:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate logs
```

## `doctor` reports the Docker Compose plugin under Podman

`podman compose` delegates to the Docker Compose plugin, which drops the
CDI GPU device request, so llama-server would start without the GPU;
`up` refuses with `the Podman compose provider is the Docker Compose
plugin, which drops CDI GPU devices; install podman-compose or set
LLM_GPU=false for CPU-only checks`. Install podman-compose so that
`podman compose version` reports `podman-compose`, then run `doctor`
again.

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

The message is `the default preset <id> is not loadable; download its
model set (bash bin/tokencrate models fetch <set>) or set
LLM_DEFAULT_PRESET to a preset listed as loadable above`: the model set
behind `LLM_DEFAULT_PRESET` has missing files, and the list `up` printed
before the refusal shows which presets are loadable. Run the `models
fetch` command the message names, or choose a listed preset.

## A command refuses because of the stack record

`up` writes `build/stack.json` with the engine it started the stack on,
and every later command uses that engine. A `CONTAINER_ENGINE` that
disagrees is refused: `the stack runs on docker, not podman
(build/stack.json); run: CONTAINER_ENGINE=docker bash bin/tokencrate
down`. Run that `down`, then `up` on the engine you want. An unreadable
record is refused as `cannot read the stack record <path>: <error>;
remove it if no stack is running`: check with `podman ps` or `docker ps`
that no TokenCrate container runs, then delete the file.

## `up` or a session refuses an internal network

`up`, `agent`, `smoke --agent`, and `ui` refuse when the `agents`, `ui`,
or `dashboard` network is not in the shape the Compose files declare:

- on Docker, `the agents network keeps a host gateway address (<address>);
  it was created without gateway mode isolated. Run: bash bin/tokencrate
  down, then up`, when a direct Compose call without
  `compose.docker.yaml` created it;
- on either engine, `the agents network is not internal. Run: bash
  bin/tokencrate down, then up`, or `the agents network was not created
  by this Compose project; remove it (podman network rm <project>_agents)
  and run: bash bin/tokencrate up` for a network made by hand under the
  project's name.

`down` removes the project's networks and `up` recreates them; a network
without the project's labels is removed with the command the message
names. [Privacy and containment](privacy.md#defaults-and-their-limits)
states the network rules.

## The agent starts but every request fails

The model is still loading, llama-server exited after the agent started,
or the request does not fit the preset's slot, and llama-server answers
`400 ... exceeds the available context size`. Check `bash bin/tokencrate
status` and `bash bin/tokencrate logs`; for a larger slot, pick a preset
with a `-long` suffix from
[Included presets](models.md#included-presets).

## The browser UI answers `403` with `refused a request for host`

The forwarder in front of a browser UI refused the request's `Host`,
`Origin`, or `Sec-Fetch-Site` header; the response names the value. Open
the address that `ui <set>` prints directly, not through a page of
another site. [Privacy and containment](privacy.md#defaults-and-their-limits)
states the rule and what a reverse proxy must pass on.

## Paseo asks to pair again or shows the previous project

After a relaunch for another project, reload the page. Paseo remembers
the daemon identity of each address; the identity lives in
`LLM_AGENTS_DIR/pi/paseo-state/`, and deleting it or changing
`LLM_AGENTS_DIR` makes the browser pair again
([Browser UIs](agents.md#browser-uis)).

## Asking for help

Open a
[bug report](https://github.com/angelo-lesniak/token-crate/issues/new?template=bug-report.yml).
Remove host paths, prompts, project content, and other private
information from logs and reports first. For security problems, follow
[SECURITY.md](../SECURITY.md) instead.
