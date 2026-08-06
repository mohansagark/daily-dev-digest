import topic_focus as tf


def test_listicle_denylist_top_n():
    assert tf.is_listicle_noise("Top 5 React libraries you need")
    assert tf.is_listicle_noise("Best 10 tools for developers")


def test_listicle_denylist_roundup():
    assert tf.is_listicle_noise("This week's roundup of links")


def test_allowlisted_article_kept():
    strategy = tf.STRATEGIES["ai"]
    articles = [
        {
            "title": "Building safer LLM agents with behavioral tests",
            "content": "How to evaluate agent prompts and trust boundaries.",
        }
    ]
    kept, skipped = tf.filter_allowlisted(articles, strategy)
    assert len(kept) == 1
    assert skipped == []


def test_off_strategy_skipped():
    strategy = tf.STRATEGIES["frontend"]
    articles = [
        {
            "title": "My gardening diary for July",
            "content": "Tomatoes and compost tips for the backyard.",
        }
    ]
    kept, skipped = tf.filter_allowlisted(articles, strategy)
    assert kept == []
    assert skipped[0][1] == "allowlist:no_keyword_hit"


def test_listicle_skipped_even_if_keywords_match():
    strategy = tf.STRATEGIES["tools"]
    articles = [
        {
            "title": "Top 7 developer tools you should try",
            "content": "cli and ide roundup for engineers.",
        }
    ]
    kept, skipped = tf.filter_allowlisted(articles, strategy)
    assert kept == []
    assert skipped[0][1] == "denylist:listicle"


def test_weekday_strategy_deterministic():
    from datetime import datetime

    # Monday -> ai
    s = tf.get_content_strategy(datetime(2026, 8, 3))  # Monday
    assert s["description"].startswith("AI systems")


def test_short_keywords_require_word_boundaries():
    # Regression: "cli" must not match "clip-path"; "ide" not "provide".
    assert tf.count_focus_hits("new clip-path value for shapes", ["cli"]) == 0
    assert tf.count_focus_hits("we provide a guide", ["ide"]) == 0
    assert tf.count_focus_hits("now available in browsers", ["ai"]) == 0
    assert tf.count_focus_hits("try the new CLI today", ["cli"]) == 1
    assert tf.count_focus_hits("shipping an IDE plugin", ["ide"]) == 1
    assert tf.count_focus_hits("LLM agents and AI safety", ["ai"]) == 1


def test_tools_strategy_rejects_css_clip_path_false_positive():
    strategy = tf.STRATEGIES["tools"]
    articles = [
        {
            "title": "Get Ready For the Powerful CSS border-shape Property!",
            "content": "border-shape is a new value for clip-path and offset-path.",
        }
    ]
    kept, skipped = tf.filter_allowlisted(articles, strategy)
    assert kept == []
    assert skipped[0][1] == "allowlist:no_keyword_hit"


def test_allowlist_scans_full_content_not_only_prefix():
    strategy = tf.STRATEGIES["ai"]
    pad = "lorem " * 800  # well past CONTENT_DENYLIST_CHARS
    articles = [
        {
            "title": "A long systems writeup",
            "content": pad + " Finally we evaluate the LLM agents carefully.",
        }
    ]
    kept, skipped = tf.filter_allowlisted(articles, strategy)
    assert len(kept) == 1
    assert skipped == []
