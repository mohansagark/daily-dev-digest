"""Topic allowlist + listicle denylist for digest candidate selection.

See docs/superpowers/specs/2026-08-06-editorial-cover-template-and-topic-focus-design.md §14.1.
"""

from __future__ import annotations

import re
from datetime import datetime

# §14.1 — each key has focus keywords, writing style, and content_strategy description.
STRATEGIES = {
    "ai": {
        "focus": [
            "ai", "llm", "agents", "machine learning", "generative", "prompt", "model",
        ],
        "style": "clear and rigorous",
        "description": "AI systems, agents, and applied ML for working engineers",
    },
    "frontend": {
        "focus": [
            "frontend", "javascript", "typescript", "react", "vue", "css",
            "next.js", "ui engineering",
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
            "ai news", "openai", "anthropic", "model release", "industry",
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

# Deterministic Mon=0..Sun=6 rotation across all seven keys (no fixed brand calendar
# required by the design — this map is an implementation choice).
WEEKDAY_STRATEGY = {
    0: "ai",
    1: "frontend",
    2: "architecture",
    3: "tools",
    4: "ai_news",
    5: "biz_ideas",
    6: "client_websites",
}

# Pre-LLM denylist on title + content prefix (spec §14 #6).
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


def get_content_strategy(now=None):
    """Pick the daily strategy from weekday (deterministic)."""
    now = now or datetime.now()
    key = WEEKDAY_STRATEGY[now.weekday()]
    return STRATEGIES[key]


def is_listicle_noise(title, content=""):
    """True if title/content matches hard-reject listicle patterns."""
    blob = f"{title or ''}\n{(content or '')[:CONTENT_DENYLIST_CHARS]}"
    return any(p.search(blob) for p in _LISTICLE_PATTERNS)


def count_focus_hits(text, focus):
    """Count strategy keywords as whole words/phrases (not substrings).

    Short tokens like ``cli``, ``ide``, ``ai`` otherwise match inside
    ``clip-path``, ``provide``, ``available``, etc.
    """
    blob = (text or "").lower()
    hits = 0
    for kw in focus or []:
        k = (kw or "").lower().strip()
        if not k:
            continue
        pattern = r"(?<!\w)" + re.escape(k).replace(r"\ ", r"\s+") + r"(?!\w)"
        if re.search(pattern, blob):
            hits += 1
    return hits


def filter_allowlisted(articles, strategy):
    """Drop denylisted noise; keep articles that score > 0 on strategy keywords.

    Returns (kept, skipped) where skipped is a list of (article, reason) tuples.
    """
    kept = []
    skipped = []
    focus = strategy.get("focus") or []
    for article in articles:
        title = article.get("title") or ""
        content = article.get("content") or ""
        if is_listicle_noise(title, content):
            skipped.append((article, "denylist:listicle"))
            print(f"⛔ Skip denylist (listicle): {title[:60]}")
            continue
        # Denylist may truncate (§14 #6); allowlist keyword gate uses full body
        # so late keyword mentions are not hard-rejected before scoring.
        hits = count_focus_hits(f"{title} {content}", focus)
        if hits < 1:
            skipped.append((article, "allowlist:no_keyword_hit"))
            print(f"⛔ Skip off-strategy: {title[:60]}")
            continue
        article = dict(article)
        article["_allowlist_hits"] = hits
        kept.append(article)
    return kept, skipped
