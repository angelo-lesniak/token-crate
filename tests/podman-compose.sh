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

unset FAKE_PODMAN_LOG LLM_AGENT_PROJECT_DIR TOKENCRATE_PRESET
# The Compose files require every setting and the four values the wrapper
# derives on each call (compose.yaml, the interpolation note). The
# settings come from the reference at their documented defaults, which
# bin/tokencrate keeps shell-literal; the storage paths are then pointed
# at a scratch directory.
set -a
# shellcheck source=/dev/null
. ./.env.example
set +a
export COMPOSE_PROJECT_NAME=tokencrate
export TOKENCRATE_HOME_OWNER=U
export TOKENCRATE_ROOT="$PROJECT_ROOT"
HOST_UID=$(id -u)
HOST_GID=$(id -g)
export HOST_UID HOST_GID
TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT
export LLM_MODELS_DIR="$TEST_ROOT/models"
export LLM_AGENTS_DIR="$TEST_ROOT/agents"
export TOKENCRATE_AGENT_HOME="$TEST_ROOT/agent-home"
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
# overlay, Podman overlay, and the egress overlay with both agent profiles;
# the wrapper always adds an engine overlay (engine.compose).
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml \
  --file compose.agent-egress.yaml --profile agent-pi --profile agent-omp
render --file compose.yaml --file compose.podman.yaml --profile ui
render --file compose.yaml --file compose.podman.yaml --profile dashboard
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml --profile dashboard --profile dashboard-gpu
render --file compose.yaml --file compose.podman.yaml --profile memory
TOKENCRATE_MEMORY_ADDRESS=10.89.9.2 render --file compose.yaml --file compose.podman.yaml \
  --file compose.agent-egress.yaml --file compose.agent-memory.yaml --profile agent-pi
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml --profile judge

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
grep -Eq -- '(-e|--env)[ =]TOKENCRATE_JUDGE_URL=( |$)' "$network_log" \
  || { printf 'podman-compose compatibility: the egress overlay did not empty the judge URL\n' >&2; exit 1; }
# With the judge running, the wrapper's `run -e` replaces the empty URL with
# the judge's address.
run_args=(-e TOKENCRATE_JUDGE_URL=http://10.89.0.9:8080)
run_logged agent-pi "${podman_files[@]}" --file compose.agent-egress.yaml --profile agent-pi
run_args=()
grep -Fq -- 'TOKENCRATE_JUDGE_URL=http://10.89.0.9:8080' "$network_log" \
  || { printf 'podman-compose compatibility: run -e did not pass the judge address\n' >&2; exit 1; }
if grep -Eq -- 'TOKENCRATE_JUDGE_URL=(http://judge|( |$))' "$network_log"; then
  printf 'podman-compose compatibility: an egress session kept a judge URL besides the address\n' >&2
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

# `agent pi --memory`: the `run` binds the store and passes the memory
# server's bank, on top of the service's own volumes and environment.
run_args=(-v "$TEST_ROOT/memory:/home/agent/.pi/agent/memory" -e HINDSIGHT_BANK_ID=tokencrate::x)
run_logged agent-pi "${podman_files[@]}" --profile agent-pi
run_args=()
grep -Fq -- "$TEST_ROOT/memory:/home/agent/.pi/agent/memory" "$network_log" \
  || { printf 'podman-compose compatibility: run -v did not bind the memory store\n' >&2; exit 1; }
grep -Fq -- 'HINDSIGHT_BANK_ID=tokencrate::x' "$network_log" \
  || { printf 'podman-compose compatibility: run -e did not pass the memory bank\n' >&2; exit 1; }
grep -Fq -- '/home/agent/.pi/agent/sessions' "$network_log" \
  || { printf 'podman-compose compatibility: run -v replaced the service volumes instead of adding to them\n' >&2; exit 1; }

# `agent pi --memory` with a route out and the hindsight set: the default
# network and the server's internal one, never the agents network, and the
# server's name as a hosts entry.
export TOKENCRATE_MEMORY_ADDRESS=10.89.9.2
run_logged agent-pi "${podman_files[@]}" --file compose.agent-egress.yaml --file compose.agent-memory.yaml --profile agent-pi
unset TOKENCRATE_MEMORY_ADDRESS
for network in default memory; do
  grep -Eq -- "--network=tokencrate_$network(:|\$| )" "$network_log" \
    || { printf 'podman-compose compatibility: an online memory session does not join %s\n' "$network" >&2; exit 1; }
done
if grep -Eq -- '--network=tokencrate_(agents|ui|ui-publish|dashboard|dashboard-publish)' "$network_log"; then
  printf 'podman-compose compatibility: an online memory session joined a network other than default and memory\n' >&2
  exit 1
fi
grep -Eq -- '--add-host[= ]hindsight:10\.89\.9\.2' "$network_log" \
  || { printf 'podman-compose compatibility: an online memory session has no hosts entry for the server\n' >&2; exit 1; }

# The memory server: the internal agents and memory networks, read-only, keep-id.
run_logged hindsight "${podman_files[@]}" --profile memory
grep -Fq -- '--network=tokencrate_agents' "$network_log" \
  || { printf 'podman-compose compatibility: hindsight does not join the agents network\n' >&2; exit 1; }
grep -Fq -- '--network=tokencrate_memory' "$network_log" \
  || { printf 'podman-compose compatibility: hindsight does not join the memory network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(default|ui|ui-publish|dashboard|dashboard-publish)' "$network_log"; then
  printf 'podman-compose compatibility: hindsight joined a network other than agents and memory\n' >&2
  exit 1
fi
grep -Fq -- '--read-only' "$network_log" \
  || { printf 'podman-compose compatibility: hindsight is not read-only\n' >&2; exit 1; }
grep -Fq -- 'keep-id' "$network_log" \
  || { printf 'podman-compose compatibility: hindsight does not use keep-id\n' >&2; exit 1; }

# The judge server: the agents, ui, and default networks (sessions with a
# route out reach it there by address), read-only, keep-id, and the GPU
# device only through the gpu overlay.
run_logged judge "${podman_files[@]}" --profile judge
grep -Fq -- '--network=tokencrate_agents' "$network_log" \
  || { printf 'podman-compose compatibility: judge does not join the agents network\n' >&2; exit 1; }
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: judge does not join the ui network\n' >&2; exit 1; }
grep -Fq -- '--network=tokencrate_default' "$network_log" \
  || { printf 'podman-compose compatibility: judge does not join the default network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(ui-publish|dashboard|dashboard-publish)' "$network_log"; then
  printf 'podman-compose compatibility: judge joined a network other than agents, ui, and default\n' >&2
  exit 1
fi
grep -Fq -- '--read-only' "$network_log" \
  || { printf 'podman-compose compatibility: judge is not read-only\n' >&2; exit 1; }
grep -Fq -- 'keep-id' "$network_log" \
  || { printf 'podman-compose compatibility: judge does not use keep-id\n' >&2; exit 1; }
grep -Fq -- '--device' "$network_log" \
  || { printf 'podman-compose compatibility: judge has no GPU device with the gpu overlay\n' >&2; exit 1; }
grep -Fq -- '--entrypoint' "$network_log" \
  || { printf 'podman-compose compatibility: judge keeps the router entrypoint\n' >&2; exit 1; }
run_logged judge --file compose.yaml --file compose.podman.yaml --env-file pins.env --profile judge
if grep -Fq -- '--device' "$network_log"; then
  printf 'podman-compose compatibility: judge has a GPU device without the gpu overlay\n' >&2
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
grep -Eq -- '--network=tokencrate_dashboard(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: llama does not join the dashboard network\n' >&2; exit 1; }

# The dashboard profile: the exporter and VictoriaMetrics on the internal
# dashboard network alone; Grafana also on dashboard-publish for its port.
for service in llama-exporter victoriametrics; do
  run_logged "$service" "${podman_files[@]}" --profile dashboard
  grep -Eq -- '--network=tokencrate_dashboard(:|$| )' "$network_log" \
    || { printf 'podman-compose compatibility: %s does not join the dashboard network\n' "$service" >&2; exit 1; }
  if grep -Eq -- '--network=tokencrate_(agents|default|ui|ui-publish|dashboard-publish)' "$network_log"; then
    printf 'podman-compose compatibility: %s joined a network other than dashboard\n' "$service" >&2
    exit 1
  fi
  grep -Fq -- '--read-only' "$network_log" \
    || { printf 'podman-compose compatibility: %s is not read-only\n' "$service" >&2; exit 1; }
done
# The GPU exporter: the dashboard network alone, the CDI device only
# through the gpu overlay, and read-only like the rest.
run_logged gpu-exporter "${podman_files[@]}" --profile dashboard-gpu
grep -Eq -- '--network=tokencrate_dashboard(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: gpu-exporter does not join the dashboard network\n' >&2; exit 1; }
grep -Fq -- '--device' "$network_log" \
  || { printf 'podman-compose compatibility: gpu-exporter has no GPU device with the gpu overlay\n' >&2; exit 1; }
grep -Fq -- '--read-only' "$network_log" \
  || { printf 'podman-compose compatibility: gpu-exporter is not read-only\n' >&2; exit 1; }
run_logged gpu-exporter --file compose.yaml --file compose.podman.yaml --env-file pins.env --profile dashboard-gpu
if grep -Fq -- '--device' "$network_log"; then
  printf 'podman-compose compatibility: gpu-exporter has a GPU device without the gpu overlay\n' >&2
  exit 1
fi
run_args=(--service-ports)
run_logged grafana "${podman_files[@]}" --profile dashboard
run_args=()
grep -Fq -- '--network=tokencrate_dashboard-publish' "$network_log" \
  || { printf 'podman-compose compatibility: grafana does not join the dashboard-publish network\n' >&2; exit 1; }
grep -Fq -- "-p 127.0.0.1:$LLM_DASHBOARD_PORT:8080" "$network_log" \
  || { printf 'podman-compose compatibility: grafana does not publish its port on loopback\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default|ui|ui-publish)' "$network_log"; then
  printf 'podman-compose compatibility: grafana joined an agent or UI network\n' >&2
  exit 1
fi

# The browser UI sits on the ui network only, and with the egress overlay
# on ui and default; the forwarder publishes from ui-publish, which no
# agent joins. The wrapper starts both with `run` and sets the UI
# variables per start (here: a set name and a host port with no meaning),
# so what the log shows is what a UI gets: the set label from the Compose
# file (podman-compose ignores `run -l`) and, for the forwarder, the
# service port through --service-ports.
export TOKENCRATE_UI_SET=x TOKENCRATE_UI_HOST_PORT=4299
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
grep -Fq -- '--label io.tokencrate.ui-set=x' "$network_log" \
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
grep -Fq -- "-p 127.0.0.1:$TOKENCRATE_UI_HOST_PORT:8080" "$network_log" \
  || { printf 'podman-compose compatibility: run --service-ports did not publish the forwarder port on loopback\n' >&2; exit 1; }
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: ui-forward does not join the ui network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default)' "$network_log"; then
  printf 'podman-compose compatibility: ui-forward joined the agents or default network\n' >&2
  exit 1
fi

printf 'TokenCrate podman-compose 1.6 compatibility checks passed.\n'
