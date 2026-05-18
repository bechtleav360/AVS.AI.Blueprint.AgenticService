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

CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

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

ENTRYPOINT ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
