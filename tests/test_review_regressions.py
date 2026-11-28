"""Regression tests for all code-review findings on PR #106."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from twitter_cli import auth, cache, graphql
from twitter_cli.article import article_markdown_to_content_state
from twitter_cli.cli import cli
from twitter_cli.client import (
    TwitterClient,
    _is_stale_query_error,
    _twitter_deeplink_to_url,
)
from twitter_cli.exceptions import MediaUploadError, TwitterAPIError
from twitter_cli.models import UserProfile
from twitter_cli.parser import (
    _extract_author,
    _render_article_text_block,
    parse_tweet_result,
    parse_user_result,
)
from twitter_cli.text import tweet_create_route, tweet_weighted_length


# ── 1. GraphQL stale-retry fallthrough, Vite asset URLs, cache TTL ───────


def test_stale_query_retry_skips_stale_github_id_and_scans_bundles(monkeypatch) -> None:
    monkeypatch.setattr(graphql, "_cached_query_ids", {})
    monkeypatch.setattr(graphql, "_disk_cache_loaded", True)
    monkeypatch.setattr(graphql, "_bundles_scanned", False)

    stale_id = graphql.FALLBACK_QUERY_IDS["HomeTimeline"]
    fresh_id = "FRESH_FROM_BUNDLE_999"

    def fake_fetch(url: str, headers=None) -> str:
        if url == graphql.TWITTER_OPENAPI_URL:
            # Simulates twitter-openapi lagging behind X with the same stale ID.
            return json.dumps({"HomeTimeline": {"queryId": stale_id}})
        if url == "https://x.com/i/jf/":
            return '<script src="https://abs.twimg.com/x-web/x-web/assets/index-abc.js"></script>'
        if url == "https://abs.twimg.com/x-web/x-web/assets/index-abc.js":
            # Also exercises Vite /x-web/x-web/assets/ chunk anchoring (no /assets/assets/).
            return 'import("./assets/chunk-1.js");'
        if url == "https://abs.twimg.com/x-web/x-web/assets/chunk-1.js":
            return 'queryId:"%s",operationName:"HomeTimeline"' % fresh_id
        raise AssertionError("Unexpected URL fetched: %s" % url)

    resolved = graphql._resolve_query_id(
        "HomeTimeline",
        prefer_fallback=False,
        url_fetch_fn=fake_fetch,
        exclude_ids={stale_id},
    )
    assert resolved == fresh_id


def test_disk_query_id_cache_preserves_created_at_and_refresh_replaces(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "query_ids_cache.json"
    monkeypatch.setattr(graphql, "_qid_cache_path", lambda: cache_file)
    monkeypatch.setattr(graphql, "_cached_query_ids", {})
    monkeypatch.setattr(graphql, "_disk_cache_loaded", False)
    monkeypatch.setattr(graphql, "_bundles_scanned", False)

    old_ts = time.time() - 3600
    cache_file.write_text(
        json.dumps({"created_at": old_ts, "query_ids": {"OldOp": "OLD1"}}),
        encoding="utf-8",
    )

    # Incremental save must NOT reset created_at (prevents immortal stale entries).
    graphql._save_disk_query_ids({"NewOp": "NEW1"})
    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["created_at"] == pytest.approx(old_ts, abs=1.0)
    assert saved["query_ids"] == {"OldOp": "OLD1", "NewOp": "NEW1"}

    # refresh_query_ids must replace old entries and reset created_at.
    def fake_fetch(url: str, headers=None) -> str:
        if url == graphql.TWITTER_OPENAPI_URL:
            return json.dumps({"FreshOp": {"queryId": "FRESH1"}})
        return "<html></html>"

    refreshed = graphql.refresh_query_ids(fake_fetch)
    assert refreshed == {"FreshOp": "FRESH1"}
    reloaded = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "OldOp" not in reloaded["query_ids"]
    assert reloaded["query_ids"] == {"FreshOp": "FRESH1"}
    assert reloaded["created_at"] > old_ts


# ── 2. Atomic owner-only cache write (symlink safety) ────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_open_owner_only_replaces_symlink_without_touching_target(tmp_path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    link = tmp_path / "cache.json"
    link.symlink_to(victim)

    with cache._open_owner_only(link) as f:
        f.write('{"ok": true}')

    assert victim.read_text(encoding="utf-8") == "precious"
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8")) == {"ok": True}


# ── 3. Client: HTTP 400 stale error, TweetDetail ancestors/count<=0, media, deeplinks ─


def test_is_stale_query_error_detects_http_400_persisted_query_not_found() -> None:
    assert _is_stale_query_error(TwitterAPIError(400, "Twitter API error 400: Query: Unspecified"))
    assert _is_stale_query_error(TwitterAPIError(400, "PersistedQueryNotFound"))
    assert not _is_stale_query_error(TwitterAPIError(400, "Bad request: missing text"))


def test_fetch_tweet_detail_preserves_focal_tweet_when_ancestors_exceed_count(tweet_factory) -> None:
    client = TwitterClient.__new__(TwitterClient)
    client._max_count = 200
    client._request_delay = 0.0

    ancestor1 = tweet_factory("100")
    ancestor2 = tweet_factory("101")
    focal = tweet_factory("102")
    reply = tweet_factory("103")

    with patch.object(client, "_graphql_get", return_value={}):
        with patch(
            "twitter_cli.client.parse_timeline_response",
            return_value=([ancestor1, ancestor2, focal, reply], "next-c"),
        ):
            tweets, cursor = client.fetch_tweet_detail("102", count=1, return_cursor=True)

    assert [t.id for t in tweets] == ["102"]
    assert cursor == "next-c"
    assert client.fetch_tweet_detail("102", count=0, return_cursor=True) == ([], None)
    assert client.fetch_tweet_detail("102", count=0, return_cursor=False) == []


@patch("twitter_cli.client.time.sleep")
@patch("twitter_cli.client._get_cffi_session")
def test_upload_gif_uses_tweet_gif_and_polls_status(mock_session, _mock_sleep, tmp_path) -> None:
    gif = tmp_path / "anim.gif"
    gif.write_bytes(b"GIF89a\x01\x00")

    sess = MagicMock()
    sess.post = MagicMock(
        side_effect=[
            MagicMock(status_code=200, text='{"media_id_string": "gif-1"}'),
            MagicMock(status_code=204, text=""),
            MagicMock(
                status_code=200,
                text='{"processing_info": {"state": "in_progress", "check_after_secs": null}}',
            ),
        ]
    )
    sess.get = MagicMock(
        return_value=MagicMock(status_code=200, text='{"processing_info": {"state": "succeeded"}}')
    )
    mock_session.return_value = sess

    client = TwitterClient.__new__(TwitterClient)
    client._auth_token = "tok"
    client._ct0 = "ct0"
    client._cookie_string = None
    client._client_transaction = MagicMock()
    client._client_transaction.generate_transaction_id.return_value = "tid"
    client._ct_init_attempted = True

    assert client.upload_media(str(gif)) == "gif-1"
    assert sess.post.call_args_list[0].kwargs["data"]["media_category"] == "tweet_gif"
    assert sess.get.call_count == 1


def test_upload_media_rejects_empty_and_unsupported_video(tmp_path) -> None:
    client = TwitterClient.__new__(TwitterClient)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(MediaUploadError, match="File is empty"):
        client.upload_media(str(empty))

    avi = tmp_path / "clip.avi"
    avi.write_bytes(b"\x00" * 16)
    with pytest.raises(MediaUploadError, match="Unsupported video format"):
        client.upload_media(str(avi))


def test_twitter_deeplink_to_url_handles_trending_query_and_search_without_slash() -> None:
    assert _twitter_deeplink_to_url("twitter://trending/12345?source=explore") == (
        "https://x.com/i/trending/12345"
    )
    assert _twitter_deeplink_to_url("twitter://search?query=ai%20agents") == (
        "https://x.com/search?q=ai%20agents"
    )


# ── 4. Auth: TWITTER_COOKIE_STRING sync/sanitization, Zen Flatpak, DPAPI ─


def test_cookie_string_env_override_syncs_cookie_header_and_strips_prefix(monkeypatch) -> None:
    monkeypatch.setenv(
        "TWITTER_COOKIE_STRING",
        'Cookie: auth_token="old_tok"; ct0="old_ct0"; guest_id=v1%3Dabc==\r\n',
    )
    monkeypatch.setenv("TWITTER_CT0", "new_ct0")

    cookies = auth.load_from_env()
    assert cookies is not None
    assert cookies["auth_token"] == "old_tok"
    assert cookies["ct0"] == "new_ct0"
    assert "ct0=new_ct0" in cookies["cookie_string"]
    assert "old_ct0" not in cookies["cookie_string"]
    assert "guest_id=v1%3Dabc==" in cookies["cookie_string"]
    assert not cookies["cookie_string"].lower().startswith("cookie:")


def test_cookie_string_incomplete_without_ct0_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("TWITTER_COOKIE_STRING", "auth_token=only_auth; twid=1")
    assert auth.load_from_env() is None


def test_windows_dpapi_diagnostic_matches_dpapi_error(monkeypatch) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    hint = auth._diagnose_keychain_issues(["chrome: Failed to decrypt the cipher text with DPAPI"])
    assert hint is not None
    assert "DPAPI" in hint


def test_zen_linux_discovers_flatpak_config_zen_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth.sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    cookie_db = tmp_path / ".var" / "app" / "app.zen_browser.zen" / "config" / "zen" / "p1.default" / "cookies.sqlite"
    cookie_db.parent.mkdir(parents=True)
    cookie_db.write_text("x", encoding="utf-8")

    found = auth._iter_zen_cookie_files()
    assert str(cookie_db) in found


# ── 5. Parser: Draft.js UTF-16 emoji offsets & null-safe user dicts ──────


def test_draft_js_emoji_utf16_roundtrip() -> None:
    state = article_markdown_to_content_state("🚀 [Click here](https://x.com)")
    block = state["blocks"][0]
    entity_map = {item["key"]: item["value"] for item in state["entity_map"]}
    rendered = _render_article_text_block(
        {
            "text": block["text"],
            "entityRanges": block["entity_ranges"],
            "inlineStyleRanges": [],
        },
        entity_map,
    )
    assert rendered == "🚀 [Click here](https://x.com)"


def test_draft_js_emoji_utf16_bold_offset() -> None:
    rendered = _render_article_text_block(
        {
            "text": "🚀 Hello world!",
            "entityRanges": [],
            "inlineStyleRanges": [{"offset": 3, "length": 5, "style": "Bold"}],
        },
        {},
    )
    assert rendered == "🚀 **Hello** world!"


def test_parser_handles_null_nested_user_dicts_and_null_strings() -> None:
    author = _extract_author(
        {
            "rest_id": "42",
            "core": None,
            "avatar": None,
            "relationship_counts": None,
            "relationship_perspectives": None,
        },
        None,
    )
    assert author.id == "42"
    assert author.name == "Unknown"

    profile = parse_user_result(
        {
            "rest_id": "42",
            "core": {"name": None, "screen_name": "alice", "created_at": None},
            "profile_bio": {"description": None},
            "website": {"url": None},
            "legacy": {"description": None, "location": None},
        }
    )
    assert profile is not None
    assert profile.bio == ""
    assert profile.url == ""
    assert profile.name == ""
    assert profile.created_at == ""

    tweet = parse_tweet_result(
        {
            "rest_id": "10",
            "legacy": {"full_text": "hi"},
            "core": {"user_results": {"result": {"rest_id": "42", "legacy": None, "core": None}}},
        }
    )
    assert tweet is not None
    assert tweet.author.id == "42"


# ── 6. Text weighting & Article Markdown edge cases ──────────────────────


def test_text_bare_url_ignores_filenames_emails_and_prose() -> None:
    assert tweet_weighted_length("config.yaml") == len("config.yaml")
    assert tweet_weighted_length("README.md") == len("README.md")
    assert tweet_weighted_length("cli.py") == len("cli.py")
    assert tweet_weighted_length("Hello.World") == len("Hello.World")
    assert tweet_weighted_length("user.com@example.com") == len("user.com@example.com")
    assert tweet_weighted_length("https://example.com") == 23
    assert tweet_weighted_length("Visit x.com/home today") == len("Visit ") + 23 + len(" today")
    assert tweet_weighted_length("(https://example.com/foo.)") == 1 + 23 + 2
    assert tweet_weighted_length("©®") == 2
    assert tweet_weighted_length("©️") == 2
    assert tweet_weighted_length("▶️") == 2
    assert tweet_weighted_length("🐦‍⬛") == 2
    op, _ = tweet_create_route("Edited config.yaml and cli.py " + "a" * 240)
    assert op == "CreateTweet"


def test_article_markdown_handles_inline_code_images_math_parens_h3_and_single_line_ticks() -> None:
    md = "\n".join(
        [
            "### Sub Heading",
            "Use `[label](https://x.com)` and compute 2 * 3 * 4 now",
            "See [Py](https://en.wikipedia.org/wiki/Python_(lang)) and ![pic](https://pbs.twimg.com/a.png)",
            "```inline``` stays paragraph",
            "Following paragraph survives",
        ]
    )
    state = article_markdown_to_content_state(md)
    blocks = state["blocks"]
    assert blocks[0]["type"] == "header-three"
    assert blocks[0]["text"] == "Sub Heading"

    # Inline code link must NOT become an entity, and `2 * 3 * 4` keeps asterisks.
    assert blocks[1]["text"] == "Use [label](https://x.com) and compute 2 * 3 * 4 now"
    assert blocks[1]["entity_ranges"] == []

    # Balanced-paren URL captured intact; image NOT turned into a link entity.
    assert len(blocks[2]["entity_ranges"]) == 1
    link_entity = state["entity_map"][blocks[2]["entity_ranges"][0]["key"]]["value"]
    assert link_entity["data"]["url"] == "https://en.wikipedia.org/wiki/Python_(lang)"
    assert "![pic](https://pbs.twimg.com/a.png)" in blocks[2]["text"]

    # Single-line triple backticks do not swallow following paragraphs.
    assert len(blocks) == 5
    assert blocks[4]["text"] == "Following paragraph survives"


# ── 7. CLI: structured error guards, upfront media checks, news, doctor, likes ─


def test_write_action_invalid_id_emits_structured_json_error() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["like", "not-a-valid-id", "--json"])
    assert res.exit_code == 1
    payload = json.loads(res.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"


def test_article_publish_rejects_empty_and_non_utf8_files(tmp_path) -> None:
    runner = CliRunner()
    empty = tmp_path / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    res_empty = runner.invoke(cli, ["article-publish", str(empty), "--title", "Hi", "--json"])
    assert res_empty.exit_code == 1
    assert json.loads(res_empty.output)["error"]["code"] == "invalid_input"

    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00")
    res_bad = runner.invoke(cli, ["article-publish", str(bad), "--title", "Hi", "--json"])
    assert res_bad.exit_code == 1
    assert json.loads(res_bad.output)["error"]["code"] == "invalid_input"


def test_post_rejects_mismatched_media_mime_before_auth(tmp_path) -> None:
    runner = CliRunner()
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00" * 16)
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    res_vid_as_img = runner.invoke(cli, ["post", "hi", "--image", str(vid)])
    assert res_vid_as_img.exit_code == 2
    assert "Unsupported image format" in res_vid_as_img.output

    res_img_as_vid = runner.invoke(cli, ["post", "hi", "--video", str(img)])
    assert res_img_as_vid.exit_code == 2
    assert "Unsupported video format" in res_img_as_vid.output


def test_news_rejects_non_positive_max() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["news", "--max", "0"])
    assert res.exit_code == 2


def test_doctor_refresh_and_error_exit_code(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setenv("TWITTER_COOKIE_STRING", "auth_token=super_secret_auth; ct0=super_secret_ct0")
    monkeypatch.setattr(
        "twitter_cli.cli.refresh_query_ids",
        lambda _fetch: {"HomeTimeline": "LIVE_ID"},
    )
    res = runner.invoke(cli, ["doctor", "--refresh", "--json"])
    assert res.exit_code == 0
    assert "super_secret_auth" not in res.output
    assert "super_secret_ct0" not in res.output
    data = json.loads(res.output)["data"]
    qid_check = next(c for c in data["checks"] if c["category"] == "query_ids")
    assert qid_check["status"] == "pass"
    assert "Refreshed 1 live queryIds" in qid_check["message"]

    # Expired query_ids cache -> warning
    qid_cache = tmp_path / "expired_qids.json"
    qid_cache.write_text(
        json.dumps({"created_at": time.time() - 90000, "query_ids": {"HomeTimeline": "OLD"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("twitter_cli.cli._qid_cache_path", lambda: qid_cache)
    res_exp = runner.invoke(cli, ["doctor", "--json"])
    assert res_exp.exit_code == 0
    qid_exp = next(c for c in json.loads(res_exp.output)["data"]["checks"] if c["category"] == "query_ids")
    assert qid_exp["status"] == "warning"
    assert "expired" in qid_exp["message"]


def test_likes_own_numeric_id_does_not_warn_private_likes(monkeypatch, tweet_factory) -> None:
    from twitter_cli import cli as cli_module

    me = UserProfile(id="42", name="Alice", screen_name="alice")
    fake_client = MagicMock()
    fake_client.fetch_user.return_value = me
    fake_client.fetch_me.return_value = me
    fake_client.fetch_user_likes.return_value = [tweet_factory("1")]

    monkeypatch.setattr(cli_module, "_get_client", lambda *_a, **_kw: fake_client)
    runner = CliRunner()
    res = runner.invoke(cli, ["likes", "42"])
    assert res.exit_code == 0
    assert "private since June 2024" not in res.output
