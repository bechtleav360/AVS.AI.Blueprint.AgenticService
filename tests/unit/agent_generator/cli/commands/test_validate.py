"""Unit tests for the `asbs validate` idempotency notice (P4, spec sec. 7.4)."""

from pathlib import Path

from blueprint.agent_generator.cli.commands.validate import IDEMPOTENCY_NOTICE, _idempotency_notice


def _project(tmp_path: Path, settings: str | None = None, *, with_handler: bool = True) -> Path:
    """Build the smallest project shape the notice looks at."""
    handlers = tmp_path / "src" / "handlers"
    handlers.mkdir(parents=True)
    if with_handler:
        (handlers / "order_handler.py").write_text("# handler", encoding="utf-8")
    if settings is not None:
        (tmp_path / "settings.toml").write_text(settings, encoding="utf-8")
    return tmp_path


class TestIdempotencyNotice:
    def test_handlers_without_the_key_are_notified(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\napp_name = "demo"\n')
        assert _idempotency_notice(project) == IDEMPOTENCY_NOTICE

    def test_opting_in_silences_the_notice(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[default]\nidempotency_enabled = true\nidempotency_ttl = 1500\n")
        assert _idempotency_notice(project) is None

    def test_opting_out_explicitly_also_silences_it(self, tmp_path: Path) -> None:
        """Declaring the key is the decision spec sec. 7.4 asks for, whichever way it goes."""
        project = _project(tmp_path, "[default]\nidempotency_enabled = false\n")
        assert _idempotency_notice(project) is None

    def test_top_level_key_without_an_environment_table_counts(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "idempotency_enabled = true\nidempotency_ttl = 60\n")
        assert _idempotency_notice(project) is None

    def test_a_project_with_no_handlers_is_not_notified(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\napp_name = "demo"\n', with_handler=False)
        assert _idempotency_notice(project) is None

    def test_missing_settings_file_is_notified(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        assert _idempotency_notice(project) == IDEMPOTENCY_NOTICE

    def test_unparseable_settings_file_stays_quiet(self, tmp_path: Path) -> None:
        """A broken settings.toml has its own report; guessing at the key would add noise."""
        project = _project(tmp_path, "[default\nthis is not toml\n")
        assert _idempotency_notice(project) is None
