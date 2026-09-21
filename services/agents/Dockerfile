ARG NODE_TAG
ARG NODE_DIGEST
ARG BUN_TAG
ARG BUN_DIGEST


# pi: the default coding agent. Installed from the pinned npm package with
# scripts disabled, as its README documents. The install telemetry switch is
# set before the install layer so the package can never report the install.
# The base image tag and its manifest digest are required build arguments
# (pins.env); the digest is what the build pulls, the tag names it.
#
# This stage is the base of the image the wrapper renders into
# build/agents/pi/<digest>/Dockerfile: the selected agent sets
# (config/agent-sets, local/agent-sets) are appended as one `agent` stage
# on top of it.
# hadolint ignore=DL3006
FROM docker.io/library/node:${NODE_TAG}@sha256:${NODE_DIGEST} AS pi
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG PI_VERSION
ARG NODE_TAG

LABEL org.opencontainers.image.title="TokenCrate pi agent" \
      org.opencontainers.image.description="pi coding agent pinned to one npm version, configured for a local llama-server endpoint" \
      io.tokencrate.pi-version="${PI_VERSION}"

# pi-lens (an agent set) must never install language servers or tools
# itself: the sets pin them. Its configuration is rendered from the
# selected sets; its caches are tmpfs.
ENV PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1 \
    PI_OFFLINE=1 \
    npm_config_update_notifier=false \
    npm_config_fund=false \
    npm_config_audit=false \
    PI_LENS_DISABLE_LSP_INSTALL=1 \
    PI_LENS_DISABLE_TOOL_INSTALL=1 \
    PI_LENS_CONFIG_PATH=/opt/tokencrate/pi-lens.json \
    PILENS_DATA_DIR=/tmp/cache/pi-lens/projects \
    PI_LENS_HOME=/tmp/cache/pi-lens/home

# The engine pulls by digest and ignores the tag beside it, so a tag raised
# without its digest would build on the old base and say nothing; assert
# that the pulled image is the Node the tag names. Exact, like the bun
# stage: a grep pattern would read the version dots as any character.
RUN test "$(node --version)" = "v${NODE_TAG%%-*}"

# Distribution packages come from the base image's Debian release at build
# time, without per-package pins. unzip extracts a set's zip assets.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        fd-find \
        git \
        jq \
        less \
        procps \
        ripgrep \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && npm install --global --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && npm cache clean --force \
    && pi --version

COPY services/agents/entrypoint.sh /usr/local/bin/tokencrate-agent-entrypoint
COPY services/agents/agent-check.sh /usr/local/bin/tokencrate-agent-check
RUN chmod 0755 /usr/local/bin/tokencrate-agent-entrypoint /usr/local/bin/tokencrate-agent-check

ENTRYPOINT ["/usr/local/bin/tokencrate-agent-entrypoint"]
CMD ["pi"]


# oh-my-pi: the optional power-user agent (Bun runtime).
# hadolint ignore=DL3006
FROM docker.io/oven/bun:${BUN_TAG}@sha256:${BUN_DIGEST} AS omp

ARG OMP_VERSION
ARG BUN_TAG

LABEL org.opencontainers.image.title="TokenCrate oh-my-pi agent" \
      org.opencontainers.image.description="oh-my-pi coding agent pinned to one npm version, configured for a local llama-server endpoint" \
      io.tokencrate.omp-version="${OMP_VERSION}"

ENV PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1 \
    PI_OFFLINE=1 \
    BUN_INSTALL=/usr/local/bun \
    PATH=/usr/local/bun/bin:${PATH}

# The same assertion as the pi stage: the tag names what the digest pulls.
RUN test "$(bun --version)" = "${BUN_TAG%%-*}"

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        jq \
        less \
        procps \
        ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && bun install --global "@oh-my-pi/pi-coding-agent@${OMP_VERSION}" \
    && rm -rf /usr/local/bun/install/cache /root/.bun \
    && omp --version

COPY services/agents/entrypoint.sh /usr/local/bin/tokencrate-agent-entrypoint
COPY services/agents/agent-check.sh /usr/local/bin/tokencrate-agent-check
RUN chmod 0755 /usr/local/bin/tokencrate-agent-entrypoint /usr/local/bin/tokencrate-agent-check

ENTRYPOINT ["/usr/local/bin/tokencrate-agent-entrypoint"]
CMD ["omp"]
