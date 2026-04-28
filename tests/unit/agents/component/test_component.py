"""Unit tests for Component, _ComponentMeta, traced decorator, and helpers."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from blueprint.agents.component.component import (
    Component,
    _is_cloud_event,
    _stamp_span,
    traced,
)
from blueprint.agents.config import Config

from .conftest import ConcreteComponent

# ---------------------------------------------------------------------------
# Module-level helpers shared across traced() tests
# ---------------------------------------------------------------------------


class _BaseTracedComp(Component):
    """Concrete lifecycle stubs — subclassed by each traced-method variant."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class _AsyncTracedComp(_BaseTracedComp):
    @traced()
    async def my_action(self) -> None:
        pass


class _SyncTracedComp(_BaseTracedComp):
    @traced()
    def my_sync_action(self) -> str:
        return "done"


class _AsyncFailingComp(_BaseTracedComp):
    @traced()
    async def failing_action(self) -> None:
        raise ValueError("boom")


class _SyncFailingComp(_BaseTracedComp):
    @traced()
    def failing_sync(self) -> None:
        raise RuntimeError("sync boom")


class _FakeEvent:
    type = "test.type"
    source = "test.source"
    specversion = "1.0"
    id = "event-id-123"


class _EventHandlerComp(_BaseTracedComp):
    @traced()
    async def handle(self, event: _FakeEvent) -> None:
        pass


class _TopicHandlerComp(_BaseTracedComp):
    @traced("topic")
    async def handle(self, topic: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _otel_provider() -> Generator[InMemorySpanExporter]:
    """Set up the real OTel SDK provider once for this module.

    OTel does not allow overriding the provider after first initialisation, so
    the provider and exporter must be created once and shared across all tests.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter


@pytest.fixture
def span_exporter(_otel_provider: InMemorySpanExporter) -> Generator[InMemorySpanExporter]:
    """Yield the shared exporter cleared before and after each test."""
    _otel_provider.clear()
    yield _otel_provider
    _otel_provider.clear()


# ---------------------------------------------------------------------------
# _ComponentMeta — configure() and init_registry()
# ---------------------------------------------------------------------------


class TestComponentMeta:
    def test_configure_sets_shared_config(self) -> None:
        mock_config = MagicMock(spec=Config)
        Component.configure(mock_config)
        assert Component.shared_config is mock_config

    def test_configure_raises_on_second_call(self) -> None:
        Component.configure(MagicMock(spec=Config))
        with pytest.raises(RuntimeError, match="already set"):
            Component.configure(MagicMock(spec=Config))

    def test_init_registry_sets_shared_registry(self) -> None:
        mock_registry = MagicMock()
        Component.init_registry(mock_registry)
        assert Component.shared_registry is mock_registry

    def test_init_registry_raises_on_second_call(self) -> None:
        Component.init_registry(MagicMock())
        with pytest.raises(RuntimeError, match="already set"):
            Component.init_registry(MagicMock())


# ---------------------------------------------------------------------------
# Component.__init__
# ---------------------------------------------------------------------------


class TestComponentInit:
    def test_auto_creates_registry_on_first_instantiation(self) -> None:
        assert Component.shared_registry is None
        ConcreteComponent()
        assert Component.shared_registry is not None

    def test_reuses_existing_registry_for_subsequent_components(self) -> None:
        ConcreteComponent()
        registry_after_first = Component.shared_registry
        _BaseTracedComp()  # different class name → different registry key
        assert Component.shared_registry is registry_after_first

    def test_name_derived_from_class_name(self) -> None:
        comp = ConcreteComponent()
        assert comp.name == "concrete_component"

    def test_registers_self_by_default(self) -> None:
        ConcreteComponent()
        assert Component.shared_registry.has_component("concrete_component")  # type: ignore[union-attr]

    def test_skips_registration_when_should_register_false(self) -> None:
        comp = ConcreteComponent(should_register=False)
        assert not comp.registry.has_component("concrete_component")


# ---------------------------------------------------------------------------
# Component properties
# ---------------------------------------------------------------------------


class TestComponentProperties:
    def test_config_raises_when_not_configured(self, concrete_component: ConcreteComponent) -> None:
        with pytest.raises(RuntimeError, match="Config not linked"):
            _ = concrete_component.config

    def test_config_returns_shared_config(self, concrete_component: ConcreteComponent) -> None:
        mock_config = MagicMock(spec=Config)
        Component.configure(mock_config)
        assert concrete_component.config is mock_config

    def test_registry_property_returns_shared_registry(self, concrete_component: ConcreteComponent) -> None:
        assert concrete_component.registry is Component.shared_registry

    def test_name_setter_updates_name_and_registry(self, concrete_component: ConcreteComponent) -> None:
        old_name = concrete_component.name
        concrete_component.name = "new_name"
        assert concrete_component.name == "new_name"
        assert concrete_component.registry.has_component("new_name")
        assert not concrete_component.registry.has_component(old_name)


# ---------------------------------------------------------------------------
# _is_cloud_event helper
# ---------------------------------------------------------------------------


class TestIsCloudEvent:
    def test_true_for_object_with_all_required_attrs(self) -> None:
        assert _is_cloud_event(MagicMock(spec=["type", "source", "specversion"])) is True

    def test_false_for_plain_object(self) -> None:
        assert _is_cloud_event(object()) is False

    def test_false_when_specversion_missing(self) -> None:
        assert _is_cloud_event(MagicMock(spec=["type", "source"])) is False

    def test_false_when_source_missing(self) -> None:
        assert _is_cloud_event(MagicMock(spec=["type", "specversion"])) is False


# ---------------------------------------------------------------------------
# _stamp_span helper
# ---------------------------------------------------------------------------


class TestStampSpan:
    def test_stamps_cloud_event_attributes(self) -> None:
        span = MagicMock()
        _stamp_span(span, "event", _FakeEvent())
        span.set_attribute.assert_any_call("event.type", "test.type")
        span.set_attribute.assert_any_call("event.source", "test.source")
        span.set_attribute.assert_any_call("event.id", "event-id-123")

    def test_stamps_plain_value_as_string(self) -> None:
        span = MagicMock()
        _stamp_span(span, "retries", 3)
        span.set_attribute.assert_called_once_with("retries", "3")

    def test_skips_falsy_cloud_event_fields(self) -> None:
        class EmptyEvent:
            type = ""
            source = ""
            specversion = "1.0"
            id = None

        span = MagicMock()
        _stamp_span(span, "event", EmptyEvent())
        span.set_attribute.assert_not_called()


# ---------------------------------------------------------------------------
# traced() decorator
# ---------------------------------------------------------------------------


class TestTraced:
    async def test_async_creates_span_with_correct_name(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _AsyncTracedComp()
        await comp.my_action()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == f"{comp.name}.my_action"

    def test_sync_creates_span_with_correct_name(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _SyncTracedComp()
        result = comp.my_sync_action()

        assert result == "done"
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == f"{comp.name}.my_sync_action"

    async def test_async_reraises_exception_and_sets_error_status(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _AsyncFailingComp()
        with pytest.raises(ValueError, match="boom"):
            await comp.failing_action()

        spans = span_exporter.get_finished_spans()
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_sync_reraises_exception_and_sets_error_status(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _SyncFailingComp()
        with pytest.raises(RuntimeError, match="sync boom"):
            comp.failing_sync()

        spans = span_exporter.get_finished_spans()
        assert spans[0].status.status_code == StatusCode.ERROR

    async def test_auto_detects_cloud_event_param(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _EventHandlerComp()
        await comp.handle(_FakeEvent())

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs.get("event.type") == "test.type"
        assert attrs.get("event.source") == "test.source"

    async def test_extract_stamps_named_param(self, span_exporter: InMemorySpanExporter) -> None:
        comp = _TopicHandlerComp()
        await comp.handle(topic="orders")

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs.get("topic") == "orders"
