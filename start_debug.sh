#!/bin/bash
# Start the agent with Dapr for debugging with RabbitMQ

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Starting Harmonizing Agent with Dapr + RabbitMQ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Change to custom directory
cd "$SCRIPT_DIR/custom"

echo -e "${GREEN}📋 Configuration:${NC}"
echo "   App ID: harmonizing-agent"
echo "   App Port: 8001"
echo "   Dapr HTTP Port: 3500"
echo "   Dapr GRPC Port: 50001"
echo "   Components: $SCRIPT_DIR/custom/dapr"
echo ""

echo -e "${YELLOW}🔧 Prerequisites:${NC}"
echo "   1. RabbitMQ should be running (docker-compose up -d rabbitmq)"
echo "   2. Redis should be running (docker-compose up -d redis)"
echo "   3. Placement should be running (docker-compose up -d placement)"
echo ""

echo -e "${GREEN}🚀 Starting Dapr + App...${NC}"
echo ""

# Start with Dapr
dapr run \
    --app-id harmonizing-agent \
    --app-port 8001 \
    --dapr-http-port 3500 \
    --dapr-grpc-port 50001 \
    --resources-path "$SCRIPT_DIR/custom/dapr" \
    --log-level debug \
    -- uv run uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
