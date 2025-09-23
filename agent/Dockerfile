# --- Builder Stage ---
FROM python:3.9-slim as builder

# Set environment variables for the build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory
WORKDIR /app

# Install dependencies (copy from repo root path)
COPY agent/requirements.txt /app/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r /app/requirements.txt


# --- Production Stage ---
FROM python:3.9-slim

# Set environment variables for production
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/app

# Create a non-root user
RUN addgroup --system app && adduser --system --group app

# Set the working directory
WORKDIR /home/app

# Copy dependencies from the builder stage
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install dependencies from the wheelhouse
RUN pip install --no-cache /wheels/*

# Copy the base framework and agent implementation (paths relative to repo root)
COPY base /home/app/base
COPY agent/src /home/app/agent/src

# Change ownership to the non-root user
RUN chown -R app:app /home/app

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 8000

# Run the application
CMD ["uvicorn", "agent.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
