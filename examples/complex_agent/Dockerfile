# --- Base Stage ---
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

# --- Builder Stage ---
FROM python:3.13-slim as builder

# Set environment variables for the build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory
WORKDIR /app

# Install build dependencies
RUN pip install --upgrade pip && pip install setuptools wheel build

# Copy pyproject.toml and install dependencies
COPY pyproject.toml /app/pyproject.toml
RUN pip install --target /app/deps -e .

# --- Production Stage ---
FROM base as production

# Copy installed dependencies from builder
COPY --from=builder /app/deps /usr/local/lib/python3.13/site-packages

# Copy application source code
COPY src /home/app/src

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
