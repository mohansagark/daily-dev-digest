# Cover Image Generation — Workstream A (daily-dev-digest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one relevant, house-styled cover image per daily post via Cloudflare Workers AI FLUX, attach it through MDX front-matter, and never let image failure block publishing.

**Architecture:** A new thin provider adapter `image_client.py` (mirroring `bedrock_client.py`) handles Cloudflare. The existing Bedrock rewrite call emits a structured `image_brief`; a pure `build_image_prompt()` assembles it with fixed house style + negatives; a best-effort `maybe_generate_cover()` orchestrates generate → save → front-matter. Text stays on Bedrock; only the image path is new.

**Tech Stack:** Python 3.11, `requests` (already a dep), Cloudflare Workers AI REST (`@cf/black-forest-labs/flux-1-schnell`), `pytest` (dev), GitHub Actions.

## Global Constraints

- **Two-provider isolation:** `image_client.py` MUST NOT import `bedrock_client`, `generate_digest`, or reference AWS. `generate_digest.py` references the image vendor ONLY via `image_client.generate(...)`. Vendor config lives ONLY in env.
- **No new runtime dependency.** `requests` covers HTTP; `base64`/`os` are stdlib. Do NOT add Pillow (WebP deferred). `pytest` is dev-only (`requirements-dev.txt`).
- **Best-effort image, always.** Image failure logs a warning and publishes text-only, UNLESS `IMAGE_REQUIRED=true`. Image concerns MUST NOT be added to the hard-required `GENERATE_KEYS` list (that would fail the text run).
- **Image is site-relative:** front-matter `image` = `/blog-images/{slug}.jpg`. The digest never hardcodes a host/CDN.
- **Dry-run makes no network calls.** `--dry-run` must skip Cloudflare exactly as it skips Bedrock.
- **Env var names (exact):** `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_IMAGE_MODEL` (default `@cf/black-forest-labs/flux-1-schnell`), `IMAGE_STEPS` (default `4`), `IMAGE_REQUIRED` (default `false`).
- **Image constants (exact):** file ext `jpg`; local output dir `digests/images/`; prompt hard-capped at 2048 chars.

---

## File Structure

- **Create** `image_client.py` — Cloudflare Workers AI adapter. Single responsibility: prompt → image bytes.
- **Create** `requirements-dev.txt` — `pytest`.
- **Create** `tests/test_image_client.py`, `tests/test_image_prompt.py`, `tests/test_generate_post_brief.py`, `tests/test_cover.py`, `tests/test_build_mdx.py`.
- **Modify** `generate_digest.py` — add `import image_client`; add `BRAND_STYLE`/`NEGATIVES` constants, `_slot()`, `build_image_prompt()`, `save_cover_image()`, `maybe_generate_cover()`; extend `generate_post` (brief in prompt + dry-run mock + soft normalize); update `build_mdx`/`save_to_mdx`; wire `main()`.
- **Modify** `.github/workflows/digest.yml` — CF secrets on generate step; copy `digests/images/*` into the blog repo; `git add images`.
- **Modify** `README.md` — document the image step + new env.

---

### Task 1: Test harness

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `pytest` invocation for all later tasks.

- [ ] **Step 1: Create dev requirements**

`requirements-dev.txt`:
```
pytest>=8,<9
```

- [ ] **Step 2: Create the tests package + a smoke test**

`tests/__init__.py`: (empty file)

`tests/test_smoke.py`:
```python
def test_smoke():
    assert True
```

- [ ] **Step 3: Run it**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/ -q`
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```bash
git add requirements-dev.txt tests/__init__.py tests/test_smoke.py
git commit -m "test: add pytest harness"
```

---

### Task 2: `image_client.py` — Cloudflare adapter

**Files:**
- Create: `image_client.py`
- Test: `tests/test_image_client.py`

**Interfaces:**
- Consumes: env `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_IMAGE_MODEL`, `IMAGE_STEPS`.
- Produces: `generate(prompt: str, *, steps: int | None = None) -> bytes` — raw JPEG bytes; raises `RuntimeError` on missing config / unsuccessful payload; propagates `requests` errors on transport/HTTP failure.

- [ ] **Step 1: Write the failing tests**

`tests/test_image_client.py`:
```python
import base64
import pytest
import requests
import image_client


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self._status = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        return self._payload


def _ok_payload(raw: bytes):
    return {"success": True, "result": {"image": base64.b64encode(raw).decode()}}


def test_generate_returns_decoded_bytes(monkeypatch):
    raw = b"\xff\xd8\xffFAKEJPEG"
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResp(200, _ok_payload(raw))

    monkeypatch.setattr(image_client.requests, "post", fake_post)
    assert image_client.generate("a robot reading") == raw
    assert "acct" in captured["url"]
    assert captured["json"]["steps"] == 4          # IMAGE_STEPS default
    assert captured["json"]["prompt"] == "a robot reading"


def test_generate_truncates_prompt_to_2048(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    seen = {}
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: seen.update(k["json"]) or _FakeResp(200, _ok_payload(b"x")))
    image_client.generate("z" * 5000)
    assert len(seen["prompt"]) == 2048


def test_generate_missing_env_raises(monkeypatch):
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        image_client.generate("x")


def test_generate_http_error_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post", lambda url, **k: _FakeResp(500, {}))
    with pytest.raises(requests.HTTPError):
        image_client.generate("x")


def test_generate_unsuccessful_payload_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: _FakeResp(200, {"success": False, "errors": ["nope"]}))
    with pytest.raises(RuntimeError):
        image_client.generate("x")


def test_generate_missing_image_field_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: _FakeResp(200, {"success": True, "result": {}}))
    with pytest.raises(RuntimeError):
        image_client.generate("x")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_image_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'image_client'`.

- [ ] **Step 3: Write `image_client.py`**

```python
"""
Thin wrapper around the Cloudflare Workers AI text-to-image REST API.

Mirrors bedrock_client.py: a single-purpose provider adapter. Config comes from
env, `requests` is the only dependency (already used by the pipeline), and errors
are raised so the caller owns dry-run and best-effort fallback decisions. This
module intentionally knows nothing about Bedrock or the orchestrator.
"""

import os
import base64

import requests

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
API_BASE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
DEFAULT_STEPS = 4
MAX_PROMPT_CHARS = 2048
REQUEST_TIMEOUT = 60


def _config():
    account_id = os.getenv("CF_ACCOUNT_ID")
    api_token = os.getenv("CF_API_TOKEN")
    if not account_id or not api_token:
        raise RuntimeError(
            "CF_ACCOUNT_ID and CF_API_TOKEN must be set for image generation"
        )
    model = os.getenv("CF_IMAGE_MODEL", DEFAULT_MODEL)
    return account_id, api_token, model


def generate(prompt, *, steps=None):
    """Text-to-image via Cloudflare Workers AI. Returns raw image bytes (JPEG).

    Raises RuntimeError on missing config or an unsuccessful response; propagates
    requests exceptions on transport/HTTP failure.
    """
    account_id, api_token, model = _config()
    if steps is None:
        steps = int(os.getenv("IMAGE_STEPS", DEFAULT_STEPS))

    url = API_BASE.format(account_id=account_id, model=model)
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        json={"prompt": prompt[:MAX_PROMPT_CHARS], "steps": steps},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare image generation failed: {data.get('errors')}")
    image_b64 = (data.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError("Cloudflare response missing result.image")
    return base64.b64decode(image_b64)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_image_client.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add image_client.py tests/test_image_client.py
git commit -m "feat: add Cloudflare Workers AI image adapter"
```

---

### Task 3: `build_image_prompt()` + house-style constants

**Files:**
- Modify: `generate_digest.py` (add near the LLM-export helpers, after imports)
- Test: `tests/test_image_prompt.py`

**Interfaces:**
- Consumes: nothing (pure function).
- Produces: `_slot(brief: dict, key: str) -> str`; `build_image_prompt(brief: dict, headline: str, tags: list) -> str`; module constants `BRAND_STYLE`, `NEGATIVES`.

- [ ] **Step 1: Write the failing tests**

`tests/test_image_prompt.py`:
```python
from generate_digest import build_image_prompt, _slot, BRAND_STYLE, NEGATIVES

FULL = {"subject": "a lighthouse over circuit-board waves",
        "composition": "centered hero, wide negative space",
        "mood": "calm, precise",
        "palette": "deep indigo, warm amber"}


def test_all_slots_present_and_ordered():
    p = build_image_prompt(FULL, "Some Headline", ["css"])
    assert p.startswith("a lighthouse over circuit-board waves.")
    assert "Composition: centered hero, wide negative space" in p
    assert "Mood: calm, precise" in p
    assert "Color palette: deep indigo, warm amber" in p
    assert BRAND_STYLE in p
    assert f"Avoid: {NEGATIVES}" in p
    # subject appears before style, style before avoid
    assert p.index("lighthouse") < p.index(BRAND_STYLE) < p.index("Avoid:")


def test_empty_slots_fall_back():
    p = build_image_prompt({}, "My Great Post", ["react"])
    assert "My Great Post" in p           # subject fallback uses headline
    assert BRAND_STYLE in p
    assert "Avoid:" in p


def test_non_string_slots_are_ignored():
    p = build_image_prompt({"subject": None, "mood": 123}, "H", [])
    assert "H" in p                       # falls back cleanly, no crash


def test_truncates_to_2048():
    brief = {"subject": "x" * 5000, "composition": "c", "mood": "m", "palette": "p"}
    assert len(build_image_prompt(brief, "H", [])) <= 2048


def test_slot_trims_and_guards():
    assert _slot({"a": "  hi  "}, "a") == "hi"
    assert _slot({"a": ""}, "a") == ""
    assert _slot({}, "a") == ""
    assert _slot({"a": 5}, "a") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_image_prompt.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_image_prompt'`.

- [ ] **Step 3: Add the code to `generate_digest.py`**

Add `import image_client` alongside `import bedrock_client` (line ~34). Then add this block (place it just above the "Markdown export" section, ~line 469):

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_image_prompt.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add generate_digest.py tests/test_image_prompt.py
git commit -m "feat: structured image-brief prompt assembly"
```

---

### Task 4: Emit `image_brief` from LLM #1 (soft, non-fatal)

**Files:**
- Modify: `generate_digest.py` — `GENERATE_USER_TEMPLATE` (JSON schema + instruction), `generate_post` dry-run mock + soft normalization.
- Test: `tests/test_generate_post_brief.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `generate_post(...)` output now always contains a dict key `image_brief` (possibly `{}`). `image_brief` is NOT added to `GENERATE_KEYS` (stays non-fatal).

- [ ] **Step 1: Write the failing tests**

`tests/test_generate_post_brief.py`:
```python
from generate_digest import generate_post, GENERATE_KEYS

STRATEGY = {"focus": ["css", "js"], "style": "energetic", "description": "Frontend"}
ARTICLE = {"title": "T", "link": "http://x", "content": "body " * 50, "author": "A"}


def test_dry_run_includes_image_brief_dict():
    out = generate_post(ARTICLE, STRATEGY, dry_run=True)
    assert isinstance(out["image_brief"], dict)
    assert out["image_brief"].get("subject")            # mock provides a subject


def test_image_brief_not_hard_required():
    # image_brief must stay OUT of the fail-loud required keys.
    assert "image_brief" not in GENERATE_KEYS
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_generate_post_brief.py -q`
Expected: FAIL — `KeyError: 'image_brief'` in the dry-run mock.

- [ ] **Step 3: Edit `generate_digest.py`**

(3a) In `GENERATE_USER_TEMPLATE`, extend the returned-JSON block and add an instruction. Change the JSON object to:

```python
Return ONLY this JSON object (no code fences, no commentary):
{{
  "headline": "string",
  "subtitle": "string",
  "meta_description": "string",
  "tags": ["string"],
  "image_brief": {{
    "subject": "one concrete visual metaphor for the cover — a clear focal object/scene a person could sketch. Never text, UI screenshots, or logos.",
    "composition": "how it is framed — focal point and negative space",
    "mood": "2-4 word emotional tone",
    "palette": "2-3 dominant colors that fit the topic"
  }},
  "body_markdown": "string"
}}
```

(3b) In the dry-run branch of `generate_post`, add `image_brief` to the returned mock dict:

```python
            "tags": strategy["focus"][:4],
            "image_brief": {
                "subject": f"a clean conceptual illustration about {article['title']}",
                "composition": "centered hero subject, generous negative space",
                "mood": "modern, precise",
                "palette": "muted modern tech palette",
            },
            "body_markdown": (
```

(3c) After the existing `GENERATE_KEYS` validation and the `tags` coercion in `generate_post`, soft-normalize the brief (do NOT add it to `GENERATE_KEYS`):

```python
    if not isinstance(data["tags"], list):
        data["tags"] = [str(data["tags"])]
    # image_brief is best-effort: normalize to a dict, never fail the text run.
    if not isinstance(data.get("image_brief"), dict):
        data["image_brief"] = {}
    return data
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_generate_post_brief.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add generate_digest.py tests/test_generate_post_brief.py
git commit -m "feat: LLM #1 emits a structured image_brief (best-effort)"
```

---

### Task 5: `save_cover_image()` + `maybe_generate_cover()` orchestration

**Files:**
- Modify: `generate_digest.py` — add image output constants + the two functions.
- Test: `tests/test_cover.py`

**Interfaces:**
- Consumes: `image_client.generate` (Task 2), `build_image_prompt` (Task 3), `generate_post` output with `image_brief` (Task 4).
- Produces:
  - `save_cover_image(image_bytes: bytes, slug: str) -> str` — writes `digests/images/{slug}.jpg`, returns `/blog-images/{slug}.jpg`.
  - `maybe_generate_cover(generated: dict, slug: str, dry_run: bool = False) -> dict | None` — returns `{"image", "alt", "prompt"}` on success, `None` on skip/failure; re-raises only if `IMAGE_REQUIRED=true`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cover.py`:
```python
import os
import generate_digest as gd

GEN = {"headline": "Great Post",
       "tags": ["css"],
       "image_brief": {"subject": "a glowing prism", "composition": "centered",
                       "mood": "calm", "palette": "indigo, amber"}}


def test_save_cover_image_writes_and_returns_rel(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    rel = gd.save_cover_image(b"JPEGDATA", "my-slug")
    assert rel == "/blog-images/my-slug.jpg"
    assert (tmp_path / "images" / "my-slug.jpg").read_bytes() == b"JPEGDATA"


def test_dry_run_returns_none(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(gd.image_client, "generate", lambda *a, **k: called.__setitem__("n", 1))
    assert gd.maybe_generate_cover(GEN, "slug", dry_run=True) is None
    assert called["n"] == 0                       # no network in dry-run


def test_success_returns_cover_dict(monkeypatch):
    monkeypatch.setattr(gd.image_client, "generate", lambda prompt, **k: b"IMG")
    monkeypatch.setattr(gd, "save_cover_image", lambda b, slug: f"/blog-images/{slug}.jpg")
    cover = gd.maybe_generate_cover(GEN, "slug")
    assert cover["image"] == "/blog-images/slug.jpg"
    assert cover["alt"] == "a glowing prism"      # subject slot
    assert "prism" in cover["prompt"] and "Avoid:" in cover["prompt"]


def test_failure_soft_returns_none(monkeypatch):
    monkeypatch.delenv("IMAGE_REQUIRED", raising=False)
    def boom(*a, **k):
        raise RuntimeError("cf down")
    monkeypatch.setattr(gd.image_client, "generate", boom)
    assert gd.maybe_generate_cover(GEN, "slug") is None


def test_failure_hard_when_required(monkeypatch):
    monkeypatch.setenv("IMAGE_REQUIRED", "true")
    def boom(*a, **k):
        raise RuntimeError("cf down")
    monkeypatch.setattr(gd.image_client, "generate", boom)
    import pytest
    with pytest.raises(RuntimeError):
        gd.maybe_generate_cover(GEN, "slug")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cover.py -q`
Expected: FAIL — `AttributeError: module 'generate_digest' has no attribute 'save_cover_image'`.

- [ ] **Step 3: Add the code to `generate_digest.py`**

Near the other module constants (after `OUTPUT_DIR = "digests"`, ~line 49) add:

```python
IMAGES_SUBDIR = os.path.join(OUTPUT_DIR, "images")
IMAGE_EXT = "jpg"
```

Then add these functions just below `build_image_prompt` (from Task 3):

```python
def save_cover_image(image_bytes, slug):
    """Write cover bytes to digests/images/{slug}.jpg; return its site-relative path."""
    os.makedirs(IMAGES_SUBDIR, exist_ok=True)
    filename = f"{slug}.{IMAGE_EXT}"
    with open(os.path.join(IMAGES_SUBDIR, filename), "wb") as f:
        f.write(image_bytes)
    return f"/blog-images/{filename}"


def maybe_generate_cover(generated, slug, dry_run=False):
    """Best-effort cover image. Returns {'image','alt','prompt'} or None.

    Never raises unless IMAGE_REQUIRED=true — a failed image must not block the
    post (mirrors the image-less fallback for legacy posts).
    """
    if dry_run:
        print("🧪 [dry-run] Skipping Cloudflare image generation.")
        return None

    brief = generated.get("image_brief") or {}
    prompt = build_image_prompt(brief, generated["headline"], generated.get("tags", []))
    try:
        image_bytes = image_client.generate(prompt)
        image_rel = save_cover_image(image_bytes, slug)
        print(f"🖼️  Cover image generated: {image_rel}")
        return {
            "image": image_rel,
            "alt": _slot(brief, "subject") or generated["headline"],
            "prompt": prompt,
        }
    except Exception as e:  # noqa: BLE001 — image is best-effort
        print(f"⚠️ Cover image generation failed ({e}); publishing text-only.")
        if os.getenv("IMAGE_REQUIRED", "false").lower() == "true":
            raise
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_cover.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add generate_digest.py tests/test_cover.py
git commit -m "feat: best-effort cover image generation + save"
```

---

### Task 6: Front-matter — replace `image_suggestion` with real image fields

**Files:**
- Modify: `generate_digest.py` — `build_mdx` (signature + front-matter), `save_to_mdx` (pass-through), `main()` wiring.
- Test: `tests/test_build_mdx.py`

**Interfaces:**
- Consumes: `maybe_generate_cover` output (Task 5).
- Produces: `build_mdx(article, strategy, generated, verified, slug, cover=None)` and `save_to_mdx(article, strategy, generated, verified, slug, cover=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_mdx.py`:
```python
from generate_digest import build_mdx

STRAT = {"style": "energetic", "description": "Frontend"}
GEN = {"headline": "H", "subtitle": "S", "meta_description": "M", "tags": ["css"]}
VER = {"corrected_body_markdown": "## Body\n\ntext"}
ART = {"link": "http://x", "published": "Fri, 01 Aug 2025 00:00:00 +0000"}


def test_with_cover_emits_image_fields():
    cover = {"image": "/blog-images/h.jpg", "alt": "a prism", "prompt": "a prism. Avoid: x."}
    mdx = build_mdx(ART, STRAT, GEN, VER, "h", cover=cover)
    assert "image: " in mdx and "/blog-images/h.jpg" in mdx
    assert "image_alt: " in mdx and "a prism" in mdx
    assert "image_prompt: " in mdx
    assert "image_suggestion:" not in mdx          # old field is gone


def test_without_cover_emits_no_image_fields():
    mdx = build_mdx(ART, STRAT, GEN, VER, "h", cover=None)
    assert "image:" not in mdx
    assert "image_alt:" not in mdx
    assert "image_suggestion:" not in mdx
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_build_mdx.py -q`
Expected: FAIL — old `build_mdx` has no `cover` param / still emits `image_suggestion`.

- [ ] **Step 3: Edit `generate_digest.py`**

(3a) Change `build_mdx` signature to accept `cover=None`. Remove the `image_suggestion:` line from the front-matter f-string and insert a conditional block. Replace the body of `build_mdx` front-matter assembly so it reads:

```python
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
```

(3b) Update `save_to_mdx` to accept and forward `cover`:

```python
def save_to_mdx(article, strategy, generated, verified, slug, cover=None):
    """Write the .mdx into OUTPUT_DIR (the workflow copies it to portfolio-blog)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{slug}.mdx")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(build_mdx(article, strategy, generated, verified, slug, cover))
    print(f"✅ Saved: {filepath}")
    return filepath
```

(3c) In `main()`, between the slug line and `save_to_mdx`, add the cover step and pass it through:

```python
    slug = slugify(generated["headline"])[:60] or slugify(best["title"])[:60]
    cover = maybe_generate_cover(generated, slug, dry_run=dry_run)
    save_to_mdx(best, strategy, generated, verified, slug, cover)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass (smoke + image_client 6 + image_prompt 5 + brief 2 + cover 5 + build_mdx 2).

- [ ] **Step 5: End-to-end dry-run smoke (no network)**

Run: `python generate_digest.py --dry-run`
Expected: completes, prints `🧪 [dry-run] Skipping Cloudflare image generation.`, writes a `digests/*.mdx` with NO `image:` front-matter and NO `image_suggestion:`.

- [ ] **Step 6: Commit**

```bash
git add generate_digest.py tests/test_build_mdx.py
git commit -m "feat: emit image front-matter; drop image_suggestion"
```

---

### Task 7: Workflow — Cloudflare secrets + ship images to the blog repo

**Files:**
- Modify: `.github/workflows/digest.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `digests/images/*.jpg` produced by Task 5/6.
- Produces: images committed into `portfolio-blog/images/` alongside the mdx.

- [ ] **Step 1: Add Cloudflare env to the generate step**

In `digest.yml`, under the `Generate Digest ...` step's `env:` block (which already has `FEED_SOURCES`, `AWS_REGION`, `BEDROCK_MODEL_ID`), add:

```yaml
          CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}
          CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}
          CF_IMAGE_MODEL: ${{ secrets.CF_IMAGE_MODEL || '@cf/black-forest-labs/flux-1-schnell' }}
          IMAGE_STEPS: ${{ secrets.IMAGE_STEPS || '4' }}
          IMAGE_REQUIRED: ${{ secrets.IMAGE_REQUIRED || 'false' }}
```

- [ ] **Step 2: Copy images into the cloned blog repo**

After the existing `Copy MDX files into portfolio-blog/posts` step, add:

```yaml
      - name: Copy cover images into portfolio-blog/images
        run: |
          mkdir -p blog/images/
          cp -v digests/images/* blog/images/ 2>/dev/null || echo "ℹ️ No cover images to copy"
```

- [ ] **Step 3: Stage images in the commit**

In the `Commit and Push to portfolio-blog` step, change the `git add` line from `git add posts/*.mdx` to:

```yaml
          git add posts/*.mdx images/ 2>/dev/null || git add posts/*.mdx
```

- [ ] **Step 4: Validate the workflow YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/digest.yml')); print('workflow YAML OK')"`
Expected: `workflow YAML OK`.

- [ ] **Step 5: Update README**

In `README.md`, under "Tech stack" add `Cloudflare Workers AI (FLUX schnell, cover images)`, and add a short "Cover images" subsection noting: one best-effort cover per post, env vars `CF_ACCOUNT_ID` / `CF_API_TOKEN` (+ optional `CF_IMAGE_MODEL`, `IMAGE_STEPS`, `IMAGE_REQUIRED`), and that a failed image publishes text-only.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/digest.yml README.md
git commit -m "ci: wire Cloudflare image secrets + ship cover images to blog repo"
```

---

## Manual verification (after Task 7, requires the Cloudflare key)

- [ ] With `CF_ACCOUNT_ID` / `CF_API_TOKEN` set locally in `.env`, run `python generate_digest.py` (a real run) and confirm `digests/images/<slug>.jpg` exists and the `.mdx` has `image: /blog-images/<slug>.jpg`.
- [ ] Open the jpg — confirm it's on-topic and matches the house style; no text/logos.
- [ ] Temporarily set a bad `CF_API_TOKEN` and re-run — confirm it prints the warning and still writes the `.mdx` with no `image:` field.

---

## Self-Review

- **Spec coverage:** §5 (two-provider isolation) → Task 2 + Global Constraints. §6.1 adapter → Task 2. §6.2/6.2a structured brief → Task 4. §6.3 assembly → Task 3. §6.4 orchestration + `IMAGE_REQUIRED` + dry-run → Task 5. §6.5 front-matter → Task 6. §6.6 workflow/secrets → Task 7. §6.7 no new runtime dep → Global Constraints. §11 tests → Tasks 2–6. Workstreams B/C are out of scope (separate plans).
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type consistency:** `generate()`, `build_image_prompt(brief, headline, tags)`, `_slot(brief, key)`, `save_cover_image(bytes, slug) -> "/blog-images/{slug}.jpg"`, `maybe_generate_cover(...) -> {"image","alt","prompt"} | None`, `build_mdx(..., cover=None)` used consistently across tasks.
- **Deviation from spec (intentional):** spec §6.2 said "add `image_brief` to `GENERATE_KEYS`"; the plan keeps it OUT of `GENERATE_KEYS` and soft-normalizes instead, because the Global Constraint "best-effort image, always" forbids letting an image concern fail the text run. Documented in Task 4.
