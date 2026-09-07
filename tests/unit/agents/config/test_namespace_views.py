"""Unit tests for per-namespace configuration views (C5) and the audited escape hatch."""

import logging
from pathlib import Path

import pytest

from blueprint.agents.config import Config
from blueprint.agents.config.config import DEPLOYMENT_IDENTITY_KEYS

from tests.unit.agents.config.conftest import WriteSettings


@pytest.fixture
def two_agent_config(write_settings: WriteSettings) -> Config:
    """Configuration with a shared root and two agents that override parts of it."""
    settings_file = write_settings("""
        [development]
        app_environment = "development"
        app_name = "root-app"
        app_port = 8000
        model_name = "root-model"
        nats_url = "nats://localhost:4222"

        [development.orders]
        app_name = "orders"
        model_name = "orders-model"

        [development.billing]
        app_name = "billing"
        """)
    return Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))


class TestForNamespace:
    def test_view_resolves_its_own_key_first(self, two_agent_config: Config) -> None:
        assert two_agent_config.for_namespace("orders").get("model_name") == "orders-model"

    def test_view_falls_back_to_the_root_key(self, two_agent_config: Config) -> None:
        """Infrastructure stays shared; only what an agent overrides is per-agent."""
        assert two_agent_config.for_namespace("orders").get("nats_url") == "nats://localhost:4222"

    def test_an_agent_without_an_override_reads_the_root_value(self, two_agent_config: Config) -> None:
        assert two_agent_config.for_namespace("billing").get("model_name") == "root-model"

    def test_two_views_disagree_where_the_agents_do(self, two_agent_config: Config) -> None:
        orders = two_agent_config.for_namespace("orders")
        billing = two_agent_config.for_namespace("billing")
        assert orders.get("model_name") != billing.get("model_name")
        assert orders.get("app_name") == "orders"
        assert billing.get("app_name") == "billing"

    def test_the_root_namespace_is_the_configuration_itself(self, two_agent_config: Config) -> None:
        """Not an optimisation: the root namespace *is* the unscoped configuration."""
        assert two_agent_config.for_namespace("") is two_agent_config

    def test_views_are_cached(self, two_agent_config: Config) -> None:
        assert two_agent_config.for_namespace("orders") is two_agent_config.for_namespace("orders")

    def test_the_tree_is_loaded_once_and_shared(self, two_agent_config: Config) -> None:
        """A view must not re-parse the settings files -- one process, one load."""
        view = two_agent_config.for_namespace("orders")
        assert view._settings is two_agent_config._settings

    def test_a_view_reports_its_scope(self, two_agent_config: Config) -> None:
        view = two_agent_config.for_namespace("orders")
        assert (view.agent_scope, view.is_view) == ("orders", True)

    def test_the_loader_is_not_a_view(self, two_agent_config: Config) -> None:
        assert (two_agent_config.agent_scope, two_agent_config.is_view) == (None, False)

    def test_a_view_cannot_hand_out_another_namespaces_view(self, two_agent_config: Config) -> None:
        """Otherwise every agent has an unlogged route to its neighbours' keys."""
        orders = two_agent_config.for_namespace("orders")
        with pytest.raises(RuntimeError, match="not from another"):
            orders.for_namespace("billing")

    def test_the_typed_getters_are_scoped_too(self, write_settings: WriteSettings) -> None:
        """Every typed getter funnels through get(), so scoping applies without per-getter work."""
        settings_file = write_settings("""
            [development]
            app_environment = "development"
            app_name = "root-app"
            app_port = 8000
            idempotency_enabled = false

            [development.orders]
            app_name = "orders"
            idempotency_enabled = true
            idempotency_ttl = 600
            """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get_event_publishing_config() is not None
        assert config.for_namespace("orders").get("idempotency_ttl") == 600


class TestDeploymentIdentityIsNotConfiguration:
    """C6 -- agent code that can read its group can be written to depend on it."""

    @pytest.mark.parametrize("key", sorted(DEPLOYMENT_IDENTITY_KEYS))
    def test_deployment_keys_are_refused(self, two_agent_config: Config, key: str) -> None:
        with pytest.raises(ValueError, match="deployment identity"):
            two_agent_config.get(key)

    def test_the_refusal_holds_for_a_view(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="deployment identity"):
            two_agent_config.for_namespace("orders").get("BLUEPRINT_GROUP")

    def test_the_check_is_case_insensitive(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="deployment identity"):
            two_agent_config.get("Pod_Name")

    def test_it_raises_rather_than_answering_none(self, two_agent_config: Config) -> None:
        """None would read as 'not configured' and send the caller hunting for a missing key."""
        with pytest.raises(ValueError):
            two_agent_config.get("hostname", "a-default")

    def test_an_ordinary_key_is_unaffected(self, two_agent_config: Config) -> None:
        assert two_agent_config.get("app_name") == "root-app"


class TestRawSettingsIsAudited:
    """Isolation is audited, not enforced -- so the audit has to actually happen."""

    def test_a_view_reading_the_tree_warns_and_names_the_namespace(
        self, two_agent_config: Config, caplog: pytest.LogCaptureFixture
    ) -> None:
        view = two_agent_config.for_namespace("orders")
        with caplog.at_level(logging.WARNING):
            _ = view.settings
        assert "orders" in caplog.text
        assert "not scoped to it" in caplog.text

    def test_the_loader_reading_the_tree_does_not_warn(self, two_agent_config: Config, caplog: pytest.LogCaptureFixture) -> None:
        """The application owns its own configuration; only reaching past a view is notable."""
        with caplog.at_level(logging.WARNING):
            _ = two_agent_config.settings
        assert caplog.text == ""

    def test_the_hatch_still_returns_the_whole_tree(self, two_agent_config: Config) -> None:
        """It is an escape hatch, not a second scoped reader -- it has to work."""
        assert two_agent_config.for_namespace("orders").settings.get("billing.app_name") == "billing"


class TestPackageRootSurvivesTheView:
    def test_view_keeps_the_root_path(self, two_agent_config: Config) -> None:
        assert isinstance(two_agent_config.for_namespace("orders").get_package_root(), Path)
        assert two_agent_config.for_namespace("orders").get_package_root() == two_agent_config.get_package_root()
