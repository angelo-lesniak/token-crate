#!/usr/bin/env bash
# Entrypoint shared by the agent images. It runs as the host user on a
# read-only root filesystem: the only writable paths are the agent home
# (/home/agent, a fresh tmpfs at every start with the retained transcript
# and UI directories bound from the host), the project directory, /tmp,
# and /run/tokencrate (tmpfs). It never writes into the project directory.
set -Eeuo pipefail

# TOKENCRATE_PREFIX puts the fixed container paths below a temporary root
# for the engine-free entrypoint test; it is empty in the container.
readonly PREFIX=${TOKENCRATE_PREFIX:-}
readonly RUN_DIR="$PREFIX/run/tokencrate"
readonly SKILLS_ROOT="$RUN_DIR/skills"
readonly STATIC_CONFIG="$PREFIX/etc/tokencrate/agent"
readonly GENERATED_CONFIG="$PREFIX/etc/tokencrate/agent-generated"
readonly FETCHED_SKILLS="$PREFIX/opt/tokencrate/skills"
readonly REPO_SKILLS="$PREFIX/opt/tokencrate/skills-repo"
readonly LOCAL_SKILLS="$PREFIX/opt/tokencrate/skills-local"
# Owned by the image: the pi packages it ships (one absolute directory per
# line) and the files it seeds into the agent home.
readonly IMAGE_PACKAGES="$PREFIX/opt/tokencrate/pi-packages.txt"
readonly HOME_SEED="$PREFIX/opt/tokencrate/home-seed"

die() {
  printf 'TokenCrate agent: %s\n' "$*" >&2
  exit 1
}

agent=${TOKENCRATE_AGENT:-}
[[ "$agent" == pi || "$agent" == omp ]] || die "TOKENCRATE_AGENT must be pi or omp"
home=${HOME:-}
[[ -n "$home" && -d "$home" && -w "$home" ]] || die "agent home is missing or not writable: ${home:-unset}"
project=${TOKENCRATE_PROJECT_DIR:-}
[[ -n "$project" && -d "$project" ]] || die "project directory is not mounted: ${project:-unset}"
preset=${TOKENCRATE_PRESET:-}
[[ "$preset" =~ ^[a-z0-9][a-z0-9.-]*$ ]] || die "TOKENCRATE_PRESET must name a rendered preset (got: ${preset:-unset})"
umask "${UMASK:-0002}"
# The run directory is a per-container tmpfs; the merged skills view is
# built from scratch.
mkdir -p "$RUN_DIR"
rm -rf "$SKILLS_ROOT"
mkdir -p "$SKILLS_ROOT"

# --- Skills: merge fetched sets, repository skills, and private skills into
# --- one tmpfs directory linked at ~/.agents/skills (the cross-agent path).
link_skill() {
  local source=$1
  local name=${source##*/}
  [[ -f "$source/SKILL.md" ]] || return 0
  # The frontmatter name is what the agent lists; it must be the directory
  # name for every source, as `skills fetch` already requires for fetched sets.
  local declared
  declared=$(awk '
    NR == 1 { if ($0 != "---") exit; next }
    $0 == "---" { exit }
    /^name:/ { sub(/^name:[[:space:]]*/, ""); gsub(/^["'"'"']|["'"'"']$/, ""); print; exit }
  ' "$source/SKILL.md")
  [[ "$declared" == "$name" ]] \
    || die "skill $name: SKILL.md frontmatter name is '${declared:-missing}', not the directory name"
  if [[ -e "$SKILLS_ROOT/$name" ]]; then
    die "duplicate skill name across sets: $name (already linked from $(readlink "$SKILLS_ROOT/$name"))"
  fi
  ln -s "$source" "$SKILLS_ROOT/$name"
}

IFS=',' read -r -a skill_sets <<< "${TOKENCRATE_SKILL_SETS:-}"
for skill_set in "${skill_sets[@]}"; do
  [[ -n "$skill_set" ]] || continue
  [[ "$skill_set" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "unsafe skill-set name: $skill_set"
  [[ -d "$FETCHED_SKILLS/$skill_set" ]] \
    || die "skill set $skill_set is not fetched (run on the host: bash bin/tokencrate skills fetch $skill_set)"
  for skill_dir in "$FETCHED_SKILLS/$skill_set"/*/; do
    [[ -d "$skill_dir" ]] && link_skill "${skill_dir%/}"
  done
done
for root in "$REPO_SKILLS" "$LOCAL_SKILLS"; do
  [[ -d "$root" ]] || continue
  for skill_dir in "$root"/*/; do
    [[ -d "$skill_dir" ]] && link_skill "${skill_dir%/}"
  done
done
mkdir -p "$home/.agents"
ln -s "$SKILLS_ROOT" "$home/.agents/skills"

# --- Image seeds: the files the image owns in the agent home (the tools
# --- note, subagent definitions, NuGet configuration).
[[ ! -d "$HOME_SEED" ]] || cp -R "$HOME_SEED/." "$home/"

# --- Agent configuration: static settings from the repository, generated
# --- model lists from the renderer, the selected preset as the default model,
# --- and for pi the package list the image ships.
case "$agent" in
  pi)
    config_dir="$home/.pi/agent"
    mkdir -p "$config_dir"
    cp "$GENERATED_CONFIG/models.json" "$config_dir/models.json"
    # The package list is the list the image ships: local directories, never
    # a registry.
    node -e '
      const fs = require("fs");
      const [seed, preset, packagesFile, target] = process.argv.slice(1);
      const settings = JSON.parse(fs.readFileSync(seed, "utf8"));
      settings.defaultProvider = "tokencrate";
      settings.defaultModel = preset;
      settings.packages = fs.existsSync(packagesFile)
        ? fs.readFileSync(packagesFile, "utf8").split("\n").filter(Boolean)
        : [];
      fs.writeFileSync(target, JSON.stringify(settings, null, 2) + "\n");
    ' "$STATIC_CONFIG/settings.json" "$preset" "$IMAGE_PACKAGES" "$config_dir/settings.json"
    ;;
  omp)
    config_dir="$home/.omp/agent"
    mkdir -p "$config_dir"
    cp "$GENERATED_CONFIG/models.yml" "$config_dir/models.yml"
    # oh-my-pi reads and rewrites these settings in the home, so its model
    # picker can save a choice for the session; the tmpfs drops it when the
    # container stops. The repository file stays an overlay as well, which
    # keeps the keys it sets above the home file and the project.
    {
      cat "$STATIC_CONFIG/config.yml"
      printf 'modelRoles:\n  default: tokencrate/%s\n' "$preset"
    } > "$config_dir/config.yml"
    export PI_CONFIG_FILES="$STATIC_CONFIG/config.yml"
    ;;
esac

# --- Git identity: commits inside the container use the values from .env;
# --- the mounted project is trusted even when its owner UID differs.
git_config="$RUN_DIR/gitconfig"
{
  printf '[safe]\n\tdirectory = *\n'
  if [[ -n "${GIT_AUTHOR_NAME:-}" && -n "${GIT_AUTHOR_EMAIL:-}" ]]; then
    printf '[user]\n\tname = %s\n\temail = %s\n' "$GIT_AUTHOR_NAME" "$GIT_AUTHOR_EMAIL"
  fi
} > "$git_config"
export GIT_CONFIG_GLOBAL=$git_config
[[ -n "${GIT_AUTHOR_NAME:-}" ]] || unset GIT_AUTHOR_NAME GIT_COMMITTER_NAME
[[ -n "${GIT_AUTHOR_EMAIL:-}" ]] || unset GIT_AUTHOR_EMAIL GIT_COMMITTER_EMAIL
export USER=agent LOGNAME=agent

cd "$project"
exec "$@"
