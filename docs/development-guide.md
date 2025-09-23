# Development Guide

This guide provides everything you need to set up your development environment, understand coding standards, and follow best practices for contributing to the Agents Blueprint.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Git
- Make (optional, for convenience commands)

### Environment Setup

0. **Import the blueprint**
   Since you are already in the repository, you can skip this step.

   If not (you are checking another repository): 
    ...
    
1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/Agents_Blueprint.git
   cd Agents_Blueprint
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set up pre-commit hooks**
   ```bash
   pre-commit install
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

## 🛠️ Development Tools

### Code Quality
- **Black**: Code formatting (140 character line length)
- **Ruff**: Fast Python linter
- **isort**: Import sorting
- **MyPy**: Static type checking
- **Bandit**: Security scanning

### Testing
- **pytest**: Testing framework
- **pytest-asyncio**: Async testing support
- **pytest-mock**: Mocking utilities
- **pytest-cov**: Coverage reporting

### Development Commands
```bash
# Run all tests
make test

# Run specific test types
make test-unit
make test-integration

# Code quality checks
make lint
make format

# Security scanning
make security-scan

# Development server
make run
```

## 📝 Coding Standards

### Python Style
- Follow **PEP 8** with Black formatting
- Use **type hints** for all public functions
- Maximum line length: **140 characters**
- Use **Google-style docstrings**

### Example Function
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

## 🧪 Testing Guidelines

### Test Structure
- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **Mock External Dependencies**: Use mocks for external services

### Test Requirements
- **Coverage**: Maintain > 80% code coverage
- **Deterministic**: Tests must be repeatable
- **Fast**: Unit tests should run in < 30 seconds
- **Clear Names**: Test names should describe scenarios

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
    result = await backup_agent.run_check(asset)

    # Assert
    assert result.backup_status == BackupStatus.ENABLED
    assert result.confidence > 0.7
```

## 🔒 Security Practices

### Code Security
- **No secrets in code**: Use environment variables or secret management
- **Input validation**: Validate all external inputs
- **SQL injection prevention**: Use parameterized queries
- **XSS protection**: Sanitize output data

### Dependency Security
```bash
# Check for vulnerabilities
pip install safety
safety check

# Update dependencies regularly
pip list --outdated
pip install --upgrade <package>
```

## 🐛 Debugging

### Common Development Issues
1. **Port conflicts**: Check if ports 8000, 5672, 15672 are available
2. **Environment variables**: Ensure `.env` file is properly configured
3. **Dependencies**: Run `pip install -e ".[dev]"` to install all dependencies
4. **Pre-commit hooks**: Run `pre-commit run --all-files` to fix formatting issues

### Debug Commands
```bash
# Run with debug logging
ENV_FOR_DYNACONF=development LOG_LEVEL=DEBUG make run

# Run tests with verbose output
pytest -v -s tests/

# Check environment configuration
python -c "from src.config import validate_configuration; validate_configuration()"
```

## 🤝 Contributing Workflow

### Before Starting Work
1. **Create an issue** or get assigned to an existing one
2. **Check out a feature branch**: `git checkout -b feature/your-feature`
3. **Set up your environment** following the steps above

### Development Process
1. **Make changes** following coding standards
2. **Write tests** for new functionality
3. **Run tests** to ensure nothing is broken
4. **Update documentation** if needed
5. **Commit changes** with clear messages

### Before Submitting PR
1. **Run all tests**: `make test`
2. **Check code quality**: `make lint`
3. **Fix any issues**: `make format`
4. **Update documentation** if changes affect user-facing features
5. **Test manually** if needed

## 📚 Additional Resources

### Architecture Documentation
- **[Design Decisions](../docs/design-decisions.md)** - Why we made specific choices
- **[Requirements](../docs/requirements.md)** - Functional and non-functional requirements
- **[Architecture](../docs/architecture.md)** - System design and components

### Best Practices
- **[Chain of Responsibility Pattern](../CONTRIBUTING.md#chain-of-responsibility-contract)** - Event handling patterns
- **[Event Design](../CONTRIBUTING.md#event-handling-patterns)** - Thin vs fat events
- **[Observability](../CONTRIBUTING.md#security-and-observability)** - Logging and tracing

### External References
- **[FastAPI Documentation](https://fastapi.tiangolo.com/)** - Web framework documentation
- **[Pydantic AI](https://ai.pydantic.dev/)** - AI agent framework
- **[Dapr Documentation](https://docs.dapr.io/)** - Distributed systems framework

---

*This development guide is maintained by the development team. For questions or suggestions, please refer to the [Contributing Guide](../CONTRIBUTING.md).*
