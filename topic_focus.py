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


def get_content_strategy(now=None):
    """Pick the daily strategy from weekday (deterministic). Includes ``key``."""
    now = now or datetime.now()
    key = WEEKDAY_STRATEGY[now.weekday()]
    strategy = dict(STRATEGIES[key])
    strategy["key"] = key
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
    """Soft theme score from title-weighted distinct keyword hits."""
    return min(1.0, (2 * title_hits + body_hits) / 4.0)


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
