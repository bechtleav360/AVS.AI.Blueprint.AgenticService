"""One name per agent: the one it was given in code, with ``app_name`` as the fallback.

An agent's identity reaches its registry keys, its NATS queue group, its JetStream durable, its
cache partition and its telemetry ``service.name``. If config could supply a second name, the
same agent could be ``orders`` on the broker and something else in a dashboard -- so the name
given in code wins wherever identity is meant, and ``app_name`` is used only when no name was
given. Everywhere else ``app_name`` is a display string for the process.
"""

from pathlib import Path

import pytest

from blueprint.agents.config import Config

TWO_AGENTS = (
    '[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n\n'
    "[development.orders]\napp_port = 8000\n\n"
    '[development.billing]\notel_service_name = "billing-override"\n'
)


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(TWO_AGENTS)
    return path


def written(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(body)
    return path


def load(settings: Path, agent: str | None = None) -> Config:
    return Config(settings_files=[str(settings)], root_path=str(settings.parent), agent_scope=agent)


class TestTelemetryIdentity:
    def test_an_agents_service_name_is_its_own_name(self, settings: Path) -> None:
        """C2: dashboards key on the agent, so regrouping cannot move work between them."""
        assert load(settings, "orders").get_observability_config().otel_service_name == "orders"

    def test_an_agent_can_override_it_for_itself(self, settings: Path) -> None:
        assert load(settings, "billing").get_observability_config().otel_service_name == "billing-override"

    def test_the_roots_override_does_not_leak_into_an_agent(self, tmp_path: Path) -> None:
        """The one place a scoped read must not fall back: it would give every agent one name."""
        path = written(tmp_path, '[development]\napp_environment = "development"\notel_service_name = "one-name-for-all"\n')

        assert load(path, "orders").get_observability_config().otel_service_name == "orders"

    def test_a_single_agent_application_still_reads_app_name(self, settings: Path) -> None:
        """No name given, so app_name is used -- unchanged, and its dashboards do not move."""
        assert load(settings).get_observability_config().otel_service_name == "the-process"

    def test_an_explicit_root_override_still_wins_at_the_root(self, tmp_path: Path) -> None:
        path = written(tmp_path, '[development]\napp_environment = "development"\napp_name = "a"\notel_service_name = "b"\n')

        assert load(path).get_observability_config().otel_service_name == "b"

    def test_with_neither_it_falls_back_to_a_default(self, tmp_path: Path) -> None:
        path = written(tmp_path, '[development]\napp_environment = "development"\n')

        assert load(path).get_observability_config().otel_service_name == "agent_blueprint"


class TestAppNameStaysADisplayString:
    def test_an_agent_reads_the_processes_app_name(self, settings: Path) -> None:
        """It is not the agent's name, so it is not scoped away from it either."""
        assert load(settings, "orders").get("app_name") == "the-process"

    def test_an_agent_may_still_set_one_for_display(self, tmp_path: Path) -> None:
        path = written(
            tmp_path,
            '[development]\napp_environment = "development"\napp_name = "the-process"\n\n'
            '[development.orders]\napp_name = "Order Processing"\n',
        )
        config = load(path, "orders")

        assert config.get("app_name") == "Order Processing"
        # Identity is unaffected by it.
        assert config.get_observability_config().otel_service_name == "orders"
