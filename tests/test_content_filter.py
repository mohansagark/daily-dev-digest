import bedrock_client as bc
import generate_digest as gd


def test_is_content_filter_block_detects_nova_refusal():
    assert bc.is_content_filter_block(
        " - The generated text has been blocked by our content filters."
    )
    assert not bc.is_content_filter_block('{"headline": "ok"}')


def test_extract_json_raises_content_filter_blocked():
    try:
        bc.extract_json(
            "The generated text has been blocked by our content filters."
        )
        assert False, "expected ContentFilterBlocked"
    except bc.ContentFilterBlocked as exc:
        assert "content filter" in str(exc).lower()


def test_generate_post_does_not_retry_content_filter(monkeypatch):
    calls = {"n": 0}

    def converse(*_a, **_k):
        calls["n"] += 1
        return "The generated text has been blocked by our content filters."

    monkeypatch.setattr(gd.bedrock_client, "converse", converse)
    article = {
        "title": "CSRF handbook",
        "link": "https://example.test/csrf",
        "content": "csrf " * 100,
        "author": "A",
    }
    strategy = {"focus": ["javascript"], "style": "practical", "description": "Frontend"}

    try:
        gd.generate_post(article, strategy, dry_run=False)
        assert False, "expected ContentFilterBlocked"
    except bc.ContentFilterBlocked:
        pass
    assert calls["n"] == 1


def test_main_skips_filtered_candidate_and_publishes_next(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    blocked = {
        "title": "CSRF Attacks Handbook",
        "link": "https://example.test/csrf",
        "published": "",
        "author": "A",
        "content": "javascript csrf attack browser " * 200,
    }
    ok = {
        "title": "CSS Grid Patterns",
        "link": "https://example.test/grid",
        "published": "",
        "author": "B",
        "content": "css javascript frontend layout " * 200,
    }

    monkeypatch.setattr(gd, "FEEDS", ["https://example.test/feed"])
    monkeypatch.setattr(gd, "fetch_articles_from_feed", lambda *_a, **_k: [blocked, ok])
    monkeypatch.setattr(gd, "load_processed_articles", lambda: {})
    monkeypatch.setattr(
        gd,
        "is_near_duplicate",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        gd.topic_focus,
        "filter_hard_rejects",
        lambda articles, _strategy=None, **_k: (list(articles), []),
    )
    monkeypatch.setattr(
        gd,
        "build_shortlist",
        lambda articles, _strategy, k=5: (
            [
                {
                    **articles[0],
                    "_triage_id": 1,
                    "_theme_hits": 1,
                    "_title_hits": 1,
                    "_body_hits": 0,
                    "_matched_keywords": ["javascript"],
                    "_score_breakdown": {"total": 0.9},
                },
                {
                    **articles[1],
                    "_triage_id": 2,
                    "_theme_hits": 1,
                    "_title_hits": 1,
                    "_body_hits": 0,
                    "_matched_keywords": ["css"],
                    "_score_breakdown": {"total": 0.8},
                },
            ],
            articles,
        ),
    )
    monkeypatch.setattr(
        gd.selection_triage,
        "triage_shortlist",
        lambda shortlist, strategy, dry_run=False: {
            "winner_id": 1,
            "none_good_enough": False,
            "reason": "test",
            "rankings": [
                {"id": 1, "reject": False, "rewrite_worthiness": 0.9},
                {"id": 2, "reject": False, "rewrite_worthiness": 0.8},
            ],
            "triage_fallback": None,
        },
    )
    monkeypatch.setattr(
        gd,
        "get_content_strategy",
        lambda: {
            "key": "frontend",
            "focus": ["javascript", "css", "frontend"],
            "style": "energetic",
            "description": "Frontend",
        },
    )

    def generate_post(article, strategy, dry_run=False):
        if "csrf" in article["link"]:
            raise bc.ContentFilterBlocked("blocked by our content filters")
        return {
            "headline": "CSS Grid Patterns",
            "subtitle": "Layouts that hold",
            "meta_description": "Practical CSS grid.",
            "tags": ["css", "frontend"],
            "body_markdown": "## Overview\n\nGrid is useful.\n",
        }

    saved = {}
    published = {"slug": None}

    monkeypatch.setattr(gd, "generate_post", generate_post)
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

    def save_to_mdx(article, strategy, generated, verified, slug, cover):
        published["slug"] = slug

    monkeypatch.setattr(gd, "save_to_mdx", save_to_mdx)
    monkeypatch.setattr(gd, "save_processed_articles", saved.update)

    gd.main(dry_run=False)

    assert published["slug"] == "css-grid-patterns"
    blocked_hash = gd.get_article_hash(blocked)
    ok_hash = gd.get_article_hash(ok)
    assert saved[blocked_hash]["skipped"] == "content_filter"
    assert ok_hash in saved
    assert "skipped" not in saved[ok_hash]


def test_main_writes_selection_report_even_on_unexpected_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    article = {
        "title": "CSS Grid Patterns",
        "link": "https://example.test/grid",
        "published": "",
        "author": "B",
        "content": "css javascript frontend layout " * 200,
    }
    monkeypatch.setattr(gd, "FEEDS", ["https://example.test/feed"])
    monkeypatch.setattr(gd, "fetch_articles_from_feed", lambda *_a, **_k: [article])
    monkeypatch.setattr(gd, "load_processed_articles", lambda: {})
    monkeypatch.setattr(gd, "is_near_duplicate", lambda *_a, **_k: False)
    monkeypatch.setattr(
        gd.topic_focus,
        "filter_hard_rejects",
        lambda articles, _strategy=None, **_k: (list(articles), []),
    )
    monkeypatch.setattr(
        gd,
        "build_shortlist",
        lambda articles, _strategy, k=5: (
            [
                {
                    **articles[0],
                    "_triage_id": 1,
                    "_theme_hits": 1,
                    "_title_hits": 1,
                    "_body_hits": 0,
                    "_matched_keywords": ["css"],
                    "_score_breakdown": {"total": 0.9},
                }
            ],
            articles,
        ),
    )
    monkeypatch.setattr(
        gd.selection_triage,
        "triage_shortlist",
        lambda *_a, **_k: {
            "winner_id": 1,
            "none_good_enough": False,
            "reason": "test",
            "rankings": [{"id": 1, "reject": False, "rewrite_worthiness": 0.9}],
            "triage_fallback": None,
        },
    )
    monkeypatch.setattr(
        gd,
        "get_content_strategy",
        lambda: {
            "key": "frontend",
            "focus": ["css"],
            "style": "energetic",
            "description": "Frontend",
        },
    )
    monkeypatch.setattr(
        gd,
        "generate_post",
        lambda *_a, **_k: {
            "headline": "CSS Grid Patterns",
            "subtitle": "Layouts",
            "meta_description": "Grid",
            "tags": ["css"],
            "body_markdown": "## Overview\n\nGrid.\n",
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
    monkeypatch.setattr(
        gd,
        "maybe_generate_cover",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cover boom")),
    )

    try:
        gd.main(dry_run=False)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "cover boom" in str(exc)

    report = (tmp_path / "selection-report.md").read_text(encoding="utf-8")
    assert "strategy_key" in report
    assert "CSS Grid Patterns" in report


def test_main_exits_cleanly_when_all_candidates_filtered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    only = {
        "title": "CSRF Attacks Handbook",
        "link": "https://example.test/csrf",
        "published": "",
        "author": "A",
        "content": "javascript csrf attack browser " * 200,
    }

    monkeypatch.setattr(gd, "FEEDS", ["https://example.test/feed"])
    monkeypatch.setattr(gd, "fetch_articles_from_feed", lambda *_a, **_k: [only])
    monkeypatch.setattr(gd, "load_processed_articles", lambda: {})
    monkeypatch.setattr(gd, "is_near_duplicate", lambda *_a, **_k: False)
    monkeypatch.setattr(
        gd.topic_focus,
        "filter_hard_rejects",
        lambda articles, _strategy=None, **_k: (list(articles), []),
    )
    monkeypatch.setattr(
        gd,
        "build_shortlist",
        lambda articles, _strategy, k=5: (
            [
                {
                    **articles[0],
                    "_triage_id": 1,
                    "_theme_hits": 1,
                    "_title_hits": 1,
                    "_body_hits": 0,
                    "_matched_keywords": ["javascript"],
                    "_score_breakdown": {"total": 0.9},
                }
            ],
            articles,
        ),
    )
    monkeypatch.setattr(
        gd.selection_triage,
        "triage_shortlist",
        lambda shortlist, strategy, dry_run=False: {
            "winner_id": 1,
            "none_good_enough": False,
            "reason": "test",
            "rankings": [{"id": 1, "reject": False, "rewrite_worthiness": 0.9}],
            "triage_fallback": None,
        },
    )
    monkeypatch.setattr(
        gd,
        "get_content_strategy",
        lambda: {
            "key": "frontend",
            "focus": ["javascript"],
            "style": "energetic",
            "description": "Frontend",
        },
    )
    monkeypatch.setattr(
        gd,
        "generate_post",
        lambda *_a, **_k: (_ for _ in ()).throw(
            bc.ContentFilterBlocked("blocked by our content filters")
        ),
    )
    saved = {}
    monkeypatch.setattr(gd, "save_processed_articles", saved.update)
    monkeypatch.setattr(
        gd,
        "save_to_mdx",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not publish")),
    )

    gd.main(dry_run=False)

    only_hash = gd.get_article_hash(only)
    assert saved[only_hash]["skipped"] == "content_filter"
