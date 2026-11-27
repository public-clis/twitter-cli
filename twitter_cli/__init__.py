"""twitter-cli: A terminal-first CLI and Python library for Twitter/X."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("twitter-cli")
except Exception:
    __version__ = "0.0.0"

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
