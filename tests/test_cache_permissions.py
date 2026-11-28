"""Owner-only permissions for cache artefacts."""

from __future__ import annotations

import json
import os
import stat

import pytest

from twitter_cli import cache

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission bits are not enforced on this OS"
)


def _make_tweet(tweet_factory, tweet_id: str = "100"):
    return tweet_factory(tweet_id=tweet_id, text="cache me")


@posix_only
def test_save_writes_owner_only(tmp_path, monkeypatch, tweet_factory) -> None:
    cache_file = tmp_path / ".twitter-cli" / "last_results.json"
    monkeypatch.setattr(cache, "_CACHE_DIR", cache_file.parent)
    monkeypatch.setattr(cache, "_CACHE_FILE", cache_file)

    cache.save_tweet_cache([_make_tweet(tweet_factory)])

    assert cache_file.exists()
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache_file.parent.stat().st_mode) == 0o700
    assert json.loads(cache_file.read_text(encoding="utf-8"))["tweets"][0]["id"] == "100"


@posix_only
def test_save_tightens_preexisting_world_readable_file(tmp_path, monkeypatch, tweet_factory) -> None:
    cache_file = tmp_path / ".twitter-cli" / "last_results.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{}", encoding="utf-8")
    cache_file.chmod(0o644)
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o644

    monkeypatch.setattr(cache, "_CACHE_DIR", cache_file.parent)
    monkeypatch.setattr(cache, "_CACHE_FILE", cache_file)

    cache.save_tweet_cache([_make_tweet(tweet_factory)])

    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600


def test_save_never_raises_on_unwritable_dir(tmp_path, monkeypatch, tweet_factory) -> None:
    cache_file = tmp_path / "missing" / "last_results.json"
    monkeypatch.setattr(cache, "_CACHE_DIR", cache_file.parent)
    monkeypatch.setattr(cache, "_CACHE_FILE", cache_file)
    blocker = tmp_path / "missing"
    blocker.write_text("not a directory", encoding="utf-8")

    cache.save_tweet_cache([_make_tweet(tweet_factory)])

    assert not cache_file.exists()


def test_client_transaction_cache_is_owner_only(tmp_path, monkeypatch) -> None:
    from twitter_cli.client import TwitterClient

    ct_cache = tmp_path / ".twitter-cli" / "transaction_cache.json"
    monkeypatch.setattr(
        TwitterClient, "_ct_cache_path", staticmethod(lambda: str(ct_cache))
    )

    client = TwitterClient.__new__(TwitterClient)
    client._save_ct_cache("<html>home</html>", "ondemand")

    assert ct_cache.exists()
    payload = json.loads(ct_cache.read_text(encoding="utf-8"))
    assert payload["home_html"] == "<html>home</html>"
    if os.name == "posix":
        assert stat.S_IMODE(ct_cache.stat().st_mode) == 0o600
        assert stat.S_IMODE(ct_cache.parent.stat().st_mode) == 0o700


def test_open_owner_only_uses_restrictive_mode(tmp_path) -> None:
    target = tmp_path / "secret.json"
    with cache._open_owner_only(target) as handle:
        handle.write('{"ok": true}')

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
