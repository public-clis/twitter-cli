"""X weighted text length and long-form routing helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple  # noqa: F401


CREATE_TWEET_OPERATION = "CreateTweet"
CREATE_NOTE_TWEET_OPERATION = "CreateNoteTweet"
STANDARD_TWEET_WEIGHT_LIMIT = 280

_TRANSFORMED_URL_LENGTH = 23
_WEIGHT_ONE_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)

# Common IANA TLDs recognized by twitter-text for bare domains without http(s)://
# (prevents filenames like config.yaml / README.md / cli.py or prose like Hello.World
# from being inflated to 23 chars and misrouted to CreateNoteTweet).
_COMMON_TLDS = (
    "com|org|net|edu|gov|mil|int|io|co|ai|app|dev|me|tv|gg|xyz|info|biz|tech|cloud|"
    "news|live|shop|store|site|online|blog|page|link|so|sh|to|ly|gl|be|de|uk|fr|jp|"
    "cn|kr|ca|au|in|br|es|it|nl|se|ch|ru|pl|tw|hk|sg|eu|us|nz|id|vn|th|mx|ar|cl|za|"
    "pro|club|top|icu|vip|cc|fm|im|is|la|vc|ws|ag|am|at|cz|dk|fi|gr|hu|ie|il|no|pt|"
    "ro|sk|tr|ua|ac|pub|run|bot|fun|wtf|lol|new|now|one|art|inc|nyc|ooo|tel|xxx"
)

_PROTOCOL_URL = r"(?<![\w@])https?://[^\s<>{}\[\]\"']+"
_BARE_URL = (
    r"(?<![\w@/.#])"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:%s|xn--[a-z0-9-]{2,59})"
    r"(?![\w@])"
    r"(?::\d{1,5})?(?:[/?#][^\s<>{}\[\]\"']*)?"
) % _COMMON_TLDS
_URL_RE = re.compile(r"(?:%s|%s)" % (_PROTOCOL_URL, _BARE_URL), re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,!?:;'\""

_EMOJI_BASE_RANGES = (
    (0x2190, 0x21FF),
    (0x2300, 0x23FF),
    (0x25AA, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B55),
    (0x1F000, 0x1FAFF),
    (0x1FC00, 0x1FFFF),
)
# 0x00A9 (©) and 0x00AE (®) only count as weight-2 emoji when followed by U+FE0F.
_EMOJI_BASES = {0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
_TEXT_DEFAULT_EMOJI_BASES = {0x00A9, 0x00AE}


def _trim_url_end(url):
    # type: (str) -> int
    """Return the URL end before prose punctuation or unmatched closers."""
    end = len(url)
    while end:
        prev = end
        while end and url[end - 1] in _TRAILING_URL_PUNCTUATION:
            end -= 1
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
            while end and url[end - 1] == closing and url[:end].count(closing) > url[:end].count(opening):
                end -= 1
        if end == prev:
            break
    return end


def _url_spans(text):
    # type: (str) -> Iterator[Tuple[int, int]]
    for match in _URL_RE.finditer(text):
        end = match.start() + _trim_url_end(match.group(0))
        if end > match.start():
            yield match.start(), end


def _is_emoji_base(codepoint):
    # type: (int) -> bool
    return codepoint in _EMOJI_BASES or any(start <= codepoint <= end for start, end in _EMOJI_BASE_RANGES)


def _consume_emoji_suffix(text, index, limit):
    # type: (str, int, int) -> int
    while index < limit and (
        ord(text[index]) in (0xFE0E, 0xFE0F)
        or 0x1F3FB <= ord(text[index]) <= 0x1F3FF
        or 0xE0020 <= ord(text[index]) <= 0xE007F
    ):
        index += 1
    return index


def _emoji_sequence_end(text, index, limit):
    # type: (str, int, int) -> Optional[int]
    codepoint = ord(text[index])

    if text[index] in "#*0123456789":
        cursor = index + 1
        if cursor < limit and ord(text[cursor]) == 0xFE0F:
            cursor += 1
        if cursor < limit and ord(text[cursor]) == 0x20E3:
            return cursor + 1
        return None

    if 0x1F1E6 <= codepoint <= 0x1F1FF:
        if index + 1 < limit and 0x1F1E6 <= ord(text[index + 1]) <= 0x1F1FF:
            return index + 2
        return index + 1

    if codepoint in _TEXT_DEFAULT_EMOJI_BASES:
        if index + 1 < limit and ord(text[index + 1]) == 0xFE0F:
            return _consume_emoji_suffix(text, index + 2, limit)
        return None

    if not _is_emoji_base(codepoint):
        return None

    cursor = _consume_emoji_suffix(text, index + 1, limit)
    while cursor + 1 < limit and ord(text[cursor]) == 0x200D:
        next_codepoint = ord(text[cursor + 1])
        if not _is_emoji_base(next_codepoint):
            break
        cursor = _consume_emoji_suffix(text, cursor + 2, limit)
    return cursor


def _character_weight(codepoint):
    # type: (int) -> int
    if any(start <= codepoint <= end for start, end in _WEIGHT_ONE_RANGES):
        return 1
    return 2


def _weighted_segment(text, start, end):
    # type: (str, int, int) -> int
    weight = 0
    index = start
    while index < end:
        emoji_end = _emoji_sequence_end(text, index, end)
        if emoji_end is not None:
            weight += 2
            index = emoji_end
            continue
        weight += _character_weight(ord(text[index]))
        index += 1
    return weight


def tweet_weighted_length(text):
    # type: (str) -> int
    """Return the twitter-text v3 weighted length used for routing."""
    normalized = unicodedata.normalize("NFC", text)
    weight = 0
    cursor = 0
    for start, end in _url_spans(normalized):
        weight += _weighted_segment(normalized, cursor, start)
        weight += _TRANSFORMED_URL_LENGTH
        cursor = end
    return weight + _weighted_segment(normalized, cursor, len(normalized))


def tweet_create_route(text):
    # type: (str) -> Tuple[str, int]
    """Return the create operation and weighted length for tweet text."""
    weighted_length = tweet_weighted_length(text)
    operation = (
        CREATE_NOTE_TWEET_OPERATION
        if weighted_length > STANDARD_TWEET_WEIGHT_LIMIT
        else CREATE_TWEET_OPERATION
    )
    return operation, weighted_length
