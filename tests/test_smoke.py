"""Integration smoke tests for twitter-cli.

These tests invoke the real CLI commands with ``--yaml`` against the live
Twitter/X API using your local browser cookies.  They are **skipped by
default** and only run when explicitly requested::

    uv run pytest -m smoke -v

Only read-only operations are tested — no writes.
"""

from __future__ import annotations

import yaml
import pytest
from click.testing import CliRunner

from twitter_cli.cli import cli

smoke = pytest.mark.smoke

runner = CliRunner()


def _invoke(*args: str):
    """Run a CLI command with --yaml and return parsed payload."""
    result = runner.invoke(cli, [*args, "--yaml"])
    if result.output:
        payload = yaml.safe_load(result.output)
    else:
        payload = None
    return result, payload


# ── Auth ────────────────────────────────────────────────────────────────


@smoke
class TestAuth:
    """Verify authentication is working end-to-end."""

    def test_status(self):
        result, payload = _invoke("status")
        assert result.exit_code == 0, f"status failed: {result.output}"
        assert payload["ok"] is True
        assert payload["data"]["authenticated"] is True
        assert payload["data"]["user"]["username"]

    def test_whoami(self):
        result, payload = _invoke("whoami")
        assert result.exit_code == 0, f"whoami failed: {result.output}"
        assert payload["ok"] is True
        assert payload["data"]["user"]["username"]
        assert payload["data"]["user"]["id"]


# ── Read-only queries ───────────────────────────────────────────────────


@smoke
class TestReadOnly:
    """Read-only CLI smoke tests."""

    def test_user(self):
        result, payload = _invoke("user", "elonmusk")
        assert result.exit_code == 0, f"user failed: {result.output}"
        assert payload["ok"] is True

    def test_search(self):
        result, payload = _invoke("search", "python", "--max", "3")
        assert result.exit_code == 0, f"search failed: {result.output}"
        assert payload["ok"] is True
        items = payload["data"]
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_user_posts(self):
        result, payload = _invoke("user-posts", "elonmusk", "--max", "3")
        assert result.exit_code == 0, f"user-posts failed: {result.output}"
        assert payload["ok"] is True

    def test_feed(self):
        result, payload = _invoke("feed", "--max", "3")
        assert result.exit_code == 0, f"feed failed: {result.output}"
        assert payload["ok"] is True


@smoke
class TestCTGatedReads:
    """Endpoints that 404 without the x-client-transaction-id header.

    These were broken (HTTP 404 on SearchTimeline/Followers/Following/Likes)
    because the CT bootstrap fetched the stripped root page. They are the
    live regression guard for the /home+cookie bootstrap.
    """

    def test_followers(self):
        result, payload = _invoke("followers", "elonmusk", "--max", "3")
        assert result.exit_code == 0, f"followers failed: {result.output}"
        assert payload["ok"] is True
        assert len(payload["data"]) >= 1

    def test_following(self):
        result, payload = _invoke("following", "elonmusk", "--max", "3")
        assert result.exit_code == 0, f"following failed: {result.output}"
        assert payload["ok"] is True
        assert len(payload["data"]) >= 1
