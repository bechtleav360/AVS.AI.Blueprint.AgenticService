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
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling import SchedulerBase
from blueprint.agents.models.events import GenericCloudEvent


class OrderApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/orders", tags=["orders"])
    async def list_orders(self) -> list[str]:
        return []


class SegmentedApi(OrderApi):
    group_segment = "reports"


class NightlyScheduler(SchedulerBase):
    def __init__(self) -> None:
        super().__init__(crontab="0 3 * * *")

    async def tick(self) -> None:
        pass


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

    def test_an_agents_segment_follows_its_prefix(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        with namespace_scope("orders"):
            api = SegmentedApi()
        assert api.route_prefix == "/api/orders/reports"

    def test_a_root_component_ignores_its_segment(self, dapr_config: Config) -> None:
        """A standalone agent's paths are a contract with its clients; a segment must not move them."""
        Component.configure(dapr_config)
        assert SegmentedApi().route_prefix == ""

    def test_the_framework_reserves_its_segments(self) -> None:
        assert NatsEventing.group_segment == "nats"
        assert SchedulerBase.group_segment == "scheduler"
        assert DaprEventing.group_segment == ""

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


class ItemApi(RestApiBase):
    """One route per tagging shape a developer can write."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/items", tags=["Items"])
    async def list_items(self) -> list[str]:
        return []

    @RestApiBase.get("/untagged")
    async def untagged(self) -> list[str]:
        return []

    @RestApiBase.get("/multi", tags=["Items", "Reports"])
    async def multi(self) -> list[str]:
        return []


class TestTags:
    """In a group an agent's operations form exactly one Swagger group, named after the agent (spec sec. 11.2)."""

    def test_a_declared_tag_is_replaced_by_the_agent(self, dapr_config: Config) -> None:
        """Kept beside the agent's tag, it would list the operation in two Swagger groups."""
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(ItemApi)}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/items") == ["orders"]

    def test_an_untagged_route_is_tagged_with_the_agent(self, dapr_config: Config) -> None:
        """The defect this replaces: untagged, it landed in "default" with every other agent's."""
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(ItemApi)}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/untagged") == ["orders"]

    def test_several_declared_tags_collapse_into_one(self, dapr_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(ItemApi)}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/multi") == ["orders"]

    def test_the_framework_endpoints_join_the_agents_group(self, nats_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_handler(OrderHandler)}).assemble(nats_config)

        assert tags_for(app, "/api/orders/nats/events/{topic}") == ["orders"]

    def test_no_agent_operation_is_left_in_default(self, dapr_config: Config) -> None:
        declaration = AppBuilder().with_rest_api(ItemApi)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(dapr_config)

        for path, operations in app.openapi()["paths"].items():
            if path.startswith("/api/"):
                for operation in operations.values():
                    assert operation.get("tags") == [path.split("/")[2]], path

    def test_two_agents_tags_do_not_merge(self, dapr_config: Config) -> None:
        declaration = AppBuilder().with_rest_api(ItemApi)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(dapr_config)

        assert tags_for(app, "/api/orders/items") == ["orders"]
        assert tags_for(app, "/api/billing/items") == ["billing"]

    def test_a_root_components_tags_are_untouched(self, dapr_config: Config) -> None:
        """Standalone keeps what was declared -- including no tag at all, which is "default"."""
        app = AppBuilder(dapr_config).with_rest_api(ItemApi).build()

        assert tags_for(app, "/api/items") == ["Items"]
        assert tags_for(app, "/api/untagged") == []
        assert tags_for(app, "/api/multi") == ["Items", "Reports"]


class ReportApi(RestApiBase):
    path_prefix = "reports"

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/daily")
    async def daily(self) -> list[str]:
        return []


class SlashedReportApi(ReportApi):
    path_prefix = "/reports/"


class CacheLookalikeApi(OrderApi):
    """A developer route in a segment the framework owns."""

    @RestApiBase.get("/cache/stats")
    async def stats(self) -> dict[str, int]:
        return {}


class NatsPrefixedApi(ReportApi):
    path_prefix = "nats"


class CachesApi(OrderApi):
    """``caches`` is not ``cache``: the segment is matched whole."""

    @RestApiBase.get("/caches/stats")
    async def stats(self) -> dict[str, int]:
        return {}


class TestPathPrefix:
    """A developer's optional prefix, applied the same in both modes (spec sec. 11.2)."""

    def test_standalone_it_follows_api(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(ReportApi).build()

        assert "/api/reports/daily" in paths(app)

    def test_in_a_group_it_follows_the_agent(self, dapr_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(ReportApi)}).assemble(dapr_config)

        assert "/api/orders/reports/daily" in paths(app)

    def test_surrounding_slashes_are_ignored(self, dapr_config: Config) -> None:
        app = AppBuilder(dapr_config).with_rest_api(SlashedReportApi).build()

        assert "/api/reports/daily" in paths(app)

    def test_no_prefix_moves_nothing(self, dapr_config: Config) -> None:
        assert OrderApi.path_prefix == ""
        assert OrderApi().router.prefix == ""


class TestReservedSegments:
    """In a group, ``nats``, ``cache`` and ``scheduler`` under ``/api/<agent>/`` are the framework's."""

    def test_a_grouped_route_in_a_reserved_segment_is_refused(self, dapr_config: Config) -> None:
        declaration = AppBuilder().with_rest_api(CacheLookalikeApi)

        with pytest.raises(ValueError, match=r"CacheLookalikeApi in agent 'orders' serves '/cache/stats'.*'cache'.*CacheManagementApi"):
            AgentGroup("g", {"orders": declaration}).assemble(dapr_config)

    def test_a_reserved_path_prefix_is_refused(self, dapr_config: Config) -> None:
        declaration = AppBuilder().with_rest_api(NatsPrefixedApi)

        with pytest.raises(ValueError, match=r"'nats'.*NatsEventing"):
            AgentGroup("g", {"orders": declaration}).assemble(dapr_config)

    def test_standalone_the_same_route_is_served(self, dapr_config: Config) -> None:
        """Standalone paths are the agent's own; ``/api/cache/stats`` may have clients (spec sec. 10)."""
        app = AppBuilder(dapr_config).with_rest_api(CacheLookalikeApi).build()

        assert "/api/cache/stats" in paths(app)

    def test_the_segment_is_matched_whole(self, dapr_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_rest_api(CachesApi)}).assemble(dapr_config)

        assert "/api/orders/caches/stats" in paths(app)

    def test_a_developers_scheduler_owns_the_scheduler_segment(self, scheduler_config: Config) -> None:
        """It inherits ``SchedulerBase``, the owner. NATS and cache are covered by their own route tests."""
        app = AgentGroup("g", {"orders": AppBuilder().with_scheduler(NightlyScheduler)}).assemble(scheduler_config)

        assert [path for path in paths(app) if path.startswith("/api/orders/scheduler/")]


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
        assert "/api/orders/nats/events/{topic}" not in paths(app)

    def test_two_agents_get_their_own_nats_delivery_paths(self, nats_config: Config) -> None:
        """Unprefixed, FastAPI would serve one agent's endpoint for both agents' deliveries."""
        declaration = AppBuilder().with_handler(OrderHandler)

        app = AgentGroup("g", {"orders": declaration, "billing": declaration}).assemble(nats_config)

        assert {"/api/orders/nats/events/{topic}", "/api/billing/nats/events/{topic}"} <= set(paths(app))
        assert not [path for path in paths(app) if path.startswith("/api/orders/events")]

    def test_a_standalone_nats_path_is_unchanged(self, nats_config: Config) -> None:
        app = AppBuilder(nats_config).with_handler(OrderHandler).build()

        assert "/events/{topic}" in paths(app)
        assert not [path for path in paths(app) if "/nats/" in path]

    async def test_a_root_document_is_unchanged(self, dapr_config: Config) -> None:
        Component.configure(dapr_config)
        OrderHandler()

        document = await DaprEventing().subscribe()

        assert document == [{"pubsubname": "pubsub", "topic": "orders.created", "route": "/events/orders.created"}]


@pytest.fixture
def scheduler_config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\nevent_bus = "nats"\nscheduler_mode = "in_process"\n\n'
        '[development.orders]\napp_name = "orders"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


class TestSchedulerRoutes:
    def test_an_agents_trigger_lives_under_the_scheduler_segment(self, scheduler_config: Config) -> None:
        app = AgentGroup("g", {"orders": AppBuilder().with_scheduler(NightlyScheduler)}).assemble(scheduler_config)

        triggers = [path for path in paths(app) if path.endswith("/trigger")]
        assert len(triggers) == 1
        assert triggers[0].startswith("/api/orders/scheduler/")

    def test_a_standalone_trigger_path_is_unchanged(self, scheduler_config: Config) -> None:
        scheduler = NightlyScheduler()
        app = AppBuilder(scheduler_config).with_scheduler(scheduler).build()

        assert f"/api/{scheduler.name}/trigger" in paths(app)


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
