from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from twitter_cli.models import Author, Metrics, Tweet

os.environ.setdefault("OUTPUT", "rich")


@pytest.fixture(autouse=True)
def _isolate_env_and_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent tests from reading/writing host ~/.twitter-cli caches or host TWITTER_* env vars."""
    from twitter_cli import cache as cache_mod
    from twitter_cli import client as client_mod
    from twitter_cli import graphql as graphql_mod

    for key in list(os.environ):
        if key.startswith("TWITTER_") or key == "XDG_CONFIG_HOME":
            monkeypatch.delenv(key, raising=False)

    cache_dir = tmp_path / ".twitter-cli-test-cache"
    monkeypatch.setattr(cache_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cache_mod, "_CACHE_FILE", cache_dir / "last_results.json")
    monkeypatch.setattr(graphql_mod, "_qid_cache_path", lambda: cache_dir / "query_ids_cache.json")
    monkeypatch.setattr(
        client_mod.TwitterClient,
        "_ct_cache_path",
        staticmethod(lambda: str(cache_dir / "transaction_cache.json")),
    )


@pytest.fixture()
def tweet_factory():
    def _make_tweet(tweet_id: str = "1", **overrides: Any) -> Tweet:
        metrics = overrides.pop(
            "metrics",
            Metrics(likes=10, retweets=2, replies=1, quotes=0, views=120, bookmarks=3),
        )
        author = overrides.pop(
            "author",
            Author(id="u1", name="Alice", screen_name="alice", verified=False),
        )
        return Tweet(
            id=tweet_id,
            text=overrides.pop("text", "hello"),
            author=author,
            metrics=metrics,
            created_at=overrides.pop("created_at", "2025-01-01"),
            media=overrides.pop("media", []),
            urls=overrides.pop("urls", []),
            is_retweet=overrides.pop("is_retweet", False),
            lang=overrides.pop("lang", "en"),
            retweeted_by=overrides.pop("retweeted_by", None),
            quoted_tweet=overrides.pop("quoted_tweet", None),
            score=overrides.pop("score", 0.0),
            article_title=overrides.pop("article_title", None),
            article_text=overrides.pop("article_text", None),
            is_subscriber_only=overrides.pop("is_subscriber_only", False),
            is_promoted=overrides.pop("is_promoted", False),
            possibly_sensitive=overrides.pop("possibly_sensitive", False),
            conversation_id=overrides.pop("conversation_id", None),
            in_reply_to_status_id=overrides.pop("in_reply_to_status_id", None),
            in_reply_to_user_id=overrides.pop("in_reply_to_user_id", None),
            in_reply_to_screen_name=overrides.pop("in_reply_to_screen_name", None),
        )

    return _make_tweet


@pytest.fixture()
def fixture_loader():
    fixture_dir = Path(__file__).parent / "fixtures"

    def _load(name: str) -> Any:
        return json.loads((fixture_dir / name).read_text(encoding="utf-8"))

    return _load
