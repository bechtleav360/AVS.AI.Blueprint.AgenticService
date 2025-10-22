#!/bin/bash

# Agent Blueprint Startup Script

set -e

echo "🚀 Starting Agent Blueprint..."

# Check if we're in the right directory
if [ ! -f "agent/src/main.py" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    exit 1
fi

# Set default environment variables
export APP_NAME="${APP_NAME:-agent-service}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export LOG_FORMAT="${LOG_FORMAT:-json}"
export APP_PORT="${APP_PORT:-8000}"
export AI_PROVIDER="${AI_PROVIDER:-openai}"
export AI_MODEL_NAME="${AI_MODEL_NAME:-gpt-4}"

echo "📋 Configuration:"
echo "   APP_NAME: $APP_NAME"
echo "   LOG_LEVEL: $LOG_LEVEL"
echo "   APP_PORT: $APP_PORT"
echo "   AI_PROVIDER: $AI_PROVIDER"
echo "   AI_MODEL_NAME: $AI_MODEL_NAME"

# Determine docker compose command (v1 or v2)
COMPOSE_CMD=""
if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
fi

# Use compose if available, otherwise fallback to Python
if [ -n "$COMPOSE_CMD" ]; then
    echo "🐳 Docker Compose detected (${COMPOSE_CMD}). Starting stack..."
    $COMPOSE_CMD up --build
elif command -v python &> /dev/null; then
    echo "🐍 Python detected. Running with uvicorn..."

    # Install dependencies if not already installed
    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        python -m venv venv
    fi

    # Activate virtual environment
    source venv/bin/activate

    # Install dependencies
    echo "📦 Installing dependencies..."
    pip install -r agent/requirements.txt

    # Run the application
    echo "🏃 Starting application..."
    uvicorn agent.src.main:app --host 0.0.0.0 --port $APP_PORT --reload
else
    echo "❌ Error: Neither Docker nor Python found"
    exit 1
fi
