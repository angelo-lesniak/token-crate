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
export TOKENCRATE_HOME_OWNER=U
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

render() {
  podman-compose "$@" --env-file pins.env --podman-path "$fake_engine" config >/dev/null
}

# The file combinations bin/tokencrate can pass, in its order: base, GPU
# overlay, Podman overlay, and the egress overlay with both agent profiles.
render --file compose.yaml
render --file compose.yaml --file compose.gpu.yaml
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml
render --file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml \
  --file compose.agent-egress.yaml --profile agent-pi --profile agent-omp

# Network placement: agents join only the internal network unless the egress
# overlay is added; llama joins the published default network and the agents
# network, with a GPU device only through the gpu overlay.
podman_files=(--file compose.yaml --file compose.gpu.yaml --file compose.podman.yaml --env-file pins.env)
run_logged() {
  local service=$1
  shift
  rm -f -- "$network_log"
  (
    export FAKE_PODMAN_LOG=$network_log
    podman-compose "$@" --podman-path "$fake_engine" run --rm --no-deps -T "$service" >/dev/null
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

run_logged agent-pi "${podman_files[@]}" --file compose.agent-egress.yaml --profile agent-pi
grep -Fq -- '--network=tokencrate_default' "$network_log" \
  || { printf 'podman-compose compatibility: the egress overlay did not add the default network\n' >&2; exit 1; }

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

# The browser UI sits on the ui network only; the forwarder publishes from
# ui-publish, which no agent joins.
run_logged agent-ui "${podman_files[@]}" --profile ui
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: agent-ui does not join the ui network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default|ui-publish)' "$network_log"; then
  printf 'podman-compose compatibility: agent-ui joined a network other than ui\n' >&2
  exit 1
fi
run_logged ui-forward "${podman_files[@]}" --profile ui
grep -Fq -- '--network=tokencrate_ui-publish' "$network_log" \
  || { printf 'podman-compose compatibility: ui-forward does not join the ui-publish network\n' >&2; exit 1; }
grep -Eq -- '--network=tokencrate_ui(:|$| )' "$network_log" \
  || { printf 'podman-compose compatibility: ui-forward does not join the ui network\n' >&2; exit 1; }
if grep -Eq -- '--network=tokencrate_(agents|default)' "$network_log"; then
  printf 'podman-compose compatibility: ui-forward joined the agents or default network\n' >&2
  exit 1
fi

printf 'TokenCrate podman-compose 1.6 compatibility checks passed.\n'
