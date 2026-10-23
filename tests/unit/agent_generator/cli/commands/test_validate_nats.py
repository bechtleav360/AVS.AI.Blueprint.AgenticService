"""``asbs validate`` reports the NATS delivery keys that would otherwise fail only at startup."""

from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.validate import _nats_findings


def _project(tmp_path: Path, settings: str) -> Path:
    (tmp_path / "settings.toml").write_text(settings, encoding="utf-8")
    return tmp_path


class TestNatsFindings:
    def test_a_project_without_the_keys_has_no_findings(self, tmp_path: Path) -> None:
        assert _nats_findings(_project(tmp_path, '[default]\napp_name = "x"\n')) == []

    def test_no_settings_file_has_no_findings(self, tmp_path: Path) -> None:
        assert _nats_findings(tmp_path) == []

    @pytest.mark.parametrize(
        "line",
        [
            "nats_max_concurrent_runs = 4",
            'nats_max_concurrent_runs = "25%"',
            "nats_extra_runs_per_process = 0",
            "nats_handler_timeout = 30.5",
            'nats_connections_readiness = "any"',
            'nats_unclaimed_subjects = "default_connection"',
        ],
    )
    def test_valid_values_pass(self, tmp_path: Path, line: str) -> None:
        assert _nats_findings(_project(tmp_path, f"[default]\n{line}\n")) == []

    @pytest.mark.parametrize(
        ("line", "named"),
        [
            ("nats_max_concurrent_runs = 0", "nats_max_concurrent_runs"),
            ('nats_max_concurrent_runs = "150%"', "nats_max_concurrent_runs"),
            ("nats_extra_runs_per_process = -1", "nats_extra_runs_per_process"),
            ("nats_handler_timeout = 0", "nats_handler_timeout"),
            ('nats_handler_timeout = "soon"', "nats_handler_timeout"),
            ('nats_connections_readiness = "some"', "nats_connections_readiness"),
            ('nats_unclaimed_subjects = "drop"', "nats_unclaimed_subjects"),
        ],
    )
    def test_a_value_startup_would_refuse_is_an_issue_naming_the_key(self, tmp_path: Path, line: str, named: str) -> None:
        """The same rule as the client's parser, so this command and startup cannot disagree."""
        findings = _nats_findings(_project(tmp_path, f"[default]\n{line}\n"))
        assert len(findings) == 1
        assert named in findings[0]

    def test_a_key_in_the_target_environment_section_is_checked(self, tmp_path: Path) -> None:
        findings = _nats_findings(_project(tmp_path, "[production]\nnats_max_concurrent_runs = 0\n"))
        assert findings and "nats_max_concurrent_runs" in findings[0]

    def test_a_key_in_another_environment_section_is_not(self, tmp_path: Path) -> None:
        """'[orders]' in the process's own file is an environment named orders to Dynaconf, not a scope."""
        assert _nats_findings(_project(tmp_path, "[orders]\nnats_max_concurrent_runs = 0\n")) == []
        assert _nats_findings(_project(tmp_path, "[development]\nnats_max_concurrent_runs = 0\n")) == []
        assert _nats_findings(_project(tmp_path, "[development]\nnats_max_concurrent_runs = 0\n"), "development") != []


class TestConnectionSource:
    def test_a_path_without_an_attribute_is_an_issue(self, tmp_path: Path) -> None:
        findings = _nats_findings(_project(tmp_path, '[default]\nnats_connection_source = "deploy.sources"\n'))
        assert findings and "package.module:attribute" in findings[0]

    def test_a_module_that_does_not_exist_is_an_issue(self, tmp_path: Path) -> None:
        findings = _nats_findings(_project(tmp_path, '[default]\nnats_connection_source = "no_such_pkg_x1.sources:make"\n'))
        assert findings and "no_such_pkg_x1" in findings[0]

    def test_a_module_in_the_project_is_found_without_being_executed(self, tmp_path: Path) -> None:
        """Only found, never run: the factory reads deployment data that may not exist here."""
        package = tmp_path / "deploy_src_y2"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "sources.py").write_text("raise RuntimeError('executed')\n", encoding="utf-8")
        findings = _nats_findings(_project(tmp_path, '[default]\nnats_connection_source = "deploy_src_y2.sources:make"\n'))
        assert findings == []
