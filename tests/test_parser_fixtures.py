from __future__ import annotations

from twitter_cli.client import TwitterClient
from twitter_cli.parser import _deep_get, _extract_media, parse_timeline_response, parse_user_result


def _make_client() -> TwitterClient:
    client = TwitterClient.__new__(TwitterClient)
    client._ct_init_attempted = True
    client._client_transaction = None
    client._request_delay = 0.0
    client._max_retries = 0
    client._retry_base_delay = 0.0
    client._max_count = 200
    return client


def test_parse_home_timeline_fixture(fixture_loader) -> None:
    payload = fixture_loader("home_timeline.json")

    tweets, cursor = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
    )

    assert [tweet.id for tweet in tweets] == ["1", "20"]
    assert cursor == "cursor-bottom-1"
    assert tweets[0].media[0].type == "photo"
    # note_tweet full text should be preferred over legacy.full_text for long tweets
    assert "Show More" in tweets[0].text
    assert tweets[0].text.startswith("Hello\nworld\n")
    assert tweets[0].urls == ["https://example.com/post"]
    assert tweets[1].is_retweet is True
    assert tweets[1].retweeted_by == "bob"
    assert tweets[1].quoted_tweet is not None
    assert tweets[1].quoted_tweet.id == "30"


def test_parse_home_timeline_fixture_marks_promoted_entries(fixture_loader) -> None:
    payload = fixture_loader("home_timeline.json")
    entry = payload["data"]["home"]["home_timeline_urt"]["instructions"][0]["entries"][0]
    entry["entryId"] = "promoted-tweet-1-demo"
    entry["content"]["itemContent"]["promotedMetadata"] = {"impressionId": "demo"}

    tweets, _ = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
    )

    assert tweets[0].is_promoted is True
    assert tweets[1].is_promoted is False


def test_parse_tweet_detail_fixture_with_nested_items(fixture_loader) -> None:
    payload = fixture_loader("tweet_detail.json")

    tweets, cursor = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "threaded_conversation_with_injections_v2", "instructions"),
    )

    assert [tweet.id for tweet in tweets] == ["100", "101"]
    assert cursor == "conversation-cursor"


def test_parse_search_timeline_fixture_with_module_items(fixture_loader) -> None:
    payload = fixture_loader("search_timeline.json")

    tweets, cursor = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions"),
    )

    assert [tweet.id for tweet in tweets] == ["500"]
    assert cursor == "search-cursor"
    assert tweets[0].media[0].type == "video"
    assert tweets[0].media[0].url == "https://video-high.mp4"


def test_parse_list_timeline_fixture_with_visibility_wrapper(fixture_loader) -> None:
    payload = fixture_loader("list_timeline.json")

    tweets, cursor = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "list", "tweets_timeline", "timeline", "instructions"),
    )

    assert [tweet.id for tweet in tweets] == ["700"]
    assert cursor == "list-cursor"
    assert tweets[0].author.verified is True
    assert tweets[0].lang == "zh"
    assert tweets[0].is_subscriber_only is True


def test_fetch_user_list_with_fixture(monkeypatch, fixture_loader) -> None:
    client = _make_client()
    payload = fixture_loader("followers_page.json")
    monkeypatch.setattr(client, "_graphql_get", lambda operation_name, variables, features: payload)

    users = client._fetch_user_list(
        "Followers",
        "user-id",
        20,
        lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
    )

    assert len(users) == 1
    assert users[0].screen_name == "follower1"
    assert users[0].verified is True


def test_parse_sensitive_media_and_thread_metadata(fixture_loader) -> None:
    payload = fixture_loader("home_timeline.json")
    entry = payload["data"]["home"]["home_timeline_urt"]["instructions"][0]["entries"][0]
    tweet_res = entry["content"]["itemContent"]["tweet_results"]["result"]
    legacy = tweet_res["legacy"]
    legacy["possibly_sensitive"] = True
    legacy["conversation_id_str"] = "1"
    legacy["in_reply_to_status_id_str"] = "999"
    legacy["in_reply_to_user_id_str"] = "42"
    legacy["in_reply_to_screen_name"] = "parent_user"
    legacy["extended_entities"]["media"][0]["ext_sensitive_media_warning"] = {
        "adult_content": True,
        "graphic_violence": False,
        "other": False,
    }
    legacy["extended_entities"]["media"][0]["ext_alt_text"] = "A cat"
    user_legacy = tweet_res["core"]["user_results"]["result"]["legacy"]
    user_legacy["followers_count"] = 1234
    user_legacy["friends_count"] = 56
    user_legacy["following"] = True
    user_legacy["followed_by"] = False

    tweets, _ = parse_timeline_response(
        payload,
        lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
    )

    t = tweets[0]
    assert t.possibly_sensitive is True
    assert t.conversation_id == "1"
    assert t.in_reply_to_status_id == "999"
    assert t.in_reply_to_user_id == "42"
    assert t.in_reply_to_screen_name == "parent_user"
    assert t.media[0].adult_content is True
    assert t.media[0].graphic_violence is False
    assert t.media[0].alt_text == "A cat"
    assert t.author.followers_count == 1234
    assert t.author.following_count == 56
    assert t.author.viewer_following is True
    assert t.author.viewer_followed_by is False


def test_extract_media_reads_nested_warning_and_video_poster() -> None:
    legacy = {
        "extended_entities": {
            "media": [
                {
                    "type": "video",
                    "media_url_https": "https://pbs.twimg.com/thumb.jpg",
                    "original_info": {"width": 1280, "height": 720},
                    "video_info": {
                        "duration_millis": 15000,
                        "variants": [
                            {"content_type": "video/mp4", "bitrate": 832000, "url": "https://v.mp4"}
                        ],
                    },
                    "media_results": {
                        "result": {
                            "sensitive_media_warning": {"graphic_violence": True}
                        }
                    },
                }
            ]
        }
    }
    media = _extract_media(legacy)
    assert len(media) == 1
    assert media[0].url == "https://v.mp4"
    assert media[0].poster_url == "https://pbs.twimg.com/thumb.jpg"
    assert media[0].duration_ms == 15000
    assert media[0].graphic_violence is True
    assert media[0].adult_content is False


def test_parse_user_result_handles_post_legacy_user_by_rest_id_shape() -> None:
    user_data = {
        "rest_id": "44196397",
        "core": {"name": "Elon Musk", "screen_name": "elonmusk", "created_at": "Tue Jun 02 20:12:29 +0000 2009"},
        "avatar": {"image_url": "https://pbs.twimg.com/avatar.jpg"},
        "location": {"location": "Mars"},
        "profile_bio": {"description": "Builder"},
        "website": {"url": "https://x.com"},
        "relationship_counts": {"followers": 200000000, "following": 800},
        "tweet_counts": {"tweets": 50000},
        "action_counts": {"favorites_count": 90000},
        "relationship_perspectives": {"following": True, "followed_by": False},
        "verification": {"verified": True},
    }
    profile = parse_user_result(user_data)
    assert profile is not None
    assert profile.id == "44196397"
    assert profile.screen_name == "elonmusk"
    assert profile.bio == "Builder"
    assert profile.url == "https://x.com"
    assert profile.followers_count == 200000000
    assert profile.following_count == 800
    assert profile.tweets_count == 50000
    assert profile.likes_count == 90000
    assert profile.verified is True
    assert profile.viewer_following is True
    assert profile.viewer_followed_by is False
