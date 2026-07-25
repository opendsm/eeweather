# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# uv (fast installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
