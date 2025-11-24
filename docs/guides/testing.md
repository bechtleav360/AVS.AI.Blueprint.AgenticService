# Testing Guide

This guide outlines the testing strategies, methodologies, and best practices for the Agents Blueprint project.

## 🎯 Testing Philosophy

Our testing approach follows these principles:
- **Comprehensive Coverage**: Test all critical paths and edge cases
- **Fast Feedback**: Unit tests should run in seconds, not minutes
- **Realistic Scenarios**: Integration tests mirror production conditions
- **Maintainable Tests**: Tests should be easy to understand and modify

## 🧪 Test Categories

### Unit Tests
- **Scope**: Individual functions, classes, and modules
- **Location**: `tests/unit/`
- **Coverage**: > 90% target for core business logic
- **Execution Time**: < 30 seconds total

### Integration Tests
- **Scope**: Component interactions and external dependencies
- **Location**: `tests/integration/`
- **Coverage**: Critical integration points
- **Execution Time**: < 2 minutes total

### End-to-End Tests (Future)
- **Scope**: Complete user workflows
- **Location**: `tests/e2e/`
- **Coverage**: Happy path and error scenarios
- **Execution Time**: < 5 minutes total

## 🛠️ Testing Tools

### Core Framework
- **pytest**: Primary testing framework
- **pytest-asyncio**: Async function testing
- **pytest-mock**: Mocking utilities
- **pytest-cov**: Coverage reporting

### Additional Tools
- **httpx**: HTTP client mocking
- **respx**: Advanced HTTP mocking
- **freezegun**: Time manipulation
- **faker**: Test data generation

## 📝 Test Structure

### Test File Organization
```
tests/
├── unit/                    # Unit tests
│   ├── test_logic.py       # Business logic tests
│   ├── test_decision.py    # Decision engine tests
│   ├── test_models.py      # Data model tests
│   └── test_tools.py       # External tool tests
└── integration/            # Integration tests
    ├── test_pubsub_flow.py # Event processing tests
    └── test_gateway.py     # External service tests
```

### Test Function Naming
```python
# Good naming examples
def test_backup_check_with_enabled_tags():
def test_thin_event_processing_success():
def test_gateway_error_handling_transient():
def test_idempotency_duplicate_events():

# Avoid generic names
def test_process():
def test_handle():
def test_check():
```

## 🧪 Writing Effective Tests

### Unit Test Example
```python
@pytest.mark.asyncio
async def test_score_backup_with_explicit_tags():
    """Test backup scoring when asset has explicit backup tags."""
    # Arrange
    asset = AssetMetadata(
        id="test-db",
        name="Test Database",
        type=AssetType.DATABASE,
        provider=CloudProvider.AWS,
        tags={"backup": "enabled", "backup-schedule": "daily"}
    )

    # Act
    has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)

    # Assert
    assert has_backup is True
    assert confidence > 0.8
    assert any("backup enabled" in e.lower() for e in evidence)
```

### Integration Test Example
```python
@pytest.mark.asyncio
async def test_event_processing_success():
    """Test complete event processing flow."""
    # Arrange
    event = create_event(EventType.ASSET_CREATED, "test-asset-1")

    with patch('blueprint.agents.services.processing_service.ProcessingService.process_event') as mock_process:
        # Configure mocks
        mock_process.return_value = {"status": "processed", "event_id": "test-event-1"}

        # Act
        response = client.post("/events", json=event.dict())

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "processed"
        mock_process.assert_called_once()
```

## 🔄 Test Data Management

### Factories and Fixtures
```python
@pytest.fixture
def sample_asset():
    """Create a sample asset for testing."""
    return AssetMetadata(
        id="test-asset-1",
        name="Test Database",
        type=AssetType.DATABASE,
        provider=CloudProvider.AWS,
        tags={"backup": "enabled"},
        uris=["s3://backup-bucket/db-backups/"]
    )

@pytest.fixture
def thin_event(sample_asset):
    """Create a thin event for testing."""
    return create_thin_event(
        EventType.ASSET_CREATED,
        sample_asset.id,
        asset_url=f"http://gateway/assets/{sample_asset.id}"
    )
```

### Test Data Generation
```python
def generate_test_asset(asset_type: AssetType = None) -> AssetMetadata:
    """Generate test asset with random but realistic data."""
    asset_type = asset_type or random.choice(list(AssetType))

    return AssetMetadata(
        id=f"test-{asset_type.value}-{uuid4().hex[:8]}",
        name=f"Test {asset_type.value.replace('_', ' ').title()}",
        type=asset_type,
        provider=random.choice(list(CloudProvider)),
        tags={"environment": random.choice(["dev", "staging", "prod"])},
        uris=[f"https://example.com/{asset_type.value}/"]
    )
```

## 🐛 Mocking Strategies

### HTTP Client Mocking
```python
# Mock external HTTP calls
with patch('httpx.AsyncClient.get') as mock_get:
    mock_response = httpx.Response(200, json={"status": "healthy"})
    mock_get.return_value = mock_response

    # Test code that makes HTTP calls
    result = await some_function()
```

### External Service Mocking
```python
# Mock external service calls
with patch('blueprint.agents.services.processing_service.ProcessingService.process_event') as mock_process:
    mock_process.return_value = {"status": "processed", "result": "success"}

    # Test code that uses the processing service
    result = await event_processor.process_event(test_event)
```

### Time-Based Mocking
```python
# Mock time for consistent test results
with freeze_time("2024-01-15 10:00:00"):
    result = await time_sensitive_function()
    assert result.created_at == datetime(2024, 1, 15, 10, 0, 0)
```

## 📊 Coverage Requirements

### Target Coverage Levels
- **Overall**: > 85% code coverage
- **Core Logic**: > 95% coverage
- **API Layer**: > 90% coverage
- **Models**: > 98% coverage
- **Error Handling**: > 95% coverage

### Coverage Exclusions
```python
# Exclude certain files from coverage
[tool.coverage.run]
omit = [
    "*/tests/*",
    "*/venv/*",
    "*/__init__.py",
    "src/main.py",  # Entry point
]
```

## 🚀 Running Tests

### Basic Commands
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/test_logic.py

# Run specific test function
pytest tests/unit/test_logic.py::test_score_backup_with_enabled_tags -v

# Run tests with coverage
pytest --cov=src --cov-report=html --cov-report=term-missing
```

### CI/CD Integration
```bash
# Run tests like CI would
pytest --cov=src --cov-report=xml --cov-report=html --junitxml=junit/test-results.xml

# Fail on low coverage
pytest --cov=src --cov-fail-under=85
```

## 🐛 Debugging Tests

### Common Issues
1. **Async Tests**: Remember to use `@pytest.mark.asyncio`
2. **Mock Assertions**: Verify mocks are called as expected
3. **Test Isolation**: Ensure tests don't depend on each other
4. **Random Data**: Use fixed seeds for reproducible tests

### Debug Commands
```bash
# Run test with detailed output
pytest -v -s tests/unit/test_logic.py::test_specific_function

# Run test with debugger
pytest --pdb tests/unit/test_logic.py::test_specific_function

# Show local variables on failure
pytest -v --tb=short tests/unit/test_logic.py
```

## 📈 Performance Testing

### Load Testing Setup
```python
# Example load test using locust
class BackupCheckLoadTest(HttpUser):
    @task
    def check_backup(self):
        asset_data = {
            "id": f"load-test-{self.user_id}",
            "name": "Load Test Asset",
            "type": "database",
            "provider": "aws",
            "tags": {"backup": "enabled"}
        }

        self.client.post("/check-backup", json={"asset": asset_data})
```

### Performance Benchmarks
```python
# Benchmark critical functions
@pytest.mark.benchmark
def test_backup_logic_performance(benchmark):
    asset = generate_test_asset()

    result = benchmark(BackupLogic.score_cloud_backup, asset)
    has_backup, confidence, evidence = result

    assert has_backup is True
    assert confidence > 0.5
```

## 🔄 Continuous Testing

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: Run Unit Tests
        entry: pytest tests/unit/
        language: system
        pass_filenames: false
```

### GitHub Actions
```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - run: pip install -e ".[dev]"
    - run: pytest --cov=src --cov-report=xml
    - uses: codecov/codecov-action@v3
```

## 📋 Test Checklist

### Before Submitting Code
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Coverage meets requirements
- [ ] No new code smells
- [ ] Tests run in reasonable time

### Before Releasing
- [ ] All tests pass in CI
- [ ] Performance tests run successfully
- [ ] Load tests meet requirements
- [ ] Edge cases are covered

## 🤝 Contributing Tests

### Guidelines for New Tests
1. **Follow naming conventions** for test functions and files
2. **Use descriptive docstrings** explaining test scenarios
3. **Include edge cases** and error conditions
4. **Mock external dependencies** appropriately
5. **Keep tests focused** on single behaviors

### Review Checklist
- [ ] Test covers the intended functionality
- [ ] Test is readable and well-documented
- [ ] Test follows project conventions
- [ ] Test doesn't duplicate existing coverage
- [ ] Test runs efficiently

---

*This testing guide is maintained by the QA team. For questions or suggestions, please refer to the [Development Guide](development-guide.md).*
