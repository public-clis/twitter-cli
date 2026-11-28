"""Response parsing for Twitter GraphQL API.

Converts raw GraphQL response JSON into domain model objects
(Tweet, UserProfile, Author, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401

from .models import Author, Metrics, Tweet, TweetMedia, UserProfile

logger = logging.getLogger(__name__)


# ── Utility helpers ──────────────────────────────────────────────────────


def _deep_get(data, *keys):
    # type: (Any, *Any) -> Any
    """Safely get nested dict/list values.  Supports int keys for list access."""
    current = data
    for key in keys:
        if isinstance(key, int):
            if isinstance(current, list) and 0 <= key < len(current):
                current = current[key]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _parse_int(value, default):
    # type: (Any, int) -> int
    """Best-effort integer conversion.  Handles commas and float strings."""
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _extract_cursor(content):
    # type: (Dict[str, Any]) -> Optional[str]
    """Extract Bottom pagination cursor from timeline content."""
    if content.get("cursorType") == "Bottom":
        return content.get("value")
    return None


# ── Media / Author extraction ────────────────────────────────────────────


def _opt_str(value):
    # type: (Any) -> Optional[str]
    if isinstance(value, str) and value:
        return value
    return None


def _opt_bool(value):
    # type: (Any) -> Optional[bool]
    if isinstance(value, bool):
        return value
    return None


def _opt_int(value):
    # type: (Any) -> Optional[int]
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _truthy(value):
    # type: (Any) -> bool
    return value is True or value == 1 or value in ("true", "True")


def _media_warning(item):
    # type: (Any) -> Dict[str, bool]
    """Read adult/graphic/other sensitive-media labels from a GraphQL media entity."""
    out = {"adult_content": False, "graphic_violence": False, "other": False}
    if not isinstance(item, dict):
        return out

    sources = [
        item.get("ext_sensitive_media_warning"),
        item.get("sensitive_media_warning"),
        item.get("extSensitiveMediaWarning"),
        item.get("sensitiveMediaWarning"),
    ]
    media_results = item.get("media_results") or item.get("mediaResults")
    if isinstance(media_results, dict):
        result = media_results.get("result") or media_results
        if isinstance(result, dict):
            sources.extend(
                [
                    result.get("ext_sensitive_media_warning"),
                    result.get("sensitive_media_warning"),
                    result.get("extSensitiveMediaWarning"),
                    result.get("sensitiveMediaWarning"),
                ]
            )
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key, value in src.items():
            lk = str(key).replace("-", "_").lower()
            if lk in ("adult_content", "adultcontent") and _truthy(value):
                out["adult_content"] = True
            elif lk in ("graphic_violence", "graphicviolence") and _truthy(value):
                out["graphic_violence"] = True
            elif lk in ("other", "other_warning", "otherwarning") and _truthy(value):
                out["other"] = True
    return out


def _tweet_media(media_type, url, media_item, poster_url=None):
    # type: (str, str, Dict[str, Any], Optional[str]) -> TweetMedia
    warning = _media_warning(media_item)
    return TweetMedia(
        type=media_type,
        url=url,
        width=_deep_get(media_item, "original_info", "width"),
        height=_deep_get(media_item, "original_info", "height"),
        adult_content=warning["adult_content"],
        graphic_violence=warning["graphic_violence"],
        other_warning=warning["other"],
        poster_url=poster_url,
        alt_text=_opt_str(media_item.get("ext_alt_text")),
        duration_ms=_opt_int(_deep_get(media_item, "video_info", "duration_millis")),
    )


def _extract_media(legacy):
    # type: (Dict[str, Any]) -> List[TweetMedia]
    """Extract media items from tweet legacy data."""
    media = []  # type: List[TweetMedia]
    for media_item in _deep_get(legacy, "extended_entities", "media") or []:
        media_type = media_item.get("type", "")
        if media_type == "photo":
            media.append(
                _tweet_media("photo", media_item.get("media_url_https", ""), media_item)
            )
        elif media_type in {"video", "animated_gif"}:
            variants = media_item.get("video_info", {}).get("variants", [])
            mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
            mp4_variants.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
            url = (
                mp4_variants[0]["url"]
                if mp4_variants
                else media_item.get("media_url_https", "")
            )
            media.append(
                _tweet_media(
                    media_type,
                    url,
                    media_item,
                    poster_url=_opt_str(media_item.get("media_url_https")),
                )
            )
    return media


def _extract_author(user_data, user_legacy):
    # type: (Dict[str, Any], Dict[str, Any]) -> Author
    """Extract Author from user result data."""
    user_data = user_data or {}
    user_legacy = user_legacy or {}
    user_core = user_data.get("core") or {}
    rel_counts = user_data.get("relationship_counts") or {}
    perspectives = user_data.get("relationship_perspectives") or {}
    avatar = user_data.get("avatar") or {}
    followers = _parse_int(user_legacy.get("followers_count"), 0) or _parse_int(
        rel_counts.get("followers"), 0
    )
    following = _parse_int(user_legacy.get("friends_count"), 0) or _parse_int(
        rel_counts.get("following"), 0
    )
    viewer_following = _opt_bool(user_legacy.get("following"))
    if viewer_following is None:
        viewer_following = _opt_bool(perspectives.get("following"))
    viewer_followed_by = _opt_bool(user_legacy.get("followed_by"))
    if viewer_followed_by is None:
        viewer_followed_by = _opt_bool(perspectives.get("followed_by"))
    return Author(
        id=user_data.get("rest_id") or "",
        name=user_core.get("name") or user_legacy.get("name") or user_data.get("name") or "Unknown",
        screen_name=(
            user_core.get("screen_name")
            or user_legacy.get("screen_name")
            or user_data.get("screen_name")
            or "unknown"
        ),
        profile_image_url=(
            avatar.get("image_url")
            or user_legacy.get("profile_image_url_https")
            or ""
        ),
        verified=bool(user_data.get("is_blue_verified") or user_legacy.get("verified", False)),
        followers_count=followers,
        following_count=following,
        viewer_following=viewer_following,
        viewer_followed_by=viewer_followed_by,
    )


# ── Article parsing ──────────────────────────────────────────────────────


def _find_article_image_url(value):
    # type: (Any) -> Optional[str]
    """Best-effort extraction of the original image URL from article entity data."""
    if isinstance(value, dict):
        for key in (
            "original_img_url",
            "originalImgUrl",
            "original_url",
            "originalUrl",
            "media_url_https",
            "mediaUrlHttps",
            "media_url",
            "mediaUrl",
            "url",
            "src",
            "uri",
        ):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                lowered = candidate.lower()
                if (
                    lowered.startswith("https://pbs.twimg.com/")
                    or lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                    or any(ext in lowered for ext in (".jpg?", ".jpeg?", ".png?", ".gif?", ".webp?"))
                ):
                    return candidate.strip()
        for nested in value.values():
            found = _find_article_image_url(nested)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_article_image_url(item)
            if found:
                return found
    return None


def _normalize_article_entity_map(entity_map):
    # type: (Any) -> Dict[str, Any]
    """Normalize Draft.js entityMap that may arrive as dict or [{key, value}, ...]."""
    if isinstance(entity_map, dict):
        return {str(key): value for key, value in entity_map.items()}
    if isinstance(entity_map, list):
        normalized = {}  # type: Dict[str, Any]
        for item in entity_map:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key is None or value is None:
                continue
            normalized[str(key)] = value
        return normalized
    return {}


def _extract_article_media_url_map(article_results):
    # type: (Dict[str, Any]) -> Dict[str, str]
    """Map article media ids/keys to original image URLs when entities reference IDs only."""
    media_url_map = {}  # type: Dict[str, str]
    media_candidates = []  # type: List[Any]

    cover_media = article_results.get("cover_media")
    if cover_media:
        media_candidates.append(cover_media)
    media_candidates.extend(article_results.get("media_entities") or [])

    for media in media_candidates:
        if not isinstance(media, dict):
            continue
        media_info = media.get("media_info") or {}
        image_url = _find_article_image_url(media_info) or _find_article_image_url(media)
        if not image_url:
            continue
        for key in ("media_id", "media_key", "id"):
            candidate = media.get(key)
            if isinstance(candidate, str) and candidate:
                media_url_map[candidate] = image_url
    return media_url_map


def _extract_atomic_content(block, entity_map):
    # type: (Dict[str, Any], Dict[str, Any]) -> List[str]
    """Extract content from atomic Draft.js entities (MARKDOWN, DIVIDER, TWEET)."""
    parts = []  # type: List[str]
    for entity_range in block.get("entityRanges", []) or []:
        if not isinstance(entity_range, dict):
            continue
        entity_key = entity_range.get("key")
        entity = entity_map.get(str(entity_key)) if entity_key is not None else None
        if not isinstance(entity, dict):
            continue
        entity_type = str(entity.get("type") or "").upper()
        if entity_type == "MARKDOWN":
            markdown = _deep_get(entity, "data", "markdown")
            if isinstance(markdown, str) and markdown.strip():
                parts.append(markdown.strip())
        elif entity_type == "DIVIDER":
            parts.append("---")
        elif entity_type == "TWEET":
            tweet_id = _deep_get(entity, "data", "tweetId")
            if isinstance(tweet_id, str) and tweet_id:
                parts.append("> [Embedded Tweet](https://x.com/i/status/%s)" % tweet_id)
    return parts


# Backwards-compatibility alias
_extract_atomic_markdown = _extract_atomic_content


def _utf16_offset_map(text):
    # type: (str) -> Dict[int, int]
    """Map UTF-16 code unit boundaries to Python codepoint indices."""
    mapping = {0: 0}
    utf16_pos = 0
    for py_idx, ch in enumerate(text):
        utf16_pos += 2 if ord(ch) > 0xFFFF else 1
        mapping[utf16_pos] = py_idx + 1
    return mapping


def _valid_draft_range(offset, length, u16_map):
    # type: (Any, Any, Dict[int, int]) -> Optional[Tuple[int, int]]
    """Convert a Draft.js UTF-16 (offset, length) range into Python slice indices."""
    if isinstance(offset, bool) or isinstance(length, bool):
        return None
    if not isinstance(offset, int) or not isinstance(length, int) or length <= 0 or offset < 0:
        return None
    py_start = u16_map.get(offset)
    py_end = u16_map.get(offset + length)
    if py_start is None or py_end is None or py_end <= py_start:
        return None
    return py_start, py_end


def _render_article_text_block(block, entity_map):
    # type: (Dict[str, Any], Dict[str, Any]) -> str
    """Render a Draft.js text block, converting inline styles and hyperlinks to Markdown.

    Both inlineStyleRanges and entityRanges (links) use Draft.js UTF-16 code
    unit offsets. Links take priority over overlapping style spans so offsets
    are never corrupted, and accepted non-overlapping spans are applied
    right-to-left.
    """
    text = block.get("text", "")
    if not isinstance(text, str) or not text:
        return ""

    u16_map = _utf16_offset_map(text)

    # Collect operations as (priority, start, end, replacement): lower priority wins overlaps.
    candidates = []  # type: List[Tuple[int, int, int, str]]

    # Entity links (priority 0)
    for entity_range in block.get("entityRanges", []) or []:
        if not isinstance(entity_range, dict):
            continue
        entity_key = entity_range.get("key")
        entity = entity_map.get(str(entity_key)) if entity_key is not None else None
        if not isinstance(entity, dict):
            continue
        if str(entity.get("type") or "").upper() != "LINK":
            continue
        bounds = _valid_draft_range(entity_range.get("offset"), entity_range.get("length"), u16_map)
        if bounds is None:
            continue
        py_start, py_end = bounds
        url = _deep_get(entity, "data", "url")
        if not isinstance(url, str) or not url.strip():
            continue
        label = text[py_start:py_end]
        if not label:
            continue
        safe_label = label.replace("[", "\\[").replace("]", "\\]")
        safe_url = url.strip().replace(")", "%29")
        candidates.append((0, py_start, py_end, "[%s](%s)" % (safe_label, safe_url)))

    # Inline styles (priority 1)
    style_markers = {
        "BOLD": ("**", "**"),
        "ITALIC": ("*", "*"),
        "CODE": ("`", "`"),
        "STRIKETHROUGH": ("~~", "~~"),
    }  # type: Dict[str, Tuple[str, str]]
    for sr in block.get("inlineStyleRanges", []) or []:
        if not isinstance(sr, dict):
            continue
        style = str(sr.get("style", "")).upper()
        bounds = _valid_draft_range(sr.get("offset"), sr.get("length"), u16_map)
        if bounds is None:
            continue
        py_start, py_end = bounds
        if style in style_markers:
            open_m, close_m = style_markers[style]
            segment = text[py_start:py_end]
            candidates.append((1, py_start, py_end, "%s%s%s" % (open_m, segment, close_m)))

    if not candidates:
        return text

    # Accept non-overlapping spans (links first, then styles).
    accepted = []  # type: List[Tuple[int, int, str]]
    for _prio, start, end, replacement in sorted(candidates, key=lambda x: (x[0], x[1], -(x[2] - x[1]))):
        if any(not (end <= a_start or start >= a_end) for a_start, a_end, _ in accepted):
            continue
        accepted.append((start, end, replacement))

    rendered = text
    for start, end, replacement in sorted(accepted, key=lambda x: x[0], reverse=True):
        rendered = "%s%s%s" % (rendered[:start], replacement, rendered[end:])
    return rendered


def _find_article_caption(value):
    # type: (Any) -> Optional[str]
    """Best-effort extraction of image caption/alt text from article entity data."""
    if isinstance(value, dict):
        for key in ("caption", "alt", "alt_text", "altText", "title", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            found = _find_article_caption(nested)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_article_caption(item)
            if found:
                return found
    return None

def _extract_article_images(block, entity_map, media_url_map):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, str]) -> List[str]
    """Convert atomic Draft.js image entities to Markdown image lines."""
    parts = []  # type: List[str]
    for entity_range in block.get("entityRanges", []) or []:
        if not isinstance(entity_range, dict):
            continue
        entity_key = entity_range.get("key")
        entity = entity_map.get(str(entity_key)) if entity_key is not None else None
        if not isinstance(entity, dict):
            continue
        image_url = _find_article_image_url(entity)
        if not image_url:
            media_items = _deep_get(entity, "data", "mediaItems") or []
            for media_item in media_items:
                media_id = media_item.get("mediaId") if isinstance(media_item, dict) else None
                if isinstance(media_id, str) and media_id in media_url_map:
                    image_url = media_url_map[media_id]
                    break
        if not image_url:
            continue
        caption = _find_article_caption(entity) or ""
        parts.append("![%s](%s)" % (caption, image_url))
    return parts
def _parse_article(tweet_data):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Extract Twitter Article data (long-form content) from a tweet.

    Returns dict with 'article_title' and 'article_text' keys (None if not an article).
    Converts draft.js content blocks to Markdown.
    """
    article_results = _deep_get(tweet_data, "article", "article_results", "result")
    if not article_results:
        return {"article_title": None, "article_text": None}

    title = article_results.get("title")  # type: Optional[str]
    content_state = article_results.get("content_state", {})
    blocks = content_state.get("blocks", [])
    if not blocks:
        return {"article_title": title, "article_text": None}

    entity_map = _normalize_article_entity_map(content_state.get("entityMap", {}))
    media_url_map = _extract_article_media_url_map(article_results)

    # Convert draft.js blocks to Markdown
    parts = []  # type: List[str]
    ordered_counter = 0
    for block in blocks:
        block_type = block.get("type", "unstyled")  # type: str
        if block_type == "atomic":
            parts.extend(_extract_atomic_content(block, entity_map))
            parts.extend(_extract_article_images(block, entity_map, media_url_map))
            ordered_counter = 0
            continue
        text = _render_article_text_block(block, entity_map)
        if not text:
            continue
        if block_type != "ordered-list-item":
            ordered_counter = 0
        if block_type == "header-one":
            parts.append("# %s" % text)
        elif block_type == "header-two":
            parts.append("## %s" % text)
        elif block_type == "header-three":
            parts.append("### %s" % text)
        elif block_type == "blockquote":
            parts.append("> %s" % text)
        elif block_type == "unordered-list-item":
            parts.append("- %s" % text)
        elif block_type == "ordered-list-item":
            ordered_counter += 1
            parts.append("%d. %s" % (ordered_counter, text))
        elif block_type == "code-block":
            parts.append("```\n%s\n```" % text)
        else:
            parts.append(text)

    return {
        "article_title": title,
        "article_text": "\n\n".join(parts) if parts else None,
    }


# ── User parsing ─────────────────────────────────────────────────────────


def parse_user_result(user_data):
    # type: (Dict[str, Any]) -> Optional[UserProfile]
    """Parse a user result object into UserProfile.

    Handles both legacy shapes (``legacy{}``) and newer post-legacy shapes
    returned by ``UserByRestId`` (``core``, ``profile_bio``, ``website``,
    ``relationship_counts``, ``tweet_counts``, ``action_counts``,
    ``relationship_perspectives``, ``verification``).
    """
    if user_data.get("__typename") == "UserUnavailable":
        return None
    legacy = user_data.get("legacy") or {}
    core = user_data.get("core") or {}
    avatar = user_data.get("avatar") or {}
    location_obj = user_data.get("location") or {}
    profile_bio = user_data.get("profile_bio") or {}
    website = user_data.get("website") or {}
    rel_counts = user_data.get("relationship_counts") or {}
    tweet_counts = user_data.get("tweet_counts") or {}
    action_counts = user_data.get("action_counts") or {}
    perspectives = user_data.get("relationship_perspectives") or {}
    verification = user_data.get("verification") or {}

    if not user_data.get("rest_id"):
        return None

    viewer_following = _opt_bool(legacy.get("following"))
    if viewer_following is None:
        viewer_following = _opt_bool(perspectives.get("following"))
    viewer_followed_by = _opt_bool(legacy.get("followed_by"))
    if viewer_followed_by is None:
        viewer_followed_by = _opt_bool(perspectives.get("followed_by"))

    return UserProfile(
        id=user_data.get("rest_id") or "",
        name=core.get("name") or legacy.get("name") or "",
        screen_name=core.get("screen_name") or legacy.get("screen_name") or "",
        bio=legacy.get("description") or profile_bio.get("description") or "",
        location=location_obj.get("location") or legacy.get("location") or "",
        url=_deep_get(legacy, "entities", "url", "urls", 0, "expanded_url") or website.get("url") or "",
        followers_count=max(
            _parse_int(legacy.get("followers_count"), 0),
            _parse_int(rel_counts.get("followers"), 0),
        ),
        following_count=max(
            _parse_int(legacy.get("friends_count"), 0),
            _parse_int(rel_counts.get("following"), 0),
        ),
        tweets_count=max(
            _parse_int(legacy.get("statuses_count"), 0),
            _parse_int(tweet_counts.get("tweets"), 0),
        ),
        likes_count=max(
            _parse_int(legacy.get("favourites_count"), 0),
            _parse_int(action_counts.get("favorites_count"), 0),
        ),
        verified=bool(
            user_data.get("is_blue_verified", False)
            or legacy.get("verified", False)
            or verification.get("verified", False)
        ),
        profile_image_url=avatar.get("image_url") or legacy.get("profile_image_url_https") or "",
        created_at=core.get("created_at") or legacy.get("created_at") or "",
        viewer_following=viewer_following,
        viewer_followed_by=viewer_followed_by,
    )


# ── Tweet parsing ────────────────────────────────────────────────────────


def _unwrap_visibility(result):
    # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], bool]
    """Unwrap TweetWithVisibilityResults, returning (inner_data, is_subscriber_only)."""
    if result.get("__typename") == "TweetWithVisibilityResults" and result.get("tweet"):
        return result["tweet"], bool(result.get("tweetInterstitial"))
    return result, False


def parse_tweet_result(result, depth=0):
    # type: (Dict[str, Any], int) -> Optional[Tweet]
    """Parse a single TweetResult into a Tweet dataclass."""
    if depth > 2:
        return None

    tweet_data, is_subscriber_only = _unwrap_visibility(result)
    if tweet_data.get("__typename") == "TweetTombstone":
        return None

    legacy = tweet_data.get("legacy")
    core = tweet_data.get("core")
    if not isinstance(legacy, dict) or not isinstance(core, dict):
        return None

    user = _deep_get(core, "user_results", "result") or {}
    user_legacy = user.get("legacy") or {}
    user_core = user.get("core") or {}

    is_retweet = bool(_deep_get(legacy, "retweeted_status_result", "result"))
    actual_data = tweet_data
    actual_legacy = legacy
    actual_user = user
    actual_user_legacy = user_legacy

    if is_retweet:
        retweet_result = _deep_get(legacy, "retweeted_status_result", "result") or {}
        retweet_result, retweet_subscriber_only = _unwrap_visibility(retweet_result)
        rt_legacy = retweet_result.get("legacy")
        rt_core = retweet_result.get("core")
        if isinstance(rt_legacy, dict) and isinstance(rt_core, dict):
            actual_data = retweet_result
            actual_legacy = rt_legacy
            actual_user = _deep_get(rt_core, "user_results", "result") or {}
            actual_user_legacy = actual_user.get("legacy") or {}

    media = _extract_media(actual_legacy)
    urls = [item.get("expanded_url", "") for item in _deep_get(actual_legacy, "entities", "urls") or []]
    quoted = _deep_get(actual_data, "quoted_status_result", "result")
    quoted_tweet = parse_tweet_result(quoted, depth=depth + 1) if isinstance(quoted, dict) else None
    author = _extract_author(actual_user, actual_user_legacy)

    retweeted_by = None  # type: Optional[str]
    if is_retweet:
        retweeted_by = user_core.get("screen_name") or user_legacy.get("screen_name", "unknown")

    # Prefer note_tweet full text for long tweets ("Show More")
    note_text = _deep_get(actual_data, "note_tweet", "note_tweet_results", "result", "text")

    return Tweet(
        id=actual_data.get("rest_id", ""),
        text=note_text or actual_legacy.get("full_text", ""),
        author=author,
        metrics=Metrics(
            likes=_parse_int(actual_legacy.get("favorite_count"), 0),
            retweets=_parse_int(actual_legacy.get("retweet_count"), 0),
            replies=_parse_int(actual_legacy.get("reply_count"), 0),
            quotes=_parse_int(actual_legacy.get("quote_count"), 0),
            views=_parse_int(_deep_get(actual_data, "views", "count"), 0),
            bookmarks=_parse_int(actual_legacy.get("bookmark_count"), 0),
        ),
        created_at=actual_legacy.get("created_at", ""),
        media=media,
        urls=urls,
        is_retweet=is_retweet,
        retweeted_by=retweeted_by,
        quoted_tweet=quoted_tweet,
        lang=actual_legacy.get("lang", ""),
        is_subscriber_only=(is_subscriber_only or retweet_subscriber_only) if is_retweet else is_subscriber_only,
        possibly_sensitive=bool(
            actual_legacy.get("possibly_sensitive") or actual_legacy.get("possiblySensitive")
        ),
        conversation_id=_opt_str(actual_legacy.get("conversation_id_str")),
        in_reply_to_status_id=_opt_str(actual_legacy.get("in_reply_to_status_id_str")),
        in_reply_to_user_id=_opt_str(actual_legacy.get("in_reply_to_user_id_str")),
        in_reply_to_screen_name=_opt_str(actual_legacy.get("in_reply_to_screen_name")),
        **_parse_article(actual_data),
    )


# ── Timeline response parsing ───────────────────────────────────────────


def parse_timeline_response(data, get_instructions):
    # type: (Any, Callable[[Any], Any]) -> Tuple[List[Tweet], Optional[str]]
    """Parse timeline GraphQL response into tweets and next cursor."""
    tweets = []  # type: List[Tweet]
    next_cursor = None  # type: Optional[str]

    instructions = get_instructions(data)
    if not isinstance(instructions, list):
        logger.warning("No timeline instructions found")
        return tweets, next_cursor

    for instruction in instructions:
        entries = instruction.get("entries") or instruction.get("moduleItems") or []
        for entry in entries:
            content = entry.get("content", {})
            next_cursor = _extract_cursor(content) or next_cursor

            item_content = content.get("itemContent", {})
            result = _deep_get(item_content, "tweet_results", "result")
            if result:
                tweet = parse_tweet_result(result)
                if tweet:
                    tweet.is_promoted = bool(
                        str(entry.get("entryId") or "").startswith("promoted-")
                        or item_content.get("promotedMetadata")
                    )
                    tweets.append(tweet)

            for nested_item in content.get("items", []):
                nested_result = _deep_get(
                    nested_item,
                    "item",
                    "itemContent",
                    "tweet_results",
                    "result",
                )
                if nested_result:
                    tweet = parse_tweet_result(nested_result)
                    if tweet:
                        nested_item_content = _deep_get(nested_item, "item", "itemContent") or {}
                        tweet.is_promoted = bool(
                            str(_deep_get(nested_item, "entryId") or "").startswith("promoted-")
                            or nested_item_content.get("promotedMetadata")
                        )
                        tweets.append(tweet)

    return tweets, next_cursor
