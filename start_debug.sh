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
echo ""

# Check if RabbitMQ is accessible
echo -e "${YELLOW}🔍 Checking RabbitMQ connection...${NC}"
if ! nc -z localhost 5672 2>/dev/null; then
    echo -e "${YELLOW}⚠️  RabbitMQ is not accessible on localhost:5672${NC}"
    echo -e "${YELLOW}   Waiting for RabbitMQ to start...${NC}"
    for i in {1..10}; do
        sleep 1
        if nc -z localhost 5672 2>/dev/null; then
            echo -e "${GREEN}✅ RabbitMQ is ready${NC}"
            break
        fi
        if [ $i -eq 10 ]; then
            echo -e "${YELLOW}⚠️  RabbitMQ still not ready after 10 seconds${NC}"
            echo -e "${YELLOW}   Starting anyway, Dapr will retry connection${NC}"
        fi
    done
else
    echo -e "${GREEN}✅ RabbitMQ is ready${NC}"
fi
echo ""

echo -e "${GREEN}🚀 Starting Dapr + App...${NC}"
echo ""

# Start with Dapr
# Note: Disabling placement and scheduler (not needed for pub/sub messaging)
dapr run \
    --app-id harmonizing-agent \
    --app-port 8001 \
    --dapr-http-port 3500 \
    --dapr-grpc-port 50001 \
    --resources-path "$SCRIPT_DIR/custom/dapr" \
    --config "$SCRIPT_DIR/custom/dapr/config.yaml" \
    --placement-host-address "" \
    --scheduler-host-address "" \
    --log-level info \
    -- uv run uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
