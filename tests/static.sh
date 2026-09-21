#!/usr/bin/env bash
# The engine-free gate: syntax and lint for the shell files, Ruff for
# the package and the tests, the unit tests (the repository contracts among
# them), the podman-compose parser, and a Compose render with every
# installed engine.
set -Eeuo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readonly PROJECT_ROOT
cd "$PROJECT_ROOT"

python_bin=python3
command -v python3 >/dev/null 2>&1 || python_bin=python
if ! command -v "$python_bin" >/dev/null 2>&1; then
  printf 'static: required command is unavailable: python3\n' >&2
  exit 1
fi

# TOKENCRATE_STATIC_STRICT=1 turns every optional-tool skip below into a
# hard failure. CI sets it so a missing tool cannot silently narrow the gate.
skip() {
  if [[ "${TOKENCRATE_STATIC_STRICT:-0}" == 1 ]]; then
    printf 'static: STRICT: %s\n' "$1" >&2
    exit 1
  fi
  printf 'SKIPPED: %s\n' "$1"
}

shell_files=(
  bin/tokencrate
  services/agents/entrypoint.sh
  services/agents/agent-check.sh
  config/agent-sets/*/tokencrate-*
  tests/podman-compose.sh
  tests/static.sh
  tests/fixtures/podman-compose-bin/podman
  tests/fixtures/engine-bin/nvidia-smi
)
for file in "${shell_files[@]}"; do
  bash -n "$file"
done
node --check config/agent-sets/web/js-debug-adapter
node --check services/agents/ui-forward.js

"$python_bin" -m unittest discover -s tests -t . -p 'test_*.py'

if command -v ruff >/dev/null 2>&1; then
  ruff check tokencrate tests tests/fixtures/engine-bin/docker
  ruff format --check tokencrate tests tests/fixtures/engine-bin/docker
else
  skip 'Ruff lint and format check (ruff not found)'
fi

if command -v podman-compose >/dev/null 2>&1; then
  bash tests/podman-compose.sh
else
  skip 'podman-compose 1.6 compatibility (podman-compose not found)'
fi

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${shell_files[@]}"
else
  skip 'ShellCheck lint (shellcheck not found; syntax checks only)'
fi

if command -v rg >/dev/null 2>&1; then
  # No tracked file may name a machine-specific host path. /home/agent, the
  # fixed home inside agent containers, is the one allowed /home literal;
  # each match is printed on its own line so that a line can hold both.
  # The first alternative is spelled with a class so it does not match this
  # script. Without a work tree (a `git archive` extract) the whole
  # directory is scanned.
  scan_paths() {
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git ls-files -z
    else
      printf '.\0'
    fi
  }
  if scan_paths | xargs -0 rg -n -o '/mnt/host[s]hare|/home/[A-Za-z0-9._-]+' \
    | grep -v ':/home/agent$'; then
    printf 'static: machine-specific absolute host paths remain\n' >&2
    exit 1
  fi
else
  skip 'absolute host path scan (rg not found)'
fi

# The pi service builds a Dockerfile the wrapper renders per agent-set
# selection; render the empty selection so Compose can resolve the path.
TOKENCRATE_AGENT_SETS_TAG=$("$python_bin" -c 'from tokencrate import PROJECT_ROOT, agentsets; print(agentsets.render(PROJECT_ROOT, PROJECT_ROOT / "build", agentsets.select(PROJECT_ROOT, "")))')
export TOKENCRATE_AGENT_SETS_TAG
# The wrapper sets the home tmpfs owner per engine; a render needs a value.
export TOKENCRATE_HOME_OWNER=U

# Render the Compose files with every installed engine; Compose interpolates
# every image tag from pins.env itself.
compose_validated=false
render_compose() {
  local engine=$1
  shift
  "$engine" compose "$@" --env-file pins.env config >/dev/null
}

for engine in docker podman; do
  command -v "$engine" >/dev/null 2>&1 || continue
  "$engine" compose version >/dev/null 2>&1 || continue
  compose_validated=true
  # The engine overlay the wrapper adds for this engine.
  overlay=(--file "compose.$engine.yaml")
  render_compose "$engine" --file compose.yaml --file compose.gpu.yaml "${overlay[@]}"
  render_compose "$engine" --file compose.yaml "${overlay[@]}"
  render_compose "$engine" --file compose.yaml --file compose.gpu.yaml "${overlay[@]}" \
    --file compose.agent-egress.yaml --profile agent-pi --profile agent-omp
  render_compose "$engine" --file compose.yaml "${overlay[@]}" --profile ui
done

if [[ "$compose_validated" != true ]]; then
  skip 'compose validation (no container engine with Compose found)'
fi

printf 'TokenCrate static checks passed.\n'
