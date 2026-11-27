"""Serialization helpers for Tweet and UserProfile models."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from .models import Author, BookmarkFolder, Metrics, Tweet, TweetMedia, UserProfile
from .timeutil import format_iso8601, format_local_time


def _media_to_dict(media: TweetMedia) -> Dict[str, Any]:
    """Convert a TweetMedia dataclass into a JSON-safe dict."""
    item: Dict[str, Any] = {
        "type": media.type,
        "url": media.url,
        "width": media.width,
        "height": media.height,
        "adultContent": media.adult_content,
        "graphicViolence": media.graphic_violence,
        "otherWarning": media.other_warning,
    }
    if media.poster_url is not None:
        item["posterUrl"] = media.poster_url
    if media.alt_text is not None:
        item["altText"] = media.alt_text
    if media.duration_ms is not None:
        item["durationMs"] = media.duration_ms
    return item


def tweet_to_dict(tweet: Tweet) -> Dict[str, Any]:
    """Convert a Tweet dataclass into a JSON-safe dict."""
    author_dict: Dict[str, Any] = {
        "id": tweet.author.id,
        "name": tweet.author.name,
        "screenName": tweet.author.screen_name,
        "profileImageUrl": tweet.author.profile_image_url,
        "verified": tweet.author.verified,
        "followers": tweet.author.followers_count,
        "following": tweet.author.following_count,
    }
    if tweet.author.viewer_following is not None:
        author_dict["viewerFollowing"] = tweet.author.viewer_following
    if tweet.author.viewer_followed_by is not None:
        author_dict["viewerFollowedBy"] = tweet.author.viewer_followed_by

    data: Dict[str, Any] = {
        "id": tweet.id,
        "text": tweet.text,
        "author": author_dict,
        "metrics": {
            "likes": tweet.metrics.likes,
            "retweets": tweet.metrics.retweets,
            "replies": tweet.metrics.replies,
            "quotes": tweet.metrics.quotes,
            "views": tweet.metrics.views,
            "bookmarks": tweet.metrics.bookmarks,
        },
        "createdAt": tweet.created_at,
        "createdAtLocal": format_local_time(tweet.created_at),
        "createdAtISO": format_iso8601(tweet.created_at),
        "media": [_media_to_dict(media) for media in tweet.media],
        "urls": list(tweet.urls),
        "isRetweet": tweet.is_retweet,
        "retweetedBy": tweet.retweeted_by,
        "lang": tweet.lang,
        "score": tweet.score,
        "isSubscriberOnly": tweet.is_subscriber_only,
        "isPromoted": tweet.is_promoted,
        "possiblySensitive": tweet.possibly_sensitive,
    }
    if tweet.conversation_id is not None:
        data["conversationId"] = tweet.conversation_id
    if tweet.in_reply_to_status_id is not None:
        data["inReplyToStatusId"] = tweet.in_reply_to_status_id
    if tweet.in_reply_to_user_id is not None:
        data["inReplyToUserId"] = tweet.in_reply_to_user_id
    if tweet.in_reply_to_screen_name is not None:
        data["inReplyToScreenName"] = tweet.in_reply_to_screen_name
    if tweet.article_title is not None:
        data["articleTitle"] = tweet.article_title
    if tweet.article_text is not None:
        data["articleText"] = tweet.article_text
    if tweet.quoted_tweet:
        data["quotedTweet"] = {
            "id": tweet.quoted_tweet.id,
            "text": tweet.quoted_tweet.text,
            "author": {
                "screenName": tweet.quoted_tweet.author.screen_name,
                "name": tweet.quoted_tweet.author.name,
            },
            "possiblySensitive": tweet.quoted_tweet.possibly_sensitive,
        }
    return data


def tweet_from_dict(data: Dict[str, Any]) -> Tweet:
    """Convert a dict into a Tweet dataclass."""
    author_data = data.get("author") or {}
    metrics_data = data.get("metrics") or {}
    media_data = data.get("media") or []
    quoted_data = data.get("quotedTweet")

    quoted_tweet = None  # type: Optional[Tweet]
    if isinstance(quoted_data, dict):
        quoted_author = quoted_data.get("author") or {}
        quoted_tweet = Tweet(
            id=str(quoted_data.get("id") or ""),
            text=str(quoted_data.get("text") or ""),
            author=Author(
                id="",
                name=str(quoted_author.get("name") or ""),
                screen_name=str(quoted_author.get("screenName") or ""),
            ),
            metrics=Metrics(),
            created_at="",
            possibly_sensitive=bool(quoted_data.get("possiblySensitive", False)),
        )

    return Tweet(
        id=str(data.get("id") or ""),
        text=str(data.get("text") or ""),
        author=Author(
            id=str(author_data.get("id") or ""),
            name=str(author_data.get("name") or ""),
            screen_name=str(author_data.get("screenName") or ""),
            profile_image_url=str(author_data.get("profileImageUrl") or ""),
            verified=bool(author_data.get("verified", False)),
            followers_count=int(author_data.get("followers") or 0),
            following_count=int(author_data.get("following") or 0),
            viewer_following=_optional_bool(author_data.get("viewerFollowing")),
            viewer_followed_by=_optional_bool(author_data.get("viewerFollowedBy")),
        ),
        metrics=Metrics(
            likes=int(metrics_data.get("likes") or 0),
            retweets=int(metrics_data.get("retweets") or 0),
            replies=int(metrics_data.get("replies") or 0),
            quotes=int(metrics_data.get("quotes") or 0),
            views=int(metrics_data.get("views") or 0),
            bookmarks=int(metrics_data.get("bookmarks") or 0),
        ),
        created_at=str(data.get("createdAt") or ""),
        media=[
            TweetMedia(
                type=str(item.get("type") or ""),
                url=str(item.get("url") or ""),
                width=_optional_int(item.get("width")),
                height=_optional_int(item.get("height")),
                adult_content=bool(item.get("adultContent", False)),
                graphic_violence=bool(item.get("graphicViolence", False)),
                other_warning=bool(item.get("otherWarning", False)),
                poster_url=_optional_str(item.get("posterUrl")),
                alt_text=_optional_str(item.get("altText")),
                duration_ms=_optional_int(item.get("durationMs")),
            )
            for item in media_data
            if isinstance(item, dict)
        ],
        urls=[str(url) for url in (data.get("urls") or [])],
        is_retweet=bool(data.get("isRetweet", False)),
        lang=str(data.get("lang") or ""),
        retweeted_by=_optional_str(data.get("retweetedBy")),
        quoted_tweet=quoted_tweet,
        score=float(data["score"]) if data.get("score") is not None else None,
        article_title=_optional_str(data.get("articleTitle")),
        article_text=_optional_str(data.get("articleText")),
        is_subscriber_only=bool(data.get("isSubscriberOnly", False)),
        is_promoted=bool(data.get("isPromoted", False)),
        possibly_sensitive=bool(data.get("possiblySensitive", False)),
        conversation_id=_optional_str(data.get("conversationId")),
        in_reply_to_status_id=_optional_str(data.get("inReplyToStatusId")),
        in_reply_to_user_id=_optional_str(data.get("inReplyToUserId")),
        in_reply_to_screen_name=_optional_str(data.get("inReplyToScreenName")),
    )


def tweets_from_json(raw: str) -> List[Tweet]:
    """Parse a JSON string into Tweet objects."""
    payload = json.loads(raw)
    if isinstance(payload, dict) and payload.get("ok") is True and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        raise ValueError("Tweet JSON payload must be a list")
    return [tweet_from_dict(item) for item in payload if isinstance(item, dict)]


def tweets_to_json(tweets: Iterable[Tweet]) -> str:
    """Serialize Tweet objects to pretty JSON."""
    return json.dumps([tweet_to_dict(tweet) for tweet in tweets], ensure_ascii=False, indent=2)


def tweets_to_data(tweets: Iterable[Tweet]) -> List[Dict[str, Any]]:
    """Serialize Tweet objects to Python dicts."""
    return [tweet_to_dict(tweet) for tweet in tweets]


def tweet_to_compact_dict(tweet: Tweet) -> Dict[str, Any]:
    """Convert a Tweet into a compact dict with minimal fields for LLM consumption."""
    text = tweet.text.replace("\n", " ").strip()
    if len(text) > 140:
        text = text[:137] + "..."
    # Short time: "Mar 07 05:51" from "Sat Mar 07 05:51:02 +0000 2026"
    parts = tweet.created_at.split()
    if len(parts) >= 4:
        time_str = "%s %s %s" % (parts[1], parts[2], parts[3][:5])
    else:
        time_str = tweet.created_at
    return {
        "id": tweet.id,
        "author": "@%s" % tweet.author.screen_name,
        "text": text,
        "likes": tweet.metrics.likes,
        "rts": tweet.metrics.retweets,
        "time": time_str,
    }


def tweets_to_compact_json(tweets: Iterable[Tweet]) -> str:
    """Serialize Tweet objects to compact JSON (minimal fields for LLM/pipe usage)."""
    return json.dumps(
        [tweet_to_compact_dict(tweet) for tweet in tweets],
        ensure_ascii=False,
        indent=2,
    )


def bookmark_folder_to_dict(folder: BookmarkFolder) -> Dict[str, Any]:
    """Convert a BookmarkFolder dataclass into a JSON-safe dict."""
    return {
        "id": folder.id,
        "name": folder.name,
    }


def bookmark_folders_to_data(folders: Iterable[BookmarkFolder]) -> List[Dict[str, Any]]:
    """Serialize BookmarkFolder objects to Python dicts."""
    return [bookmark_folder_to_dict(f) for f in folders]


def user_profile_to_dict(user: UserProfile) -> Dict[str, Any]:
    """Convert a UserProfile dataclass into a JSON-safe dict."""
    data: Dict[str, Any] = {
        "id": user.id,
        "name": user.name,
        "screenName": user.screen_name,
        "bio": user.bio,
        "location": user.location,
        "url": user.url,
        "followers": user.followers_count,
        "following": user.following_count,
        "tweets": user.tweets_count,
        "likes": user.likes_count,
        "verified": user.verified,
        "profileImageUrl": user.profile_image_url,
        "createdAt": user.created_at,
        "createdAtISO": format_iso8601(user.created_at),
    }
    if user.viewer_following is not None:
        data["viewerFollowing"] = user.viewer_following
    if user.viewer_followed_by is not None:
        data["viewerFollowedBy"] = user.viewer_followed_by
    return data


def users_to_json(users: Iterable[UserProfile]) -> str:
    """Serialize UserProfile objects to pretty JSON."""
    return json.dumps(
        [user_profile_to_dict(user) for user in users],
        ensure_ascii=False,
        indent=2,
    )


def users_to_data(users: Iterable[UserProfile]) -> List[Dict[str, Any]]:
    """Serialize UserProfile objects to Python dicts."""
    return [user_profile_to_dict(user) for user in users]


def _optional_int(value: Any) -> Optional[int]:
    """Parse an optional integer value."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> Optional[str]:
    """Parse an optional string value."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_bool(value: Any) -> Optional[bool]:
    """Parse an optional boolean value."""
    if isinstance(value, bool):
        return value
    return None
