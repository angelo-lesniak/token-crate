# Troubleshooting

Each section is one observed failure and how to recover. Most refusals
name their remedy; when one does not, start with these two commands:

```bash
bash bin/tokencrate doctor
bash bin/tokencrate logs
```

## `doctor` reports the Docker Compose plugin under Podman

Podman prefers the Docker Compose plugin when both are installed. After
installing podman-compose, select it with
`PODMAN_COMPOSE_PROVIDER=podman-compose` in your shell profile, or
`compose_providers` in `containers.conf`, and confirm that
`podman compose version` reports `podman-compose`.

## CUDA fails to initialize although `nvidia-smi` works

The log shows `no CUDA-capable device is detected` or a driver version
mismatch, or the model server loads every layer on the CPU. The likely
cause is a CDI specification left stale by a driver upgrade; under
Podman, `doctor` warns `the CDI spec references driver <version> but
the host runs <version>`. Regenerate the specification and start again:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
bash bin/tokencrate doctor
bash bin/tokencrate up
```

The warning is gone and `bash bin/tokencrate logs` names the GPU.

## The agent starts but every request fails

The model is still loading, the model server exited after the agent
started, or the request does not fit the preset's slot and the model
server answers `400 ... exceeds the available context size`. Check
`bash bin/tokencrate status` and `bash bin/tokencrate logs`. For a
larger slot, choose a preset with a `-long` suffix from [Included
presets](models.md#included-presets).

## The browser UI answers `403` with `refused a request for host`

The forwarder in front of the UI refused the request's `Host`,
`Origin`, or `Sec-Fetch-Site` header; the response names the address to
open. Open it directly, not through a page of another site.
[Forwarder](privacy.md#forwarder) lists the values a reverse proxy must
pass on.

## Paseo asks to pair again or shows the previous project

After a relaunch for another project, reload the page. For a fresh
identity, stop the UI (`bash bin/tokencrate ui stop paseo`) and delete
`daemon-keypair.json` and `server-id` from the per-set store
`LLM_AGENTS_DIR/pi/paseo-state/` and from the `.paseo` directory of
every project's agent home. Deleting them from the store alone changes
nothing, because the next start copies a project's identity back into
it.

## pi reports `Summarization failed` and refuses the next prompt

After a turn that fills the preset's slot ends with `length`, pi's
compaction can fail with `Summarization failed: generation hit the
token cap and the summary is incomplete`; the agent then stays busy and
refuses the next prompt. In PI WEB, reopen the conversation: it
compacts and continues. No recovery in terminal pi is known; start a
new session, on a preset with a larger slot if the slot fills often.

## A reply ends with `length` and no answer

At `xhigh` the model can spend the whole reply budget on reasoning and
return no answer. Lower the effort for the prompt or raise the client's
token limit ([Reasoning effort](models.md#reasoning-effort)). In
[`smoke`](cli.md#smoke), the same ending fails the `reply terminates`
check; on an abliterated preset it can also be a reasoning loop.

## Ask for help

Ask a question in
[Discussions](https://github.com/angelo-lesniak/token-crate/discussions/categories/q-a);
the issue chooser links the categories. Report a failure with a
[bug report](https://github.com/angelo-lesniak/token-crate/issues/new?template=bug-report.yml).
Remove host paths, prompts, project content, and other private
information from logs and reports first. For security problems, follow
[SECURITY.md](../SECURITY.md) instead.
