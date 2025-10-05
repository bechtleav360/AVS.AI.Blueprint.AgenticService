# Dapr Components

This directory contains Dapr component configurations for the agent service.

## RabbitMQ PubSub Component

The RabbitMQ pubsub component is generated from a template at runtime to inject credentials from Dynaconf settings.

### Files:
- **`rabbitmq-pubsub.yaml.template`** - Template file with `$RABBITMQ_CONNECTION` placeholder (committed to git)
- **`rabbitmq-pubsub.yaml`** - Generated file with actual credentials (gitignored, auto-generated)

### Configuration Source:
- **Host**: `custom/settings.toml` → `rabbitmq_host`
- **Credentials**: `custom/secrets.toml` → `rabbitmq_username`, `rabbitmq_password`

### Generation Process:
1. `export_rabbitmq_env.sh` loads settings from Dynaconf
2. Exports `RABBITMQ_CONNECTION` environment variable
3. `envsubst` substitutes `$RABBITMQ_CONNECTION` in template
4. Generates `rabbitmq-pubsub.yaml` for Dapr to consume

### Usage:
The component is automatically generated when running:
- `./start_with_dapr.sh`
- VS Code launch configuration "Dapr: sidecar"

### Manual Generation:
```bash
cd custom
source export_rabbitmq_env.sh
envsubst < dapr/components/rabbitmq-pubsub.yaml.template > dapr/components/rabbitmq-pubsub.yaml
```
