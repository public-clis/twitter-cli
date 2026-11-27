"""Tests for the public Python library API exported from twitter_cli."""

import twitter_cli


def test_public_api_exports():
    expected = {
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
        "user_profile_to_dict",
    }
    assert expected.issubset(set(twitter_cli.__all__))
    for name in twitter_cli.__all__:
        assert hasattr(twitter_cli, name), f"Missing exported symbol: {name}"
