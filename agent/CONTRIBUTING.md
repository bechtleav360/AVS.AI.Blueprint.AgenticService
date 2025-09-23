# Contributing to Asset Backup Checker

Thank you for your interest in contributing to the Asset Backup Checker microservice! This document provides guidelines and information for contributors.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Development Setup](#development-setup)
- [Code Style and Standards](#code-style-and-standards)
- [Chain of Responsibility Contract](#chain-of-responsibility-contract)
- [Event Handling Patterns](#event-handling-patterns)
- [Security and Observability](#security-and-observability)
- [Testing Guidelines](#testing-guidelines)
- [Pull Request Process](#pull-request-process)

## Architecture Overview

### Layering

The codebase follows a clean architecture with clear separation of concerns:

- **`api/`** - Transport layer (FastAPI routes, HTTP handling)
- **`agent/logic.py`** - Pure business logic (no side effects)
- **`agent/tools.py`** - Side-effecting operations (DNS, CMDB, cloud API calls)
- **`agent/runtime.py`** - Pydantic AI agent assembly and orchestration
- **`agent/decision.py`** - Chain of responsibility predicates and routing
- **`gateways/`** - External service clients (data gateway, etc.)
- **`models/`** - Data schemas and validation

### Key Principles

1. **Pure Functions**: Business logic in `agent/logic.py` must be pure (no side effects)
2. **Dependency Injection**: Use FastAPI's dependency system for service composition
3. **Observability First**: All operations must be traceable and monitorable
4. **Event-Driven**: Embrace asynchronous, event-driven patterns

## Development Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git

### Local Development

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd asset-backup-checker
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

2. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

3. **Set up environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run tests**:
   ```bash
   pytest
   ```

5. **Start services**:
   ```bash
   docker-compose up -d
   ```

6. **Run the application**:
   ```bash
   uvicorn src.app:app --reload --port 8000
   ```

## Code Style and Standards

### Formatting and Linting

We use the following tools (configured in `pyproject.toml`):

- **Black** (line length: 140) for code formatting
- **Ruff** for linting with common rules
- **isort** (black profile) for import sorting
- **MyPy** for basic type checking

### Style Guidelines

1. **Line Length**: Maximum 140 characters (pragmatic, not pedantic)
2. **Type Hints**: Use type hints for all public functions and class methods
3. **Docstrings**: Use Google-style docstrings for public APIs
4. **Error Handling**: Prefer specific exceptions over generic ones
5. **Logging**: Use structured logging with appropriate levels

### Example Code Style

```python
async def process_backup_check(
    asset: AssetMetadata,
    correlation_id: Optional[UUID] = None,
) -> AgentOutput:
    """
    Process backup check for an asset.
    
    Args:
        asset: Asset metadata to analyze
        correlation_id: Optional correlation ID for tracing
        
    Returns:
        Agent output with backup analysis results
        
    Raises:
        BackupCheckError: If the backup check fails
    """
    with tracer.start_as_current_span("process_backup_check") as span:
        span.set_attribute("asset_id", asset.id)
        
        try:
            # Implementation here
            pass
        except Exception as e:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Backup check failed for {asset.id}: {e}")
            raise
```

## Chain of Responsibility Contract

### Handler Requirements

All event handlers must follow these contracts:

1. **Cheap Evaluation**: Predicates must be fast to evaluate (< 10ms typically)
2. **Single Owner**: Only one handler may own the final action per event
3. **Fail Fast**: If not relevant, return `False` from `can_handle()` quickly
4. **Precedence**: Document handler precedence in priority values

### Handler Implementation

```python
class MyCustomHandler(EventHandler):
    def __init__(self):
        super().__init__("MyCustomHandler", priority=50)  # Lower = higher priority
    
    async def can_handle(self, envelope: EventEnvelope, asset: Optional[AssetMetadata] = None) -> bool:
        """Fast predicate check - must be < 10ms."""
        # Quick checks only - no expensive operations
        return envelope.event_type == EventType.ASSET_CREATED
    
    async def handle(self, envelope: EventEnvelope, asset: AssetMetadata) -> Optional[AgentOutput]:
        """Process the event or return None to pass to next handler."""
        # Actual processing logic here
        pass
```

### Handler Precedence

Current handler priorities (lower number = higher priority):

1. **IdempotencyHandler** (priority: 1) - Duplicate detection
2. **TenantHandler** (priority: 3) - Multi-tenancy filtering
3. **EventTypeHandler** (priority: 5) - Event type filtering
4. **RelevantAssetTypeHandler** (priority: 10) - Asset type filtering
5. **BackupIndicatorHandler** (priority: 20) - Backup relevance filtering
6. **BackupCheckHandler** (priority: 1000) - Actual processing

## Event Handling Patterns

### Thin vs Fat Events

#### Thin Events
- **Must** fetch via `gateways.data_gateway` - never bypass
- **Must** handle gateway failures gracefully (transient vs permanent)
- **Must** include `asset_id` in data payload
- **Should** include minimal summary data when possible

```python
# Thin event processing
if isinstance(event, EventEnvelopeThin):
    try:
        asset = await data_gateway.get_asset(event.get_asset_id())
    except DataGatewayError as e:
        if e.is_transient:
            # Retry logic or return error for reprocessing
            raise HTTPException(status_code=502, detail=str(e))
        else:
            # Permanent error - acknowledge and log
            logger.warning(f"Permanent error: {e}")
            return {"status": "acknowledged"}
```

#### Fat Events
- **Must** treat as immutable snapshot - never mutate
- **Must** never echo secrets in logs or results
- **Should** validate size limits (< 256KB recommended)

```python
# Fat event processing
if isinstance(event, EventEnvelopeFat):
    asset = event.get_asset()  # Direct extraction, no gateway call
    # Process immediately
```

### Idempotency

All handlers **must** check and set `event_id` in dedup store before acting:

```python
# Check idempotency
if event.event_id in processed_events:
    logger.info(f"Duplicate event: {event.event_id}")
    return None

# Mark as processed
processed_events[event.event_id] = datetime.utcnow()
```

## Security and Observability

### Security Requirements

1. **No Secrets in Logs**: Never log sensitive data (passwords, keys, tokens)
2. **No Secrets in Events**: Clean sensitive fields from fat events
3. **Input Validation**: Validate all external inputs
4. **Principle of Least Privilege**: Minimal required permissions

### Observability Requirements

1. **Tracing**: Include `asset_id` in all spans and logs
2. **Correlation**: Propagate `traceparent` and `correlation_id`
3. **Metrics**: Instrument key business operations
4. **Structured Logging**: Use structured logs with consistent fields

```python
# Good observability example
with tracer.start_as_current_span("backup_analysis") as span:
    span.set_attribute("asset_id", asset.id)
    span.set_attribute("asset_type", asset.type)
    
    logger.info(
        "Starting backup analysis",
        extra={
            "asset_id": asset.id,
            "correlation_id": correlation_id,
            "event_id": event_id,
        }
    )
```

### Sensitive Data Handling

```python
# Clean sensitive data from events
SENSITIVE_FIELDS = {"password", "secret", "key", "token", "credential"}

def clean_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive fields from data."""
    return {
        k: v for k, v in data.items()
        if not any(sensitive in k.lower() for sensitive in SENSITIVE_FIELDS)
    }
```

## Testing Guidelines

### Test Structure

- **Unit Tests**: `tests/unit/` - Test individual components in isolation
- **Integration Tests**: `tests/integration/` - Test component interactions
- **Mock External Dependencies**: Use mocks for external services

### Test Requirements

1. **Coverage**: Maintain > 80% code coverage
2. **Fast Execution**: Unit tests should run in < 30 seconds
3. **Deterministic**: Tests must be repeatable and not flaky
4. **Clear Names**: Test names should describe the scenario being tested

### Example Test

```python
@pytest.mark.asyncio
async def test_backup_check_with_enabled_tags():
    """Test backup checking when asset has explicit backup tags."""
    # Arrange
    asset = AssetMetadata(
        id="test-asset",
        name="Test DB",
        type=AssetType.DATABASE,
        provider=CloudProvider.AWS,
        tags={"backup": "enabled"}
    )
    
    # Act
    has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)
    
    # Assert
    assert has_backup is True
    assert confidence > 0.7
    assert any("backup enabled" in e.lower() for e in evidence)
```

## Pull Request Process

### Before Submitting

1. **Run Tests**: Ensure all tests pass locally
2. **Pre-commit Hooks**: Let pre-commit hooks fix formatting issues
3. **Update Documentation**: Update relevant documentation
4. **Add Tests**: Include tests for new functionality

### PR Requirements

1. **Clear Description**: Explain what changes and why
2. **Small Scope**: Keep PRs focused and reasonably sized
3. **Backward Compatibility**: Avoid breaking changes when possible
4. **Performance Impact**: Document any performance implications

### PR Template

```markdown
## Description
Brief description of changes and motivation.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No sensitive data exposed
```

### Review Process

1. **Automated Checks**: All CI checks must pass
2. **Code Review**: At least one approving review required
3. **Security Review**: Required for security-sensitive changes
4. **Architecture Review**: Required for significant architectural changes

## Questions and Support

- **Issues**: Use GitHub Issues for bug reports and feature requests
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Security**: Report security issues privately to the maintainers

Thank you for contributing to the Asset Backup Checker! 🚀
