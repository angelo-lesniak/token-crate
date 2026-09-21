#!/usr/bin/env bash
# Runs inside an agent container: proves that the model endpoint is reachable
# and that the routes out are absent (no default route, no path to an address
# literal, no name resolution, no browser-UI peer, and on Docker no host
# address on the bridge). It proves the absence of those routes, nothing
# about what the reachable model does. Used by `bin/tokencrate smoke
# --agent`, which passes the engine name and the gateway in.
set -uo pipefail

readonly LLAMA_URL=http://llama:8080
failures=0

report() {
  local status=$1
  shift
  printf '[%s] %s\n' "$status" "$*"
  [[ "$status" != fail ]] || failures=$((failures + 1))
}

printf '== TokenCrate agent container check (%s) ==\n' "${TOKENCRATE_AGENT:-unknown}"
report ok "running as $(id -u):$(id -g) with HOME=$HOME"

if [[ -w "$HOME" ]]; then
  report ok "agent home is writable: $HOME"
else
  report fail "agent home is not writable: $HOME"
fi

if [[ -d "$HOME/.agents/skills" ]]; then
  skills=$(find -L "$HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d -printf '%f ' 2>/dev/null)
  report ok "skills linked at ~/.agents/skills: ${skills:-none}"
else
  report fail 'skills directory ~/.agents/skills is missing'
fi

if curl -fsS --max-time 10 "$LLAMA_URL/health" >/dev/null 2>&1; then
  report ok "model endpoint is reachable: $LLAMA_URL"
else
  report fail "model endpoint is not reachable: $LLAMA_URL"
fi

# Containment is proven by routes, not names: no default route, no path to an
# address literal, and no name resolution.
if awk '$2 == "00000000" { found = 1 } END { exit !found }' /proc/net/route; then
  report fail 'the routing table has a default route; egress is NOT blocked'
else
  report ok 'no default route'
fi
if curl -sS --max-time 5 http://1.1.1.1/ >/dev/null 2>&1; then
  report fail 'the container reached http://1.1.1.1/; egress is NOT blocked'
else
  report ok 'no route to 1.1.1.1'
fi
if curl -sS --max-time 8 https://example.com >/dev/null 2>&1; then
  report fail 'the container reached https://example.com; egress is NOT blocked'
elif getent hosts example.com >/dev/null 2>&1; then
  report fail 'the container resolved example.com; DNS egress is NOT blocked'
else
  report ok 'no name resolution (https://example.com and DNS both fail)'
fi

# The wrapper discovers every active UI set, including custom sets. Probe
# both DNS names and effective container addresses; DNS failure alone is
# not proof that an address is unreachable.
for target in ${TOKENCRATE_UI_TARGETS:-}; do
  peer=${target%:*}
  port=${target##*:}
  if [[ ! "$peer" =~ ^[0-9.]+$ ]] && getent hosts "$peer" >/dev/null 2>&1; then
    report fail "the container resolves $peer; a browser UI is reachable by name"
  fi
  # Expanded by the inner shell; arguments stay data.
  # shellcheck disable=SC2016
  if timeout 3 bash -c 'exec 3<>/dev/tcp/"$1"/"$2"' _ "$peer" "$port" 2>/dev/null; then
    report fail "the container reached browser UI $target"
  else
    report ok "browser UI $target is not reachable"
  fi
done

# On Docker an internal bridge normally keeps a host address (the gateway),
# through which host services bound to all interfaces are reachable;
# compose.docker.yaml removes it, so on Docker any gateway at all is a
# failure (a network created without the overlay, or an old Engine). The
# wrapper passes the gateway the engine reports, because from inside the
# container the first address of the subnet can belong to a peer. The probe
# says whether the address answers (a closed port that refuses is an
# answer); on Podman that is the user's network namespace, not the host.
gateway=${TOKENCRATE_AGENTS_GATEWAY:-}
if [[ -z "$gateway" ]]; then
  report ok 'the agents network has no gateway address; no host address is reachable'
else
  # Expanded by the inner shell; arguments stay data.
  # shellcheck disable=SC2016
  outcome=$(timeout 3 bash -c 'exec 3<>/dev/tcp/"$1"/1' _ "$gateway" 2>&1)
  status=$?
  if ((status == 0)) || [[ "$outcome" == *"Connection refused"* ]]; then
    answers=true
  else
    answers=false
  fi
  if [[ "${TOKENCRATE_ENGINE:-}" == docker ]]; then
    if [[ "$answers" == true ]]; then
      report fail "the bridge gateway $gateway answers; host services bound to all interfaces are reachable (run bash bin/tokencrate down, then up)"
    else
      report fail "the agents network has a gateway address ($gateway) although Docker should create it without one (run bash bin/tokencrate down, then up)"
    fi
  elif [[ "$answers" == true ]]; then
    report ok "the gateway $gateway answers from the user's network namespace (rootless Podman), which holds no host service"
  else
    report ok "the gateway $gateway does not answer"
  fi
fi

# `touch /` fails for any unprivileged user; the mount options are the proof.
if awk '$2 == "/" && $4 ~ /(^|,)ro(,|$)/ { found = 1 } END { exit !found }' /proc/self/mounts; then
  report ok 'the root filesystem is mounted read-only'
else
  report fail 'the root filesystem is not mounted read-only'
fi

if [[ -n "${TOKENCRATE_PROJECT_DIR:-}" && -d "$TOKENCRATE_PROJECT_DIR" ]]; then
  report ok "project directory is mounted: $TOKENCRATE_PROJECT_DIR"
else
  report fail "project directory is missing: ${TOKENCRATE_PROJECT_DIR:-unset}"
fi

# --- oh-my-pi saves its settings by writing a temporary file next to them
# --- and renaming it into place, which a read-only mount refuses.
if [[ "${TOKENCRATE_AGENT:-}" == omp ]]; then
  settings="$HOME/.omp/agent/config.yml"
  if [[ -f "$settings" ]] && cp "$settings" "$settings.check.tmp" && mv "$settings.check.tmp" "$settings"; then
    report ok "the agent can save its settings for this session: $settings"
  else
    rm -f "$settings.check.tmp"
    report fail "the agent cannot save its settings: $settings"
  fi
fi

# --- Agent sets: what a selected set ships must run for the container user
# --- with no route out; each probe keys on the binary its set installs.
if [[ "${TOKENCRATE_AGENT:-}" == pi ]]; then
  packages=$(jq -r '.packages | length' "$HOME/.pi/agent/settings.json")
  if [[ -f "$HOME/.pi/agent/AGENTS.md" ]]; then
    report ok "agent sets seeded: $packages pi package(s) and the tools note"
  else
    report fail 'the tools note of the agent sets is not seeded (AGENTS.md is missing)'
  fi
  if grep -q '/subagent$' /opt/tokencrate/pi-packages.txt 2>/dev/null; then
    if [[ -f "$HOME/.pi/agent/agents/scout.md" ]]; then
      # A definition that names a model of its own would send the subagent to
      # a provider this container cannot reach; without one it inherits the
      # session's model.
      seeded=$(find "$HOME/.pi/agent/agents" -maxdepth 1 -name '*.md' | wc -l)
      pinned=$(grep -l '^model:' "$HOME"/.pi/agent/agents/*.md 2>/dev/null | wc -l)
      if ((pinned == 0)); then
        report ok "$seeded subagent definition(s) seeded, none pinned to another model"
      else
        report fail "$pinned of $seeded subagent definition(s) name a model this container cannot reach"
      fi
    else
      report fail 'the subagent definitions of the coding set are not seeded'
    fi
  fi
  check=$(mktemp -d)
  if command -v dotnet >/dev/null; then
    # The xunit template is the one whose packages are not part of the SDK.
    if (cd "$check" && dotnet new xunit --name check --output xunit >/dev/null 2>&1 && dotnet build xunit --nologo -v quiet >/dev/null 2>&1); then
      report ok "dotnet $(dotnet --version) builds the xunit template from the cached packages"
    else
      report fail 'dotnet cannot build the xunit template offline'
    fi
  fi
  if command -v js-debug-adapter >/dev/null; then
    # The bridge must answer a DAP request over stdio from the container user.
    request='{"seq":1,"type":"request","command":"initialize","arguments":{"adapterID":"pwa-node"}}'
    if printf 'Content-Length: %d\r\n\r\n%s' "${#request}" "$request" | timeout 30 js-debug-adapter 2>/dev/null | grep -q '"command":"initialize"'; then
      report ok 'js-debug answers a DAP initialize request over stdio'
    else
      report fail 'js-debug does not answer a DAP initialize request over stdio'
    fi
  fi
  if command -v tokencrate-chromium >/dev/null; then
    if tokencrate-chromium --version >/dev/null 2>&1; then
      report ok "$(tokencrate-chromium --version 2>/dev/null | head -1) answers --version"
    else
      report fail 'chromium does not answer --version'
    fi
  fi
  if command -v tokencrate-ui-pi-web >/dev/null; then
    # The daemon must load the image's pi (the scope directory of the set is
    # a link to the global install, never a second copy) and node-pty from
    # its prebuild.
    if [[ "$(readlink -f /opt/tokencrate/sets/pi-web/node_modules/@earendil-works/pi-coding-agent)" != /usr/local/lib/node_modules/@earendil-works/pi-coding-agent ]]; then
      report fail 'the pi-web set carries its own copy of pi instead of a link to the image'"'"'s'
    elif (cd /opt/tokencrate/sets/pi-web && node -e 'import("@earendil-works/pi-ai").then(() => import("@earendil-works/pi-coding-agent")).then(() => import("node-pty")).then(() => process.exit(0), (error) => { console.error(error.message); process.exit(1); })' 2>/dev/null); then
      report ok "pi-web $(pi-web --version 2>/dev/null | head -1) resolves the image's pi and node-pty"
    else
      report fail 'pi-web cannot load the image'"'"'s pi or node-pty'
    fi
  fi
  if command -v tokencrate-ui-paseo >/dev/null; then
    if paseo --version >/dev/null 2>&1; then
      report ok "paseo $(paseo --version 2>/dev/null | head -1) answers --version"
    else
      report fail 'paseo does not answer --version'
    fi
  fi
  if command -v odin >/dev/null; then
    printf 'package main\nimport "core:fmt"\nmain :: proc() { fmt.println("ok") }\n' > "$check/hello.odin"
    if odin run "$check/hello.odin" -file -out:"$check/hello" 2>/dev/null | grep -q '^ok$'; then
      report ok "$(odin version 2>/dev/null | head -1) builds and runs a program"
    else
      report fail 'odin cannot build and run a program'
    fi
  fi
  rm -rf "$check"
fi

printf 'Mounts (path, type):\n'
awk '$3 != "proc" && $3 != "sysfs" && $3 != "cgroup2" && $3 != "devpts" && $3 != "mqueue" { printf "  %s %s\n", $2, $3 }' /proc/self/mounts

printf 'Agent check completed with %d failure(s).\n' "$failures"
((failures == 0))
