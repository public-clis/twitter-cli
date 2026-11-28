"""Shell completion script generation (issue #36)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from twitter_cli.cli import cli


def _run(*args: str):
    return CliRunner().invoke(cli, list(args))


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_script_is_emitted(shell: str) -> None:
    result = _run("completion", shell)

    assert result.exit_code == 0, result.output
    script = result.output
    assert len(script) > 100
    assert "twitter" in script


def test_bash_script_defines_completion_function() -> None:
    result = _run("completion", "bash")
    assert result.exit_code == 0
    assert "_twitter_completion" in result.output
    assert "complete" in result.output


def test_zsh_script_is_a_compdef() -> None:
    result = _run("completion", "zsh")
    assert result.exit_code == 0
    assert result.output.lstrip().startswith("#compdef")
    assert "_TWITTER_COMPLETE" in result.output


def test_fish_script_defines_function() -> None:
    result = _run("completion", "fish")
    assert result.exit_code == 0
    assert "function" in result.output


def test_unknown_shell_is_rejected() -> None:
    result = _run("completion", "powershell")
    assert result.exit_code != 0
