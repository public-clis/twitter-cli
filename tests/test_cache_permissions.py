"""Owner-only permissions for cache artefacts.

The ClientTransaction cache stores the full ``x.com/home`` HTML, which embeds the
session's live ``auth_token``/``ct0``; the index cache stores tweet text the user
has read. Both used to be written with the process umask default (typically
``0644``), so any other local user could read a session off disk.

These assertions are POSIX-only: Windows has no POSIX permission bits and
``os.chmod`` there only toggles the read-only flag, so ``stat.S_IMODE`` returns
``0o666`` regardless.
"""

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
    # Still valid JSON that round-trips.
    assert json.loads(cache_file.read_text(encoding="utf-8"))["tweets"][0]["id"] == "100"


@posix_only
def test_save_tightens_preexisting_world_readable_file(tmp_path, monkeypatch, tweet_factory) -> None:
    cache_file = tmp_path / ".twitter-cli" / "last_results.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{}", encoding="utf-8")
    cache_file.chmod(0o644)  # simulate a file left behind by an older build
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o644

    monkeypatch.setattr(cache, "_CACHE_DIR", cache_file.parent)
    monkeypatch.setattr(cache, "_CACHE_FILE", cache_file)

    cache.save_tweet_cache([_make_tweet(tweet_factory)])

    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600


def test_save_never_raises_on_unwritable_dir(tmp_path, monkeypatch, tweet_factory) -> None:
    """A cache write must never break the command that triggered it."""
    cache_file = tmp_path / "missing" / "last_results.json"
    monkeypatch.setattr(cache, "_CACHE_DIR", cache_file.parent)
    monkeypatch.setattr(cache, "_CACHE_FILE", cache_file)
    # Parent creation will fail because we point at a file, not a directory.
    blocker = tmp_path / "missing"
    blocker.write_text("not a directory", encoding="utf-8")

    cache.save_tweet_cache([_make_tweet(tweet_factory)])  # must not raise

    assert not cache_file.exists()


def test_client_transaction_cache_is_owner_only(tmp_path, monkeypatch) -> None:
    """The CT cache embeds auth_token/ct0 and must be created owner-only."""
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
    """The create mode itself is narrow, not just a post-hoc chmod."""
    target = tmp_path / "secret.json"
    with cache._open_owner_only(target) as handle:
        handle.write('{"ok": true}')

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


