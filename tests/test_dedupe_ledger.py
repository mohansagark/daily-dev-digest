"""Historical dedupe: the ledger is derived from what actually shipped.

`processed_articles.json` alone was never persisted between CI runs (issue #18),
so every run started from a stale file and republished covered stories. The
authoritative record of what shipped is portfolio-blog: every post carries
`source_url` in its front-matter.
"""

import generate_digest as gd


def write_post(posts_dir, name, source_url, extra=""):
    posts_dir.mkdir(parents=True, exist_ok=True)
    (posts_dir / name).write_text(
        "---\n"
        "title: Some Post\n"
        f"source_url: {source_url}\n"
        f"{extra}"
        "---\n\nBody\n",
        encoding="utf-8",
    )


# --- URL normalisation -----------------------------------------------------

def test_normalize_source_url_ignores_case_fragment_and_trailing_slash():
    canonical = "https://dev.to/user/post-slug"
    assert gd.normalize_source_url("https://dev.to/user/post-slug/") == canonical
    assert gd.normalize_source_url("HTTPS://DEV.TO/user/post-slug") == canonical
    assert gd.normalize_source_url("https://dev.to/user/post-slug#comments") == canonical


def test_normalize_source_url_drops_tracking_params_but_keeps_real_ones():
    assert (
        gd.normalize_source_url("https://ex.test/a?utm_source=rss&utm_medium=feed")
        == "https://ex.test/a"
    )
    assert gd.normalize_source_url("https://ex.test/a?id=7") == "https://ex.test/a?id=7"
    # Bare ?source= can be a real content key on some sites — keep it.
    assert (
        gd.normalize_source_url("https://ex.test/a?source=canonical&ref=rss")
        == "https://ex.test/a?source=canonical"
    )


def test_normalize_source_url_tolerates_empty_input():
    assert gd.normalize_source_url("") == ""
    assert gd.normalize_source_url(None) == ""


# --- deriving the ledger from portfolio-blog -------------------------------

def test_load_published_source_urls_reads_front_matter(tmp_path):
    posts = tmp_path / "blog" / "posts"
    write_post(posts, "a.mdx", "https://dev.to/user/a")
    write_post(posts, "b.mdx", "https://ex.test/b/")
    urls = gd.load_published_source_urls(str(tmp_path / "blog"))
    assert urls == {"https://dev.to/user/a", "https://ex.test/b"}


def test_load_published_source_urls_ignores_non_mdx_and_missing_field(tmp_path):
    posts = tmp_path / "blog" / "posts"
    write_post(posts, "a.mdx", "https://dev.to/user/a")
    (posts / "notes.txt").write_text("source_url: https://ex.test/nope\n", encoding="utf-8")
    (posts / "c.mdx").write_text("---\ntitle: No source\n---\n\nBody\n", encoding="utf-8")
    assert gd.load_published_source_urls(str(tmp_path / "blog")) == {
        "https://dev.to/user/a"
    }


def test_load_published_source_urls_returns_empty_when_repo_absent(tmp_path):
    assert gd.load_published_source_urls(str(tmp_path / "nope")) == set()


def test_load_published_source_urls_only_reads_the_front_matter_block(tmp_path):
    """A source_url mentioned in the body must not count as published."""
    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    (posts / "a.mdx").write_text(
        "---\ntitle: T\nsource_url: https://ex.test/real\n---\n\n"
        "source_url: https://ex.test/body-mention\n",
        encoding="utf-8",
    )
    assert gd.load_published_source_urls(str(tmp_path / "blog")) == {
        "https://ex.test/real"
    }


def test_load_published_source_urls_handles_crlf_and_quoted_values(tmp_path):
    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    (posts / "crlf.mdx").write_bytes(
        b"---\r\ntitle: CRLF\r\nsource_url: https://ex.test/crlf/\r\n---\r\n\r\nBody\r\n"
    )
    (posts / "quoted.mdx").write_text(
        "---\n"
        "title: Quoted\n"
        'source_url: "https://ex.test/quoted?utm_source=rss"\n'
        "---\n\nBody\n",
        encoding="utf-8",
    )
    assert gd.load_published_source_urls(str(tmp_path / "blog")) == {
        "https://ex.test/crlf",
        "https://ex.test/quoted",
    }


# --- the ledger the pipeline actually consults ------------------------------

def test_known_source_urls_unions_blog_posts_and_json_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_post(tmp_path / "blog" / "posts", "a.mdx", "https://dev.to/user/a")
    ledger = {
        "hash1": {"title": "Old", "link": "https://ex.test/from-ledger?utm_source=rss"}
    }
    known = gd.known_source_urls(ledger, blog_dir="blog")
    assert known == {"https://dev.to/user/a", "https://ex.test/from-ledger"}


def test_known_source_urls_survives_a_wiped_json_ledger(tmp_path, monkeypatch):
    """The exact failure in #18: ledger reset to 1 entry, 249 posts published."""
    monkeypatch.chdir(tmp_path)
    posts = tmp_path / "blog" / "posts"
    for i in range(10):
        write_post(posts, f"p{i}.mdx", f"https://dev.to/user/p{i}")
    known = gd.known_source_urls({}, blog_dir="blog")
    assert len(known) == 10


# --- integration: a covered article is never republished --------------------

def _stub_pipeline(monkeypatch, articles, published):
    monkeypatch.setattr(gd, "FEEDS", ["https://example.test/feed"])
    monkeypatch.setattr(gd, "fetch_articles_from_feed", lambda *_a, **_k: list(articles))
    monkeypatch.setattr(gd, "load_processed_articles", lambda: {})
    monkeypatch.setattr(gd, "is_near_duplicate", lambda *_a, **_k: False)
    monkeypatch.setattr(
        gd.topic_focus,
        "filter_hard_rejects",
        lambda arts, _strategy=None, **_k: (list(arts), []),
    )
    monkeypatch.setattr(
        gd,
        "build_shortlist",
        lambda arts, _strategy, k=5: (
            [
                {
                    **a,
                    "_triage_id": i + 1,
                    "_theme_hits": 1,
                    "_title_hits": 1,
                    "_body_hits": 0,
                    "_matched_keywords": ["javascript"],
                    "_score_breakdown": {"total": 0.9},
                }
                for i, a in enumerate(arts)
            ],
            arts,
        ),
    )
    monkeypatch.setattr(
        gd.selection_triage,
        "triage_shortlist",
        lambda shortlist, strategy, dry_run=False: {
            "winner_id": shortlist[0]["_triage_id"],
            "none_good_enough": False,
            "reason": "test",
            "rankings": [
                {"id": s["_triage_id"], "reject": False, "rewrite_worthiness": 0.9}
                for s in shortlist
            ],
            "triage_fallback": None,
        },
    )
    monkeypatch.setattr(
        gd,
        "get_content_strategy",
        lambda *a, **k: {
            "key": "frontend",
            "focus": ["javascript", "css", "frontend"],
            "style": "energetic",
            "description": "Frontend",
        },
    )
    monkeypatch.setattr(
        gd,
        "generate_post",
        lambda article, strategy, dry_run=False: {
            "headline": article["title"],
            "subtitle": "Sub",
            "meta_description": "Meta.",
            "tags": ["css"],
            "body_markdown": "## Overview\n\nText.\n",
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
    monkeypatch.setattr(
        gd,
        "save_to_mdx",
        lambda article, strategy, generated, verified, slug, cover: published.update(
            {"slug": slug, "link": article["link"]}
        ),
    )
    monkeypatch.setattr(gd, "save_processed_articles", lambda *_a, **_k: None)


def test_main_skips_an_article_already_published_to_the_blog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    covered = {
        "title": "Already Covered",
        "link": "https://dev.to/user/covered",
        "published": "",
        "author": "A",
        "content": "javascript css frontend layout " * 200,
    }
    fresh = {
        "title": "Brand New",
        "link": "https://dev.to/user/fresh",
        "published": "",
        "author": "B",
        "content": "javascript css frontend layout " * 200,
    }
    # The blog already carries the first article — with a tracking param and a
    # trailing slash, so matching cannot be a naive string compare.
    write_post(
        tmp_path / "blog" / "posts",
        "covered.mdx",
        "https://dev.to/user/covered/?utm_source=rss",
    )

    published = {}
    _stub_pipeline(monkeypatch, [covered, fresh], published)
    gd.main(dry_run=False)

    assert published["link"] == "https://dev.to/user/fresh"


def test_main_exits_when_every_candidate_is_already_published(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    covered = {
        "title": "Already Covered",
        "link": "https://dev.to/user/covered",
        "published": "",
        "author": "A",
        "content": "javascript css frontend layout " * 200,
    }
    write_post(tmp_path / "blog" / "posts", "covered.mdx", "https://dev.to/user/covered")

    published = {}
    _stub_pipeline(monkeypatch, [covered], published)
    gd.main(dry_run=False)

    assert published == {}
    report = (tmp_path / gd.SELECTION_REPORT_PATH).read_text()
    assert "- after_dedupe: 0" in report
