"""Unit tests for AppBuilder health checker integration."""

from pathlib import Path

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from blueprint.agents.models.api import ComponentHealth


class MockHealthChecker:
    """Mock health checker for testing."""

    async def health_check(self) -> ComponentHealth:
        """Return a mock health check result."""
        return ComponentHealth(status="UP", message="Mock checker OK")


@pytest.fixture
def config() -> Config:
    """Create a test config."""
    return Config(
        settings_files=[],
        root_path=Path(__file__).parent.parent.parent,
    )


@pytest.fixture
def builder(config: Config) -> AppBuilder:
    """Create a test AppBuilder."""
    return AppBuilder(config)


class TestAppBuilderHealthChecker:
    """Test suite for AppBuilder health checker integration."""

    def test_with_health_checker_registers_checker(self, builder: AppBuilder) -> None:
        """Test that with_health_checker registers a checker."""
        checker = MockHealthChecker()
        result = builder.with_health_checker("test_checker", checker)

        # Should return self for chaining
        assert result is builder

        # Checker should be registered
        assert builder._health_checker_registry.has("test_checker")
        assert builder._health_checker_registry.get("test_checker") is checker

    def test_with_health_checker_chaining(self, builder: AppBuilder) -> None:
        """Test that with_health_checker supports method chaining."""
        checker1 = MockHealthChecker()
        checker2 = MockHealthChecker()
        checker3 = MockHealthChecker()

        result = (
            builder.with_health_checker("checker1", checker1)
            .with_health_checker("checker2", checker2)
            .with_health_checker("checker3", checker3)
        )

        assert result is builder
        assert builder._health_checker_registry.has("checker1")
        assert builder._health_checker_registry.has("checker2")
        assert builder._health_checker_registry.has("checker3")

    def test_with_health_checker_replaces_existing(self, builder: AppBuilder) -> None:
        """Test that with_health_checker replaces existing checker with same name."""
        checker1 = MockHealthChecker()
        checker2 = MockHealthChecker()

        builder.with_health_checker("test", checker1)
        assert builder._health_checker_registry.get("test") is checker1

        builder.with_health_checker("test", checker2)
        assert builder._health_checker_registry.get("test") is checker2

    def test_health_checker_registry_initialized(self, builder: AppBuilder) -> None:
        """Test that health checker registry is initialized."""
        assert builder._health_checker_registry is not None
        assert len(builder._health_checker_registry.get_all()) == 0

    def test_multiple_checkers_registered(self, builder: AppBuilder) -> None:
        """Test registering multiple different checkers."""
        checkers = {
            "database": MockHealthChecker(),
            "cache": MockHealthChecker(),
            "external_api": MockHealthChecker(),
        }

        for name, checker in checkers.items():
            builder.with_health_checker(name, checker)

        all_checkers = builder._health_checker_registry.get_all()
        assert len(all_checkers) == 3

        for name, checker in checkers.items():
            assert all_checkers[name] is checker
