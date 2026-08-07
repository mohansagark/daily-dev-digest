import topic_focus as tf


def test_listicle_denylist_top_n():
    assert tf.is_listicle_noise("Top 5 React libraries you need")
    assert tf.is_listicle_noise("Best 10 tools for developers")


def test_listicle_denylist_roundup():
    assert tf.is_listicle_noise("This week's roundup of links")


def test_hard_rejects_keeps_on_theme_article():
    strategy = tf.STRATEGIES["ai"]
    articles = [
        {
            "title": "Building safer LLM agents with behavioral tests",
            "content": "How to evaluate agent prompts and trust boundaries." + (" x" * 200),
        }
    ]
    kept, skipped = tf.filter_hard_rejects(articles, strategy)
    assert len(kept) == 1
    assert skipped == []


def test_off_strategy_kept_for_soft_theme_ranking():
    strategy = tf.STRATEGIES["frontend"]
    articles = [
        {
            "title": "My gardening diary for July",
            "content": ("Tomatoes and compost tips for the backyard. " * 30),
        }
    ]
    kept, skipped = tf.filter_hard_rejects(articles, strategy)
    assert len(kept) == 1
    assert skipped == []
    title_hits, body_hits, matched = tf.title_body_hits(
        articles[0]["title"], articles[0]["content"], strategy["focus"]
    )
    assert title_hits == 0 and body_hits == 0 and matched == []


def test_listicle_skipped_even_if_keywords_match():
    strategy = tf.STRATEGIES["tools"]
    articles = [
        {
            "title": "Top 7 developer tools you should try",
            "content": ("cli and ide roundup for engineers. " * 30),
        }
    ]
    kept, skipped = tf.filter_hard_rejects(articles, strategy)
    assert kept == []
    assert skipped[0][1] == "denylist:listicle"


def test_thin_body_hard_rejected():
    articles = [{"title": "Hi", "content": "short"}]
    kept, skipped = tf.filter_hard_rejects(articles, tf.STRATEGIES["ai"])
    assert kept == []
    assert skipped[0][1] == "hard:thin_body"


def test_weekday_strategy_deterministic():
    from datetime import datetime

    s = tf.get_content_strategy(datetime(2026, 8, 3))  # Monday
    assert s["key"] == "ai"
    assert s["description"].startswith("AI systems")


def test_short_keywords_require_word_boundaries():
    assert tf.count_focus_hits("new clip-path value for shapes", ["cli"]) == 0
    assert tf.count_focus_hits("we provide a guide", ["ide"]) == 0
    assert tf.count_focus_hits("now available in browsers", ["ai"]) == 0
    assert tf.count_focus_hits("try the new CLI today", ["cli"]) == 1
    assert tf.count_focus_hits("shipping an IDE plugin", ["ide"]) == 1
    assert tf.count_focus_hits("LLM agents and AI safety", ["ai"]) == 1


def test_tools_clip_path_not_hard_rejected_but_zero_theme_hits():
    strategy = tf.STRATEGIES["tools"]
    articles = [
        {
            "title": "Get Ready For the Powerful CSS border-shape Property!",
            "content": ("border-shape is a new value for clip-path and offset-path. " * 20),
        }
    ]
    kept, skipped = tf.filter_hard_rejects(articles, strategy)
    assert len(kept) == 1
    assert skipped == []
    assert tf.count_focus_hits(
        f"{articles[0]['title']} {articles[0]['content']}", strategy["focus"]
    ) == 0


def test_ai_news_pack_matches_ai_and_chatgpt_not_industry_alone():
    focus = tf.STRATEGIES["ai_news"]["focus"]
    assert "ai" in focus
    assert "chatgpt" in focus
    assert "industry" not in focus
    assert "ai news" not in focus
    assert tf.count_focus_hits("OpenAI ships ChatGPT updates", focus) >= 1
    title_hits, body_hits, _ = tf.title_body_hits(
        "Industry roundtable notes",
        "A long piece about the industry at large. " * 40,
        focus,
    )
    assert title_hits == 0 and body_hits == 0
    assert tf.theme_score(title_hits, body_hits) == 0.0


def test_title_weighting_in_theme_score():
    assert tf.theme_score(1, 0) == 0.5  # 2/4
    assert tf.theme_score(0, 1) == 0.25  # 1/4
    assert tf.theme_score(1, 0) > tf.theme_score(0, 1)


def test_filter_allowlisted_alias_matches_hard_rejects():
    articles = [
        {
            "title": "A long systems writeup",
            "content": ("lorem " * 800) + " Finally we evaluate the LLM agents carefully.",
        }
    ]
    a, sa = tf.filter_allowlisted(articles, tf.STRATEGIES["ai"])
    b, sb = tf.filter_hard_rejects(articles, tf.STRATEGIES["ai"])
    assert len(a) == len(b) == 1
    assert sa == sb == []
