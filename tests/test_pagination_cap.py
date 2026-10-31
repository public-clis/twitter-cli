"""Followers/following pagination must honour an explicit --max (issue #50).

`_fetch_user_list` used to clamp the requested count to ``self._max_count``,
which is derived from the ``rateLimit.maxCount`` config (default 200) and was
additionally bounded by a hard 500 ceiling. The pagination loop itself was
correct, so large accounts were silently truncated regardless of ``--max``.
"""

from __future__ import annotations

from types import SimpleNamespace

from twitter_cli import client as client_mod
from twitter_cli.client import _ABSOLUTE_MAX_COUNT, TwitterClient


class _StubClient(TwitterClient):
    """Client whose GraphQL calls are fully stubbed."""

    def __init__(self):
        self._auth_token = "t"
        self._ct0 = "c"
        self._cookie_string = None
        self._client_transaction = None
        self._ct_init_attempted = True
        self._max_count = 200  # the configured default that used to clamp
        self._request_delay = 0.0
        self._max_retries = 0
        self.pages_requested = 0


def _instructions(user_ids, cursor=None):
    """One page of user entries plus an optional bottom cursor."""
    entries = []
    for index, uid in enumerate(user_ids):
        entries.append(
            {
                "content": {
                    "entryType": "TimelineTimelineItem",
                    "itemContent": {"user_results": {"result": {"rest_id": uid}}},
                }
            }
        )
    if cursor:
        entries.append(
            {
                "content": {
                    "entryType": "TimelineTimelineCursor",
                    "cursorType": "Bottom",
                    "value": cursor,
                }
            }
        )
    return [{"entries": entries}]


def _make_paged_client(monkeypatch, page_size=20, total_pages=40):
    """Return a client that serves `total_pages` full pages then stops."""
    stub = _StubClient()
    state = {"page": 0}

    def fake_graphql_get(operation_name, variables, features, field_toggles=None):
        index = state["page"]
        state["page"] += 1
        stub.pages_requested += 1
        ids = ["u%d" % (index * page_size + i) for i in range(page_size)]
        has_more = index + 1 < total_pages
        return {
            "instructions": _instructions(
                ids, cursor="cursor-%d" % (index + 1) if has_more else None
            )
        }

    monkeypatch.setattr(stub, "_graphql_get", fake_graphql_get)
    monkeypatch.setattr(stub, "_graphql_post", fake_graphql_get)
    monkeypatch.setattr(
        client_mod,
        "parse_user_result",
        lambda result: SimpleNamespace(id=result.get("rest_id")) if result.get("rest_id") else None,
    )
    return stub


def test_explicit_max_beyond_old_500_cap_is_fetched(monkeypatch) -> None:
    """600 users must be retrievable; the old ceiling stopped at 500."""
    stub = _make_paged_client(monkeypatch, page_size=20, total_pages=40)

    users = stub._fetch_user_list(
        "Followers", "123", 600, lambda data: data.get("instructions")
    )

    assert len(users) == 600
    assert stub.pages_requested >= 30


def test_explicit_max_ignores_configured_default(monkeypatch) -> None:
    """A config default of 200 must not truncate an explicit --max of 300."""
    stub = _make_paged_client(monkeypatch, page_size=20, total_pages=40)

    users = stub._fetch_user_list(
        "Following", "123", 300, lambda data: data.get("instructions")
    )

    assert len(users) == 300


def test_safety_ceiling_still_applies(monkeypatch, caplog) -> None:
    """An absurd request is capped at the safety ceiling, not unbounded."""
    stub = _StubClient()
    requested = {}

    def fake_graphql_get(operation_name, variables, features, field_toggles=None):
        requested["count"] = requested.get("count", 0) + 1
        # Single page then stop, so we observe the clamp without 500 pages.
        return {"instructions": _instructions(["u1"])}

    monkeypatch.setattr(stub, "_graphql_get", fake_graphql_get)
    monkeypatch.setattr(client_mod, "parse_user_result", lambda r: SimpleNamespace(id="u1"))

    with caplog.at_level("WARNING"):
        stub._fetch_user_list("Followers", "1", _ABSOLUTE_MAX_COUNT + 5000, lambda d: d["instructions"])

    assert "exceeds the safety ceiling" in caplog.text


def test_zero_or_negative_count_returns_empty(monkeypatch) -> None:
    stub = _make_paged_client(monkeypatch)
    assert stub._fetch_user_list("Followers", "1", 0, lambda d: d["instructions"]) == []
    assert stub._fetch_user_list("Followers", "1", -5, lambda d: d["instructions"]) == []


def test_ceiling_is_large_enough_for_real_accounts() -> None:
    """Regression guard: the ceiling must stay well above the old 500."""
    assert _ABSOLUTE_MAX_COUNT >= 5000
