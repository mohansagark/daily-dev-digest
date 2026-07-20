"""
Daily Dev Digest — AI rewrite pipeline (Amazon Bedrock).

Flow (deterministic stages in Python, two LLM calls on Bedrock):

  scrape -> content-clean -> dedupe -> citation-extract      [deterministic]
    -> LLM #1 (structured generate) -> LLM #2 (fact-verify)  [LLM / Bedrock]
    -> markdown export (.mdx + front-matter)                 [deterministic]

Volume is capped at exactly ONE post per run: after cleaning + dedupe we rank
all candidates and keep only the single best one.

Run `python generate_digest.py --dry-run` to exercise the whole deterministic
path without any AWS calls (the two LLM stages are mocked). See README notes.
"""

import os
import re
import sys
import json
import time
import random
import difflib
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup
from slugify import slugify
from dotenv import load_dotenv

from yaml_utils import yaml_safe_value
import bedrock_client
import image_client

# `trafilatura` gives much cleaner article text (strips nav/ads/boilerplate).
# Imported defensively so the script still runs if it is not installed.
try:
    import trafilatura
except ImportError:  # pragma: no cover - optional dependency
    trafilatura = None

# Load environment variables
load_dotenv()
FEEDS = [f.strip() for f in os.getenv("FEED_SOURCES", "").split(",") if f.strip()]

MAX_PER_FEED = 5
MAX_TOTAL = 1  # exactly one post per day (single best candidate)
OUTPUT_DIR = "digests"
DUPLICATES_FILE = "processed_articles.json"
AUTHOR_NAME = os.getenv("BLOG_AUTHOR", "Mohan Sagar")

# Near-duplicate content guard: if a new article's cleaned text is >= this
# similarity ratio to a recently-processed article, treat it as a duplicate.
NEAR_DUP_THRESHOLD = 0.85
NEAR_DUP_SAMPLE_CHARS = 800  # how much cleaned text we fingerprint / compare


# ---------------------------------------------------------------------------
# Content strategy (one run/day -> pick a single strategy, rotated by weekday)
# ---------------------------------------------------------------------------
# The pipeline now runs once per day, so the old four time-of-day strategies
# collapse. We rotate the strategy by weekday to keep topical variety across the
# week while staying deterministic for any given day.
STRATEGIES = {
    "frontend": {
        "focus": ["javascript", "frontend", "react", "vue", "angular",
                  "typescript", "node.js", "css"],
        "style": "energetic and practical",
        "description": "Frontend and JavaScript engineering",
    },
    "backend": {
        "focus": ["backend", "databases", "api", "devops", "cloud",
                  "architecture", "performance", "security"],
        "style": "detailed and informative",
        "description": "Backend, cloud, and systems engineering",
    },
    "design_career": {
        "focus": ["ux", "ui", "design", "productivity", "tools",
                  "career", "soft-skills", "trends"],
        "style": "thoughtful and reflective",
        "description": "Design, tooling, and developer career growth",
    },
    "fundamentals": {
        "focus": ["tutorials", "learning", "fundamentals", "concepts",
                  "theory", "best-practices", "algorithms"],
        "style": "educational and foundational",
        "description": "Computer-science fundamentals and best practices",
    },
}

# Weekday (Mon=0 .. Sun=6) -> strategy key. Deterministic weekly rotation.
WEEKDAY_STRATEGY = {
    0: "frontend",
    1: "backend",
    2: "design_career",
    3: "fundamentals",
    4: "frontend",
    5: "backend",
    6: "design_career",
}


def get_content_strategy():
    """Pick the daily strategy based on the weekday (deterministic rotation)."""
    key = WEEKDAY_STRATEGY[datetime.now().weekday()]
    return STRATEGIES[key]


# ---------------------------------------------------------------------------
# Duplicate-detection store (URL-hash + near-duplicate content)
# ---------------------------------------------------------------------------
def load_processed_articles():
    """Load previously processed articles to prevent duplicates."""
    if os.path.exists(DUPLICATES_FILE):
        try:
            with open(DUPLICATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_processed_articles(processed_articles):
    """Persist processed articles to prevent future duplicates."""
    with open(DUPLICATES_FILE, "w", encoding="utf-8") as f:
        json.dump(processed_articles, f, indent=2, ensure_ascii=False)


def get_article_hash(article):
    """Generate a unique URL/title hash for exact duplicate detection."""
    content = f"{article['title']}{article['link']}{article['content'][:200]}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _normalize_for_similarity(text):
    """Lowercase + collapse whitespace so similarity compares words, not layout."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()[:NEAR_DUP_SAMPLE_CHARS]


def is_near_duplicate(article, processed_articles):
    """
    True if the article's cleaned text closely matches a recently-processed one.

    Uses difflib's ratio against the stored `content_sample` of prior posts.
    Cheap and dependency-free; good enough to catch the same story re-syndicated
    across feeds.
    """
    new_sample = _normalize_for_similarity(article["content"])
    if not new_sample:
        return False
    for entry in processed_articles.values():
        prior = entry.get("content_sample")
        if not prior:
            continue
        ratio = difflib.SequenceMatcher(None, new_sample, prior).ratio()
        if ratio >= NEAR_DUP_THRESHOLD:
            print(f"⚠️ Near-duplicate (ratio {ratio:.2f}) of: {entry.get('title', '')[:50]}")
            return True
    return False


# ---------------------------------------------------------------------------
# Scrape + content-clean
# ---------------------------------------------------------------------------
def clean_article_html(html, url):
    """
    content-clean stage: strip nav/ads/boilerplate to clean article text.

    Prefers trafilatura (readability-style main-content extraction); falls back
    to a BeautifulSoup heuristic if trafilatura is unavailable or returns nothing.
    """
    if trafilatura is not None:
        extracted = trafilatura.extract(
            html, include_comments=False, include_tables=False, favor_recall=True
        )
        if extracted and len(extracted.strip()) > 200:
            return extracted.strip()

    # Fallback: crude main-content heuristic.
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "aside", "header"]):
        element.decompose()
    for selector in ["article", ".post-content", ".entry-content", ".content",
                     "main", ".article-body", ".post-body"]:
        node = soup.select_one(selector)
        if node:
            return re.sub(r"\s+", " ", node.get_text()).strip()
    body = soup.find("body")
    return re.sub(r"\s+", " ", body.get_text()).strip() if body else ""


def fetch_clean_content(url):
    """Fetch a page and return cleaned article text (or empty string on error)."""
    try:
        print(f"📖 Fetching + cleaning: {url}")
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return clean_article_html(response.text, url)
    except Exception as e:  # noqa: BLE001 - network is best-effort
        print(f"⚠️ Error fetching {url}: {e}")
        return ""


def _extract_author(item):
    """citation-extract: pull an author name from RSS metadata if present."""
    for tag in ("dc:creator", "creator", "author"):
        node = item.find(tag)
        if node and node.text.strip():
            # <author> is sometimes "email (Name)" — keep it readable.
            return re.sub(r"\s+", " ", node.text).strip()
    return ""


def fetch_articles_from_feed(url):
    """Fetch + clean up to MAX_PER_FEED articles from a single RSS feed."""
    print(f"🔗 Fetching feed: {url}")
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        soup = BeautifulSoup(res.content, features="xml")
        items = soup.find_all("item")[:MAX_PER_FEED]
        articles = []
        for item in items:
            title = item.title.text if item.title else ""
            link = item.link.text if item.link else ""
            pub_date = item.pubDate.text if item.find("pubDate") else ""
            author = _extract_author(item)

            # Prefer full-page cleaned content; fall back to feed description.
            body = fetch_clean_content(link)
            if not body:
                desc = item.find("description") or item.find("content:encoded")
                body = re.sub(r"<.*?>", "", desc.text).strip() if desc else ""

            if not title or not body:
                continue
            articles.append({
                "title": title.strip(),
                "link": link.strip(),
                "published": pub_date.strip(),
                "author": author,
                "content": body,
            })
        return articles
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Error fetching feed {url}: {e}")
        return []


# ---------------------------------------------------------------------------
# Ranking: pick the single best candidate of the day
# ---------------------------------------------------------------------------
def _recency_score(published):
    """0..1 recency score from an RSS pubDate; 0.5 if unparseable."""
    if not published:
        return 0.5
    try:
        dt = parsedate_to_datetime(published)
        age_hours = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600.0
        # Full credit <6h old, decaying to ~0 by ~4 days.
        return max(0.0, min(1.0, 1.0 - (age_hours / 96.0)))
    except (TypeError, ValueError):
        return 0.5


def score_article(article, strategy):
    """
    Composite score = strategy-keyword match + recency + content length.

    Weighted so topical relevance dominates, recency breaks ties, and we avoid
    thin/stub articles.
    """
    text = f"{article['title']} {article['content']}".lower()

    keyword_hits = sum(1 for kw in strategy["focus"] if kw.lower() in text)
    keyword_score = min(1.0, keyword_hits / 3.0)  # 3+ hits saturates

    recency = _recency_score(article["published"])

    length = len(article["content"])
    # Reward substantial articles; saturate around 2500 chars.
    length_score = min(1.0, length / 2500.0)

    score = (0.55 * keyword_score) + (0.25 * recency) + (0.20 * length_score)
    article["_score_breakdown"] = {
        "keyword": round(keyword_score, 3),
        "recency": round(recency, 3),
        "length": round(length_score, 3),
        "total": round(score, 3),
    }
    return score


def select_best_article(articles, strategy):
    """Rank candidates and return the single highest-scoring article (or None)."""
    if not articles:
        return None
    ranked = sorted(articles, key=lambda a: score_article(a, strategy), reverse=True)
    best = ranked[0]
    print(f"🏆 Best candidate ({best['_score_breakdown']}): {best['title'][:60]}")
    return best


# ---------------------------------------------------------------------------
# LLM #1 — structured generate  (Bedrock converse)
# ---------------------------------------------------------------------------
GENERATE_SYSTEM_PROMPT = (
    "You are a senior software engineer who writes a well-regarded developer "
    "blog. You transform source material into ORIGINAL, technically-accurate "
    "posts in your own voice — you never copy sentences from the source. Your "
    "voice is clear, pragmatic, and lightly opinionated, aimed at working "
    "developers. You always attribute the original source. "
    "You respond with ONLY a single valid JSON object and no other text."
)

GENERATE_USER_TEMPLATE = """\
Rewrite the following source material into an original technical blog post.

Requirements:
- Genuinely rewrite and restructure — do NOT reproduce the source's wording.
- Keep it technically accurate; do not invent facts not in the source.
- Structure the body with a short intro, 3-5 `##` sections (each 2-3 focused
  paragraphs with concrete detail and a short example where useful), and a
  takeaways list.
- Tone/style: {style}. Audience: professional developers.
- Near the end, attribute the original with a Markdown link to the source URL.
- Target 700-1000 words in body_markdown (do not exceed 1100). Prefer depth over
  filler. Do NOT include an H1 title (front-matter owns it).
- tags: 3-6 short lowercase topic tags.
- meta_description: <= 160 chars, SEO-friendly.

Return ONLY this JSON object (no code fences, no commentary):
{{
  "headline": "string",
  "subtitle": "string",
  "meta_description": "string",
  "tags": ["string"],
  "body_markdown": "string"
}}

SOURCE_URL: {source_url}
SOURCE_AUTHOR: {source_author}
SOURCE_TITLE: {source_title}

SOURCE_TEXT:
\"\"\"
{source_text}
\"\"\"
"""

# Structured-output shape produced by LLM #1.
GENERATE_KEYS = ["headline", "subtitle", "meta_description", "tags", "body_markdown"]


def generate_post(article, strategy, dry_run=False):
    """LLM #1: produce a structured, rewritten post from the cleaned source."""
    source_text = article["content"][:8000]  # keep prompt bounded

    if dry_run:
        # Mock structured output so the deterministic path stays exercisable
        # without AWS. Clearly marked as a dry-run stub.
        print("🧪 [dry-run] Skipping Bedrock LLM #1; emitting mock structured output.")
        return {
            "headline": article["title"],
            "subtitle": f"[dry-run] {strategy['description']}",
            "meta_description": (
                f"[dry-run] A rewritten take on '{article['title']}'."[:160]
            ),
            "tags": strategy["focus"][:4],
            "body_markdown": (
                "> **Dry-run stub.** Bedrock was not called; this is placeholder "
                "body text so the export path can be exercised.\n\n"
                "## Overview\n\nThis is where the rewritten article would go.\n\n"
                "## Key Takeaways\n\n1. Placeholder takeaway.\n\n"
                f"*Original source: [{article['title']}]({article['link']})*\n"
            ),
        }

    prompt = GENERATE_USER_TEMPLATE.format(
        style=strategy["style"],
        source_url=article["link"],
        source_author=article.get("author") or "Unknown",
        source_title=article["title"],
        source_text=source_text,
    )
    raw = bedrock_client.converse(GENERATE_SYSTEM_PROMPT, prompt, max_tokens=5000,
                                  temperature=0.6)
    data = bedrock_client.extract_json(raw)

    # Validate the structured shape; fail loudly rather than push garbage.
    missing = [k for k in GENERATE_KEYS if k not in data]
    if missing:
        raise ValueError(f"LLM #1 output missing keys: {missing}")
    if not isinstance(data["tags"], list):
        data["tags"] = [str(data["tags"])]
    return data


# ---------------------------------------------------------------------------
# LLM #2 — fact-grounding verify  (Bedrock converse, fresh context)
# ---------------------------------------------------------------------------
VERIFY_SYSTEM_PROMPT = (
    "You are a meticulous technical fact-checker. You are given an ORIGINAL "
    "source text and a DRAFT blog post derived from it. Your job is to catch "
    "claims in the draft that the source does not support (hallucinations). "
    "You do not add new information. "
    "You respond with ONLY a single valid JSON object and no other text."
)

VERIFY_USER_TEMPLATE = """\
Check the DRAFT against the SOURCE. Identify any factual/technical claims in the
draft that are NOT supported by the source. Then return a corrected body that
removes or softens unsupported claims while preserving the source-grounded
content, structure, and the source attribution link.

Return ONLY this JSON object (no code fences, no commentary):
{{
  "verdict": "pass" | "revise",
  "issues": ["short description of each unsupported claim, or empty list"],
  "corrected_body_markdown": "the full body markdown, corrected if needed"
}}

SOURCE_TEXT:
\"\"\"
{source_text}
\"\"\"

DRAFT_BODY_MARKDOWN:
\"\"\"
{draft_body}
\"\"\"
"""


def verify_post(article, generated, dry_run=False):
    """
    LLM #2: fact-ground the draft against the original source.

    Bounded (single pass, no loops): if the checker flags issues it returns a
    corrected body which we adopt directly.
    """
    if dry_run:
        print("🧪 [dry-run] Skipping Bedrock LLM #2; treating draft as verified.")
        return {
            "verdict": "pass",
            "issues": [],
            "corrected_body_markdown": generated["body_markdown"],
        }

    prompt = VERIFY_USER_TEMPLATE.format(
        source_text=article["content"][:8000],
        draft_body=generated["body_markdown"],
    )
    raw = bedrock_client.converse(VERIFY_SYSTEM_PROMPT, prompt, max_tokens=5000,
                                  temperature=0.1)
    data = bedrock_client.extract_json(raw)

    corrected = data.get("corrected_body_markdown") or generated["body_markdown"]
    if data.get("verdict") == "revise":
        print(f"🔎 Fact-check flagged {len(data.get('issues', []))} issue(s); "
              f"using corrected body.")
    else:
        print("🔎 Fact-check passed.")
    data["corrected_body_markdown"] = corrected
    return data


# ---------------------------------------------------------------------------
# Cover image prompt (structured brief -> one ordered FLUX prompt)
# ---------------------------------------------------------------------------
# Constant half of the "series look": every cover shares this style + exclusions.
BRAND_STYLE = (
    "editorial tech illustration, flat vector style, soft geometric shapes, "
    "clean, high detail, subtle grain, professional blog cover"
)
NEGATIVES = (
    "no text, no words, no letters, no watermark, no logos, "
    "no UI screenshots, no photorealistic faces"
)
MAX_IMAGE_PROMPT_CHARS = 2048


def _slot(brief, key):
    """Return a trimmed string slot from the brief, or '' if missing/blank/non-str."""
    val = brief.get(key) if isinstance(brief, dict) else None
    return val.strip() if isinstance(val, str) and val.strip() else ""


def build_image_prompt(brief, headline, tags):
    """Assemble a structured image brief into one ordered FLUX prompt.

    Subject first (FLUX weights the front most), then framing, mood, color, then
    the fixed house style and exclusions. Every empty slot falls back to a
    headline/tags-derived default so we always produce a usable prompt.
    """
    subject = _slot(brief, "subject") or (
        f"a clean conceptual illustration about {headline}"
    )
    composition = _slot(brief, "composition") or (
        "centered hero subject, generous negative space"
    )
    mood = _slot(brief, "mood") or "modern, precise"
    palette = _slot(brief, "palette") or "muted modern tech palette"
    prompt = (
        f"{subject}. "
        f"Composition: {composition}. "
        f"Mood: {mood}. "
        f"Color palette: {palette}. "
        f"Style: {BRAND_STYLE}. "
        f"Avoid: {NEGATIVES}."
    )
    return prompt[:MAX_IMAGE_PROMPT_CHARS]


# ---------------------------------------------------------------------------
# Markdown export (.mdx + front-matter)
# ---------------------------------------------------------------------------
def build_mdx(article, strategy, generated, verified, slug):
    """Assemble the final .mdx (front-matter + verified body)."""
    now = datetime.now()
    tags = generated.get("tags", [])[:6]
    body = verified["corrected_body_markdown"].strip()

    frontmatter = f"""---
title: {yaml_safe_value(generated['headline'])}
subtitle: {yaml_safe_value(generated['subtitle'])}
summary: {yaml_safe_value(generated['meta_description'])}
slug: {yaml_safe_value(slug)}
date: {yaml_safe_value(now.strftime('%Y-%m-%d'))}
time: {yaml_safe_value(now.strftime('%H:%M'))}
content_strategy: {yaml_safe_value(strategy['description'])}
writing_style: {yaml_safe_value(strategy['style'])}
tags: {json.dumps(tags)}
image_suggestion: {yaml_safe_value(f"Professional illustration representing {generated['headline']}")}
source_url: {yaml_safe_value(article['link'])}
published_date: {yaml_safe_value(article['published'])}
author: {yaml_safe_value(AUTHOR_NAME)}
---
"""
    return f"{frontmatter}\n{body}\n"


def save_to_mdx(article, strategy, generated, verified, slug):
    """Write the .mdx into OUTPUT_DIR (the workflow copies it to portfolio-blog)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{slug}.mdx")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(build_mdx(article, strategy, generated, verified, slug))
    print(f"✅ Saved: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def main(dry_run=False):
    mode = " (DRY RUN — no Bedrock calls)" if dry_run else ""
    print(f"📥 Daily Dev Digest — AI rewrite pipeline{mode}")

    strategy = get_content_strategy()
    print(f"🎯 Strategy: {strategy['description']} | style: {strategy['style']}")
    print(f"🏷️  Focus: {', '.join(strategy['focus'])}")

    processed_articles = load_processed_articles()
    print(f"📚 Loaded {len(processed_articles)} previously processed articles")

    # --- scrape + content-clean -------------------------------------------
    all_articles = []
    for feed_url in FEEDS:
        all_articles.extend(fetch_articles_from_feed(feed_url))
    print(f"📄 Fetched {len(all_articles)} articles")
    if not all_articles:
        print("❌ No articles found. Exiting.")
        return

    # --- dedupe (URL-hash + near-duplicate content) ------------------------
    candidates = []
    for article in all_articles:
        article_hash = get_article_hash(article)
        if article_hash in processed_articles:
            print(f"⚠️ Skipping exact duplicate: {article['title'][:50]}")
            continue
        if is_near_duplicate(article, processed_articles):
            continue
        article["hash"] = article_hash
        candidates.append(article)
    print(f"🆕 {len(candidates)} candidate(s) after dedupe")
    if not candidates:
        print("❌ No new articles. Exiting.")
        return

    # --- rank -> single best candidate (MAX_TOTAL == 1) --------------------
    best = select_best_article(candidates, strategy)
    if best is None:
        print("❌ No suitable candidate. Exiting.")
        return

    # --- LLM #1 generate -> LLM #2 verify ----------------------------------
    print(f"📝 Generating post for: {best['title']}")
    generated = generate_post(best, strategy, dry_run=dry_run)
    verified = verify_post(best, generated, dry_run=dry_run)

    # --- export ------------------------------------------------------------
    slug = slugify(generated["headline"])[:60] or slugify(best["title"])[:60]
    save_to_mdx(best, strategy, generated, verified, slug)

    # --- record for dedupe (store a content fingerprint too) ---------------
    processed_articles[best["hash"]] = {
        "title": best["title"],
        "link": best["link"],
        "processed_date": datetime.now().isoformat(),
        "strategy_used": strategy["description"],
        "content_sample": _normalize_for_similarity(best["content"]),
    }
    save_processed_articles(processed_articles)

    print(f"🎉 Done. Generated 1 post ({slug}.mdx).")
    print(f"📝 Total processed articles: {len(processed_articles)}")
    if dry_run:
        print("🧪 Dry run complete — Bedrock was NOT called.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
