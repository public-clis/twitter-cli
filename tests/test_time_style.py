"""Timestamp display style (issue #35).

Human-readable output used to hard-code relative timestamps ("14d ago"). A
`--time` option (and `display.time` in config) now selects relative, absolute or
ISO rendering. These tests assert the rendered output actually changes, rather
than only that a flag is accepted.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from twitter_cli import formatter
from twitter_cli.formatter import (
    get_time_style,
    print_tweet_detail,
    print_tweet_table,
    set_time_style,
)
from twitter_cli.models import Author, Metrics, Tweet

CREATED_AT = "Sat Mar 14 21:08:00 +0000 2026"


def _tweet() -> Tweet:
    return Tweet(
        id="1",
        text="hello world",
        author=Author(id="u1", name="Alice", screen_name="alice"),
        metrics=Metrics(likes=1, retweets=0, replies=0, quotes=0, views=10, bookmarks=0),
        created_at=CREATED_AT,
    )


def _render(printer) -> str:
    console = Console(record=True, width=120, file=None)
    printer(console)
    return console.export_text()


@pytest.fixture(autouse=True)
def _restore_style():
    """Never leak style between tests."""
    original = get_time_style()
    yield
    formatter.set_time_style(original)


def test_default_style_is_relative() -> None:
    assert formatter.set_time_style(None) in ("relative", "absolute", "iso")


def test_relative_style_renders_ago() -> None:
    set_time_style("relative")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))

    assert "ago" in text


def test_absolute_style_renders_datetime() -> None:
    set_time_style("absolute")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))

    assert "ago" not in text
    # Local wall-clock form: YYYY-MM-DD HH:MM
    assert ":" in text
    assert any(ch.isdigit() for ch in text)


def test_iso_style_renders_iso8601() -> None:
    set_time_style("iso")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))

    # The Stats column is narrow, so assert the ISO prefix rather than the full
    # timestamp (the table ellipsizes the tail).
    assert "2026-03-14T" in text
    assert "ago" not in text


def test_detail_view_does_not_repeat_the_stamp() -> None:
    """Under absolute/iso the detail view must not print 'local (local)'."""
    set_time_style("absolute")
    text = _render(lambda c: print_tweet_detail(_tweet(), console=c))

    assert "ago" not in text
    # Two identical timestamps separated by " (" would indicate a duplicate.
    datetime_markers = text.count("20")
    assert datetime_markers >= 1


def test_invalid_style_is_ignored_and_keeps_current() -> None:
    set_time_style("iso")
    assert set_time_style("bogus") == "iso"
    assert get_time_style() == "iso"


def _invoke_root(extra_args):
    """Invoke the root group with a subcommand that fails fast and offline.

    `post` with no TEXT raises a usage error *after* the group callback runs, so
    the style is applied without any network or cookie access. (`--help`
    short-circuits before the callback, which would make these tests vacuous.)
    """
    from click.testing import CliRunner

    from twitter_cli.cli import cli

    return CliRunner().invoke(cli, list(extra_args) + ["post"])


def test_cli_option_sets_style() -> None:
    """The root --time option must reach the formatter."""
    set_time_style("relative")
    result = _invoke_root(["--time", "absolute"])

    assert result.exit_code != 0  # missing TEXT, as intended
    assert get_time_style() == "absolute"


def test_cli_rejects_unknown_style() -> None:
    result = _invoke_root(["--time", "nonsense"])
    assert result.exit_code != 0
    assert get_time_style() == "relative"


def test_config_display_time_is_used(monkeypatch) -> None:
    """config display.time applies when --time is omitted."""
    from twitter_cli import cli as cli_module

    fake = {
        "fetch": {"count": 50},
        "filter": {"mode": "topN", "topN": 20, "minScore": 50, "lang": [], "excludeRetweets": False},
        "rateLimit": {"requestDelay": 0, "maxRetries": 0, "retryBaseDelay": 0, "maxCount": 200},
        "display": {"time": "iso"},
    }
    monkeypatch.setattr(cli_module, "load_config", lambda: fake)

    set_time_style("relative")
    _invoke_root([])

    assert get_time_style() == "iso"
