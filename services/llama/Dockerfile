ARG LLAMA_CPP_TAG
ARG LLAMA_CPP_DIGEST

# The base image tag and its manifest digest are required build arguments
# (pins.env). The tag names an exact llama.cpp build, the digest is what
# the build pulls; the official server image runs llama-server.
# hadolint ignore=DL3006
FROM ghcr.io/ggml-org/llama.cpp:${LLAMA_CPP_TAG}@sha256:${LLAMA_CPP_DIGEST} AS runtime

ARG LLAMA_CPP_TAG

LABEL org.opencontainers.image.title="TokenCrate llama runtime" \
      org.opencontainers.image.description="llama-server in router mode from a pinned upstream image, prepared for CDI devices and a read-only root filesystem" \
      io.tokencrate.base-image="ghcr.io/ggml-org/llama.cpp:${LLAMA_CPP_TAG}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The upstream CUDA image ships forward-compatibility driver libraries under
# /usr/local/cuda*/compat. Under CDI the host driver is injected instead, and
# the bundled libcuda breaks CUDA initialization on newer host drivers
# (ggml-org/llama.cpp issue 23111). The runtime root filesystem is read-only,
# so the directory is removed here, once, and the build asserts it is gone.
# The build also asserts that the pulled tag still carries the llama.cpp
# build number (-b<N>) named by the pin.
RUN rm -rf /usr/local/cuda*/compat \
    && ldconfig \
    && test ! -e /usr/local/cuda/compat \
    && /app/llama-server --version 2>&1 | grep -E "build ${LLAMA_CPP_TAG##*-b}([^0-9]|$)"

# Router mode: llama-server starts without a model, reads the preset file the
# wrapper renders and mounts at the path below, and spawns one child server
# per requested model (at most one loaded at a time). The runtime user is set
# by compose.yaml; every writable path lives on tmpfs or a host mount.
ENTRYPOINT ["/app/llama-server", "--host", "0.0.0.0", "--port", "8080", \
            "--models-preset", "/etc/tokencrate/models.ini", "--models-max", "1", \
            "--ui-config-file", "/etc/tokencrate/ui-config.json"]
