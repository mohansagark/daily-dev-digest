"""Curated RSS/Atom feed list for every allowed topic (#17).

`FEED_SOURCES` (comma-separated env/secret) still overrides this list when set,
so experiments remain possible without a code change. When unset/empty, these
defaults are used — that is what CI should run day-to-day.
"""

from __future__ import annotations

import os

# Dropped vs the old secret list: feedburner Smashing (duplicate), TechCrunch
# web-development (stale 2022–2024), bare dev.to firehose (noisy journals).
# Hackernoon kept out — crypto press-release spam in recent samples.
DEFAULT_FEEDS = [
    # frontend (kept)
    "https://css-tricks.com/feed/",
    "https://www.smashingmagazine.com/feed/",
    "https://www.sitepoint.com/feed/",
    "https://www.freecodecamp.org/news/rss/",
    # ai
    "https://simonwillison.net/atom/everything/",
    "https://huggingface.co/blog/feed.xml",
    "https://jack-clark.net/feed/",
    "https://bair.berkeley.edu/blog/feed.xml",
    # ai_news
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    # architecture
    "https://netflixtechblog.com/feed",
    "https://feed.infoq.com/",
    "https://blog.cloudflare.com/rss/",
    "https://blog.bytebytego.com/feed",
    "https://stackoverflow.blog/feed/",
    "https://martinfowler.com/feed.atom",
    # tools
    "https://blog.jetbrains.com/feed/",
    "https://github.blog/feed/",
    "https://console.dev/rss.xml",
    # biz_ideas (HN items link out; fetch_clean_content follows the target URL)
    "https://hnrss.org/show",
    "https://hnrss.org/newest?q=Launch+HN",
    "https://www.saastr.com/feed/",
    "https://sive.rs/en.atom",
    # client_websites
    "https://webflow.com/blog/rss.xml",
    "https://wptavern.com/feed",
    "https://cssauthor.com/feed/",
    "https://www.webdesignerdepot.com/feed/",
    # narrow technical tags (better than /tag/webdev hustle posts)
    "https://dev.to/feed/tag/architecture",
    "https://dev.to/feed/tag/python",
    "https://dev.to/feed/tag/devops",
]

# Reject articles whose RSS pubDate is older than this (when parseable).
MAX_ARTICLE_AGE_DAYS = int(os.getenv("MAX_ARTICLE_AGE_DAYS", "21"))


def resolve_feed_sources(env_value: str | None = None) -> list[str]:
    """Return the feed URL list for this run."""
    raw = os.getenv("FEED_SOURCES", "") if env_value is None else env_value
    from_env = [f.strip() for f in (raw or "").split(",") if f.strip()]
    if from_env:
        return from_env
    return list(DEFAULT_FEEDS)
