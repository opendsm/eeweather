# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12-slim AS app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# uv (fast installer) from the digest-pinned stage above
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# deps layer (cacheable): resolve and install dependencies only
COPY pyproject.toml README.md LICENSE /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml --extra dev -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

COPY eeweather/ /app/eeweather
RUN uv pip install --system --no-deps -e /app

# Run as an unprivileged user whose UID matches the host user that bind-mounts the
# repository, so files written into the mount stay writable on both sides
ARG UID=1000
RUN useradd --uid ${UID} --create-home --shell /bin/sh app
ENV UV_CACHE_DIR=/home/app/.cache/uv
USER app
