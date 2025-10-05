#!/bin/bash
# Start the agent service with Dapr and RabbitMQ

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Agent Blueprint with Dapr...${NC}"

# Check if port-forward is running
if ! pgrep -f "port-forward.*rabbitmq" > /dev/null; then
    echo -e "${YELLOW}Warning: RabbitMQ port-forward not detected${NC}"
    echo "Start it with: kubectl port-forward -n dev-bios-bechtle svc/rabbitmq 5672:5672 15672:15672"
    echo ""
fi

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Set PYTHONPATH to include project root so base module can be imported
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
echo -e "${GREEN}PYTHONPATH set to: $PYTHONPATH${NC}"

# Change to custom directory
cd "$SCRIPT_DIR"

# Load RabbitMQ configuration from Dynaconf
source "$SCRIPT_DIR/export_rabbitmq_env.sh"
echo -e "${GREEN}Loaded RabbitMQ configuration from settings/secrets.toml${NC}"

# Generate Dapr component from template
envsubst < "$SCRIPT_DIR/dapr/components/rabbitmq-pubsub.yaml.template" > "$SCRIPT_DIR/dapr/components/rabbitmq-pubsub.yaml"
echo -e "${GREEN}Generated Dapr component configuration${NC}"

# Start with Dapr
echo -e "${GREEN}Starting Dapr sidecar and application...${NC}"
dapr run \
    --app-id agent_blueprint \
    --app-port 8001 \
    --dapr-http-port 3500 \
    --dapr-grpc-port 50001 \
    --resources-path ./dapr/components \
    --log-level info \
    -- "$SCRIPT_DIR/.venv/bin/python" -m uvicorn src.main:app --host 0.0.0.0 --port 8001
