"""twitter-cli: A terminal-first CLI and Python library for Twitter/X."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

try:
    from importlib.metadata import version

    __version__ = version("twitter-cli")
except Exception:
    __version__ = "0.0.0"

if TYPE_CHECKING:
    from .auth import get_cookies
    from .client import TwitterClient
    from .config import load_config
    from .exceptions import (
        AuthenticationError,
        InvalidInputError,
        MediaUploadError,
        NetworkError,
        NotFoundError,
        QueryIdError,
        RateLimitError,
        TwitterAPIError,
        TwitterError,
    )
    from .filter import filter_tweets
    from .models import Author, BookmarkFolder, Metrics, Tweet, TweetMedia, UserProfile
    from .serialization import (
        bookmark_folder_to_dict,
        bookmark_folders_to_data,
        tweet_from_dict,
        tweet_to_compact_dict,
        tweet_to_dict,
        tweets_from_json,
        tweets_to_compact_json,
        tweets_to_data,
        tweets_to_json,
        user_profile_to_dict,
        users_to_data,
        users_to_json,
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "TwitterClient": (".client", "TwitterClient"),
    "get_cookies": (".auth", "get_cookies"),
    "load_config": (".config", "load_config"),
    "filter_tweets": (".filter", "filter_tweets"),
    "Author": (".models", "Author"),
    "BookmarkFolder": (".models", "BookmarkFolder"),
    "Metrics": (".models", "Metrics"),
    "Tweet": (".models", "Tweet"),
    "TweetMedia": (".models", "TweetMedia"),
    "UserProfile": (".models", "UserProfile"),
    "TwitterError": (".exceptions", "TwitterError"),
    "AuthenticationError": (".exceptions", "AuthenticationError"),
    "InvalidInputError": (".exceptions", "InvalidInputError"),
    "MediaUploadError": (".exceptions", "MediaUploadError"),
    "NetworkError": (".exceptions", "NetworkError"),
    "NotFoundError": (".exceptions", "NotFoundError"),
    "QueryIdError": (".exceptions", "QueryIdError"),
    "RateLimitError": (".exceptions", "RateLimitError"),
    "TwitterAPIError": (".exceptions", "TwitterAPIError"),
    "tweet_to_dict": (".serialization", "tweet_to_dict"),
    "tweet_from_dict": (".serialization", "tweet_from_dict"),
    "tweets_to_json": (".serialization", "tweets_to_json"),
    "tweets_from_json": (".serialization", "tweets_from_json"),
    "tweets_to_data": (".serialization", "tweets_to_data"),
    "tweet_to_compact_dict": (".serialization", "tweet_to_compact_dict"),
    "tweets_to_compact_json": (".serialization", "tweets_to_compact_json"),
    "bookmark_folder_to_dict": (".serialization", "bookmark_folder_to_dict"),
    "bookmark_folders_to_data": (".serialization", "bookmark_folders_to_data"),
    "user_profile_to_dict": (".serialization", "user_profile_to_dict"),
    "users_to_data": (".serialization", "users_to_data"),
    "users_to_json": (".serialization", "users_to_json"),
}

__all__ = [
    "__version__",
    "TwitterClient",
    "get_cookies",
    "load_config",
    "filter_tweets",
    "Author",
    "BookmarkFolder",
    "Metrics",
    "Tweet",
    "TweetMedia",
    "UserProfile",
    "TwitterError",
    "AuthenticationError",
    "InvalidInputError",
    "MediaUploadError",
    "NetworkError",
    "NotFoundError",
    "QueryIdError",
    "RateLimitError",
    "TwitterAPIError",
    "tweet_to_dict",
    "tweet_from_dict",
    "tweets_to_json",
    "tweets_from_json",
    "tweets_to_data",
    "tweet_to_compact_dict",
    "tweets_to_compact_json",
    "bookmark_folder_to_dict",
    "bookmark_folders_to_data",
    "user_profile_to_dict",
    "users_to_data",
    "users_to_json",
]


def __getattr__(name: str) -> Any:
    spec = _LAZY_EXPORTS.get(name)
    if spec is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    module_name, attr_name = spec
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
