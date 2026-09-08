"""Where an agent's HTTP routes are mounted, and how they are tagged.

The problem: a group applies the same registration once per agent, so two agents declare the
same paths. Without a per-agent prefix FastAPI serves the first match and one agent's requests
are silently answered by another agent's code. The constraint alongside it is that a single-agent
application's paths must not move at all.

Assertions go through ``app.openapi()`` rather than ``app.routes``, because FastAPI stores an
included router as one opaque entry rather than flattening its routes into the app -- so
``app.routes`` does not contain the paths being tested, while the OpenAPI document is exactly
what the application serves.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from blueprint.agents.app_builder import AgentRegistration, AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.models.events import GenericCloudEvent


class OrderApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/orders", tags=["orders"])
    async def list_orders(self) -> list[str]:
        return []


class OrderHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return ["orders.created"]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return None


@pytest.fixture
def dapr_config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\nevent_bus = "dapr"\n\n'
        '[development.orders]\napp_name = "orders"\n\n'
        '[development.billing]\napp_name = "billing"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


@pytest.fixture
def nats_config(tmp_path: Path) -> Config:
    """The same tree on NATS, for the cases that host more than one consuming agent.

    Dapr cannot host a group of consumers yet -- the sidecar fetches the subscription document
    from one fixed path -- and ``build()`` refuses it rather than starting a pod that subscribes
    to nothing. See ``TestGroupedDaprIsRefused``.
    """
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\nevent_bus = "nats"\n\n'
        '[development.orders]\napp_name = "orders"\n\n'
        '[development.billing]\napp_name = "billing"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def paths(app: FastAPI) -> list[str]:
    return sorted(app.openapi()["paths"])


def tags_for(app: FastAPI, path: str) -> list[str]:
    operations = app.openapi()["paths"][path]
    return sorted({tag for operation in operations.values() for tag in operation.get("tags", [])})


class TestRoutePrefix:
    def test_a_root_component_has_no_prefix(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        assert OrderApi().route_prefix == ""

    def test_an_agents_component_is_prefixed_with_its_name(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        assert DaprEventing(namespace="orders").route_prefix == "/api/orders"


class TestRestRoutesMoveUnderTheAgent:
    def test_a_single_agent_applications_paths_do_not_move(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(OrderApi).build()

        assert "/api/orders" in paths(app)

    def test_an_agents_route_carries_its_namespace(self, dapr_config: Config) -> None:
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_rest_api(OrderApi))

        app = builder.build()

        assert "/api/orders/orders" in paths(app)

    def test_two_agents_declaring_one_route_do_not_collide(self, dapr_config: Config) -> None:
        """The failure without a prefix: FastAPI serves the first match for both agents."""
        registration = AgentRegistration().with_rest_api(OrderApi)
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        app = builder.build()

        assert {"/api/orders/orders", "/api/billing/orders"} <= set(paths(app))


class TestTags:
    def test_an_agents_tags_are_prefixed(self, dapr_config: Config) -> None:
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_rest_api(OrderApi))

        app = builder.build()

        assert tags_for(app, "/api/orders/orders") == ["orders.orders"]

    def test_the_bare_tag_is_replaced_rather_than_added_to(self, dapr_config: Config) -> None:
        """Appending would put the operation in two Swagger groups instead of one."""
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_rest_api(OrderApi))

        app = builder.build()

        assert "orders" not in tags_for(app, "/api/orders/orders")

    def test_two_agents_tags_do_not_merge(self, dapr_config: Config) -> None:
        registration = AgentRegistration().with_rest_api(OrderApi)
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        app = builder.build()

        assert tags_for(app, "/api/orders/orders") == ["orders.orders"]
        assert tags_for(app, "/api/billing/orders") == ["billing.orders"]

    def test_a_root_components_tags_are_untouched(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(OrderApi).build()

        assert tags_for(app, "/api/orders") == ["orders"]


class TestGroupedDaprIsRefused:
    """Discovery cannot be per agent: the sidecar fetches it from one path, fixed by Dapr.

    Each agent's document behind its own prefix leaves the sidecar with no document at all --
    subscribed to nothing, on a pod that reports itself healthy. That is refused at build time
    rather than deployed.
    """

    def test_two_consuming_agents_on_dapr_are_refused(self, dapr_config: Config) -> None:
        registration = AgentRegistration().with_handler(OrderHandler)
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        with pytest.raises(ValueError, match="cannot yet host a group"):
            builder.build()

    def test_the_refusal_names_both_agents(self, dapr_config: Config) -> None:
        registration = AgentRegistration().with_handler(OrderHandler)
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        with pytest.raises(ValueError, match="'orders', 'billing'"):
            builder.build()

    def test_one_agent_on_dapr_is_fine(self, dapr_config: Config) -> None:
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))

        assert "/api/orders/events/{topic}" in paths(builder.build())

    def test_two_agents_on_nats_are_fine(self, nats_config: Config) -> None:
        """NATS has no discovery endpoint; the client subscribes directly, per agent."""
        registration = AgentRegistration().with_handler(OrderHandler)
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        assert len(builder.build().openapi()["paths"]) > 0


class TestEventingRoutes:
    def test_a_root_delivery_path_is_unchanged(self, dapr_config: Config) -> None:
        """A sidecar posting to /events/{topic} keeps working for every existing deployment."""
        app = AppBuilder(dapr_config).with_handler(OrderHandler).build()

        assert "/events/{topic}" in paths(app)

    def test_an_agents_delivery_path_moves_under_it(self, dapr_config: Config) -> None:
        builder = AppBuilder(dapr_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))

        app = builder.build()

        assert "/api/orders/events/{topic}" in paths(app)

    def test_two_agents_get_their_own_delivery_paths(self, nats_config: Config) -> None:
        """Unprefixed, FastAPI would serve one agent's endpoint for both agents' deliveries."""
        registration = AgentRegistration().with_handler(OrderHandler)
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        app = builder.build()

        assert {"/api/orders/events/{topic}", "/api/billing/events/{topic}"} <= set(paths(app))

    async def test_the_subscription_document_names_the_mounted_path(self, dapr_config: Config) -> None:
        """The document and the mount must agree, or every delivery 404s on a healthy app."""
        Component.configure(dapr_config)
        with namespace_scope("orders"):
            OrderHandler()

        document = await DaprEventing(namespace="orders").subscribe()

        assert document == [{"pubsubname": "pubsub", "topic": "orders.created", "route": "/api/orders/events/orders.created"}]

    async def test_a_root_document_is_unchanged(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        OrderHandler()

        document = await DaprEventing().subscribe()

        assert document == [{"pubsubname": "pubsub", "topic": "orders.created", "route": "/events/orders.created"}]
