# syntax=docker/dockerfile:1.7

# ============================================================================
# Builder - Install dependencies
# ============================================================================
FROM python:3.14-bookworm AS builder

ARG pypifeed

RUN pip install --no-cache-dir --upgrade pip uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN --mount=type=secret,id=pat \
    export UV_INDEX_AVS_PASSWORD="$(cat /run/secrets/pat)" && \
    export PIP_EXTRA_INDEX_URL="${pypifeed}" && \
    uv pip install --system --no-cache \
    --upgrade pip setuptools wheel && \
    uv pip install --system --no-cache .

# ============================================================================
# Development - Include dev tools and tests
# ============================================================================
FROM builder AS dev

ARG pypifeed

RUN --mount=type=secret,id=pat \
    export UV_INDEX_AVS_PASSWORD="$(cat /run/secrets/pat)" && \
    export PIP_EXTRA_INDEX_URL="${pypifeed}" && \
    uv pip install --system --no-cache ".[dev]" && \
    uv pip install --system --no-cache ipython debugpy pytest

COPY tests ./tests
COPY pytest.ini ./

ENV PYTHONPATH="/app/src"
ENV DYNACONF_ENVIRONMENT="development"

CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================================================
# Production - Minimal runtime image
# ============================================================================
FROM python:3.14-slim AS final

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

# Copy Python packages and binaries using wildcard
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser settings.toml ./

ENV PYTHONPATH="/app/src" \
    DYNACONF_ENVIRONMENT="production" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
