"""Tweet formatter for terminal output (rich) and JSON export."""

from __future__ import annotations

import sys
from typing import List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .models import Tweet, UserProfile
from .timeutil import format_iso8601, format_local_time, format_relative_time

# How timestamps are rendered in human-readable output (issue #35).
#   relative -> "28s ago", "14d ago"   (default, most compact)
#   absolute -> "2026-03-14 21:08"     (local wall-clock, stable to eyeball)
#   iso      -> "2026-03-14T21:08:00+00:00"  (unambiguous, scriptable)
# Single-threaded CLI, so a module-level setting is sufficient; it is set once
# from the root command (or config) before any rendering happens.
_TIME_STYLES = ("relative", "absolute", "iso")
_TIME_STYLE = "relative"


def set_time_style(style: Optional[str]) -> str:
    """Select the timestamp rendering style; returns the style in effect."""
    global _TIME_STYLE
    if style and style in _TIME_STYLES:
        _TIME_STYLE = style
    return _TIME_STYLE


def get_time_style() -> str:
    """Return the timestamp rendering style currently in effect."""
    return _TIME_STYLE


def _render_time(created_at: str) -> str:
    """Render one timestamp according to the selected style."""
    if _TIME_STYLE == "absolute":
        return format_local_time(created_at)
    if _TIME_STYLE == "iso":
        return format_iso8601(created_at)
    return format_relative_time(created_at)


def _make_console() -> Console:
    """Create a Console that works correctly on Windows pipes.

    On Windows, rich may use WriteConsoleW API directly instead of writing
    to stdout, making output invisible to pipe/subprocess capture.
    Using force_terminal=False in non-TTY contexts prevents this.
    """
    if sys.platform == "win32" and not sys.stdout.isatty():
        return Console(force_terminal=False)
    return Console()


def format_number(n: int) -> str:
    """Format number with K/M suffixes."""
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fK" % (n / 1_000)
    return str(n)


def print_tweet_table(
    tweets: List[Tweet],
    console: Optional[Console] = None,
    title: Optional[str] = None,
    full_text: bool = False,
) -> None:
    """Print tweets as a rich table."""
    if console is None:
        console = _make_console()

    if not title:
        title = "ðŸ“± Twitter â€” %d tweets" % len(tweets)

    table = Table(title=title, show_lines=True, expand=True)
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Author", style="cyan", width=18, no_wrap=True)
    table.add_column("Tweet", ratio=3)
    table.add_column("Stats", style="green", width=22, no_wrap=True)
    table.add_column("Score", style="yellow", width=6, justify="right")

    for i, tweet in enumerate(tweets):
        # Author
        verified = " âœ“" if tweet.author.verified else ""
        author_text = "@%s%s" % (tweet.author.screen_name, verified)
        if tweet.is_retweet and tweet.retweeted_by:
            author_text += "\nðŸ”„ @%s" % tweet.retweeted_by

        # Tweet text
        text = tweet.text.replace("\n", " ").strip()
        if not full_text and len(text) > 120:
            text = text[:117] + "..."

        # Media indicators
        if tweet.media:
            media_icons = []
            for m in tweet.media:
                if m.type == "photo":
                    media_icons.append("ðŸ“·")
                elif m.type == "video":
                    media_icons.append("ðŸ“¹")
                else:
                    media_icons.append("ðŸŽžï¸")
            text += " " + " ".join(media_icons)

        # Quoted tweet
        if tweet.quoted_tweet:
            qt = tweet.quoted_tweet
            qt_text = qt.text.replace("\n", " ")
            if not full_text and len(qt_text) > 60:
                qt_text = qt_text[:57] + "..."
            text += "\nâ”Œ @%s: %s" % (qt.author.screen_name, qt_text)

        # Tweet link
        text += "\nðŸ”— x.com/%s/status/%s" % (tweet.author.screen_name, tweet.id)

        # Stats
        rel_time = _render_time(tweet.created_at)
        stats = (
            "â¤ï¸ %s  ðŸ”„ %s\nðŸ’¬ %s  ðŸ‘ï¸ %s\nðŸ• %s"
            % (
                format_number(tweet.metrics.likes),
                format_number(tweet.metrics.retweets),
                format_number(tweet.metrics.replies),
                format_number(tweet.metrics.views),
                rel_time,
            )
        )

        # Score
        score_str = "%.1f" % tweet.score if tweet.score is not None else "-"

        table.add_row(str(i + 1), author_text, text, stats, score_str)

    console.print(table)


def print_tweet_detail(tweet: Tweet, console: Optional[Console] = None) -> None:
    """Print a single tweet in detail using a rich panel."""
    if console is None:
        console = _make_console()

    verified = " âœ“" if tweet.author.verified else ""
    header = "@%s%s (%s)" % (tweet.author.screen_name, verified, tweet.author.name)

    body_parts = []

    if tweet.is_retweet and tweet.retweeted_by:
        body_parts.append("ðŸ”„ Retweeted by @%s\n" % tweet.retweeted_by)

    body_parts.append(tweet.text)

    if tweet.media:
        body_parts.append("")
        for m in tweet.media:
            icon = "ðŸ“·" if m.type == "photo" else ("ðŸ“¹" if m.type == "video" else "ðŸŽžï¸")
            body_parts.append("%s %s: %s" % (icon, m.type, m.url))

    if tweet.urls:
        body_parts.append("")
        for url in tweet.urls:
            body_parts.append("ðŸ”— %s" % url)

    if tweet.quoted_tweet:
        qt = tweet.quoted_tweet
        body_parts.append("")
        body_parts.append("â”Œâ”€â”€ Quoted @%s â”€â”€" % qt.author.screen_name)
        body_parts.append(qt.text)

    body_parts.append("")
    body_parts.append(
        "â¤ï¸ %s  ðŸ”„ %s  ðŸ’¬ %s  ðŸ”– %s  ðŸ‘ï¸ %s"
        % (
            format_number(tweet.metrics.likes),
            format_number(tweet.metrics.retweets),
            format_number(tweet.metrics.replies),
            format_number(tweet.metrics.bookmarks),
            format_number(tweet.metrics.views),
        )
    )
    local_time = format_local_time(tweet.created_at)
    rel_time = _render_time(tweet.created_at)
    # In the default (relative) view the absolute time is the useful companion;
    # under absolute/iso the stamp is already unambiguous, so do not repeat it.
    if _TIME_STYLE == "relative":
        time_text = "%s (%s)" % (local_time, rel_time)
    else:
        time_text = local_time if _TIME_STYLE == "absolute" else rel_time
    body_parts.append(
        "🕐 %s · https://x.com/%s/status/%s"
        % (time_text, tweet.author.screen_name, tweet.id)
    )

    console.print(Panel(
        "\n".join(body_parts),
        title=header,
        border_style="blue",
        expand=True,
    ))


def article_to_markdown(tweet: Tweet) -> str:
    """Convert a Twitter Article tweet into a Markdown document."""
    title = tweet.article_title or "Twitter Article"
    lines = [
        "# %s" % title,
        "",
        "- Author: @%s (%s)" % (tweet.author.screen_name, tweet.author.name),
        "- Published: %s" % (tweet.created_at or "unknown"),
        "- URL: https://x.com/%s/status/%s" % (tweet.author.screen_name, tweet.id),
        "- Likes: %s" % format_number(tweet.metrics.likes),
        "- Retweets: %s" % format_number(tweet.metrics.retweets),
        "- Replies: %s" % format_number(tweet.metrics.replies),
        "- Bookmarks: %s" % format_number(tweet.metrics.bookmarks),
        "- Views: %s" % format_number(tweet.metrics.views),
    ]

    if tweet.article_text:
        lines.extend(["", tweet.article_text.strip()])

    return "\n".join(lines).strip() + "\n"


def print_article(tweet: Tweet, console: Optional[Console] = None) -> None:
    """Print a Twitter Article with rich formatting."""
    if console is None:
        console = _make_console()

    verified = " âœ“" if tweet.author.verified else ""
    title = tweet.article_title or "Twitter Article"
    meta_parts = [
        "By @%s%s (%s)" % (tweet.author.screen_name, verified, tweet.author.name),
        "ðŸ• %s" % tweet.created_at,
        "ðŸ”— x.com/%s/status/%s" % (tweet.author.screen_name, tweet.id),
        "",
        "â¤ï¸ %s  ðŸ”„ %s  ðŸ’¬ %s  ðŸ”– %s  ðŸ‘ï¸ %s"
        % (
            format_number(tweet.metrics.likes),
            format_number(tweet.metrics.retweets),
            format_number(tweet.metrics.replies),
            format_number(tweet.metrics.bookmarks),
            format_number(tweet.metrics.views),
        ),
    ]
    console.print(Panel(
        "\n".join(meta_parts),
        title="ðŸ“° %s" % title,
        border_style="blue",
        expand=True,
    ))

    if tweet.article_text:
        console.print()
        console.print(Markdown(tweet.article_text))


def print_filter_stats(
    original_count: int,
    filtered: List[Tweet],
    console: Optional[Console] = None,
) -> None:
    """Print filter statistics."""
    if console is None:
        console = _make_console()

    console.print(
        "ðŸ“Š Filter: %d â†’ %d tweets" % (original_count, len(filtered))
    )
    if filtered:
        top_score = filtered[0].score or 0.0
        bottom_score = filtered[-1].score or 0.0
        console.print(
            "   Score range: %.1f ~ %.1f" % (bottom_score, top_score)
        )


def print_user_profile(user: UserProfile, console: Optional[Console] = None) -> None:
    """Print user profile as a rich panel."""
    if console is None:
        console = _make_console()

    verified = " âœ“" if user.verified else ""
    header = "@%s%s (%s)" % (user.screen_name, verified, user.name)

    lines = []
    if user.bio:
        lines.append(user.bio)
        lines.append("")

    if user.location:
        lines.append("ðŸ“ %s" % user.location)
    if user.url:
        lines.append("ðŸ”— %s" % user.url)
    if user.location or user.url:
        lines.append("")

    lines.append(
        "ðŸ‘¥ %s followers Â· %s following Â· %s tweets Â· %s likes"
        % (
            format_number(user.followers_count),
            format_number(user.following_count),
            format_number(user.tweets_count),
            format_number(user.likes_count),
        )
    )

    if user.created_at:
        lines.append("ðŸ“… Joined %s" % user.created_at)
    lines.append("ðŸ”— x.com/%s" % user.screen_name)

    console.print(Panel(
        "\n".join(lines),
        title=header,
        border_style="cyan",
        expand=True,
    ))


def print_user_table(
    users: List[UserProfile],
    console: Optional[Console] = None,
    title: Optional[str] = None,
) -> None:
    """Print a list of users as a rich table."""
    if console is None:
        console = _make_console()

    if not title:
        title = "ðŸ‘¥ Users â€” %d" % len(users)

    table = Table(title=title, show_lines=True, expand=True)
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("User", style="cyan", width=20, no_wrap=True)
    table.add_column("Bio", ratio=3)
    table.add_column("Stats", style="green", width=22, no_wrap=True)

    for i, user in enumerate(users):
        verified = " âœ“" if user.verified else ""
        user_text = "@%s%s\n%s" % (user.screen_name, verified, user.name)

        bio = (user.bio or "").replace("\n", " ").strip()
        if len(bio) > 100:
            bio = bio[:97] + "..."

        stats = (
            "ðŸ‘¥ %s followers\nðŸ“ %s following"
            % (
                format_number(user.followers_count),
                format_number(user.following_count),
            )
        )

        table.add_row(str(i + 1), user_text, bio, stats)

    console.print(table)

