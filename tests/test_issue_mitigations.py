"""Mitigations for account-safety and Windows-cookie issues (#72, #28/#66/#46).

Both are advisory rather than behavioural: we do not refuse to run, we make the
cause and the workaround visible instead of leaving users with a silent 404 or a
generic "decryption failed".
"""

from __future__ import annotations

import pytest

from twitter_cli import auth
from twitter_cli.client import TwitterClient

# ── #28 / #66 / #46: Windows App-Bound Encryption ────────────────────────

ABC_DIAGNOSTIC = [
    "chrome in-process extraction failed: Unable to get key for cookie decryption"
]


@pytest.fixture()
def windows(monkeypatch):
    """Pin the platform to Windows so these assertions are host-independent.

    `_diagnose_keychain_issues` branches on `sys.platform`; without this they
    only hold when the suite happens to run on Windows.
    """
    monkeypatch.setattr(auth.sys, "platform", "win32")
    for var in ("SSH_CLIENT", "SSH_TTY", "SSH_CONNECTION"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_windows_abc_failure_names_app_bound_encryption(windows) -> None:
    hint = auth._diagnose_keychain_issues(ABC_DIAGNOSTIC)

    assert hint is not None
    assert "App-Bound Encryption" in hint
    # Must not send people down the admin rabbit hole.
    assert "not a permissions issue" in hint


def test_windows_abc_hint_gives_actionable_workarounds(windows) -> None:
    hint = auth._diagnose_keychain_issues(ABC_DIAGNOSTIC)

    assert hint is not None
    assert "TWITTER_AUTH_TOKEN" in hint
    assert "TWITTER_CT0" in hint
    assert "TWITTER_BROWSER=firefox" in hint


def test_windows_generic_failure_keeps_generic_hint(windows) -> None:
    hint = auth._diagnose_keychain_issues(["chrome: Safe Storage unavailable"])

    assert hint is not None
    assert "App-Bound Encryption" not in hint


def test_windows_hint_retains_dpapi_advice(windows) -> None:
    """The non-ABC causes (Chrome lock / VSS shadowcopy) stay documented."""
    hint = auth._diagnose_keychain_issues(ABC_DIAGNOSTIC)
    assert hint is not None
    assert "VSS shadowcopy" in hint


def test_non_matching_diagnostic_returns_none(windows) -> None:
    assert auth._diagnose_keychain_issues(["browser not found"]) is None


# ── #72: writing without x-client-transaction-id ─────────────────────────


def _unsigned_client():
    client = TwitterClient.__new__(TwitterClient)
    client._auth_token = "tok"
    client._ct0 = "ct0"
    client._cookie_string = None
    client._client_transaction = None  # bootstrap failed
    return client


def test_unsigned_write_logs_a_prominent_warning(caplog) -> None:
    client = _unsigned_client()

    with caplog.at_level("WARNING"):
        headers = client._build_headers("https://x.com/i/api/graphql/q/CreateTweet", method="POST")

    assert "X-Client-Transaction-Id" not in headers
    assert "UNSIGNED" in caplog.text
    assert "automation" in caplog.text


def test_signed_write_does_not_warn(caplog) -> None:
    client = _unsigned_client()
    client._client_transaction = type(
        "CT", (), {"generate_transaction_id": staticmethod(lambda method, path: "tid-123")}
    )()

    with caplog.at_level("WARNING"):
        headers = client._build_headers("https://x.com/i/api/graphql/q/CreateTweet", method="POST")

    assert headers["X-Client-Transaction-Id"] == "tid-123"
    assert "UNSIGNED" not in caplog.text


def test_unsigned_read_does_not_warn(caplog) -> None:
    """Reads without the header mostly just 404; warning would be noise."""
    client = _unsigned_client()

    with caplog.at_level("WARNING"):
        client._build_headers("https://x.com/i/api/graphql/q/HomeTimeline", method="GET")

    assert "UNSIGNED" not in caplog.text


def test_write_does_not_raise(caplog) -> None:
    """The warning must not turn into a hard failure."""
    client = _unsigned_client()
    with caplog.at_level("WARNING"):
        headers = client._build_headers("https://x.com/i/api/graphql/q/CreateTweet", method="POST")

    assert isinstance(headers, dict)
