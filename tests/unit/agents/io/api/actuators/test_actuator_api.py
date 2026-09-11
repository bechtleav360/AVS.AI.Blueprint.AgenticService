"""Unit tests for ActuatorApi."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config
from blueprint.agents.io.api.actuators.health.health_base import HealthCheckEntry
from blueprint.agents.io.api.actuators.actuator_api import ActuatorApi
from blueprint.agents.io.api.actuators.health.readiness_policy import ReadinessPolicy


@pytest.fixture
def actuator_api(mock_config: MagicMock, mock_registry: MagicMock) -> ActuatorApi:
    """Return an ActuatorApi instance with mocked config and registry."""
    mock_config.get.side_effect = lambda key, default=None: {
        "health_check_interval_seconds": 30,
    }.get(key, default)
    return ActuatorApi()


# ---------------------------------------------------------------------------
# _sanitize_config
# ---------------------------------------------------------------------------


class TestSanitizeConfig:
    def test_non_sensitive_values_are_unchanged(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"app_name": "agent", "port": 8080})
        assert result == {"app_name": "agent", "port": 8080}

    def test_api_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"api_key": "secret-value"})
        assert result["api_key"] == "***"

    def test_password_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"password": "hunter2"})
        assert result["password"] == "***"

    def test_secret_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"secret": "shh"})
        assert result["secret"] == "***"

    def test_token_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"token": "bearer-abc"})
        assert result["token"] == "***"

    def test_nested_sensitive_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"database": {"host": "localhost", "password": "db-pass"}})
        assert result["database"]["host"] == "localhost"
        assert result["database"]["password"] == "***"

    def test_deeply_nested_api_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"ai": {"provider": {"api_key": "sk-1234", "model": "gpt-4"}}})
        assert result["ai"]["provider"]["api_key"] == "***"
        assert result["ai"]["provider"]["model"] == "gpt-4"

    def test_empty_dict_returns_empty_dict(self, actuator_api: ActuatorApi) -> None:
        assert actuator_api._sanitize_config({}) == {}

    @pytest.mark.parametrize(
        "key",
        [
            "openai_api_key",
            "vllm_api_key",
            "nats_password",
            "redis_password",
            "azure_client_secret",
            "client_token",
            "service_credentials",
            "signing_salt",
            "private_key_pem",
            "OPENAI_API_KEY",
        ],
    )
    def test_compound_keys_are_masked(self, actuator_api: ActuatorApi, key: str) -> None:
        """The whole-key match returned every one of these in clear (issue #91)."""
        assert actuator_api._sanitize_config({key: "s3cr3t"})[key] == "***"

    def test_secrets_inside_a_list_are_masked(self, actuator_api: ActuatorApi) -> None:
        """Only dict values used to be walked, so a list of provider entries was returned whole."""
        result = actuator_api._sanitize_config({"providers": [{"name": "openai", "api_key": "sk-1234"}]})
        assert result["providers"][0] == {"name": "openai", "api_key": "***"}

    def test_a_list_of_secret_values_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"api_keys": ["sk-a", "sk-b"]})
        assert result["api_keys"] == ["***", "***"]

    def test_url_userinfo_is_stripped_although_the_key_names_nothing_sensitive(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"redis_url": "redis://admin:hunter2@cache.internal:6379/0"})
        assert result["redis_url"] == "redis://cache.internal:6379/0"
        assert "hunter2" not in result["redis_url"]

    def test_url_without_userinfo_is_untouched(self, actuator_api: ActuatorApi) -> None:
        assert actuator_api._sanitize_config({"nats_url": "nats://localhost:4222"})["nats_url"] == "nats://localhost:4222"

    def test_ipv6_url_keeps_its_brackets(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"redis_url": "redis://user:pw@[::1]:6379/0"})
        assert result["redis_url"] == "redis://[::1]:6379/0"

    def test_booleans_pass_through_even_under_a_matching_key(self, actuator_api: ActuatorApi) -> None:
        """A flag cannot carry a credential, and it is what the endpoint is read for."""
        assert actuator_api._sanitize_config({"auth_enabled": True})["auth_enabled"] is True

    def test_a_plain_string_that_merely_contains_an_at_sign_is_untouched(self, actuator_api: ActuatorApi) -> None:
        assert actuator_api._sanitize_config({"contact": "team@example.com"})["contact"] == "team@example.com"


# ---------------------------------------------------------------------------
# liveness_probe
# ---------------------------------------------------------------------------


class TestLivenessProbe:
    async def test_returns_up_when_no_config_errors(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.has_validation_errors.return_value = False
        result = await actuator_api.liveness_probe()
        assert result.status == "UP"

    async def test_returns_up_even_when_config_has_validation_errors(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.has_validation_errors.return_value = True
        mock_config.get_validation_errors.return_value = ["missing field"]
        result = await actuator_api.liveness_probe()
        assert result.status == "UP"


# ---------------------------------------------------------------------------
# on_startup / on_shutdown
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_creates_health_cache(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            await actuator_api.on_startup()
        mock_cache_cls.assert_called_once()
        assert actuator_api._health_cache is mock_cache_cls.return_value

    async def test_on_startup_uses_configured_interval(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: 60 if key == "health_check_interval_seconds" else default
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            await actuator_api.on_startup()
        assert mock_cache_cls.call_args.kwargs["check_interval_seconds"] == 60

    async def test_on_startup_registers_pending_providers(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        entry = HealthCheckEntry(name="db", namespace="", checker=MagicMock())
        actuator_api.add_health_providers([entry])
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            mock_cache_cls.return_value.set_health_entries = MagicMock()
            await actuator_api.on_startup()
        mock_cache_cls.return_value.set_health_entries.assert_called_once_with([entry])

    async def test_on_shutdown_stops_health_cache(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_cache = MagicMock()
        mock_cache.stop = AsyncMock()
        actuator_api._health_cache = mock_cache
        await actuator_api.on_shutdown()
        mock_cache.stop.assert_awaited_once()

    async def test_on_shutdown_is_safe_when_cache_none(self, actuator_api: ActuatorApi) -> None:
        actuator_api._health_cache = None
        await actuator_api.on_shutdown()  # must not raise


# ---------------------------------------------------------------------------
# readiness_probe — HTTP code reflects aggregated health
# ---------------------------------------------------------------------------


class TestReadinessProbe:
    @pytest.fixture
    def actuator_with_cache(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> ActuatorApi:
        # Default to "no validation errors" so the validation branch doesn't
        # fire in tests that exercise the aggregated-health branch.
        mock_config.has_validation_errors = MagicMock(return_value=False)
        actuator_api._health_cache = MagicMock()
        return actuator_api

    async def test_returns_response_when_status_is_up(self, actuator_with_cache: ActuatorApi) -> None:
        from blueprint.agents.models.api import ReadinessResponse

        ready = ReadinessResponse(status="UP", components={})
        actuator_with_cache._health_cache.get_health_status = AsyncMock(return_value=ready)
        actuator_with_cache._health_cache.get_cache_age_seconds = MagicMock(return_value=0.5)

        result = await actuator_with_cache.readiness_probe()
        assert result.status == "UP"

    async def test_raises_503_when_aggregated_status_is_down(self, actuator_with_cache: ActuatorApi) -> None:
        from fastapi import HTTPException, status

        from blueprint.agents.models.api import ComponentHealth, ReadinessResponse

        not_ready = ReadinessResponse(
            status="DOWN",
            components={"cache": ComponentHealth(status="unhealthy", message="Redis unreachable")},
        )
        actuator_with_cache._health_cache.get_health_status = AsyncMock(return_value=not_ready)
        actuator_with_cache._health_cache.get_cache_age_seconds = MagicMock(return_value=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await actuator_with_cache.readiness_probe()

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # Body retains the full diagnostic payload — not "Readiness probe failed".
        assert exc_info.value.detail["status"] == "DOWN"
        assert "cache" in exc_info.value.detail["components"]

    async def test_validation_error_payload_is_preserved(self, actuator_with_cache: ActuatorApi, mock_config: MagicMock) -> None:
        from fastapi import HTTPException, status

        mock_config.has_validation_errors = MagicMock(return_value=True)
        mock_config.get_validation_errors = MagicMock(return_value=["missing redis_url"])

        with pytest.raises(HTTPException) as exc_info:
            await actuator_with_cache.readiness_probe()

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # Detail keeps the original error list — earlier the generic catch
        # below would have overwritten it with "Readiness probe failed".
        assert exc_info.value.detail["status"] == "DOWN"
        assert exc_info.value.detail["errors"] == ["missing redis_url"]


# ---------------------------------------------------------------------------
# env_status
# ---------------------------------------------------------------------------


@pytest.fixture
def grouped_config(tmp_path: Path, mock_registry: MagicMock) -> Config:
    """A real Config with two agents, injected as the shared component config.

    A MagicMock cannot stand in here: the endpoint is being tested for how it uses the scoping
    and audit behaviour of the real Config, not for which methods it happens to call.
    """
    settings = tmp_path / "settings.toml"
    content = textwrap.dedent("""
            [development]
            app_name = "root-app"
            app_port = 8000
            health_check_interval_seconds = 30
            model_name = "root-model"
            nats_url = "nats://localhost:4222"
            openai_api_key = "sk-must-not-appear"

            [development.orders]
            app_name = "orders"
            model_name = "orders-model"
            orders_api_token = "tok-must-not-appear"

            [development.billing]
            app_name = "billing"
            """)
    settings.write_text(content)
    config = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(config)
    return config


class TestEnvStatus:
    async def test_a_single_agent_service_reports_no_namespaces(self, grouped_config: Config) -> None:
        """Nothing has asked for a view, so the response is shaped as it always was."""
        result = await ActuatorApi().env_status()
        assert result.namespaces == {}
        assert result.settings["MODEL_NAME"] == "root-model"

    async def test_each_namespace_that_asked_for_config_is_reported(self, grouped_config: Config) -> None:
        grouped_config.for_namespace("orders")
        grouped_config.for_namespace("billing")

        result = await ActuatorApi().env_status()

        assert sorted(result.namespaces) == ["billing", "orders"]

    async def test_a_namespace_entry_is_what_that_agent_resolves(self, grouped_config: Config) -> None:
        """Including keys it inherits: an operator debugging a value needs where it is read, not declared."""
        view = grouped_config.for_namespace("orders")

        result = await ActuatorApi().env_status()

        orders = result.namespaces["orders"]
        assert orders["MODEL_NAME"] == view.get("model_name") == "orders-model"
        assert orders["NATS_URL"] == "nats://localhost:4222"

    async def test_one_namespace_does_not_see_another(self, grouped_config: Config) -> None:
        grouped_config.for_namespace("orders")
        grouped_config.for_namespace("billing")

        result = await ActuatorApi().env_status()

        assert "BILLING" not in result.namespaces["orders"]
        assert result.namespaces["billing"]["APP_NAME"] == "billing"

    async def test_secrets_are_masked_in_every_namespace(self, grouped_config: Config) -> None:
        """The per-namespace breakdown is a second copy of the tree, so it needs the same masking."""
        grouped_config.for_namespace("orders")

        result = await ActuatorApi().env_status()

        assert result.settings["OPENAI_API_KEY"] == "***"
        assert result.namespaces["orders"]["OPENAI_API_KEY"] == "***"
        assert result.namespaces["orders"]["ORDERS_API_TOKEN"] == "***"
        assert "must-not-appear" not in str(result.model_dump())

    async def test_the_resolved_envvar_prefix_is_reported(self, grouped_config: Config) -> None:
        assert (await ActuatorApi().env_status()).envvar_prefix == "DYNACONF"

    async def test_a_disabled_prefix_is_reported_as_null(self, tmp_path: Path, mock_registry: MagicMock) -> None:
        """Null is unambiguous for a JSON consumer; an empty string reads as a prefix of nothing."""
        settings = tmp_path / "settings.toml"
        settings.write_text('envvar_prefix = false\n\n[development]\napp_name = "root-app"\napp_port = 8000\n')
        Component.configure(Config(settings_files=[str(settings)], root_path=str(tmp_path)))

        assert (await ActuatorApi().env_status()).envvar_prefix is None

    async def test_the_raw_tree_is_read_once_per_request(self, grouped_config: Config) -> None:
        """Config.settings is audited, so re-reading it turns one operator request into three records."""
        grouped_config.for_namespace("orders")
        with patch.object(type(grouped_config), "settings", new_callable=PropertyMock) as raw:
            raw.return_value = grouped_config._settings
            await ActuatorApi().env_status()

        assert raw.call_count == 1

    async def test_an_agent_scoped_actuator_reports_only_its_own_scope(self, grouped_config: Config) -> None:
        """C6 refuses both halves of the breakdown on a view, so the endpoint must not attempt it."""
        Component.reset_shared_state()
        Component.configure(grouped_config.for_namespace("orders"))
        Component.shared_registry = MagicMock(spec=Registry)

        result = await ActuatorApi().env_status()

        assert result.namespaces == {}
        assert result.settings["APP_NAME"] == "root-app"


class TestRegisteringChecks:
    """``add_health_providers`` is the one funnel, so the rules about entries live there."""

    def test_checks_accumulate_across_calls(self, actuator_api: ActuatorApi) -> None:
        """It used to assign: a with_health_checker() after build() wiped every wired check."""
        first = HealthCheckEntry(name="nats_client", namespace="", checker=MagicMock())
        second = HealthCheckEntry(name="db", namespace="", checker=MagicMock())

        actuator_api.add_health_providers([first])
        actuator_api.add_health_providers([second])

        assert actuator_api.health_entries == (first, second)

    def test_two_agents_may_use_one_name(self, actuator_api: ActuatorApi) -> None:
        orders = HealthCheckEntry(name="db", namespace="orders", checker=MagicMock())
        billing = HealthCheckEntry(name="db", namespace="billing", checker=MagicMock())

        actuator_api.add_health_providers([orders, billing])

        assert [entry.key for entry in actuator_api.health_entries] == ["orders.db", "billing.db"]

    def test_a_duplicate_key_is_refused(self, actuator_api: ActuatorApi) -> None:
        """A dict kept the last one, so a check could vanish with nothing logged."""
        actuator_api.add_health_providers([HealthCheckEntry(name="db", namespace="orders", checker=MagicMock())])

        with pytest.raises(ValueError, match="already taken"):
            actuator_api.add_health_providers([HealthCheckEntry(name="db", namespace="orders", checker=MagicMock())])

    def test_a_duplicate_within_one_call_is_refused(self, actuator_api: ActuatorApi) -> None:
        entry = HealthCheckEntry(name="db", namespace="", checker=MagicMock())

        with pytest.raises(ValueError, match="already taken"):
            actuator_api.add_health_providers([entry, HealthCheckEntry(name="db", namespace="", checker=MagicMock())])

    def test_a_check_added_after_startup_reaches_the_live_cache(self, actuator_api: ActuatorApi) -> None:
        cache = MagicMock()
        actuator_api._health_cache = cache
        entry = HealthCheckEntry(name="db", namespace="", checker=MagicMock())

        actuator_api.add_health_providers([entry])

        cache.set_health_entries.assert_called_once_with([entry])


class TestTheReadinessPolicy:
    """C3: which agents may take the pod out of service rotation, and who knows they exist."""

    @staticmethod
    def _actuator(mock_config: MagicMock, policy: object, namespaces: tuple[str, ...], critical: tuple[str, ...]) -> ActuatorApi:
        mock_config.get.side_effect = lambda key, default=None: {"readiness_policy": policy}.get(key, default)
        return ActuatorApi(namespaces, critical)

    async def test_the_default_reproduces_todays_behaviour(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: default
        actuator = ActuatorApi()
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as cache_cls:
            cache_cls.return_value.start = AsyncMock()
            await actuator.on_startup()
        assert cache_cls.call_args.kwargs["policy"] == ReadinessPolicy.ALL

    async def test_a_configured_policy_reaches_the_cache(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        actuator = self._actuator(mock_config, "critical", ("", "orders"), ("orders",))
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as cache_cls:
            cache_cls.return_value.start = AsyncMock()
            await actuator.on_startup()
        assert cache_cls.call_args.kwargs["policy"] == ReadinessPolicy.CRITICAL

    async def test_an_unknown_policy_refuses_to_start(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        """Defaulting would remove a whole group from rotation the first time an agent wobbled."""
        actuator = self._actuator(mock_config, "critcal", ("",), ())
        with pytest.raises(ValueError, match="readiness_policy"):
            await actuator.on_startup()

    async def test_the_supervisor_knows_every_hosted_agent(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        actuator = self._actuator(mock_config, "all", ("", "orders", "billing"), ("orders",))
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as cache_cls:
            cache_cls.return_value.start = AsyncMock()
            await actuator.on_startup()
        assert actuator.supervisor is not None
        assert set(actuator.supervisor.status) == {"", "orders", "billing"}
        assert actuator.supervisor.critical_namespaces == frozenset({"orders"})

    def test_there_is_no_supervisor_before_startup(self, actuator_api: ActuatorApi) -> None:
        """The gauges belong to per-agent providers, which the lifespan configures first."""
        assert actuator_api.supervisor is None
