"""Topic packs, hard rejects, and theme scoring for digest candidate selection.

See docs/superpowers/specs/2026-08-07-hybrid-candidate-selection-design.md.
"""

from __future__ import annotations

import re
from datetime import datetime

# Weekday packs — keywords boost ranking (soft); they do not hard-drop candidates.
STRATEGIES = {
    "ai": {
        "focus": [
            "ai", "llm", "agents", "machine learning", "generative", "prompt", "model",
            "rag", "fine-tuning",
        ],
        "style": "clear and rigorous",
        "description": "AI systems, agents, and applied ML for working engineers",
    },
    "frontend": {
        "focus": [
            "frontend", "javascript", "typescript", "react", "vue", "css",
            "next.js", "ui engineering", "html", "dom", "browser",
        ],
        "style": "energetic and practical",
        "description": "Frontend and JavaScript engineering",
    },
    "architecture": {
        "focus": [
            "architecture", "system design", "distributed", "microservices",
            "patterns", "scalability",
        ],
        "style": "detailed and informative",
        "description": "Software architecture and system design",
    },
    "tools": {
        "focus": [
            "developer tools", "cli", "ide", "devops tools", "new release", "tooling",
        ],
        "style": "practical and evaluative",
        "description": "New and notable software tools for developers",
    },
    "ai_news": {
        "focus": [
            "ai", "llm", "chatgpt", "claude", "gemini", "model release",
            "openai", "anthropic",
        ],
        "style": "timely and analytical",
        "description": "AI industry news and model releases",
    },
    "biz_ideas": {
        "focus": [
            "indie hacker", "saas", "solopreneur", "consulting",
            "product idea", "monetization",
        ],
        "style": "pragmatic and opinionated",
        "description": "Business ideas and monetization for software engineers",
    },
    "client_websites": {
        "focus": [
            "freelance", "client site", "agency", "portfolio site",
            "web design for clients",
        ],
        "style": "practical and client-aware",
        "description": "Building websites and web presence for clients",
    },
}

WEEKDAY_STRATEGY = {
    0: "ai",
    1: "frontend",
    2: "architecture",
    3: "tools",
    4: "ai_news",
    5: "biz_ideas",
    6: "client_websites",
}

_LISTICLE_PATTERNS = [
    re.compile(r"\btop\s+\d+\b", re.I),
    re.compile(r"\bbest\s+\d+\b", re.I),
    re.compile(
        r"\b\d+\s+(tips|tools|libraries|resources|ways|things)\b.*\b(you|for|to)\b",
        re.I,
    ),
    re.compile(r"\b(weekly\s+)?roundup\b", re.I),
    re.compile(r"\bweekly\s+links\b", re.I),
]

CONTENT_DENYLIST_CHARS = 2000
MIN_BODY_CHARS = 400


def allowed_strategy_keys() -> list[str]:
    """Every topic eligible for selection on any day (#16)."""
    return list(STRATEGIES.keys())


def preferred_strategy_key(now=None) -> str:
    """Soft weekday preference — used only as a tiny ranking bias, not a gate."""
    now = now or datetime.now()
    return WEEKDAY_STRATEGY[now.weekday()]


def get_content_strategy(now=None, key=None):
    """Resolve a strategy pack.

    - ``key`` set → that pack (winning topic after multi-topic scoring).
    - otherwise → weekday pack as a soft default for callers that still want
      a single strategy (tests, repair scripts). Selection itself scores all
      topics via ``score_against_all_topics``.
    """
    now = now or datetime.now()
    resolved = key or WEEKDAY_STRATEGY[now.weekday()]
    if resolved not in STRATEGIES:
        raise KeyError(f"Unknown strategy key: {resolved}")
    strategy = dict(STRATEGIES[resolved])
    strategy["key"] = resolved
    return strategy


def is_listicle_noise(title, content=""):
    """True if title/content matches hard-reject listicle patterns."""
    blob = f"{title or ''}\n{(content or '')[:CONTENT_DENYLIST_CHARS]}"
    return any(p.search(blob) for p in _LISTICLE_PATTERNS)


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    k = (keyword or "").lower().strip()
    return re.compile(
        r"(?<!\w)" + re.escape(k).replace(r"\ ", r"\s+") + r"(?!\w)",
        re.I,
    )


def matched_keywords(text, focus) -> list[str]:
    """Return distinct focus keywords that appear as whole words/phrases in text."""
    blob = text or ""
    found = []
    for kw in focus or []:
        k = (kw or "").strip()
        if not k:
            continue
        if _keyword_pattern(k).search(blob):
            found.append(k.lower())
    return found


def count_focus_hits(text, focus):
    """Count strategy keywords as whole words/phrases (not substrings)."""
    return len(matched_keywords(text, focus))


def title_body_hits(title, content, focus) -> tuple[int, int, list[str]]:
    """Distinct keyword hits in full title and full body (no truncation)."""
    title_matched = matched_keywords(title or "", focus)
    body_matched = matched_keywords(content or "", focus)
    combined = sorted(set(title_matched) | set(body_matched))
    return len(title_matched), len(body_matched), combined


def theme_score(title_hits: int, body_hits: int) -> float:
    """Soft theme score from title-weighted distinct keyword hits.

    A lone incidental body hit (e.g. the word "saas" inside a security post)
    must not outrank a real on-title match — require a title hit or ≥2 body
    hits before awarding any theme credit (#16).
    """
    if title_hits <= 0 and body_hits < 2:
        return 0.0
    return min(1.0, (3 * title_hits + body_hits) / 6.0)


def best_topic_for_article(title: str, content: str, *, preferred_key: str | None = None):
    """Return (strategy_key, title_hits, body_hits, matched, theme) for best fit.

    Scores every allowed topic; a tiny bonus keeps the weekday preference as a
    tie-breaker only when theme strength is otherwise equal.
    """
    preferred_key = preferred_key or preferred_strategy_key()
    best = ("frontend", 0, 0, [], 0.0)
    best_rank = -1.0
    for key in allowed_strategy_keys():
        focus = STRATEGIES[key]["focus"]
        title_hits, body_hits, matched = title_body_hits(title, content, focus)
        theme = theme_score(title_hits, body_hits)
        rank = theme + (0.03 if key == preferred_key else 0.0)
        if rank > best_rank:
            best_rank = rank
            best = (key, title_hits, body_hits, matched, theme)
    return best


def filter_hard_rejects(articles, strategy=None, *, min_body_chars: int = MIN_BODY_CHARS):
    """Drop listicle noise and thin bodies only — theme keywords do not hard-drop.

    Returns (kept, skipped) where skipped is a list of (article, reason) tuples.
    """
    del strategy  # soft theme only; kept for call-site compatibility
    kept = []
    skipped = []
    for article in articles:
        title = article.get("title") or ""
        content = article.get("content") or ""
        if is_listicle_noise(title, content):
            skipped.append((article, "denylist:listicle"))
            print(f"⛔ Skip denylist (listicle): {title[:60]}")
            continue
        if len(content) < min_body_chars:
            skipped.append((article, "hard:thin_body"))
            print(f"⛔ Skip thin body ({len(content)} chars): {title[:60]}")
            continue
        kept.append(dict(article))
    return kept, skipped


def filter_allowlisted(articles, strategy):
    """Backward-compatible alias for ``filter_hard_rejects`` (keyword gate removed)."""
    return filter_hard_rejects(articles, strategy)
