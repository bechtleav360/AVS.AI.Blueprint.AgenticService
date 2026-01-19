"""Unit tests for HealthCheckerRegistry."""

import pytest

from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.services.health.registry import HealthCheckerRegistry


class MockHealthChecker:
    """Mock health checker for testing."""

    async def health_check(self) -> ComponentHealth:
        """Return a mock health check result."""
        return ComponentHealth(status="UP", message="Mock checker OK")


class TestHealthCheckerRegistry:
    """Test suite for HealthCheckerRegistry."""

    @pytest.fixture
    def registry(self) -> HealthCheckerRegistry:
        """Create a fresh registry for each test."""
        return HealthCheckerRegistry()

    def test_register_checker(self, registry: HealthCheckerRegistry) -> None:
        """Test registering a health checker."""
        checker = MockHealthChecker()
        registry.register("test_checker", checker)

        assert registry.has("test_checker")
        assert registry.get("test_checker") is checker

    def test_register_duplicate_raises_error(self, registry: HealthCheckerRegistry) -> None:
        """Test that registering duplicate checker raises ValueError."""
        checker1 = MockHealthChecker()
        checker2 = MockHealthChecker()

        registry.register("test", checker1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("test", checker2)

    def test_register_or_replace_replaces_existing(self, registry: HealthCheckerRegistry) -> None:
        """Test that register_or_replace replaces existing checker."""
        checker1 = MockHealthChecker()
        checker2 = MockHealthChecker()

        registry.register_or_replace("test", checker1)
        assert registry.get("test") is checker1

        registry.register_or_replace("test", checker2)
        assert registry.get("test") is checker2

    def test_get_nonexistent_returns_none(self, registry: HealthCheckerRegistry) -> None:
        """Test that getting nonexistent checker returns None."""
        assert registry.get("nonexistent") is None

    def test_get_all_returns_all_checkers(self, registry: HealthCheckerRegistry) -> None:
        """Test that get_all returns all registered checkers."""
        checker1 = MockHealthChecker()
        checker2 = MockHealthChecker()
        checker3 = MockHealthChecker()

        registry.register("checker1", checker1)
        registry.register("checker2", checker2)
        registry.register("checker3", checker3)

        all_checkers = registry.get_all()
        assert len(all_checkers) == 3
        assert all_checkers["checker1"] is checker1
        assert all_checkers["checker2"] is checker2
        assert all_checkers["checker3"] is checker3

    def test_get_all_returns_copy(self, registry: HealthCheckerRegistry) -> None:
        """Test that get_all returns a copy, not the internal dict."""
        checker = MockHealthChecker()
        registry.register("test", checker)

        all_checkers = registry.get_all()
        all_checkers["new_key"] = MockHealthChecker()

        # Original registry should not be modified
        assert not registry.has("new_key")

    def test_has_checker(self, registry: HealthCheckerRegistry) -> None:
        """Test checking if checker exists."""
        checker = MockHealthChecker()
        registry.register("test", checker)

        assert registry.has("test")
        assert not registry.has("nonexistent")

    def test_clear_removes_all_checkers(self, registry: HealthCheckerRegistry) -> None:
        """Test that clear removes all checkers."""
        registry.register("checker1", MockHealthChecker())
        registry.register("checker2", MockHealthChecker())

        assert len(registry.get_all()) == 2

        registry.clear()

        assert len(registry.get_all()) == 0
        assert not registry.has("checker1")
        assert not registry.has("checker2")

    def test_list_names(self, registry: HealthCheckerRegistry) -> None:
        """Test listing all checker names."""
        registry.register("checker1", MockHealthChecker())
        registry.register("checker2", MockHealthChecker())
        registry.register("checker3", MockHealthChecker())

        names = registry.list_names()
        assert len(names) == 3
        assert "checker1" in names
        assert "checker2" in names
        assert "checker3" in names

    def test_list_names_empty_registry(self, registry: HealthCheckerRegistry) -> None:
        """Test listing names from empty registry."""
        names = registry.list_names()
        assert names == []
