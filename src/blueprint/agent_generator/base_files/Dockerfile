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

# A development default, and only in this stage: the production image bakes no group, so
# which agents it runs stays a deployment decision. This stage expects the project to be
# bind-mounted at /app, which is also where agents.toml is read from.
ENV BLUEPRINT_AGENTS="agent_namespace"

# src/main.py declares an agent; it does not build one, so there is no `src.main:app` to
# serve. The framework's factory resolves this process's group and returns the application,
# which is what lets uvicorn reload it -- reload needs an import string, not a built object.
# BLUEPRINT_AGENTS above is a development default; a deployment sets its own.
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "uvicorn", "blueprint.agents.entrypoint:create_group_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

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

# The agent map belongs to the image -- it lists the agents this image contains and where
# their declarations live. The group file does NOT: which of those agents a process runs is
# a deployment decision, so it arrives as a mount or as BLUEPRINT_AGENTS. See the ENTRYPOINT.
COPY --chown=appuser:appuser agents.toml ./

# The disk cache backend writes here, and it cannot create this itself: WORKDIR made /app
# root-owned, so mkdir() as appuser fails with EACCES. Created and handed over at build time,
# which is also the mount point to use under a read-only root filesystem -- see the
# "Writable cache directory" section of docs/guides/deployment.md.
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache

# Note: secrets.toml is NOT copied into the image.
# Mount it at runtime via Docker secrets or volume mount.
# Example (Docker Swarm):
#   docker run --secret secrets_file_id \
#     -e DYNACONF_SETTINGS=/run/secrets/secrets_file_id \
#     pir-agent:latest
# Example (Volume mount):
#   docker run -v ./secrets.toml:/app/secrets.toml:ro pir-agent:latest

ENV PYTHONPATH="/app/src" \
    DYNACONF_ENVIRONMENT="production" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# One command for every deployment. Which agents this process hosts is injected at container
# start, never baked in, so regrouping is a Deployment edit rather than a rebuild:
#
#   docker run -e BLUEPRINT_AGENTS=agent_namespace <image>
#   docker run -v ./deployment-groups.yaml:/app/deployment-groups.yaml:ro \n#              -e BLUEPRINT_GROUP=<group> <image>
#
# With neither, the process stops before binding the port and says which of the two is
# missing -- a crash-loop with a readable message rather than a pod that passes its probes
# while a queue goes unconsumed.
ENTRYPOINT ["python", "-m", "blueprint.agents.entrypoint"]
