"""Unit tests for the component Registry."""

import pytest
from unittest.mock import MagicMock

from blueprint.agents.component.registry import Registry


class StubBase:
    """Root type used as component_class for the registry under test."""


class StubA(StubBase):
    pass


class StubB(StubBase):
    pass


@pytest.fixture
def registry() -> Registry:
    return Registry(StubBase)


class TestInit:
    def test_rejects_non_class(self) -> None:
        with pytest.raises(ValueError):
            Registry("not_a_class")

    def test_accepts_valid_class(self) -> None:
        assert Registry(StubBase) is not None


class TestAddComponent:
    def test_happy_path(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.has_component("a")

    def test_rejects_wrong_type(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.add_component("bad", object())

    def test_rejects_duplicate_name(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        with pytest.raises(ValueError):
            registry.add_component("a", StubA())


class TestGetComponent:
    def test_by_name_returns_component(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.get_component("a") is comp

    def test_by_name_not_found_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.get_component("missing")

    def test_by_class_single_match(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.get_component(StubA) is comp

    def test_by_class_no_match_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.get_component(StubA)

    def test_by_class_multiple_matches_raises(self, registry: Registry) -> None:
        registry.add_component("a1", StubA())
        registry.add_component("a2", StubA())
        with pytest.raises(ValueError):
            registry.get_component(StubA)


class TestGetComponentsByType:
    def test_returns_matching_subset(self, registry: Registry) -> None:
        a, b = StubA(), StubB()
        registry.add_component("a", a)
        registry.add_component("b", b)
        assert registry.get_components_by_type(StubA) == [a]

    def test_returns_empty_when_none(self, registry: Registry) -> None:
        assert registry.get_components_by_type(StubA) == []

    def test_returns_all_matching(self, registry: Registry) -> None:
        a1, a2 = StubA(), StubA()
        registry.add_component("a1", a1)
        registry.add_component("a2", a2)
        result = registry.get_components_by_type(StubA)
        assert len(result) == 2
        assert a1 in result and a2 in result


class TestGetComponentNamesByType:
    def test_returns_matching_names(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.add_component("b", StubB())
        assert registry.get_component_names_by_type(StubA) == ["a"]

    def test_returns_empty_when_none(self, registry: Registry) -> None:
        assert registry.get_component_names_by_type(StubA) == []


class TestUpdateComponentName:
    def test_renames_component(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("old", comp)
        registry.update_component_name("old", "new")
        assert registry.has_component("new")
        assert not registry.has_component("old")
        assert registry.get_component("new") is comp

    def test_raises_on_unknown_old_name(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.update_component_name("nonexistent", "new")


class TestHasComponent:
    def test_by_name_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component("a") is True

    def test_by_name_false(self, registry: Registry) -> None:
        assert registry.has_component("missing") is False

    def test_by_class_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component(StubA) is True

    def test_by_class_false(self, registry: Registry) -> None:
        assert registry.has_component(StubA) is False


class TestHasComponentOfType:
    def test_type_only_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component_of_type(StubA) is True

    def test_type_only_false(self, registry: Registry) -> None:
        assert registry.has_component_of_type(StubA) is False

    def test_type_and_name_correct_type(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component_of_type(StubA, name="a") is True

    def test_type_and_name_wrong_type_raises(self, registry: Registry) -> None:
        registry.add_component("b", StubB())
        with pytest.raises(ValueError):
            registry.has_component_of_type(StubA, name="b")

    def test_type_and_name_not_found_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.has_component_of_type(StubA, name="missing")


class TestCacheService:
    def test_getter_raises_when_unset(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            _ = registry.cache_service

    def test_setter_assigns(self, registry: Registry) -> None:
        mock_cache = MagicMock()
        registry.cache_service = mock_cache
        assert registry.cache_service is mock_cache

    def test_setter_raises_on_second_set(self, registry: Registry) -> None:
        registry.cache_service = MagicMock()
        with pytest.raises(ValueError):
            registry.cache_service = MagicMock()

    def test_has_cache_false_when_unset(self, registry: Registry) -> None:
        assert registry.has_cache() is False

    def test_has_cache_true_when_set(self, registry: Registry) -> None:
        registry.cache_service = MagicMock()
        assert registry.has_cache() is True


class TestClear:
    def test_clear_components_empties_registry(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.clear_components()
        assert not registry.has_component("a")

    def test_clear_removes_components_and_resets_cache(self, registry: Registry) -> None:
        mock_cache = MagicMock()
        registry.add_component("a", StubA())
        registry.cache_service = mock_cache

        registry.clear()

        assert not registry.has_component("a")
        assert not registry.has_cache()
        mock_cache.clear.assert_called_once()

    def test_clear_without_cache_does_not_raise(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.clear()
        assert not registry.has_component("a")
