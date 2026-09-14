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

from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder
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


@pytest.fixture
def cache_config(tmp_path: Path) -> Config:
    """One writable cache directory for the process, as a mounted volume would be.

    The agents share it and the *stores* inside it are separated per agent, which is the shape
    a pod can actually satisfy -- see "Writable Cache Directory" in ``docs/guides/deployment.md``.
    """
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\n\n'
        f'[development.cache]\ncache_dir = "{(tmp_path / "cache").as_posix()}"\n\n'
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
        with namespace_scope("orders"):
            api = OrderApi()
        assert api.route_prefix == "/api/orders"

    def test_the_dapr_endpoint_is_always_the_root_one(self, dapr_config: Config) -> None:
        """It takes no namespace at all: Dapr's paths are fixed, so there is one endpoint."""
        Component.configure(dapr_config)
        assert DaprEventing().route_prefix == ""


class TestRestRoutesMoveUnderTheAgent:
    def test_a_single_agent_applications_paths_do_not_move(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(OrderApi).build()

        assert "/api/orders" in paths(app)

    def test_an_agents_route_carries_its_namespace(self, dapr_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(OrderApi)}).assemble(dapr_config)

        assert "/api/orders/orders" in paths(app)

    def test_two_agents_declaring_one_route_do_not_collide(self, dapr_config: Config) -> None:
        """The failure without a prefix: FastAPI serves the first match for both agents."""
        declaration = AppBuilder().with_rest_api(OrderApi)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(dapr_config)

        assert {"/api/orders/orders", "/api/billing/orders"} <= set(paths(app))


class TestTags:
    def test_an_agents_tags_are_prefixed(self, dapr_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(OrderApi)}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/orders") == ["orders.orders"]

    def test_the_bare_tag_is_replaced_rather_than_added_to(self, dapr_config: Config) -> None:
        """Appending would put the operation in two Swagger groups instead of one."""
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(OrderApi)}).assemble(dapr_config)

        assert "orders" not in tags_for(app, "/api/orders/orders")

    def test_two_agents_tags_do_not_merge(self, dapr_config: Config) -> None:
        declaration = AppBuilder().with_rest_api(OrderApi)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/orders") == ["orders.orders"]
        assert tags_for(app, "/api/billing/orders") == ["billing.orders"]

    def test_a_root_components_tags_are_untouched(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(OrderApi).build()

        assert tags_for(app, "/api/orders") == ["orders"]


class TestEventingRoutes:
    def test_a_root_delivery_path_is_unchanged(self, dapr_config: Config) -> None:
        """A sidecar posting to /events/{topic} keeps working for every existing deployment."""
        app = AppBuilder(dapr_config).with_handler(OrderHandler).build()

        assert "/events/{topic}" in paths(app)

    def test_the_dapr_delivery_path_never_moves(self, dapr_config: Config) -> None:
        """Dapr's two paths are fixed by its protocol, so its endpoint stays at the root."""
        app = AgentGroup("g", {"orders": AppBuilder().with_handler(OrderHandler)}).assemble(dapr_config)

        assert {"/events/{topic}", "/dapr/subscribe"} <= set(paths(app))
        assert "/api/orders/events/{topic}" not in paths(app)

    def test_two_agents_get_their_own_nats_delivery_paths(self, nats_config: Config) -> None:
        """Unprefixed, FastAPI would serve one agent's endpoint for both agents' deliveries."""
        declaration = AppBuilder().with_handler(OrderHandler)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(nats_config)

        assert {"/api/orders/events/{topic}", "/api/billing/events/{topic}"} <= set(paths(app))

    async def test_a_root_document_is_unchanged(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        OrderHandler()

        document = await DaprEventing().subscribe()

        assert document == [{"pubsubname": "pubsub", "topic": "orders.created", "route": "/events/orders.created"}]


class TestCacheEndpointsPerAgent:
    """``/cache/*`` is per agent, because one process-wide endpoint reports one agent's keys to another.

    The router is not keyed on the set of caches at request time -- a cache can be registered
    after startup and routes cannot -- so what is per agent is the *mount*: one router per agent
    that declared a cache, each resolving names within its own agent.
    """

    def test_an_agents_cache_endpoints_live_under_its_prefix(self, cache_config: Config) -> None:
        declaration = AppBuilder().with_cache()

        app = AgentGroup("finance", {"orders": declaration}).assemble(cache_config)

        assert "/api/orders/cache/stats" in paths(app)
        assert "/api/cache/stats" not in paths(app)

    def test_each_agent_gets_its_own(self, cache_config: Config) -> None:
        orders = AppBuilder().with_cache()
        billing = AppBuilder().with_cache(name="sessions")

        app = AgentGroup("finance", {"orders": orders, "billing": billing}).assemble(cache_config)

        assert {"/api/orders/cache/stats", "/api/billing/cache/stats"} <= set(paths(app))

    def test_an_agent_that_declared_no_cache_gets_no_endpoint(self, cache_config: Config) -> None:
        orders = AppBuilder().with_cache()
        billing = AppBuilder()

        app = AgentGroup("finance", {"orders": orders, "billing": billing}).assemble(cache_config)

        assert "/api/billing/cache/stats" not in paths(app)

    def test_a_standalone_application_keeps_the_paths_it_had(self, cache_config: Config) -> None:
        app = AppBuilder(cache_config).with_cache().build()

        assert "/api/cache/stats" in paths(app)

    def test_no_endpoint_at_all_without_a_cache(self, cache_config: Config) -> None:
        app = AppBuilder(cache_config).build()

        assert not [path for path in paths(app) if "/cache/" in path]
