"""Followers/following pagination honours explicit --max (issue #50)."""

from __future__ import annotations

from types import SimpleNamespace

from twitter_cli import client as client_mod
from twitter_cli.client import _ABSOLUTE_MAX_COUNT, TwitterClient


class _StubClient(TwitterClient):
    def __init__(self):
        self._auth_token = "t"
        self._ct0 = "c"
        self._cookie_string = None
        self._client_transaction = None
        self._ct_init_attempted = True
        self._max_count = 200
        self._request_delay = 0.0
        self._max_retries = 0
        self.pages_requested = 0


def _instructions(user_ids, cursor=None):
    entries = [
        {
            "content": {
                "entryType": "TimelineTimelineItem",
                "itemContent": {"user_results": {"result": {"rest_id": uid}}},
            }
        }
        for uid in user_ids
    ]
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
    stub = _StubClient()
    state = {"page": 0}

    def fake_graphql(operation_name, variables, features, field_toggles=None):
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

    monkeypatch.setattr(stub, "_graphql_get", fake_graphql)
    monkeypatch.setattr(stub, "_graphql_post", fake_graphql)
    monkeypatch.setattr(
        client_mod,
        "parse_user_result",
        lambda result: SimpleNamespace(id=result.get("rest_id")) if result.get("rest_id") else None,
    )
    return stub


def test_explicit_max_beyond_old_500_cap_is_fetched(monkeypatch) -> None:
    stub = _make_paged_client(monkeypatch, page_size=20, total_pages=40)
    users = stub._fetch_user_list("Followers", "123", 600, lambda data: data.get("instructions"))
    assert len(users) == 600
    assert stub.pages_requested >= 30


def test_safety_ceiling_still_applies(monkeypatch, caplog) -> None:
    stub = _StubClient()
    monkeypatch.setattr(stub, "_graphql_get", lambda *a, **kw: {"instructions": _instructions(["u1"])})
    monkeypatch.setattr(client_mod, "parse_user_result", lambda r: SimpleNamespace(id="u1"))

    with caplog.at_level("WARNING"):
        stub._fetch_user_list("Followers", "1", _ABSOLUTE_MAX_COUNT + 5000, lambda d: d["instructions"])

    assert "exceeds the safety ceiling" in caplog.text


def test_ceiling_is_large_enough_for_real_accounts() -> None:
    assert _ABSOLUTE_MAX_COUNT >= 5000
