#!/usr/bin/env bash
# Renders each Compose file combination the wrapper can produce with the
# pinned standalone podman-compose parser and checks the network placement
# the privacy model depends on. No container engine is used: the fake podman
# only answers the probes that podman-compose performs.
set -Eeuo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readonly PROJECT_ROOT
cd "$PROJECT_ROOT"

command -v podman-compose >/dev/null 2>&1 \
  || { printf 'podman-compose compatibility: podman-compose is required\n' >&2; exit 1; }

unset COMPOSE_PROJECT_NAME FAKE_PODMAN_LOG LLM_AGENT_PROJECT_DIR TOKENCRATE_PRESET
export COMPOSE_PROJECT_NAME=tokencrate
TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT
export LLM_MODELS_DIR="$TEST_ROOT/models"
export LLM_AGENTS_DIR="$TEST_ROOT/agents"
export TOKENCRATE_AGENT_HOME="$TEST_ROOT/agent-home"
# The wrapper sets these on every call; a render needs them too.
export TOKENCRATE_HOME_OWNER=U
export TOKENCRATE_ROOT="$PROJECT_ROOT"
export LLM_SKILLS_DIR="$TEST_ROOT/skills"
export LLM_LOCAL_SKILLS_DIR="$TEST_ROOT/local-skills"
export LLM_AGENT_PROJECT_DIR="$TEST_ROOT/project"
mkdir -p "$LLM_MODELS_DIR" "$LLM_AGENTS_DIR/pi" "$LLM_AGENTS_DIR/omp" \
  "$LLM_SKILLS_DIR" "$LLM_LOCAL_SKILLS_DIR" "$LLM_AGENT_PROJECT_DIR" build/agents/pi build/agents/omp local
network_log="$TEST_ROOT/network.log"

fake_engine="$PROJECT_ROOT/tests/fixtures/podman-compose-bin/podman"
chmod +x "$fake_engine"
python_bin=python3
command -v python3 >/dev/null 2>&1 || python_bin=python
# The pi service builds a Dockerfile the wrapper renders per agent-set
# selection; render the empty selection so Compose can resolve the path.
TOKENCRATE_AGENT_SETS_TAG=$("$python_bin" -c 'from tokencrate import PROJECT_ROOT, agentsets; print(agentsets.render(PROJECT_ROOT, PROJECT_ROOT / "build", agentsets.select(PROJECT_ROOT, "")))')
export TOKENCRATE_AGENT_SETS_TAG

# podman-compose warns about every network the selected services leave
# unused; its output is shown only when a render fails.
quiet() {
  local output
  output=$("$@" 2>&1 >/dev/null) || { printf '%s\n' "$output" >&2; return 1; }
}

render() {
  quiet podman-compose "$@" --env-file pins.env --podman-path "$fake_engine" config
}

# The file combinations bin/tokencrate can pass, in its order: base, GPU
# overlay, Podman overlay, and the egress overlay with both agent profiles.
render --file compose.yaml
render --file compose.yaml --file compose.gpu.yaml
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml \
  --file compose.agent-egress.yaml --profile agent-pi --profile agent-omp
render --file compose.yaml --file compose.podman.yaml --profile ui

# Network placement: agents join only the internal network unless the egress
# overlay is added; llama joins the published default network and the agents
# network, with a GPU device only through the gpu overlay.
podman_files=(--file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml --env-file pins.env)
# Arguments of the `run` itself (before the service), as `agent --cloud`
# passes its `-v`; empty unless a check sets them.
run_args=()
run_logged() {
  local service=$1
  shift
  rm -f -- "$network_log"
  (
    export FAKE_PODMAN_LOG=$network_log
    quiet podman-compose "$@" --podman-path "$fake_engine" run --rm --no-deps -T "${run_args[@]}" "$service"
  )
}

run_logged agent-pi "${podman_files[@]}" --profile agent-pi
grep -Fq -- '--network=tokencrate_agents' "$network_log" \
  || { printf 'podman-compose compatibility: agent-pi does not join the agents network\n' >&2; exit 1; }
if grep -Fq -- '--network=tokencrate_default' "$network_log"; then
  printf 'podman-compose compatibility: agent-pi joined the default network without the egress overlay\n' >&2
  exit 1
fi
grep -Fq -- '--read-only' "$network_log" \
  || { printf 'podman-compose compatibility: agent-pi is not read-only\n' >&2; exit 1; }
grep -Fq -- 'keep-id' "$network_log" \
  || { printf 'podman-compose compatibility: agent-pi does not use keep-id\n' >&2; exit 1; }

# oh-my-pi's service sits on the agents network alone, like pi's.
run_logged agent-omp "${podman_files[@]}" --profile agent-omp
grep -Fq -- '--network=tokencrate_agents' "$network_log" \
  || { printf 'podman-compose compatibility: agent-omp does not join the agents network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(default|ui|ui-publish)' "$network_log"; then
  printf 'podman-compose compatibility: agent-omp joined a network other than agents\n' >&2
  exit 1
fi

# The egress overlay replaces the network list (`!override`): the session is
# on the default network and no longer on the agents network.
run_logged agent-pi "${podman_files[@]}" --file compose.agent-egress.yaml --profile agent-pi
grep -Fq -- '--network=tokencrate_default' "$network_log" \
  || { printf 'podman-compose compatibility: the egress overlay did not add the default network\n' >&2; exit 1; }
if grep -Fq -- '--network=tokencrate_agents' "$network_log"; then
  printf 'podman-compose compatibility: an egress session is still on the agents network\n' >&2
  exit 1
fi

# `agent --cloud`: the `run -v` binds the key file read-only, on top of the
# service's own volumes. Only its path reaches the command line, never a key.
key_file="$TEST_ROOT/cloud-keys"
printf 'ANTHROPIC_API_KEY=sk-fixture-not-a-key\n' > "$key_file"
run_args=(-v "$key_file:/etc/tokencrate/cloud-keys:ro")
run_logged agent-pi "${podman_files[@]}" --file compose.agent-egress.yaml --profile agent-pi
run_args=()
grep -Fq -- "$key_file:/etc/tokencrate/cloud-keys:ro" "$network_log" \
  || { printf 'podman-compose compatibility: run -v did not bind the key file read-only\n' >&2; exit 1; }
grep -Fq -- '/opt/tokencrate/skills' "$network_log" \
  || { printf 'podman-compose compatibility: run -v replaced the service volumes instead of adding to them\n' >&2; exit 1; }
if grep -Fq -- 'sk-fixture-not-a-key' "$network_log"; then
  printf 'podman-compose compatibility: a key reached the podman command line\n' >&2
  exit 1
fi

run_logged llama "${podman_files[@]}"
grep -Fq -- '--network=tokencrate_default' "$network_log" \
  || { printf 'podman-compose compatibility: llama does not join the default network\n' >&2; exit 1; }
grep -Fq -- '--network=tokencrate_agents' "$network_log" \
  || { printf 'podman-compose compatibility: llama does not join the agents network\n' >&2; exit 1; }
grep -Fq -- '--device' "$network_log" \
  || { printf 'podman-compose compatibility: llama has no GPU device with the gpu overlay\n' >&2; exit 1; }
grep -Fq -- 'keep-id' "$network_log" \
  || { printf 'podman-compose compatibility: llama does not use keep-id\n' >&2; exit 1; }

run_logged llama --file compose.yaml --file compose.podman.yaml --env-file pins.env
if grep -Fq -- '--device' "$network_log"; then
  printf 'podman-compose compatibility: llama has a GPU device without the gpu overlay\n' >&2
  exit 1
fi
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: llama does not join the ui network\n' >&2; exit 1; }

# The browser UI sits on the ui network only, and with the egress overlay
# on ui and default; the forwarder publishes from ui-publish, which no
# agent joins. The wrapper starts both with `run`, so what the log shows
# is what a UI gets: the set label from the Compose file (podman-compose
# ignores `run -l`) and, for the forwarder, the service port through
# --service-ports.
run_args=(--name tokencrate-ui-x)
run_logged agent-ui "${podman_files[@]}" --profile ui
run_args=()
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: agent-ui does not join the ui network\n' >&2; exit 1; }
grep -Fq -- '--name=tokencrate-ui-x' "$network_log" \
  || { printf 'podman-compose compatibility: run --name did not name the container\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default|ui-publish)' "$network_log"; then
  printf 'podman-compose compatibility: agent-ui joined a network other than ui\n' >&2
  exit 1
fi
grep -Fq -- '--label io.tokencrate.ui-set=' "$network_log" \
  || { printf 'podman-compose compatibility: agent-ui carries no UI set label\n' >&2; exit 1; }
run_logged agent-ui "${podman_files[@]}" --file compose.agent-egress.yaml --profile ui
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: an egress UI left the ui network\n' >&2; exit 1; }
grep -Fq -- '--network=tokencrate_default' "$network_log" \
  || { printf 'podman-compose compatibility: the egress overlay did not add default to agent-ui\n' >&2; exit 1; }
grep -Fq -- '--label io.tokencrate.ui-egress=1' "$network_log" \
  || { printf 'podman-compose compatibility: the egress overlay did not label agent-ui\n' >&2; exit 1; }
run_args=(--service-ports)
run_logged ui-forward "${podman_files[@]}" --profile ui
run_args=()
grep -Fq -- '--network=tokencrate_ui-publish' "$network_log" \
  || { printf 'podman-compose compatibility: ui-forward does not join the ui-publish network\n' >&2; exit 1; }
grep -Fq -- '-p 127.0.0.1:4224:8080' "$network_log" \
  || { printf 'podman-compose compatibility: run --service-ports did not publish the forwarder port on loopback\n' >&2; exit 1; }
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: ui-forward does not join the ui network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default)' "$network_log"; then
  printf 'podman-compose compatibility: ui-forward joined the agents or default network\n' >&2
  exit 1
fi

printf 'TokenCrate podman-compose 1.6 compatibility checks passed.\n'
