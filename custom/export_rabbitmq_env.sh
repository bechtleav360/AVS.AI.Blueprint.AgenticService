#!/bin/bash
# Export RabbitMQ configuration from Dynaconf settings/secrets
# This script is meant to be sourced: source export_rabbitmq_env.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export DYNACONF_APP_ENVIRONMENT="${DYNACONF_APP_ENVIRONMENT:-development}"

# Load settings using Python
RABBITMQ_HOST=$(python3 -c 'from dynaconf import Dynaconf; settings = Dynaconf(settings_files=["settings.toml", "secrets.toml"], environments=True); print(settings.RABBITMQ_HOST)')
RABBITMQ_VHOST=$(python3 -c 'from dynaconf import Dynaconf; settings = Dynaconf(settings_files=["settings.toml", "secrets.toml"], environments=True); print(settings.RABBITMQ_VHOST)')
RABBITMQ_USERNAME=$(python3 -c 'from dynaconf import Dynaconf; settings = Dynaconf(settings_files=["settings.toml", "secrets.toml"], environments=True); print(settings.RABBITMQ_USERNAME)')
RABBITMQ_PASSWORD=$(python3 -c 'from dynaconf import Dynaconf; settings = Dynaconf(settings_files=["settings.toml", "secrets.toml"], environments=True); print(settings.RABBITMQ_PASSWORD)')

# Build connection string
export RABBITMQ_HOST
export RABBITMQ_VHOST
export RABBITMQ_USERNAME
export RABBITMQ_PASSWORD
export RABBITMQ_CONNECTION="amqp://${RABBITMQ_USERNAME}:${RABBITMQ_PASSWORD}@${RABBITMQ_HOST}/${RABBITMQ_VHOST}"
