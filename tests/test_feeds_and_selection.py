"""Feeds (#17), multi-topic ranking (#16), and slug hygiene (#1)."""

from datetime import datetime, timedelta, timezone

import feeds
import generate_digest as gd
import topic_focus as tf


def test_default_feeds_cover_every_allowed_topic_bucket():
    urls = "\n".join(feeds.DEFAULT_FEEDS)
    assert "simonwillison.net/atom/entries" in urls
    assert "react.dev/rss.xml" in urls
    assert "netflixtechblog.com" in urls
    assert "openai.com" in urls
    assert "anthropic.com" in urls
    assert "kubernetes.io/feed.xml" in urls
    assert "security.googleblog.com" in urls
    assert "hnrss.org/show" in urls
    assert "webflow.com" in urls
    assert "jetbrains.com" in urls
    assert "jvns.ca/atom.xml" in urls
    assert "techcrunch.com" not in urls
    assert "feedburner.com" not in urls
    assert "hackernoon.com" not in urls
    assert "dev.to/feed\n" not in urls + "\n"
    assert "dev.to/feed/tag/architecture" in urls
    # Cross-group duplicates collapse (Cloudflare / Josh Comeau / Overreacted / AWS).
    assert feeds.DEFAULT_FEEDS.count("https://blog.cloudflare.com/rss/") == 1
    assert feeds.DEFAULT_FEEDS.count("https://joshwcomeau.com/rss.xml") == 1
    assert set(feeds.FEED_CATALOG) >= {
        "frontend",
        "ai",
        "architecture",
        "cloud_devops",
        "tools",
        "security",
        "business",
        "web_design",
        "dev_community",
        "independent",
    }


def test_resolve_feed_sources_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("FEED_SOURCES", "https://a.example/feed, https://b.example/feed")
    assert feeds.resolve_feed_sources() == [
        "https://a.example/feed",
        "https://b.example/feed",
    ]
    assert feeds.resolve_feed_sources("") == list(feeds.DEFAULT_FEEDS)


def test_make_slug_strips_trailing_hyphen_and_caps_length():
    long = "from zero to chat my journey building a production grade llm agent stack"
    slug = gd.make_slug(long, max_len=40)
    assert len(slug) <= 40
    assert not slug.endswith("-")
    assert "--" not in slug
    assert gd.make_slug("", "Hello World!") == "hello-world"


def test_is_stale_article_age_gate():
    old = {
        "published": (datetime.now(timezone.utc) - timedelta(days=40)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
    }
    fresh = {
        "published": (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
    }
    assert gd.is_stale_article(old, max_age_days=21) is True
    assert gd.is_stale_article(fresh, max_age_days=21) is False
    assert gd.is_stale_article({"published": ""}) is False


def test_rank_articles_picks_best_topic_not_weekday_pin(monkeypatch):
    # Pin preferred weekday to biz_ideas; architecture article must still win.
    monkeypatch.setattr(tf, "preferred_strategy_key", lambda now=None: "biz_ideas")
    arch = {
        "title": "Scalable microservices architecture at Netflix scale",
        "content": (
            "system design distributed microservices patterns scalability "
            "architecture for high traffic. " * 40
        ),
        "published": "",
        "link": "https://example.test/arch",
    }
    weak = {
        "title": "Random gardening notes",
        "content": ("tomatoes and compost in the backyard. " * 40),
        "published": "",
        "link": "https://example.test/garden",
    }
    ranked = gd.rank_articles([weak, arch])
    assert ranked[0]["link"] == arch["link"]
    assert ranked[0]["_strategy_key"] == "architecture"


def test_main_intra_run_dedupes_duplicate_feed_urls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = "javascript css frontend layout patterns for modern apps. " * 40
    twin_a = {
        "title": "CSS Grid Patterns",
        "link": "https://example.test/grid",
        "published": "",
        "author": "A",
        "content": body,
    }
    twin_b = {
        "title": "CSS Grid Patterns (mirror)",
        "link": "https://example.test/grid?utm_source=feed",
        "published": "",
        "author": "A",
        "content": body,
    }
    other = {
        "title": "React Server Components deep dive",
        "link": "https://example.test/rsc",
        "published": "",
        "author": "B",
        "content": "react javascript typescript frontend next.js ui. " * 40,
    }
    monkeypatch.setattr(gd, "FEEDS", ["https://example.test/feed"])
    monkeypatch.setattr(
        gd, "fetch_articles_from_feed", lambda *_a, **_k: [twin_a, twin_b, other]
    )
    monkeypatch.setattr(gd, "load_processed_articles", lambda: {})
    monkeypatch.setattr(gd, "load_published_source_urls", lambda *_a, **_k: set())
    monkeypatch.setattr(gd, "is_near_duplicate", lambda *_a, **_k: False)
    monkeypatch.setattr(
        gd.selection_triage,
        "triage_shortlist",
        lambda shortlist, strategy, dry_run=False: {
            "winner_id": 1,
            "none_good_enough": False,
            "reason": "test",
            "rankings": [
                {"id": item["_triage_id"], "reject": False, "rewrite_worthiness": 0.9}
                for item in shortlist
            ],
            "triage_fallback": None,
        },
    )
    monkeypatch.setattr(
        gd,
        "generate_post",
        lambda article, strategy, dry_run=False: {
            "headline": article["title"],
            "subtitle": "s",
            "meta_description": "m",
            "tags": ["frontend"],
            "body_markdown": "## Key Takeaways\n\n- x\n",
        },
    )
    monkeypatch.setattr(
        gd,
        "verify_post",
        lambda article, generated, dry_run=False: {
            "verdict": "pass",
            "issues": [],
            "corrected_body_markdown": generated["body_markdown"],
        },
    )
    monkeypatch.setattr(gd, "maybe_generate_cover", lambda *a, **k: None)
    published = {}
    monkeypatch.setattr(
        gd,
        "save_to_mdx",
        lambda article, strategy, generated, verified, slug, cover: published.update(
            {"slug": slug, "link": article["link"], "topic": strategy.get("key")}
        ),
    )
    monkeypatch.setattr(gd, "save_processed_articles", lambda *_a, **_k: None)

    gd.main(dry_run=False)

    report = (tmp_path / "selection-report.md").read_text(encoding="utf-8")
    assert "after_dedupe: 2" in report  # twin collapsed; other kept
    assert published["slug"]
