"""Unit tests for AppBuilder."""

import types
from unittest.mock import MagicMock

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.services.service_base import ServiceBase
from tests.unit.agents.app_builder.conftest import StubHandler, wire_empty_registry

# ---------------------------------------------------------------------------
# with_handler
# ---------------------------------------------------------------------------


class TestWithHandler:
    def test_rejects_non_handler_type(self, builder: AppBuilder) -> None:
        class NotAHandler:
            pass

        with pytest.raises(TypeError):
            builder.with_handler(NotAHandler)

    def test_class_is_instantiated_and_registered(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        builder.with_handler(StubHandler)
        mock_registry.add_component.assert_called_once()

    def test_instance_is_accepted_without_re_instantiation(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        instance = StubHandler()
        mock_registry.reset_mock()  # clear the add_component call from StubHandler()
        builder.with_handler(instance)
        mock_registry.add_component.assert_not_called()

    def test_name_set_on_created_instance(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        builder.with_handler(StubHandler, name="custom_handler")
        mock_registry.update_component_name.assert_called_once()

    def test_returns_self_for_chaining(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        assert builder.with_handler(StubHandler) is builder


# ---------------------------------------------------------------------------
# with_service / with_agent / with_scheduler / with_rest_api
# ---------------------------------------------------------------------------


class TestOtherFluentSetters:
    """Smoke-test each with_*() method — all share the same class/instance dispatch
    pattern as with_handler (minus the type check) so one coverage pass suffices."""

    def test_with_service_instance_accepted_returns_self(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        class StubService(ServiceBase):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

        instance = StubService()
        mock_registry.reset_mock()
        assert builder.with_service(instance) is builder

    def test_with_agent_instance_accepted_returns_self(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        mock_agent = MagicMock()
        assert builder.with_agent(mock_agent) is builder

    def test_with_scheduler_instance_accepted_returns_self(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        mock_scheduler = MagicMock()
        assert builder.with_scheduler(mock_scheduler) is builder

    def test_with_rest_api_instance_accepted_returns_self(self, builder: AppBuilder, mock_registry: MagicMock) -> None:
        mock_api = MagicMock()
        assert builder.with_rest_api(mock_api) is builder


# ---------------------------------------------------------------------------
# with_cache
# ---------------------------------------------------------------------------


class TestWithCache:
    def test_enabled_creates_and_stores_cache_service(self, builder: AppBuilder, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        cache_cfg = MagicMock(cache_dir="/tmp/cache", size_limit=1024, eviction_policy="lru")
        mock_config.get_cache_config.return_value = cache_cfg

        builder.with_cache(enabled=True)

        assert mock_registry.cache_service is not None

    def test_disabled_does_not_read_cache_config(self, builder: AppBuilder, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        builder.with_cache(enabled=False)
        mock_config.get_cache_config.assert_not_called()

    def test_returns_self_for_chaining(self, builder: AppBuilder, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get_cache_config.return_value = MagicMock(cache_dir="/tmp/c", size_limit=512, eviction_policy="lru")
        assert builder.with_cache() is builder


# ---------------------------------------------------------------------------
# with_health_checker
# ---------------------------------------------------------------------------


class TestWithHealthChecker:
    def test_stored_pending_before_build(self, builder: AppBuilder) -> None:
        checker = MagicMock()
        builder.with_health_checker("my_service", checker)
        assert builder._custom_health_checkers["my_service"] is checker

    def test_multiple_checkers_accumulated_before_build(self, builder: AppBuilder) -> None:
        a, b = MagicMock(), MagicMock()
        builder.with_health_checker("svc_a", a)
        builder.with_health_checker("svc_b", b)
        assert len(builder._custom_health_checkers) == 2

    def test_added_immediately_after_build(self, builder: AppBuilder) -> None:
        mock_actuator = MagicMock()
        builder._actuator_api = mock_actuator

        checker = MagicMock()
        builder.with_health_checker("live_service", checker)

        mock_actuator.add_health_providers.assert_called_once_with({"live_service": checker})

    def test_returns_self_for_chaining(self, builder: AppBuilder) -> None:
        assert builder.with_health_checker("svc", MagicMock()) is builder


# ---------------------------------------------------------------------------
# build — event-bus routing
# ---------------------------------------------------------------------------


class TestBuild:
    def _set_event_bus(self, build_config: MagicMock, value: str) -> None:
        build_config.get.side_effect = lambda key, default="": value if key == "event_bus" else default

    def test_returns_fastapi_instance(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
    ) -> None:
        wire_empty_registry(mock_registry)
        result = builder_for_build.build()
        assert result is all_build_mocks.fastapi.return_value

    def test_event_bus_dapr_creates_dapr_client_and_eventing(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
        build_config: MagicMock,
    ) -> None:
        wire_empty_registry(mock_registry)
        mock_registry.get_event_handler.return_value = [MagicMock()]
        self._set_event_bus(build_config, "dapr")

        builder_for_build.build()

        all_build_mocks.dapr_client.assert_called_once()
        all_build_mocks.dapr_eventing.assert_called_once()
        all_build_mocks.nats_client.assert_not_called()
        all_build_mocks.nats_eventing.assert_not_called()

    def test_event_bus_nats_creates_nats_client_and_eventing(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
        build_config: MagicMock,
    ) -> None:
        wire_empty_registry(mock_registry)
        mock_registry.get_event_handler.return_value = [MagicMock()]
        self._set_event_bus(build_config, "nats")

        builder_for_build.build()

        all_build_mocks.nats_client.assert_called_once()
        all_build_mocks.nats_eventing.assert_called_once()
        all_build_mocks.dapr_client.assert_not_called()
        all_build_mocks.dapr_eventing.assert_not_called()

    def test_unknown_event_bus_with_handlers_logs_warning(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
        build_config: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        wire_empty_registry(mock_registry)
        mock_registry.get_event_handler.return_value = [MagicMock()]
        self._set_event_bus(build_config, "unknown_bus")

        with caplog.at_level("WARNING"):
            builder_for_build.build()

        assert "Event handling will be disabled" in caplog.text
        all_build_mocks.dapr_client.assert_not_called()
        all_build_mocks.nats_client.assert_not_called()

    def test_no_handlers_skips_eventing_setup(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
    ) -> None:
        wire_empty_registry(mock_registry)  # get_event_handler returns []

        builder_for_build.build()

        all_build_mocks.dapr_client.assert_not_called()
        all_build_mocks.dapr_eventing.assert_not_called()
        all_build_mocks.nats_client.assert_not_called()
        all_build_mocks.nats_eventing.assert_not_called()

    def test_event_publishing_service_created_only_with_io_clients(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
    ) -> None:
        wire_empty_registry(mock_registry)
        mock_registry.get_io_clients.return_value = [MagicMock()]  # has IO client

        builder_for_build.build()

        all_build_mocks.epubs.assert_called_once()

    def test_event_publishing_service_not_created_without_io_clients(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
    ) -> None:
        wire_empty_registry(mock_registry)  # get_io_clients returns []

        builder_for_build.build()

        all_build_mocks.epubs.assert_not_called()

    def test_custom_health_checkers_wired_during_build(
        self,
        builder_for_build: AppBuilder,
        mock_registry: MagicMock,
        all_build_mocks: types.SimpleNamespace,
    ) -> None:
        wire_empty_registry(mock_registry)
        checker = MagicMock()
        builder_for_build.with_health_checker("my_svc", checker)

        builder_for_build.build()

        actuator_instance = all_build_mocks.actuator.return_value
        actuator_instance.add_health_providers.assert_called_once()
        call_kwargs = actuator_instance.add_health_providers.call_args[0][0]
        assert "my_svc" in call_kwargs
