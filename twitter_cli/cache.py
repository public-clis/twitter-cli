"""Short-index cache: persist the last displayed tweet list for quick `show` access."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, List, Optional, Tuple

from .models import Tweet

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".twitter-cli"
_CACHE_FILE = _CACHE_DIR / "last_results.json"
_TTL = 3600  # seconds

# Owner-only permissions for cache artefacts (0600 files / 0700 directory).
_OWNER_ONLY_FILE = 0o600
_OWNER_ONLY_DIR = 0o700


@contextmanager
def _open_owner_only(path: Path) -> Iterator[IO[str]]:
    """Atomically write ``path`` with owner-only permissions.

    Creates a unique sibling temporary file using ``O_CREAT | O_EXCL`` (and
    ``O_NOFOLLOW`` where supported) with mode ``0o600``, then atomically
    replaces ``path`` via ``os.replace``. This prevents symlink-following
    attacks and partial/interleaved reads under concurrent invocations.
    """
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    tmp_path = path.parent / (".%s.%d.%s.tmp" % (path.name, os.getpid(), uuid.uuid4().hex[:8]))
    fd = os.open(str(tmp_path), flags, _OWNER_ONLY_FILE)
    handle: Optional[IO[str]] = None
    try:
        try:
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(fd, _OWNER_ONLY_FILE)
            else:  # pragma: no cover - non-POSIX
                os.chmod(str(tmp_path), _OWNER_ONLY_FILE)
        except OSError:  # pragma: no cover - permission change is best-effort
            pass
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        yield handle
        handle.flush()
        handle.close()
        handle = None
        os.replace(str(tmp_path), str(path))
    except BaseException:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        elif fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _tighten_dir(directory: Path) -> None:
    """Best-effort owner-only permission on a cache directory."""
    try:
        os.chmod(str(directory), _OWNER_ONLY_DIR)
    except OSError:
        pass


def save_tweet_cache(tweets: List[Tweet]) -> None:
    """Persist tweet list so indices can be resolved by `show`."""
    try:
        _CACHE_DIR.mkdir(mode=_OWNER_ONLY_DIR, parents=True, exist_ok=True)
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
