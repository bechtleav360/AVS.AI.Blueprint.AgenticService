# --- Base Stage (Reusable by all agents) ---
FROM python:3.13-slim as base

# Set environment variables for production
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/app

# Create a non-root user
RUN addgroup --system app && adduser --system --group --home /home/app app

# Set the working directory
WORKDIR /home/app

# Change ownership to the non-root user
RUN chown -R app:app /home/app

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 8000

# --- Builder Stage (Reusable wheel builder) ---
FROM python:3.13-slim as builder

# Set environment variables for the build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory
WORKDIR /app

# Install build dependencies
RUN pip install --upgrade pip && pip install setuptools wheel build

# Copy pyproject.toml and build the wheel
COPY custom/pyproject.toml /app/pyproject.toml
COPY custom/src /app/src
RUN python -m build --wheel --no-isolation

# --- Production Stage (Agent-specific) ---
FROM base as production

# Copy and install the wheel
COPY --from=builder /app/dist/*.whl /tmp/
USER root
RUN pip install --no-cache /tmp/*.whl
USER app

# Copy the base framework (shared across all agents)
COPY base /home/app/base

# Copy agent-specific implementation
# This should be overridden in agent-specific Dockerfiles
COPY custom/src /home/app/src

# Run the application
# This should be overridden in agent-specific Dockerfiles
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
