"""Timestamp display style (issue #35)."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from twitter_cli import formatter
from twitter_cli.formatter import (
    get_time_style,
    print_article,
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
        article_title="My Article",
        article_text="Body",
    )


def _render(printer) -> str:
    console = Console(record=True, width=120, file=io.StringIO())
    printer(console)
    return console.export_text()


@pytest.fixture(autouse=True)
def _restore_style():
    original = get_time_style()
    yield
    formatter.set_time_style(original)


def test_relative_style_renders_ago(monkeypatch) -> None:
    monkeypatch.setattr(formatter, "format_relative_time", lambda _s: "3d ago")
    set_time_style("relative")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))
    assert "3d ago" in text


def test_absolute_style_renders_datetime() -> None:
    set_time_style("absolute")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))
    assert "ago" not in text
    assert ":" in text


def test_iso_style_renders_full_iso8601_without_truncation() -> None:
    set_time_style("iso")
    text = _render(lambda c: print_tweet_table([_tweet()], console=c))
    assert "2026-03-14T21:08:00+00:00" in text
    assert "ago" not in text


def test_detail_view_does_not_repeat_stamp_under_absolute() -> None:
    set_time_style("absolute")
    text = _render(lambda c: print_tweet_detail(_tweet(), console=c))
    assert "ago" not in text
    assert text.count("2026-03-") == 1


def test_article_view_respects_time_style() -> None:
    set_time_style("iso")
    text = _render(lambda c: print_article(_tweet(), console=c))
    assert "2026-03-14T21:08:00+00:00" in text


def test_set_time_style_none_resets_to_relative() -> None:
    set_time_style("iso")
    assert set_time_style(None) == "relative"
    assert get_time_style() == "relative"


def test_invalid_style_is_ignored() -> None:
    set_time_style("iso")
    assert set_time_style("bogus") == "iso"
    assert get_time_style() == "iso"


def test_cli_option_and_config_set_time_style(monkeypatch) -> None:
    from click.testing import CliRunner
    from twitter_cli import cli as cli_module
    from twitter_cli.cli import cli

    set_time_style("relative")
    result = CliRunner().invoke(cli, ["--time", "absolute", "post"])
    assert result.exit_code != 0
    assert get_time_style() == "absolute"

    fake = {
        "fetch": {"count": 50},
        "display": {"time": "iso"},
        "filter": {"mode": "topN", "topN": 20, "minScore": 50, "lang": [], "excludeRetweets": False},
        "rateLimit": {"requestDelay": 0, "maxRetries": 0, "retryBaseDelay": 0, "maxCount": 200},
    }
    monkeypatch.setattr(cli_module, "load_config", lambda: fake)
    set_time_style("relative")
    CliRunner().invoke(cli, ["post"])
    assert get_time_style() == "iso"
