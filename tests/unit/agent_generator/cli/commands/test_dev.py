"""Unit tests for the `asbs dev` command (issue #15)."""

import sys
from argparse import Namespace
from unittest.mock import patch

from blueprint.agent_generator.cli.commands import dev


class TestRunInterpreter:
    def test_spawns_uvicorn_with_sys_executable_not_literal_python(self) -> None:
        """The subprocess must use the launching interpreter (venv-correct on Windows),
        not the literal "python" which can resolve to uv's base interpreter."""
        args = Namespace(host="127.0.0.1", port=8000)
        with (
            patch("blueprint.agent_generator.cli.commands.dev.Path") as mock_path,
            patch("blueprint.agent_generator.cli.commands.dev.subprocess.run") as mock_run,
        ):
            mock_path.return_value.exists.return_value = True
            dev.run(args)

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == sys.executable
        assert cmd[0] != "python"
        assert cmd[1:4] == ["-m", "uvicorn", "src.main:app"]
        assert "--reload" in cmd
        assert cmd[-4:] == ["--host", "127.0.0.1", "--port", "8000"]
