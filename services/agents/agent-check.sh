#!/usr/bin/env bash
# Runs inside an agent container: proves that the model endpoint is reachable
# and that the routes out are absent (one network, no route through a
# gateway, no name resolution, no browser-UI peer except one that asked for
# a route out itself, and on Docker no gateway address on the agents
# network, through which host services would be reachable). It proves the
# absence of those routes, nothing about what the reachable model does.
# Used by `bin/tokencrate smoke --agent`, which passes the engine name and,
# for an offline session, the gateway in.
set -uo pipefail

readonly LLAMA_URL=http://llama:8080
failures=0

report() {
  local status=$1
  shift
  printf '[%s] %s\n' "$status" "$*"
  [[ "$status" != fail ]] || failures=$((failures + 1))
}

printf '== TokenCrate agent container check (%s%s) ==\n' "${TOKENCRATE_AGENT:-unknown}" \
  "${TOKENCRATE_EGRESS:+, --egress}"
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

# Containment is proven by routes, not names. The container sits on exactly
# one network, so it cannot relay between two. An offline session has no
# route through a gateway (IPv4 or IPv6; a route to the model's network is
# on-link) and resolves no public name. With TOKENCRATE_EGRESS the session
# asked for a route out, so a default route is the expected result; what
# it must never reach, below, stays a failure either way, which is what
# makes an egress run worth doing. Whether the internet answers is the
# host's network, not the container's placement, and is not probed.
egress=${TOKENCRATE_EGRESS:-}
# Ethernet devices only (type 1): a kernel with tunnel modules loaded puts
# fallback tunnel devices into every network namespace.
interfaces=0
for device in /sys/class/net/*; do
  [[ "$(cat "$device/type" 2>/dev/null)" == 1 ]] && interfaces=$((interfaces + 1))
done
if ((interfaces == 1)); then
  report ok 'the container has one network interface'
else
  report fail "the container has $interfaces network interfaces instead of one"
fi
default_route=false
awk '$2 == "00000000" { found = 1 } END { exit !found }' /proc/net/route && default_route=true
gateway_route=false
# RTF_GATEWAY is bit 0x2 of the flags: the fourth field of the IPv4 table,
# the ninth of the IPv6 one.
while read -r _ _ _ flags _; do
  [[ "$flags" =~ ^[0-9A-Fa-f]+$ ]] && ((16#$flags & 2)) && gateway_route=true
done < /proc/net/route
while read -r _ _ _ _ _ _ _ _ flags _; do
  [[ "$flags" =~ ^[0-9A-Fa-f]+$ ]] && ((16#$flags & 2)) && gateway_route=true
done < /proc/net/ipv6_route
resolved=false
getent hosts example.com >/dev/null 2>&1 && resolved=true

if [[ -n "$egress" ]]; then
  if [[ "$default_route" == true ]]; then
    report ok 'the routing table has a default route (expected with --egress)'
  else
    report fail 'no default route although --egress was requested'
  fi
elif [[ "$gateway_route" == true || "$default_route" == true ]]; then
  report fail 'the routing table has a default route or a route through a gateway; egress is NOT blocked'
else
  report ok 'no default route and no route through a gateway (IPv4 or IPv6)'
fi
if [[ "$resolved" == true ]]; then
  if [[ -n "$egress" ]]; then
    report ok 'example.com resolves (expected with --egress)'
  else
    report fail 'the container resolved example.com; DNS egress is NOT blocked'
  fi
elif [[ -z "$egress" ]]; then
  report ok 'no name resolution (example.com does not resolve)'
fi

# The wrapper discovers every active UI set, including custom sets. Probe
# both DNS names and effective container addresses; DNS failure alone is
# not proof that an address is unreachable. Without a running UI there is
# nothing to probe, which the report says rather than passing silently.
# A target the wrapper prefixed with `egress:` belongs to a UI started
# with --egress or --cloud, which sits on the default network too: an
# egress session reaching it is what the flag means, not a failure; an
# offline session must still not reach it.
if [[ -z "${TOKENCRATE_UI_TARGETS:-}" ]]; then
  report warn 'no browser UI running; UI isolation not tested'
fi
for target in ${TOKENCRATE_UI_TARGETS:-}; do
  verdict=fail
  note=
  if [[ "$target" == egress:* ]]; then
    target=${target#egress:}
    note='; that UI was started with --egress or --cloud'
    [[ -n "$egress" ]] && verdict=info
  fi
  peer=${target%:*}
  port=${target##*:}
  if [[ ! "$peer" =~ ^[0-9.]+$ ]] && getent hosts "$peer" >/dev/null 2>&1; then
    report "$verdict" "the container resolves $peer; a browser UI is reachable by name$note"
  fi
  # Expanded by the inner shell; arguments stay data.
  # shellcheck disable=SC2016
  if timeout 3 bash -c 'exec 3<>/dev/tcp/"$1"/"$2"' _ "$peer" "$port" 2>/dev/null; then
    report "$verdict" "the container reached browser UI $target$note"
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
# An egress session is not on the agents network, so the probe does not
# apply to it (the default network's gateway is a host address by design).
gateway=${TOKENCRATE_AGENTS_GATEWAY:-}
if [[ -n "$egress" ]]; then
  report info 'the session is on the default network, not the agents network; the gateway probe does not apply'
elif [[ -z "$gateway" ]]; then
  report ok 'the agents network has no gateway address'
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
# --- with no route out, so the set checks are an offline session's.
if [[ "${TOKENCRATE_AGENT:-}" == pi && -z "$egress" ]]; then
  packages=$(jq -r '.packages | length' "$HOME/.pi/agent/settings.json")
  if [[ -f "$HOME/.pi/agent/AGENTS.md" ]]; then
    report ok "agent sets seeded: $packages pi package(s) and the tools note"
  else
    report fail 'the tools note of the agent sets is not seeded (AGENTS.md is missing)'
  fi
  # Each selected set's `check` lines, rendered into one script per set,
  # run as the container user in a scratch directory with no route out;
  # the last line a script prints is its report.
  for script in "${TOKENCRATE_CHECKS_DIR:-/opt/tokencrate/checks}"/*; do
    [[ -f "$script" ]] || continue
    set_name=${script##*/}
    scratch=$(mktemp -d)
    if output=$(cd "$scratch" && CHECK_DIR=$scratch bash -e -o pipefail "$script" 2>&1); then
      report ok "$set_name: ${output##*$'\n'}"
    else
      last=${output##*$'\n'}
      report fail "$set_name: ${last:-the check script failed without output}"
    fi
    rm -rf "$scratch"
  done
fi

printf 'Mounts (path, type):\n'
awk '$3 != "proc" && $3 != "sysfs" && $3 != "cgroup2" && $3 != "devpts" && $3 != "mqueue" { printf "  %s %s\n", $2, $3 }' /proc/self/mounts

printf 'Agent check completed with %d failure(s).\n' "$failures"
((failures == 0))
