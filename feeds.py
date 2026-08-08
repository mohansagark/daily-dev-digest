"""Curated RSS/Atom feed catalog for digest generation (#17).

`FEED_SOURCES` (comma-separated env/secret) still overrides the flattened URL
list when set. When unset/empty, ``DEFAULT_FEEDS`` (unique URLs from
``FEED_CATALOG``, first-seen order) is used.
"""

from __future__ import annotations

import os

# Grouped catalog — names are documentation; the fetcher uses URLs only.
# Duplicate URLs across groups are fine here; DEFAULT_FEEDS dedupes them.
FEED_CATALOG: dict[str, list[dict[str, str]]] = {
    # ============================================================
    # FRONTEND / WEB DEVELOPMENT
    # ============================================================
    "frontend": [
        {"name": "Smashing Magazine", "url": "https://www.smashingmagazine.com/feed/"},
        {"name": "CSS-Tricks", "url": "https://css-tricks.com/feed/"},
        {"name": "freeCodeCamp", "url": "https://www.freecodecamp.org/news/rss/"},
        {"name": "SitePoint", "url": "https://www.sitepoint.com/feed/"},
        {"name": "React", "url": "https://react.dev/rss.xml"},
        {"name": "Next.js", "url": "https://nextjs.org/feed.xml"},
        {"name": "web.dev", "url": "https://web.dev/feed.xml"},
        {"name": "Josh Comeau", "url": "https://joshwcomeau.com/rss.xml"},
        {"name": "Overreacted", "url": "https://overreacted.io/rss.xml"},
    ],
    # ============================================================
    # AI / LLM / MACHINE LEARNING
    # ============================================================
    "ai": [
        {"name": "Simon Willison", "url": "https://simonwillison.net/atom/entries/"},
        {"name": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml"},
        {"name": "BAIR", "url": "https://bair.berkeley.edu/blog/feed.xml"},
        {"name": "Jack Clark", "url": "https://jack-clark.net/feed/"},
        {"name": "OpenAI", "url": "https://openai.com/news/rss.xml"},
        # anthropic.com has no public RSS; Lilian Weng is a strong applied-LLM alternate.
        {"name": "Lilian Weng", "url": "https://lilianweng.github.io/index.xml"},
        {"name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml"},
        {"name": "Google AI", "url": "https://blog.google/technology/ai/rss/"},
        {"name": "NVIDIA Developer", "url": "https://developer.nvidia.com/blog/feed/"},
        {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/"},
    ],
    # ============================================================
    # SOFTWARE ARCHITECTURE / SYSTEM DESIGN
    # ============================================================
    "architecture": [
        {"name": "Martin Fowler", "url": "https://martinfowler.com/feed.atom"},
        {"name": "Netflix TechBlog", "url": "https://netflixtechblog.com/feed"},
        {"name": "AWS Architecture Blog", "url": "https://aws.amazon.com/blogs/architecture/feed/"},
        {"name": "Cloudflare Blog", "url": "https://blog.cloudflare.com/rss/"},
        {"name": "InfoQ", "url": "https://feed.infoq.com/"},
        {"name": "ByteByteGo", "url": "https://blog.bytebytego.com/feed"},
        {"name": "Stack Overflow Blog", "url": "https://stackoverflow.blog/feed/"},
        {"name": "Meta Engineering", "url": "https://engineering.fb.com/feed/"},
        {"name": "Spotify Engineering", "url": "https://engineering.atspotify.com/feed/"},
        # shopify.engineering atom redirects to HTML; Airbnb eng is a working peer feed.
        {"name": "Airbnb Engineering", "url": "https://medium.com/feed/airbnb-engineering"},
    ],
    # ============================================================
    # CLOUD / DEVOPS / INFRASTRUCTURE
    # ============================================================
    "cloud_devops": [
        {"name": "AWS Architecture", "url": "https://aws.amazon.com/blogs/architecture/feed/"},
        # cloud.google.com/blog/rss serves HTML; the Atom/RSS feed lives here.
        {"name": "Google Cloud", "url": "https://cloudblog.withgoogle.com/rss/"},
        {"name": "Microsoft Azure", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
        {"name": "Kubernetes Blog", "url": "https://kubernetes.io/feed.xml"},
        {"name": "CNCF", "url": "https://www.cncf.io/feed/"},
        {"name": "Docker Blog", "url": "https://www.docker.com/feed/"},
        {"name": "Grafana Labs", "url": "https://grafana.com/blog/index.xml"},
        {"name": "Cloudflare", "url": "https://blog.cloudflare.com/rss/"},
    ],
    # ============================================================
    # DEVELOPER TOOLS / OPEN SOURCE
    # ============================================================
    "tools": [
        {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
        {"name": "GitHub Engineering", "url": "https://github.blog/category/engineering/feed/"},
        {"name": "JetBrains", "url": "https://blog.jetbrains.com/feed/"},
        {"name": "WebStorm", "url": "https://blog.jetbrains.com/webstorm/feed/"},
        {"name": "PyCharm", "url": "https://blog.jetbrains.com/pycharm/feed/"},
        {"name": "Chromium Blog", "url": "https://blog.chromium.org/feeds/posts/default"},
        {"name": "Console.dev", "url": "https://console.dev/rss.xml"},
    ],
    # ============================================================
    # SECURITY
    # ============================================================
    "security": [
        {"name": "Google Security Blog", "url": "https://security.googleblog.com/feeds/posts/default"},
        {"name": "GitHub Security", "url": "https://github.blog/category/security/feed/"},
        {"name": "Cloudflare Security", "url": "https://blog.cloudflare.com/tag/security/rss/"},
        {"name": "Mozilla Security", "url": "https://blog.mozilla.org/security/feed/"},
        {"name": "OWASP", "url": "https://owasp.org/feed.xml"},
    ],
    # ============================================================
    # BUSINESS / STARTUPS / PRODUCT IDEAS
    # ============================================================
    "business": [
        {"name": "Hacker News Show", "url": "https://hnrss.org/show"},
        {"name": "Hacker News Launch HN", "url": "https://hnrss.org/newest?q=Launch+HN"},
        {"name": "Hacker News Frontpage", "url": "https://hnrss.org/frontpage"},
        {"name": "SaaStr", "url": "https://www.saastr.com/feed/"},
        {"name": "Sive", "url": "https://sive.rs/en.atom"},
        {"name": "Product Hunt", "url": "https://www.producthunt.com/feed"},
    ],
    # ============================================================
    # WEB DESIGN / CMS / CLIENT WEBSITES
    # ============================================================
    "web_design": [
        {"name": "Webflow", "url": "https://webflow.com/blog/rss.xml"},
        {"name": "WP Tavern", "url": "https://wptavern.com/feed"},
        {"name": "CSS Author", "url": "https://cssauthor.com/feed/"},
    ],
    # ============================================================
    # DEV COMMUNITY / DISCOVERY
    # ============================================================
    "dev_community": [
        {"name": "DEV.to Architecture", "url": "https://dev.to/feed/tag/architecture"},
        {"name": "DEV.to Python", "url": "https://dev.to/feed/tag/python"},
        {"name": "DEV.to DevOps", "url": "https://dev.to/feed/tag/devops"},
    ],
    # ============================================================
    # INDEPENDENT ENGINEERS / TECHNICAL WRITERS
    # ============================================================
    "independent": [
        {"name": "Julia Evans", "url": "https://jvns.ca/atom.xml"},
        {"name": "Josh Comeau", "url": "https://joshwcomeau.com/rss.xml"},
        {"name": "Dan Abramov / Overreacted", "url": "https://overreacted.io/rss.xml"},
        {"name": "Dan Luu", "url": "https://danluu.com/atom.xml"},
        {"name": "Sophie Alpert", "url": "https://sophiebits.com/atom.xml"},
    ],
}


def flatten_feed_urls(catalog: dict[str, list[dict[str, str]]] | None = None) -> list[str]:
    """Unique feed URLs in catalog order (first occurrence wins)."""
    seen: set[str] = set()
    urls: list[str] = []
    for entries in (catalog or FEED_CATALOG).values():
        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


DEFAULT_FEEDS = flatten_feed_urls()

# Reject articles whose RSS pubDate is older than this (when parseable).
MAX_ARTICLE_AGE_DAYS = int(os.getenv("MAX_ARTICLE_AGE_DAYS", "21"))


def resolve_feed_sources(env_value: str | None = None) -> list[str]:
    """Return the feed URL list for this run."""
    raw = os.getenv("FEED_SOURCES", "") if env_value is None else env_value
    from_env = [f.strip() for f in (raw or "").split(",") if f.strip()]
    if from_env:
        return from_env
    return list(DEFAULT_FEEDS)
