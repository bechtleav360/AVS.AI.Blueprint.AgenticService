# Makefile for Asset Backup Checker

.PHONY: help install install-dev test test-unit test-integration lint format clean build run docker-build docker-run docker-compose-up docker-compose-down pre-commit

# Default target
help: ## Show this help message
	@echo "Asset Backup Checker - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Installation
install: ## Install production dependencies
	pip install -e .

install-dev: ## Install development dependencies
	pip install -e ".[dev]"
	pre-commit install

# Testing
test: ## Run all tests
	pytest

test-unit: ## Run unit tests only
	pytest tests/unit/ -v

test-integration: ## Run integration tests only
	pytest tests/integration/ -v

test-coverage: ## Run tests with coverage report
	pytest --cov=src --cov-report=html --cov-report=term-missing

# Code Quality
lint: ## Run linting checks
	ruff check src/ tests/
	black --check --line-length 140 src/ tests/
	isort --check-only --profile black --line-length 140 src/ tests/
	mypy src/ --ignore-missing-imports --no-strict-optional

format: ## Format code
	black --line-length 140 src/ tests/
	isort --profile black --line-length 140 src/ tests/
	ruff check --fix src/ tests/

security-scan: ## Run security scans
	bandit -r src/ -f json -o bandit-report.json
	safety check --json --output safety-report.json || true

pre-commit: ## Run pre-commit hooks on all files
	pre-commit run --all-files

# Development
clean: ## Clean up build artifacts and cache
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

run: ## Run the application locally
	uvicorn src.app:app --reload --port 8000

run-prod: ## Run the application in production mode
	uvicorn src.app:app --host 0.0.0.0 --port 8000

# Docker
docker-build: ## Build Docker image
	docker build -t asset-backup-checker:latest .

docker-run: ## Run Docker container
	docker run -p 8000:8000 --env-file .env asset-backup-checker:latest

docker-compose-up: ## Start all services with Docker Compose
	docker-compose up -d

docker-compose-down: ## Stop all services
	docker-compose down

docker-compose-logs: ## View Docker Compose logs
	docker-compose logs -f

# Development with Dapr
dapr-run: ## Run with Dapr sidecar
	dapr run --app-id asset-backup-checker --app-port 8000 --dapr-http-port 3500 --components-path ../common/dapr/components --config ../common/.dapr/config.yaml -- uvicorn src.app:app --port 8000

dapr-stop: ## Stop Dapr sidecar
	dapr stop --app-id asset-backup-checker

# Database and Infrastructure
setup-rabbitmq: ## Start RabbitMQ for local development
	docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management

setup-redis: ## Start Redis for local development
	docker run -d --name redis -p 6379:6379 redis:7-alpine

setup-jaeger: ## Start Jaeger for local development
	docker run -d --name jaeger -p 16686:16686 -p 14268:14268 -p 4317:4317 -p 4318:4318 -e COLLECTOR_OTLP_ENABLED=true jaegertracing/all-in-one:1.50

setup-dev-env: setup-rabbitmq setup-redis setup-jaeger ## Set up complete development environment

teardown-dev-env: ## Tear down development environment
	docker stop rabbitmq redis jaeger || true
	docker rm rabbitmq redis jaeger || true

# CI/CD
ci-lint: ## CI linting (strict)
	ruff check src/ tests/ --output-format=github
	black --check --line-length 140 src/ tests/
	isort --check-only --profile black --line-length 140 src/ tests/
	mypy src/ --ignore-missing-imports --no-strict-optional

ci-test: ## CI testing with coverage
	pytest tests/ -v --junitxml=junit/test-results.xml --cov=src --cov-report=xml --cov-report=html

ci-security: ## CI security scanning
	bandit -r src/ -f json -o bandit-report.json
	safety check --json --output safety-report.json

ci-build: ## CI Docker build
	docker build -t asset-backup-checker:$(shell git rev-parse --short HEAD) .
	docker tag asset-backup-checker:$(shell git rev-parse --short HEAD) asset-backup-checker:latest

# Documentation
docs-serve: ## Serve documentation locally
	mkdocs serve

docs-build: ## Build documentation
	mkdocs build

# Utilities
check-env: ## Check environment configuration
	python -c "from src.config import validate_configuration; validate_configuration(); print('✅ Configuration is valid')"

health-check: ## Check application health
	curl -f http://localhost:8000/actuators/health || echo "❌ Health check failed"

version: ## Show version information
	python -c "import src; print(f'Asset Backup Checker v0.1.0')"

# Development helpers
shell: ## Start Python shell with app context
	python -c "from src.app import app; from src.config import settings; print('App and settings loaded'); import IPython; IPython.start_ipython()"

logs: ## View application logs (if running with docker-compose)
	docker-compose logs -f asset-backup-checker

restart: ## Restart the application (docker-compose)
	docker-compose restart asset-backup-checker

# Performance testing
load-test: ## Run basic load test (requires hey or similar tool)
	hey -n 100 -c 10 http://localhost:8000/actuators/health

# Backup and restore (for development data)
backup-dev-data: ## Backup development data
	mkdir -p backups
	docker-compose exec rabbitmq rabbitmqctl export_definitions /tmp/rabbitmq-definitions.json
	docker cp $$(docker-compose ps -q rabbitmq):/tmp/rabbitmq-definitions.json backups/

restore-dev-data: ## Restore development data
	docker cp backups/rabbitmq-definitions.json $$(docker-compose ps -q rabbitmq):/tmp/
	docker-compose exec rabbitmq rabbitmqctl import_definitions /tmp/rabbitmq-definitions.json
