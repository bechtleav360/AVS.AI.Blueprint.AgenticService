"""The connection source: what the framework gets told about the two sites."""

import asyncio
from types import SimpleNamespace

import pytest

from blueprint.agents.clients.io.nats_connections import ConnectionSource

from src.connections import PASSWORD_ENV, SiteSource, create_source
from src.sites import current_site

SETTINGS = {
    "example_broker_url": "nats://localhost:4224",
    "example_sites": {
        "site_a": {"user": "agent-site-a", "alert_threshold": 50.0},
        "site_b": {"user": "agent-site-b", "alert_threshold": 80.0},
    },
}


class _Config:
    def get(self, key, default=None):
        return SETTINGS.get(key, default)


@pytest.fixture
def source(monkeypatch) -> SiteSource:
    monkeypatch.setenv(PASSWORD_ENV, "placeholder-for-tests")
    return create_source(_Config())


def _event(source: str) -> SimpleNamespace:
    return SimpleNamespace(source=source)


class TestTheSource:
    def test_it_is_a_connection_source(self, source):
        assert isinstance(source, ConnectionSource)

    def test_without_the_password_the_factory_refuses(self, monkeypatch):
        monkeypatch.delenv(PASSWORD_ENV, raising=False)
        with pytest.raises(ValueError, match=PASSWORD_ENV):
            create_source(_Config())

    def test_two_connections_one_per_site_each_with_its_own_user(self, source):
        connections = source.connections()
        assert sorted(connections) == ["site_a", "site_b"]
        assert connections["site_a"].user == "agent-site-a"
        assert connections["site_b"].user == "agent-site-b"
        assert "placeholder" not in repr(connections["site_a"]), "a password must never appear in a repr"

    def test_claims_every_readings_subject_and_nothing_else(self, source):
        assert source.claims("site_readings", ("readings.>", "maintenance.tick")) == ("readings.>",)

    def test_the_binding_prefixes_the_subject_per_site(self, source):
        binding = source.binding("site_readings", ("readings.>",), source.connections()["site_b"])
        assert binding.subject_prefix == "site.site_b."
        assert binding.filter_subjects == ("site.site_b.readings.>",)
        assert binding.deliver_subject == "deliver.site_b.site_readings"
        assert binding.stream == "READINGS_SITE_B"
        assert binding.local_subject("site.site_b.readings.recorded") == "readings.recorded"

    def test_no_binding_for_an_agent_that_declares_no_readings(self, source):
        assert source.binding("other", ("maintenance.tick",), source.connections()["site_a"]) is None


class TestValidate:
    def test_matching_subject_and_source_run(self, source):
        assert source.validate("site_a", "site.site_a.readings.recorded", _event("/sites/site_a")) is None

    def test_a_subject_of_another_site_is_refused(self, source):
        assert "not under" in source.validate("site_a", "site.site_b.readings.recorded", _event("/sites/site_a"))

    def test_an_event_claiming_another_site_is_refused(self, source):
        assert "event source" in source.validate("site_a", "site.site_a.readings.recorded", _event("/sites/site_b"))


class TestRunScope:
    def test_the_run_sees_its_sites_settings_and_nothing_after(self, source):
        with source.run_scope("site_b"):
            assert current_site().name == "site_b"
            assert current_site().alert_threshold == 80.0
        with pytest.raises(LookupError):
            current_site()

    async def test_concurrent_runs_see_their_own_site(self, source):
        seen: dict[str, str] = {}

        async def run(site: str) -> None:
            with source.run_scope(site):
                await asyncio.sleep(0.01)
                seen[site] = current_site().name

        await asyncio.gather(asyncio.create_task(run("site_a")), asyncio.create_task(run("site_b")))
        assert seen == {"site_a": "site_a", "site_b": "site_b"}
