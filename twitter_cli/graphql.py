"""GraphQL infrastructure for Twitter API.

Handles queryId resolution (env overrides, disk cache, community OpenAPI,
JS bundle scanning, and fallback constants), URL building, and feature flag
management.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Collection, Dict, Optional  # noqa: F401

from .cache import _OWNER_ONLY_DIR, _open_owner_only, _tighten_dir
from .exceptions import QueryIdError
from .text import CREATE_NOTE_TWEET_OPERATION, CREATE_TWEET_OPERATION

logger = logging.getLogger(__name__)

# ── Community OpenAPI queryId source ─────────────────────────────────────
TWITTER_OPENAPI_URL = (
    "https://raw.githubusercontent.com/fa0311/"
    "twitter-openapi/refs/heads/main/src/config/placeholder.json"
)

# ── Fallback (hardcoded) queryIds ────────────────────────────────────────
# Refreshed against twitter-openapi placeholder.json on 2026-11-27.
# Override any single operation at runtime via TWITTER_QID_<OPERATION>.
FALLBACK_QUERY_IDS = {
    "HomeTimeline": "KmJCeZ__ef1fNos7tKN_fg",
    "HomeLatestTimeline": "IVA5BUbeYPTrpYekQH7jiA",
    "UserByScreenName": "AMIBMjtxEEATh4z8V9GtRg",
    "UserByRestId": "mxaYWwt52eAb6OAzYHMVzg",
    "UserTweets": "7_KBXBpG0zBPRN6UCIV0-w",
    "TweetDetail": "dQDdKtt882nl-Km98FJGSQ",
    "Likes": "ZjyvI1V9gajq5eclHCObzA",
    "SearchTimeline": "vLHjqbDv7TPFMBkIIO1nOA",
    "ExplorePage": "CVExg1KY6Ec9BioRBbI8Jg",
    "GenericTimelineById": "UToImY30uYcerTaw8gu21w",
    "Bookmarks": "fjf5b5Lu82lYMSBRhppK2g",
    "ListLatestTweetsTimeline": "UMc_lPEeKz_WiKSY8ZT7yw",
    "Followers": "Xe3y9_ndZ9-RtWz8zd_wpg",
    "Following": "eDqlbOS46zda8jDT8dEQ_Q",
    CREATE_TWEET_OPERATION: "wR5Z_lEibLvkew3tF9w-Sg",
    CREATE_NOTE_TWEET_OPERATION: "_eeuQKX1-VyRP_ROM-GN7g",
    "DeleteTweet": "nxpZCY2K-I6QoFHAHeojFQ",
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "CreateRetweet": "mbRO74GrOvSfRcJnlMapnQ",
    "DeleteRetweet": "ZyZigVsNiFO6v1dEks1eWg",
    "CreateBookmark": "aoDbu3RHznuiSkQ9aNM67Q",
    "DeleteBookmark": "Wlmlj2-xzyS1GN3a6cj-mQ",
    "TweetResultByRestId": "U8lc5aomF5krJzZ9vJ9wxg",
    "BookmarkFoldersSlice": "i78YDd0Tza-dV4SYs58kRg",
    "BookmarkFolderTimeline": "hNY7X2xE2N7HVF6Qb_mu6w",
    "ArticleEntityDraftCreate": "g1l5N8BxGewYuCy5USe_bQ",
    "ArticleEntityUpdateTitle": "x75E2ABzm8_mGTg1bz8hcA",
    "ArticleEntityUpdateContent": "M7N2FrPrlOmu-YrVIBxFnQ",
    "ArticleEntityPublish": "m4SHicYMoWO_qkLvjhDk7Q",
}

# ── Default feature flags ────────────────────────────────────────────────
_DEFAULT_FEATURES = {
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "responsive_web_enhance_cards_enabled": False,
}

# Features dict that gets updated dynamically from x.com JS bundles
FEATURES = dict(_DEFAULT_FEATURES)

# Extra composer flags scoped to CreateNoteTweet
NOTE_TWEET_FEATURES = {
    "longform_notetweets_creation_enabled": True,
    "longform_notetweets_richtext_consumption_enabled": True,
    "articles_preview_enabled": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
}

# Feature flags scoped to X Article authoring mutations
ARTICLE_FEATURES = {
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}


def operation_features(operation_name):
    # type: (str) -> Dict[str, Any]
    """Return base features plus overrides scoped to one operation."""
    if operation_name == CREATE_NOTE_TWEET_OPERATION:
        return dict(FEATURES, **NOTE_TWEET_FEATURES)
    return FEATURES

# Module-level caches (not thread-safe — CLI is single-threaded)
_cached_query_ids: Dict[str, str] = {}
_disk_cache_loaded = False
_bundles_scanned = False

_QID_CACHE_TTL = 86400  # 24 hours
_MAX_SCAN_CHUNKS = 100


def _qid_cache_path() -> Path:
    """Return path for the persistent queryId cache file."""
    return Path.home() / ".twitter-cli" / "query_ids_cache.json"


def _load_disk_query_ids() -> Dict[str, str]:
    """Load non-expired queryIds from disk cache."""
    global _disk_cache_loaded
    if _disk_cache_loaded:
        return {}
    _disk_cache_loaded = True
    try:
        path = _qid_cache_path()
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        if time.time() - float(payload.get("created_at", 0)) > _QID_CACHE_TTL:
            return {}
        qids = payload.get("query_ids", {})
        if isinstance(qids, dict):
            return {str(k): str(v) for k, v in qids.items() if k and v}
    except Exception as exc:
        logger.debug("Failed to load queryId disk cache: %s", exc)
    return {}


def _save_disk_query_ids(query_ids: Dict[str, str], replace: bool = False) -> None:
    """Persist live-resolved queryIds to disk with owner-only permissions.

    When ``replace`` is False, merges into any non-expired existing cache while
    preserving its original ``created_at`` timestamp so stale entries cannot
    live forever via a sliding TTL. When ``replace`` is True (full refresh),
    replaces the cache contents and resets ``created_at``.
    """
    if not query_ids:
        return
    try:
        path = _qid_cache_path()
        path.parent.mkdir(mode=_OWNER_ONLY_DIR, parents=True, exist_ok=True)
        _tighten_dir(path.parent)
        existing: Dict[str, str] = {}
        created_at = time.time()
        if not replace and path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                old_created_at = float(old.get("created_at", 0)) if isinstance(old, dict) else 0.0
                if (
                    isinstance(old, dict)
                    and time.time() - old_created_at <= _QID_CACHE_TTL
                    and isinstance(old.get("query_ids"), dict)
                ):
                    existing = {str(k): str(v) for k, v in old["query_ids"].items() if k and v}
                    created_at = old_created_at
            except Exception:
                pass
        existing.update(query_ids)
        payload = {"created_at": created_at, "query_ids": existing}
        with _open_owner_only(path) as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:
        logger.debug("Failed to save queryId disk cache: %s", exc)


def _remove_disk_query_id(operation_name: str) -> None:
    """Remove a stale queryId from the disk cache if present."""
    try:
        path = _qid_cache_path()
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("query_ids"), dict):
            return
        if operation_name in payload["query_ids"]:
            payload["query_ids"].pop(operation_name, None)
            with _open_owner_only(path) as f:
                json.dump(payload, f, indent=2)
    except Exception as exc:
        logger.debug("Failed to update queryId disk cache: %s", exc)


def _build_graphql_url(query_id, operation_name, variables, features, field_toggles=None):
    # type: (str, str, Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]) -> str
    """Build GraphQL GET URL with encoded variables/features/fieldToggles.

    Only includes True-valued feature flags in the URL to avoid 414 URI Too Long.
    Twitter's API defaults missing features to False.
    """
    compact_features = {k: v for k, v in features.items() if v is not False}
    url = "https://x.com/i/api/graphql/%s/%s?variables=%s&features=%s" % (
        query_id,
        operation_name,
        urllib.parse.quote(json.dumps(variables, separators=(",", ":"))),
        urllib.parse.quote(json.dumps(compact_features, separators=(",", ":"))),
    )
    if field_toggles:
        url += "&fieldToggles=%s" % urllib.parse.quote(
            json.dumps(field_toggles, separators=(",", ":"))
        )
    return url


def _scan_bundles(url_fetch_fn):
    # type: (Any) -> None
    """Scan Twitter JS bundles and cache queryId mappings.

    Supports both legacy ``responsive-web/client-web`` bundles (via ``/i/jf/``)
    and newer ``x-web/x-web`` Vite bundles (following relative asset chunks).

    Args:
        url_fetch_fn: Function to fetch URLs (injected to avoid circular import).
    """
    global _bundles_scanned
    if _bundles_scanned:
        return
    _bundles_scanned = True

    script_pattern = re.compile(
        r'(?:src|href)=["\']'
        r'(https://abs\.twimg\.com/(?:responsive-web/client-web|x-web/x-web)[^"\']+'
        r'\.js)'
        r'["\']'
    )
    script_urls = []
    try:
        from .constants import get_user_agent

        headers = {"user-agent": get_user_agent()}
        for page_url in ("https://x.com/i/jf/", "https://x.com"):
            try:
                html = url_fetch_fn(page_url, headers)
                found_urls = script_pattern.findall(html)
                if found_urls:
                    script_urls = found_urls
                    break
            except Exception as exc:  # pragma: no cover - network-dependent branch
                logger.debug("Bundle page fetch failed for %s: %s", page_url, exc)
                continue
    except Exception as exc:  # pragma: no cover - network-dependent branch
        logger.warning("Failed to scan JS bundles: %s", exc)
        return

    if not script_urls:
        return

    discovered: Dict[str, str] = {}
    op_pattern = re.compile(
        r'queryId:\s*"([A-Za-z0-9_-]+)"[^}]{0,200}'
        r'operationName:\s*"([^"]+)"'
    )
    chunk_ref_pattern = re.compile(r'["\'](?:\./)?assets/([A-Za-z0-9._\-]+\.js)["\']')

    seen_urls = set()
    queue = list(script_urls)
    scanned = 0
    while queue and scanned < _MAX_SCAN_CHUNKS:
        script_url = queue.pop(0)
        if script_url in seen_urls:
            continue
        seen_urls.add(script_url)
        scanned += 1
        try:
            bundle = url_fetch_fn(script_url)
            for match in op_pattern.finditer(bundle):
                query_id, operation_name = match.group(1), match.group(2)
                _cached_query_ids.setdefault(operation_name, query_id)
                discovered.setdefault(operation_name, query_id)

            if "/x-web/x-web/" in script_url:
                base = script_url.split("/x-web/x-web/", 1)[0] + "/x-web/x-web/"
                for rel in chunk_ref_pattern.findall(bundle):
                    if ".." in rel:
                        continue
                    chunk_url = base + "assets/" + rel
                    if chunk_url not in seen_urls:
                        queue.append(chunk_url)
        except Exception:
            continue

    if discovered:
        _save_disk_query_ids(discovered)
    logger.info("Scanned %d JS bundles, cached %d query IDs", scanned, len(_cached_query_ids))


def _update_features_from_html(html):
    # type: (str) -> None
    """Extract live feature flags from x.com HTML and update the global FEATURES dict.

    Twitter embeds feature switch config in inline scripts on the homepage.
    We parse these to keep FEATURES in sync with the current frontend.
    Only UPDATES existing keys — never adds new ones to avoid URL bloat.
    """
    try:
        feature_pattern = re.compile(
            r'"([a-z][a-z0-9_]+)":\s*\{\s*"value"\s*:\s*(true|false)',
            re.IGNORECASE,
        )
        found = 0
        for match in feature_pattern.finditer(html):
            key = match.group(1)
            value = match.group(2).lower() == "true"
            if key in FEATURES and FEATURES[key] != value:
                logger.debug("Feature flag updated: %s = %s -> %s", key, FEATURES[key], value)
                FEATURES[key] = value
                found += 1
        if found:
            logger.info("Updated %d feature flags from x.com", found)
    except Exception as exc:
        logger.debug("Feature extraction from HTML failed: %s", exc)


def _fetch_from_github(url_fetch_fn, operation_name):
    # type: (Any, str) -> Optional[str]
    """Fetch queryId from community-maintained twitter-openapi file."""
    try:
        payload = url_fetch_fn(TWITTER_OPENAPI_URL)
        parsed = json.loads(payload)
        operation = parsed.get(operation_name, {})
        query_id = operation.get("queryId")
        if isinstance(query_id, str) and query_id:
            return query_id
    except Exception as exc:  # pragma: no cover - network-dependent branch
        logger.debug("GitHub queryId lookup failed: %s", exc)
    return None


def _invalidate_query_id(operation_name):
    # type: (str) -> None
    """Remove a cached queryId for an operation (memory and disk)."""
    _cached_query_ids.pop(operation_name, None)
    _remove_disk_query_id(operation_name)


def refresh_query_ids(url_fetch_fn):
    # type: (Any) -> Dict[str, str]
    """Force a live refresh of queryIds from twitter-openapi and x.com bundles."""
    global _bundles_scanned, _disk_cache_loaded
    _cached_query_ids.clear()
    _bundles_scanned = False
    _disk_cache_loaded = True
    refreshed: Dict[str, str] = {}

    try:
        payload = url_fetch_fn(TWITTER_OPENAPI_URL)
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            for op_name, op_data in parsed.items():
                if isinstance(op_data, dict):
                    qid = op_data.get("queryId")
                    if isinstance(qid, str) and qid:
                        refreshed[op_name] = qid
    except Exception as exc:
        logger.debug("GitHub bulk queryId refresh failed: %s", exc)

    _scan_bundles(url_fetch_fn)
    refreshed.update(_cached_query_ids)
    _cached_query_ids.update(refreshed)
    if refreshed:
        _save_disk_query_ids(refreshed, replace=True)
    return dict(refreshed)


def _resolve_query_id(operation_name, prefer_fallback=True, url_fetch_fn=None, exclude_ids=None):
    # type: (str, bool, Any, Optional[Collection[str]]) -> str
    """Resolve queryId using env override, caches, remote sources, and fallbacks."""
    excluded = set(exclude_ids) if exclude_ids else set()

    # 1. Explicit per-operation environment override: TWITTER_QID_<OperationName>
    env_override = os.environ.get("TWITTER_QID_%s" % operation_name, "").strip()
    if env_override:
        return env_override

    # 2. In-memory cache (populated from disk cache or prior lookups)
    if not _disk_cache_loaded:
        for op_name, qid in _load_disk_query_ids().items():
            _cached_query_ids.setdefault(op_name, qid)

    cached = _cached_query_ids.get(operation_name)
    if cached and cached not in excluded:
        return cached

    # 3. Fallback constants (when prefer_fallback=True)
    fallback = FALLBACK_QUERY_IDS.get(operation_name)
    if prefer_fallback and fallback and fallback not in excluded:
        _cached_query_ids[operation_name] = fallback
        return fallback

    # 4. Live resolution: community twitter-openapi -> x.com JS bundle scan
    if url_fetch_fn:
        github_query_id = _fetch_from_github(url_fetch_fn, operation_name)
        if github_query_id and github_query_id not in excluded:
            _cached_query_ids[operation_name] = github_query_id
            _save_disk_query_ids({operation_name: github_query_id})
            return github_query_id

        _scan_bundles(url_fetch_fn)
        cached = _cached_query_ids.get(operation_name)
        if cached and cached not in excluded:
            return cached

    # 5. Last-resort fallback
    if fallback:
        if fallback not in excluded:
            _cached_query_ids[operation_name] = fallback
        return fallback

    raise QueryIdError('Cannot resolve queryId for "%s"' % operation_name)
