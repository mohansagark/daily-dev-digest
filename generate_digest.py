"""
Daily Dev Digest — AI rewrite pipeline (Amazon Bedrock).

Flow (deterministic stages in Python, LLM calls on Bedrock + FLUX photo):

  scrape -> content-clean -> dedupe -> hard filters          [deterministic]
    -> soft-theme rank -> top-K shortlist -> Bedrock triage  [hybrid select]
    -> LLM #1 generate -> LLM #2 verify                      [Bedrock]
    -> cover_hook -> FLUX photo -> Playwright compose        [cover]
    -> markdown export (.mdx + front-matter)                 [deterministic]

Volume is capped at exactly ONE post per run: hard filters + shortlist + triage
pick the rewrite target (theme is a soft boost, not a hard allowlist).

Run `python generate_digest.py --dry-run` to exercise the deterministic path
(Bedrock/FLUX mocked; cover still composed with a placeholder photo).
"""

import io
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
import topic_focus
import cover_hook
import cover_compose
import selection_triage

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
SHORTLIST_K = 5
SELECTION_REPORT_PATH = "selection-report.md"
OUTPUT_DIR = "digests"
IMAGES_SUBDIR = os.path.join(OUTPUT_DIR, "images")
IMAGE_EXT = "jpg"

# A bare "Mozilla/5.0" is a well-known bot signature: sitepoint.com and
# hackernoon.com both answered it with 403 while a full browser UA gets 200,
# so two feeds were silently contributing nothing. Verified 2026-07-20.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DUPLICATES_FILE = "processed_articles.json"
AUTHOR_NAME = os.getenv("BLOG_AUTHOR", "Mohan Sagar")

# Near-duplicate content guard: if a new article's cleaned text is >= this
# similarity ratio to a recently-processed article, treat it as a duplicate.
NEAR_DUP_THRESHOLD = 0.85
NEAR_DUP_SAMPLE_CHARS = 800  # how much cleaned text we fingerprint / compare


# ---------------------------------------------------------------------------
# Content strategy — allowlisted packs in topic_focus.py (§14.1).
get_content_strategy = topic_focus.get_content_strategy


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
        response = requests.get(url, timeout=15, headers=REQUEST_HEADERS)
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
        res = requests.get(url, timeout=10, headers=REQUEST_HEADERS)
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
    """Soft theme boost + recency + length (hybrid selection spec §4.3)."""
    focus = strategy.get("focus") or []
    title_hits, body_hits, matched = topic_focus.title_body_hits(
        article.get("title") or "",
        article.get("content") or "",
        focus,
    )
    t_score = topic_focus.theme_score(title_hits, body_hits)
    recency = _recency_score(article.get("published"))
    length = len(article.get("content") or "")
    length_score = min(1.0, length / 2500.0)
    thin_penalty = 0.15 if length < 800 else 0.0
    score = (0.45 * t_score) + (0.30 * recency) + (0.25 * length_score) - thin_penalty
    article["_title_hits"] = title_hits
    article["_body_hits"] = body_hits
    article["_theme_hits"] = len(matched)
    article["_matched_keywords"] = matched
    article["_score_breakdown"] = {
        "theme": round(t_score, 3),
        "recency": round(recency, 3),
        "length": round(length_score, 3),
        "thin_penalty": thin_penalty,
        "total": round(score, 3),
        "title_hits": title_hits,
        "body_hits": body_hits,
    }
    return score


def rank_articles(articles, strategy):
    """Return candidates sorted best-first (mutates each with ``_score_breakdown``)."""
    if not articles:
        return []
    return sorted(articles, key=lambda a: score_article(a, strategy), reverse=True)


def build_shortlist(articles, strategy, *, k: int = SHORTLIST_K):
    """Rank survivors and return (top-K shortlist with triage ids, full ranked)."""
    ranked = rank_articles(articles, strategy)
    shortlist = [dict(item) for item in ranked[:k]]
    for index, item in enumerate(shortlist, start=1):
        item["_triage_id"] = index
    return shortlist, ranked


def select_best_article(articles, strategy):
    """Rank candidates and return the single highest-scoring article (or None)."""
    ranked = rank_articles(articles, strategy)
    if not ranked:
        return None
    best = ranked[0]
    print(f"🏆 Best candidate ({best['_score_breakdown']}): {best['title'][:60]}")
    return best


def write_selection_report(path: str, report: dict) -> str:
    """Write selection-report.md for Actions artifact upload."""
    lines = [
        "# Digest selection report",
        "",
        f"- strategy_key: `{report.get('strategy_key', '')}`",
        f"- description: {report.get('strategy_description', '')}",
        f"- focus: {', '.join(report.get('focus') or [])}",
        f"- fetched: {report.get('fetched', 0)}",
        f"- after_dedupe: {report.get('after_dedupe', 0)}",
        f"- after_hard_filters: {report.get('after_hard_filters', 0)}",
        f"- shortlist_size: {report.get('shortlist_size', 0)}",
        f"- triage_fallback: {report.get('triage_fallback')}",
        f"- none_good_enough: {report.get('none_good_enough')}",
        f"- winner_id: {report.get('winner_id')}",
        f"- reason: {report.get('reason', '')}",
        f"- published_slug: {report.get('published_slug') or '(none)'}",
        "",
        "## Shortlist",
        "",
        "| id | score | title_hits | body_hits | matched | title |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report.get("shortlist") or []:
        bd = item.get("_score_breakdown") or {}
        title = str(item.get("title") or "").replace("|", "\\|")
        matched = ", ".join(item.get("_matched_keywords") or [])
        lines.append(
            f"| {item.get('_triage_id')} | {bd.get('total')} | "
            f"{item.get('_title_hits')} | {item.get('_body_hits')} | "
            f"{matched} | {title[:80]} |"
        )
    lines.extend(["", "## Triage rankings", ""])
    for row in report.get("rankings") or []:
        lines.append(f"- {row}")
    text = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"📋 Wrote {path}")
    return path


# ---------------------------------------------------------------------------
# LLM #1 — structured generate  (Bedrock converse)
# ---------------------------------------------------------------------------

# Single source of truth for the cover "subject" instruction — used by the daily
# GENERATE prompt AND the cover_backfill brief-only prompt, so the two can never
# drift. FLUX has no negative_prompt and renders any named label as garbled text,
# so the subject must describe shapes and relationships WITHOUT naming or
# labelling the parts (naming layers "Developer Interface"/"Delivery Layer" made
# FLUX try to spell them and produce garbage signage).
IMAGE_SUBJECT_INSTRUCTION = (
    "the STRUCTURE of the system or idea this post describes, as abstract "
    "geometry a person could sketch — nodes, layers, pipelines, flows, "
    "boundaries, groupings. Describe topology and relationships ONLY. Describe "
    "shapes and how they connect; NEVER assign a name, label, caption, or any "
    "word to a node, box or layer — the finished image must contain NO readable "
    "text of any kind. Do NOT name screens, dashboards, panels, sidebars, "
    "charts, windows or any interface region; that produces a UI mockup, not a "
    "diagram. Do NOT name products, languages or their mascots. Do NOT use a "
    "metaphor. Banned as lazy and generic: roads, paths, highways, bridges, "
    "mountains, sunrises, horizons, lightbulbs, puzzle pieces, handshakes, "
    "rockets, chess pieces, icebergs."
)

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
- JSON must be valid: escape every " inside string values as \\". Prefer
  single quotes inside body_markdown code/prose when possible.

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
    data = None
    last_err = None
    for attempt in range(2):
        raw = bedrock_client.converse(
            GENERATE_SYSTEM_PROMPT, prompt, max_tokens=5000, temperature=0.6
        )
        try:
            data = bedrock_client.extract_json(raw)
            break
        except bedrock_client.ContentFilterBlocked:
            # Same prompt will hit the same filter — do not burn a retry.
            raise
        except ValueError as e:
            last_err = e
            if attempt == 0:
                print("⚠️ LLM #1 JSON parse failed; retrying once.")
                continue
            raise
    if data is None:  # pragma: no cover - loop always sets data or raises
        raise last_err

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
    "isometric technical illustration, schematic diagram aesthetic, "
    "precise geometric forms, clean linework, layered depth, "
    "subtle grain, professional blog cover"
)
# flux-1-schnell takes ONLY prompt/steps/seed — there is no negative_prompt, so
# everything here lands in the POSITIVE prompt. Diffusion text encoders do not
# reliably parse negation, so "no text, no logos" injected those very concepts:
# the first schematic cover came back covered in garbled signage and a Python
# logo. State the desired surface treatment affirmatively instead.
SURFACE_RULE = (
    "all surfaces blank and unmarked, panels plain and untextured, "
    "purely geometric abstract forms, empty smooth faces"
)
MAX_IMAGE_PROMPT_CHARS = 2048


def _slot(brief, key):
    """Return a trimmed string slot from the brief, or '' if missing/blank/non-str."""
    val = brief.get(key) if isinstance(brief, dict) else None
    return val.strip() if isinstance(val, str) and val.strip() else ""


def _clause(text):
    """Terminate a brief slot with exactly one sentence-ending mark.

    The LLM usually returns slots as full sentences ending in '.', so appending
    our own separator produced "…platform.. Composition:". Strip any trailing
    period first; '?' and '!' carry meaning, so they stand as the terminator.
    """
    text = text.rstrip().rstrip(".").rstrip()
    if not text:
        return ""
    return text if text.endswith(("?", "!")) else f"{text}."


MAX_PROMPT_TAGS = 5


def _tag_clause(tags, limit=MAX_PROMPT_TAGS):
    """Render post tags as a domain anchor, or '' when there are none usable.

    Tags are the strongest topical signal the pipeline has. They were accepted
    here and silently discarded, which let covers drift toward generic stock
    imagery that fit any post equally badly.
    """
    if not isinstance(tags, (list, tuple)):
        return ""
    clean = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
    if not clean:
        return ""
    return f"Subject domain: {', '.join(clean[:limit])}."


def build_image_prompt(brief, headline, tags):
    """Assemble a structured image brief into one ordered FLUX prompt.

    Subject first (FLUX weights the front most), then the tag-derived domain
    anchor, then framing, mood, color, then the fixed house style and
    exclusions. Every empty slot falls back to a headline-derived default so we
    always produce a usable prompt.
    """
    subject = _slot(brief, "subject") or (
        f"abstract structural diagram of the system described by {headline}"
    )
    composition = _slot(brief, "composition") or (
        "centered hero subject, generous negative space"
    )
    mood = _slot(brief, "mood") or "modern, precise"
    palette = _slot(brief, "palette") or "muted modern tech palette"
    parts = [
        _clause(subject),
        _tag_clause(tags),
        f"Composition: {_clause(composition)}",
        f"Mood: {_clause(mood)}",
        f"Color palette: {_clause(palette)}",
        f"Style: {BRAND_STYLE}.",
        f"Surfaces: {SURFACE_RULE}.",
    ]
    prompt = " ".join(p for p in parts if p)
    return prompt[:MAX_IMAGE_PROMPT_CHARS]


def downscale_cover(image_bytes, max_px=None, quality=None):
    """Shrink/recompress a cover for web delivery. Best-effort.

    FLUX returns 1024x1024 at ~260KB, but the card renders it ~380px wide and
    the article ~800px. The site serves images unoptimized, so whatever we write
    here is exactly what every visitor downloads — and a backfill would multiply
    that by 238. Any decode/encode failure returns the original bytes: a heavy
    cover beats no cover.
    """
    # Editorial covers are 1200×630 OG; default max edge preserves that canvas.
    max_px = int(os.getenv("COVER_MAX_PX", max_px or 1200))
    quality = int(os.getenv("COVER_JPEG_QUALITY", quality or 82))
    try:
        from PIL import Image  # imported lazily so the text pipeline never needs it

        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        out = buf.getvalue()
    except Exception as e:  # noqa: BLE001 - never lose a cover to a resize bug
        print(f"⚠️ Cover downscale skipped ({e}); writing original bytes.")
        return image_bytes
    # Already-JPEG: keep original if recompress didn't shrink. PNG/other inputs
    # (editorial compositor) always take the single JPEG encode.
    already_jpeg = image_bytes[:3] == b"\xff\xd8\xff"
    if already_jpeg and len(out) >= len(image_bytes):
        return image_bytes
    print(f"🗜️  Cover {len(image_bytes) // 1024}KB → {len(out) // 1024}KB")
    return out


def save_cover_image(image_bytes, slug):
    """Write cover bytes to digests/images/{slug}.jpg; return its site-relative path."""
    os.makedirs(IMAGES_SUBDIR, exist_ok=True)
    filename = f"{slug}.{IMAGE_EXT}"
    with open(os.path.join(IMAGES_SUBDIR, filename), "wb") as f:
        f.write(downscale_cover(image_bytes))
    return f"/blog-images/{filename}"


def maybe_generate_cover(generated, verified, slug, dry_run=False):
    """Best-effort editorial cover. Returns {'image','alt','prompt'} or None.

    Flow: cover_hook (Bedrock) → FLUX photo (skipped in dry-run) → Playwright
    template compose (PNG) → single JPEG via save_cover_image. Never raises
    unless IMAGE_REQUIRED=true.
    """
    try:
        body = (verified or {}).get("corrected_body_markdown") or ""
        hook = cover_hook.generate_cover_hook(
            generated.get("headline") or "",
            generated.get("tags") or [],
            body,
            dry_run=dry_run,
        )
        flux_prompt = cover_hook.build_flux_photo_prompt(hook)

        if dry_run:
            print("🧪 [dry-run] Skipping Cloudflare FLUX; using placeholder photo.")
            photo_bytes = None
        else:
            photo_bytes = image_client.generate(flux_prompt)

        composed = cover_compose.compose_cover(hook, photo_bytes)
        image_rel = save_cover_image(composed, slug)
        print(f"🖼️  Cover image generated: {image_rel}")
        print("COVER_STATUS=ok")
        return {
            "image": image_rel,
            "alt": hook["headline"],
            "prompt": flux_prompt,
        }
    except Exception as e:  # noqa: BLE001 — image is best-effort
        print(f"⚠️ Cover image generation failed ({e}); publishing text-only.")
        print(f"COVER_STATUS=failed:{type(e).__name__}")
        if os.getenv("IMAGE_REQUIRED", "false").lower() == "true":
            raise
        return None


# ---------------------------------------------------------------------------
# Markdown export (.mdx + front-matter)
# ---------------------------------------------------------------------------
def build_mdx(article, strategy, generated, verified, slug, cover=None):
    """Assemble the final .mdx (front-matter + verified body)."""
    now = datetime.now()
    tags = generated.get("tags", [])[:6]
    body = verified["corrected_body_markdown"].strip()

    image_lines = ""
    if cover:
        image_lines = (
            f"image: {yaml_safe_value(cover['image'])}\n"
            f"image_alt: {yaml_safe_value(cover['alt'])}\n"
            f"image_prompt: {yaml_safe_value(cover['prompt'])}\n"
        )

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
{image_lines}source_url: {yaml_safe_value(article['link'])}
published_date: {yaml_safe_value(article['published'])}
author: {yaml_safe_value(AUTHOR_NAME)}
---
"""
    return f"{frontmatter}\n{body}\n"


def save_to_mdx(article, strategy, generated, verified, slug, cover=None):
    """Write the .mdx into OUTPUT_DIR (the workflow copies it to portfolio-blog)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{slug}.mdx")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(build_mdx(article, strategy, generated, verified, slug, cover))
    print(f"✅ Saved: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def main(dry_run=False):
    mode = " (DRY RUN — no Bedrock calls)" if dry_run else ""
    print(f"📥 Daily Dev Digest — AI rewrite pipeline{mode}")

    strategy = get_content_strategy()
    print(
        f"🎯 Strategy [{strategy.get('key')}]: {strategy['description']} | "
        f"style: {strategy['style']}"
    )
    print(f"🏷️  Focus (soft): {', '.join(strategy['focus'])}")

    processed_articles = load_processed_articles()
    print(f"📚 Loaded {len(processed_articles)} previously processed articles")

    report = {
        "strategy_key": strategy.get("key"),
        "strategy_description": strategy.get("description"),
        "focus": list(strategy.get("focus") or []),
        "fetched": 0,
        "after_dedupe": 0,
        "after_hard_filters": 0,
        "shortlist_size": 0,
        "shortlist": [],
        "rankings": [],
        "winner_id": None,
        "reason": "",
        "triage_fallback": None,
        "none_good_enough": False,
        "published_slug": None,
    }

    def _persist_report():
        write_selection_report(SELECTION_REPORT_PATH, report)

    # --- scrape + content-clean -------------------------------------------
    all_articles = []
    for feed_url in FEEDS:
        all_articles.extend(fetch_articles_from_feed(feed_url))
    report["fetched"] = len(all_articles)
    print(f"📄 Fetched {len(all_articles)} articles")
    if not all_articles:
        print("❌ No articles found. Exiting.")
        _persist_report()
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
    report["after_dedupe"] = len(candidates)
    print(f"🆕 {len(candidates)} candidate(s) after dedupe")
    if not candidates:
        print("❌ No new articles. Exiting.")
        _persist_report()
        return

    # --- hard rejects only (listicle + thin); theme is soft ------------------
    candidates, _skipped = topic_focus.filter_hard_rejects(candidates, strategy)
    report["after_hard_filters"] = len(candidates)
    print(f"🎯 {len(candidates)} candidate(s) after hard filters")
    if not candidates:
        print("❌ No candidates after hard filters. Exiting.")
        _persist_report()
        return

    shortlist, _ranked = build_shortlist(candidates, strategy, k=SHORTLIST_K)
    report["shortlist_size"] = len(shortlist)
    report["shortlist"] = shortlist
    if not shortlist:
        print("❌ Empty shortlist. Exiting.")
        _persist_report()
        return

    print(f"📋 Shortlist top {len(shortlist)}:")
    for item in shortlist:
        bd = item.get("_score_breakdown") or {}
        print(
            f"  #{item['_triage_id']} score={bd.get('total')} "
            f"theme_hits={item.get('_theme_hits')} | {item['title'][:60]}"
        )

    # --- batch triage (1 Bedrock call) --------------------------------------
    triage = selection_triage.triage_shortlist(shortlist, strategy, dry_run=dry_run)
    report["rankings"] = triage.get("rankings") or []
    report["reason"] = triage.get("reason") or ""
    report["triage_fallback"] = triage.get("triage_fallback")
    report["none_good_enough"] = bool(triage.get("none_good_enough"))
    report["winner_id"] = triage.get("winner_id")

    if triage.get("none_good_enough"):
        print("⚠️ Triage: none_good_enough — no post today.")
        if not dry_run:
            by_id = {item["_triage_id"]: item for item in shortlist}
            for rid in selection_triage.triage_rejects_to_mark(triage):
                art = by_id.get(rid)
                if not art:
                    continue
                processed_articles[art["hash"]] = {
                    "title": art["title"],
                    "link": art["link"],
                    "processed_date": datetime.now().isoformat(),
                    "strategy_used": strategy["description"],
                    "content_sample": _normalize_for_similarity(art["content"]),
                    "skipped": "triage_reject",
                }
            save_processed_articles(processed_articles)
        _persist_report()
        return

    winner_id = triage.get("winner_id")
    try:
        winner_id = int(winner_id) if winner_id is not None else None
    except (TypeError, ValueError):
        winner_id = shortlist[0]["_triage_id"]

    attempt_ids = selection_triage.ordered_attempt_ids(
        shortlist, triage, winner_id=winner_id
    )
    by_id = {item["_triage_id"]: item for item in shortlist}

    published = False
    for triage_id in attempt_ids:
        best = by_id[triage_id]
        breakdown = best.get("_score_breakdown") or {}
        print(
            f"🏆 Trying id={triage_id} ({breakdown}): {best['title'][:60]}"
        )
        print(f"📝 Generating post for: {best['title']}")
        try:
            generated = generate_post(best, strategy, dry_run=dry_run)
            verified = verify_post(best, generated, dry_run=dry_run)
        except bedrock_client.ContentFilterBlocked as exc:
            print(f"⛔ Bedrock content filter blocked this source: {exc}")
            if dry_run:
                print("🧪 [dry-run] Would mark article skipped (content_filter).")
            else:
                processed_articles[best["hash"]] = {
                    "title": best["title"],
                    "link": best["link"],
                    "processed_date": datetime.now().isoformat(),
                    "strategy_used": strategy["description"],
                    "content_sample": _normalize_for_similarity(best["content"]),
                    "skipped": "content_filter",
                }
                save_processed_articles(processed_articles)
            continue

        slug = slugify(generated["headline"])[:60] or slugify(best["title"])[:60]
        cover = maybe_generate_cover(generated, verified, slug, dry_run=dry_run)
        save_to_mdx(best, strategy, generated, verified, slug, cover)

        if dry_run:
            print("🧪 [dry-run] Skipping processed_articles.json update.")
        else:
            processed_articles[best["hash"]] = {
                "title": best["title"],
                "link": best["link"],
                "processed_date": datetime.now().isoformat(),
                "strategy_used": strategy["description"],
                "content_sample": _normalize_for_similarity(best["content"]),
            }
            save_processed_articles(processed_articles)

        report["published_slug"] = slug
        print(f"🎉 Done. Generated 1 post ({slug}.mdx).")
        print(f"📝 Total processed articles: {len(processed_articles)}")
        published = True
        break

    if not published:
        print(
            "⚠️ All eligible shortlist candidates were blocked or unusable. "
            "No post today — exiting cleanly."
        )

    _persist_report()
    if dry_run:
        print("🧪 Dry run complete — Bedrock was NOT called.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
