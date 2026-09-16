# syntax=docker/dockerfile:1.7

# ============================================================================
# Builder - Install dependencies
# ============================================================================
FROM python:3.13-bookworm AS builder

RUN pip install --no-cache-dir --upgrade pip uv

WORKDIR /app

# Layer 1: Copy dependency manifests and install dependencies
# This layer caches if only code changes, not deps
COPY pyproject.toml README.md ./

RUN uv pip install --system --no-cache \
    --upgrade pip setuptools wheel && \
    uv pip install --system --no-cache .

# Layer 2: Copy application code
# This layer rebuilds if code changes, but reuses dependency cache above
COPY src ./src

# ============================================================================
# Development - Include dev tools and tests
# ============================================================================
FROM builder AS dev

RUN uv pip install --system --no-cache ".[dev]" ipython debugpy pytest

ENV PYTHONPATH="/app/src"
ENV DYNACONF_ENVIRONMENT="development"

# src/main.py declares an agent; it does not build one, so there is no `src.main:app` to
# serve. create_app() builds the declaration with this directory's settings, and uvicorn
# reloads it because a factory is an import string rather than a built object.
#
# Nothing group-related here either: this stage expects the project bind-mounted at /app and
# serves the one agent it contains.
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "uvicorn", "src.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================================================
# Production - Minimal runtime image
# ============================================================================
FROM python:3.13-slim-bookworm AS final

RUN pip install --no-cache-dir --upgrade pip

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    jq \
    curl \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy Python packages and binaries from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code and settings
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser settings.toml ./

# No agent map, and no group. This image contains one agent and serves it directly through
# its own create_app() factory -- a standalone agent defines nothing group-related, because
# a group of one is a group, and an agent must not have to declare itself one to run alone.
#
# The same directory is hosted by a group image without changing a line: that image's
# agents.toml names this module and builds the same declaration under the agent's namespace,
# which is where the routes gain their /api/<agent> prefix.

# The disk cache backend writes here, and it cannot create this itself: WORKDIR made /app
# root-owned, so mkdir() as appuser fails with EACCES. Created and handed over at build time,
# which is also the mount point to use under a read-only root filesystem -- see the
# "Writable cache directory" section of docs/guides/deployment.md.
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache

# Note: .secrets.toml is NOT copied into the image. Mount it at runtime, at that exact path --
# the entry point loads ["settings.toml", ".secrets.toml"] relative to the working directory, so
# a file mounted under any other name is loaded by nothing and reports nothing.
# Example (volume mount):
#   docker run -v ./.secrets.toml:/app/.secrets.toml:ro <image>
# Example (Docker secret, which lands under /run/secrets):
#   docker run --secret source=agent_secrets,target=/app/.secrets.toml <image>
# An individual key can also be supplied as an environment variable instead, with no file at
# all:  -e DYNACONF_MODEL_API_KEY=...

ENV PYTHONPATH="/app/src" \
    DYNACONF_ENVIRONMENT="production" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# This image contains one agent and serves it. There is no group to choose at container
# start, no agent map to read and no BLUEPRINT_* variable to set:
#
#   docker run -p 8000:8000 <image>
#
# Its components are built at the root namespace, so the routes are the ones the API
# declares. Hosted in a group image instead, the same directory gains an /api/<agent>
# prefix -- that identity change happens once, on the first grouped deploy, and is what
# the migration guide covers. Nothing in this directory changes to make it.
ENTRYPOINT ["python", "-m", "uvicorn", "src.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
