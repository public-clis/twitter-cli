"""Short-index cache: persist the last displayed tweet list for quick `show` access."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import IO, List, Optional, Tuple

from .models import Tweet

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".twitter-cli"
_CACHE_FILE = _CACHE_DIR / "last_results.json"
_TTL = 3600  # seconds

# Owner-only permissions for cache artefacts.
#
# The ClientTransaction cache stores the full x.com/home HTML, which embeds the
# live auth_token / ct0 for the session, and the index cache stores tweet text
# the user has read. Neither should be world- or group-readable on a host with
# other local users.
_OWNER_ONLY_FILE = 0o600
_OWNER_ONLY_DIR = 0o700


def _open_owner_only(path: Path) -> IO[str]:
    """Open ``path`` for writing with owner-only permissions.

    Uses ``O_CREAT`` with an explicit mode so a newly created file is never
    briefly world-readable (a plain ``open()`` would honour the umask first and
    only narrow afterwards). An existing file with looser permissions is
    tightened on every write. Permission changes are best-effort: on Windows
    ``chmod`` only toggles the read-only bit, and a cache write must never fail
    the command that triggered it.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(str(path), flags, _OWNER_ONLY_FILE)
    try:
        # Not declared on every platform by typeshed; guarded on AttributeError.
        os.fchmod(fd, _OWNER_ONLY_FILE)  # type: ignore[attr-defined]
    except (AttributeError, OSError):  # pragma: no cover - platform dependent
        try:
            os.chmod(str(path), _OWNER_ONLY_FILE)
        except OSError:
            pass
    return os.fdopen(fd, "w", encoding="utf-8")


def save_tweet_cache(tweets: List[Tweet]) -> None:
    """Persist tweet list so indices can be resolved by `show`."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _tighten_dir(_CACHE_DIR)
        entries = [
            {"index": i + 1, "id": t.id, "author": t.author.screen_name, "text": t.text[:80]}
            for i, t in enumerate(tweets)
            if t.id
        ]
        payload = {"created_at": time.time(), "tweets": entries}
        with _open_owner_only(_CACHE_FILE) as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError as exc:
        logger.debug("Failed to write tweet cache: %s", exc)


def _tighten_dir(directory: Path) -> None:
    """Best-effort owner-only permission on a cache directory."""
    try:
        os.chmod(str(directory), _OWNER_ONLY_DIR)
    except OSError:
        pass


def _load_cache() -> Optional[List[dict]]:
    """Load and validate the cache file; return tweet entries or None if stale/missing."""
    try:
        if not _CACHE_FILE.exists():
            return None
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if time.time() - payload.get("created_at", 0) > _TTL:
            return None
        entries = payload.get("tweets", [])
        if not isinstance(entries, list):
            return None
        return [e for e in entries if isinstance(e, dict)]
    except (OSError, json.JSONDecodeError):
        return None


def resolve_cached_tweet(index: int) -> Tuple[Optional[str], int]:
    """Resolve a 1-based index to a tweet ID, returning (tweet_id, cache_size).

    Returns (tweet_id, cache_size) where tweet_id is None if the index
    cannot be resolved (empty/expired cache or out-of-range index).
    """
    entries = _load_cache()
    if entries is None:
        return None, 0
    for entry in entries:
        if entry.get("index") == index:
            tweet_id = entry.get("id")
            return (str(tweet_id) if tweet_id is not None else None), len(entries)
    return None, len(entries)