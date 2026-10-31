"""Shell completion script generation (issue #36).

Click can emit completion scripts itself, so this needs no extra dependency
(the issue suggested shtab). These tests assert each shell actually produces a
script for `twitter`, not merely that the command succeeds.
"""

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
    assert len(script) > 100, "expected a real script, got %r" % script
    # Each shell's script must register a twitter completion entry point.
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


def test_fish_script_defines_function() -> None:
    result = _run("completion", "fish")

    assert result.exit_code == 0
    assert "function" in result.output


def test_unknown_shell_is_rejected() -> None:
    result = _run("completion", "powershell")

    assert result.exit_code != 0
    assert "powershell" in result.output


def test_completion_requires_a_shell_argument() -> None:
    result = _run("completion")

    assert result.exit_code != 0


def test_completion_lists_known_subcommands() -> None:
    """The generated script should drive completion from the CLI's own tree."""
    result = _run("completion", "zsh")

    assert result.exit_code == 0
    # Click's zsh template shells out to the CLI's completion protocol.
    assert "_TWITTER_COMPLETE" in result.output
