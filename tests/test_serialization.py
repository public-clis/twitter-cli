from __future__ import annotations

from twitter_cli.models import Author, TweetMedia
from twitter_cli.serialization import tweet_from_dict, tweet_to_dict, tweets_from_json, tweets_to_json


def test_tweet_roundtrip_dict(tweet_factory) -> None:
    tweet = tweet_factory("42")
    payload = tweet_to_dict(tweet)
    restored = tweet_from_dict(payload)

    assert restored.id == tweet.id
    assert restored.author.screen_name == tweet.author.screen_name
    assert restored.metrics.likes == tweet.metrics.likes


def test_tweets_json_roundtrip(tweet_factory) -> None:
    tweets = [tweet_factory("1"), tweet_factory("2", lang="zh")]
    raw = tweets_to_json(tweets)
    restored = tweets_from_json(raw)

    assert [tweet.id for tweet in restored] == ["1", "2"]
    assert restored[1].lang == "zh"


def test_tweets_from_json_accepts_structured_success_envelope(tweet_factory) -> None:
    tweets = [tweet_factory("1")]
    raw = (
        "{\n"
        '  "ok": true,\n'
        '  "schema_version": "1",\n'
        '  "data": %s\n'
        "}\n"
    ) % tweets_to_json(tweets)

    restored = tweets_from_json(raw)

    assert [tweet.id for tweet in restored] == ["1"]


def test_compact_serialization(tweet_factory) -> None:
    from twitter_cli.serialization import tweet_to_compact_dict, tweets_to_compact_json
    import json

    tweet = tweet_factory(
        "42",
        created_at="Sat Mar 07 05:51:02 +0000 2026",
        text="A" * 200,
    )
    compact = tweet_to_compact_dict(tweet)

    assert compact["id"] == "42"
    assert compact["author"] == "@alice"
    assert compact["time"] == "Mar 07 05:51"
    assert len(compact["text"]) <= 140
    assert compact["text"].endswith("...")
    assert compact["likes"] == 10
    assert compact["rts"] == 2
    # Should only have 6 keys
    assert set(compact.keys()) == {"id", "author", "text", "likes", "rts", "time"}

    # Test batch serialization
    raw = tweets_to_compact_json([tweet])
    parsed = json.loads(raw)
    assert len(parsed) == 1
    assert parsed[0]["author"] == "@alice"


def test_tweet_roundtrip_preserves_article_fields(tweet_factory) -> None:
    tweet = tweet_factory(
        "88",
        article_title="Long-form title",
        article_text="Intro\n\n## Details",
    )

    payload = tweet_to_dict(tweet)
    restored = tweet_from_dict(payload)

    assert restored.article_title == "Long-form title"
    assert restored.article_text == "Intro\n\n## Details"


def test_tweet_roundtrip_preserves_subscriber_only(tweet_factory) -> None:
    tweet = tweet_factory("99", is_subscriber_only=True)
    payload = tweet_to_dict(tweet)
    assert payload["isSubscriberOnly"] is True
    restored = tweet_from_dict(payload)
    assert restored.is_subscriber_only is True


def test_tweet_roundtrip_preserves_promoted_flag(tweet_factory) -> None:
    tweet = tweet_factory("100", is_promoted=True)
    payload = tweet_to_dict(tweet)
    assert payload["isPromoted"] is True
    restored = tweet_from_dict(payload)
    assert restored.is_promoted is True


def test_tweet_roundtrip_preserves_rich_metadata(tweet_factory) -> None:
    quoted = tweet_factory("101", possibly_sensitive=True)
    tweet = tweet_factory(
        "100",
        author=Author(
            id="u1",
            name="Alice",
            screen_name="alice",
            followers_count=500,
            following_count=120,
            viewer_following=True,
            viewer_followed_by=False,
        ),
        possibly_sensitive=True,
        conversation_id="100",
        in_reply_to_status_id="99",
        in_reply_to_user_id="u0",
        in_reply_to_screen_name="bob",
        quoted_tweet=quoted,
        media=[
            TweetMedia(
                type="video",
                url="https://video.mp4",
                width=1280,
                height=720,
                adult_content=True,
                graphic_violence=True,
                other_warning=False,
                poster_url="https://thumb.jpg",
                alt_text="clip",
                duration_ms=4500,
            )
        ],
    )
    payload = tweet_to_dict(tweet)
    assert payload["author"]["followers"] == 500
    assert payload["author"]["following"] == 120
    assert payload["author"]["viewerFollowing"] is True
    assert payload["author"]["viewerFollowedBy"] is False
    assert payload["possiblySensitive"] is True
    assert payload["conversationId"] == "100"
    assert payload["inReplyToStatusId"] == "99"
    assert payload["inReplyToUserId"] == "u0"
    assert payload["inReplyToScreenName"] == "bob"
    assert payload["quotedTweet"]["possiblySensitive"] is True
    assert payload["media"][0]["adultContent"] is True
    assert payload["media"][0]["posterUrl"] == "https://thumb.jpg"
    assert payload["media"][0]["altText"] == "clip"
    assert payload["media"][0]["durationMs"] == 4500

    restored = tweet_from_dict(payload)
    assert restored.author.followers_count == 500
    assert restored.author.following_count == 120
    assert restored.author.viewer_following is True
    assert restored.author.viewer_followed_by is False
    assert restored.possibly_sensitive is True
    assert restored.conversation_id == "100"
    assert restored.in_reply_to_status_id == "99"
    assert restored.in_reply_to_user_id == "u0"
    assert restored.in_reply_to_screen_name == "bob"
    assert restored.quoted_tweet is not None
    assert restored.quoted_tweet.possibly_sensitive is True
    assert restored.media[0].adult_content is True
    assert restored.media[0].poster_url == "https://thumb.jpg"
    assert restored.media[0].alt_text == "clip"
    assert restored.media[0].duration_ms == 4500
