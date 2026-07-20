# Design: Auto-generated cover images for the Daily Dev Digest

- **Date:** 2026-07-20
- **Status:** Draft — awaiting review
- **Author:** Mohan Sagar (with Claude)
- **Primary repo:** `daily-dev-digest` · **Also touches:** `portfolio-blog`, `next-gen-portfolio`

## 1. Goal

Every daily post currently ships as plain text. Attach **exactly one relevant
cover image** to each new post, generated from the post's own content, so the
blog on devmohan.in looks finished instead of bare.

The image must:

- be **topically relevant** (derived from the rewritten post, not a stock keyword),
- look like **one consistent series** (a fixed house style across all covers),
- cost **~$0** at the pipeline's volume (1 post/day), and
- **never block publishing** — a failed image ships the post text-only.

## 2. Non-goals (YAGNI)

- **No backfill.** The 238 existing posts stay image-less; the frontend renders a
  graceful fallback for them. New posts only.
- **No multiple images per post.** One cover, full stop.
- **No separate LLM call to craft the image prompt.** The prompt rides along on
  the existing rewrite call (see §6.2).
- **No WebP transcoding / Pillow dependency** for v1. Store the provider's bytes
  as-is (`.jpg`). Repo growth is ~50 MB/year — negligible. (Future optimization.)
- **No aspect-ratio variants.** FLUX schnell on Workers AI returns a fixed
  1024×1024; the frontend crops as needed.

## 3. Provider decision

**Image provider: Cloudflare Workers AI — `@cf/black-forest-labs/flux-1-schnell`.**

- **Cost: $0** at this volume. Workers AI free tier = 10,000 neurons/day; FLUX
  schnell ≈ 9.6 neurons/step (~40 neurons at 4 steps) → ~250 free images/day.
  One post/day never approaches the cap.
- Reuses `requests` (already a dependency) — a plain REST call, no new SDK.
- FLUX quality suits editorial blog covers.

The text pipeline stays on **Amazon Bedrock (Nova Pro)** — unchanged. This is a
deliberate **two-provider** system (text = Bedrock, image = Cloudflare); §5
covers how that stays clean.

## 4. End-to-end architecture (three repos, one contract)

```
daily-dev-digest (Python)
  scrape → Bedrock rewrite → [NEW] Cloudflare image → write {slug}.mdx + {slug}.jpg
      │  front-matter now carries: image, image_alt, image_prompt
      ▼  workflow copies mdx → portfolio-blog/posts/, jpg → portfolio-blog/images/
portfolio-blog (Node)
  build-index.mjs parses front-matter → [NEW] carries `image` into blogs.json
      ▼  commits generated/blogs.json, fires Vercel deploy hook
next-gen-portfolio (Next.js)
  fetch-blog-content.mjs clones portfolio-blog →
      copies blogs.json AND [NEW] images/ → public/blog-images/
  blog card + article header → [NEW] render coverImage with fallback
```

**The contract between repos is the front-matter `image` field**, resolved to the
site-relative path `/blog-images/{slug}.jpg`. Because `portfolio-blog` is
**private**, external CDNs (jsDelivr, raw.githubusercontent) can't serve the
files — so images travel the same private-clone path the JSON already uses, and
are served as ordinary Next.js static assets. No external hosting, no new infra.

## 5. Clean two-provider architecture (the core design principle)

The existing `bedrock_client.py` is the model to copy: a **thin provider adapter**
— model-agnostic, deps imported lazily, env-configured, raises on error so the
caller owns failure handling. We add a **second adapter of the same shape** and
keep the orchestrator provider-agnostic.

| Concern | Text provider | Image provider |
|---|---|---|
| Module | `bedrock_client.py` (existing) | `image_client.py` (new) |
| Entry point | `converse(system, user, …) -> str` | `generate(prompt, *, steps) -> bytes` |
| Config | `BEDROCK_MODEL_ID`, `AWS_REGION` | `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_IMAGE_MODEL` |
| Deps | `boto3` (lazy) | `requests` (already imported) |
| On error | raises | raises |

**Invariants that keep two providers from turning into a mess:**

1. **Adapters never import each other or the orchestrator.** Dependencies point
   one way: `generate_digest.py` → each adapter.
2. **The orchestrator depends on interfaces, not vendors.** It calls
   `bedrock_client.converse(...)` and `image_client.generate(...)`; nothing in
   `generate_digest.py` references Cloudflare or AWS specifics.
3. **Each provider is swappable in exactly one file.** Just as `BEDROCK_MODEL_ID`
   swaps text models without touching callers, `image_client.py` hides the image
   vendor behind `generate()` — moving to fal.ai/Bedrock later is a one-file change.
4. **Provider details live only in env**, mirroring the existing pattern — no
   vendor constants leak into orchestration or front-matter.

## 6. Detailed design

### 6.1 `image_client.py` (new — Cloudflare adapter)

```python
# Env-configured; requests reused; raises on error (caller owns dry-run + fallback).
CF_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"

def generate(prompt: str, *, steps: int = 4) -> bytes:
    """Text-to-image via Cloudflare Workers AI. Returns raw JPEG bytes.
    Raises on missing config, transport error, or an unsuccessful CF response."""
```

- Reads `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_IMAGE_MODEL` (default above),
  `IMAGE_STEPS` (default 4, schnell max 8) from env.
- `POST` with `Authorization: Bearer {token}`, body `{"prompt": prompt[:2048], "steps": steps}`.
- CF returns `{"success": true, "result": {"image": "<base64 jpeg>"}}`; decode
  `result.image` (base64) → bytes. If `success` is false or the field is missing,
  raise `RuntimeError` with the CF error payload.
- No retries in v1 (single daily run; a failure degrades gracefully per §6.4).

### 6.2 Structured image brief from LLM #1 (no extra call)

A single free-form sentence produces inconsistent, hit-or-miss covers. Instead,
the **existing** `generate_post` call emits a **structured `image_brief` object**
— typed slots the model must fill, so every prompt covers the same dimensions.
Add `image_brief` to `GENERATE_KEYS`, the prompt's JSON schema, and the dry-run
mock:

```json
"image_brief": {
  "subject": "the single central visual metaphor — concrete, literal, one clear focal object/scene (NOT abstract mush)",
  "composition": "how it's framed — e.g. 'centered hero object, generous negative space, slight top-down angle'",
  "mood": "emotional tone in 2-4 words — e.g. 'calm, precise, optimistic'",
  "palette": "2-3 dominant colors that fit the topic — e.g. 'deep indigo, warm amber, off-white'"
}
```

Prompt instruction to the model: *"Design a cover image brief for this post. The
subject must be one concrete visual metaphor a person could sketch — never text,
UI screenshots, or logos. Fill every field."*

This is **extra output on a call we already make** — zero added API calls, zero
added cost. It's validated like the other keys (§6.4): a missing/malformed brief
falls back to a minimal brief derived from `headline` + `tags`, so we always have
enough to build a prompt.

### 6.2a Why structured (over a one-liner)

- **Consistency:** fixed slots force subject *and* composition *and* palette every
  time — the loose sentence routinely dropped composition/color, so covers drifted.
- **Brand coherence:** subject/mood/palette vary per post while §6.3's house-style
  and negatives stay constant — that split is what makes a recognizable series.
- **FLUX responds to descriptive, well-ordered prompts;** assembling from slots
  yields a fuller, better-ordered prompt than a single clause.
- **Debuggable & regenerable:** the brief is stored (see `image_prompt`, §6.5), so
  a bad cover can be diagnosed slot-by-slot and re-rendered.

### 6.3 `build_image_prompt()` (new — pure function in `generate_digest.py`)

Deterministically assembles the structured brief into a single ordered prompt.
Domain logic (house style + negatives) lives here, out of the provider adapter, so
the adapter stays vendor-only and this stays unit-testable. FLUX schnell on
Workers AI takes **no separate negative-prompt param**, so exclusions are folded
into the positive prompt as an explicit "avoid" clause.

```python
# Fixed across every cover — the constant half of the series look.
BRAND_STYLE = (
    "editorial tech illustration, flat vector style, soft geometric shapes, "
    "clean, high detail, subtle grain, professional blog cover"
)
NEGATIVES = "no text, no words, no letters, no watermark, no logos, no UI screenshots, no photorealistic faces"

def build_image_prompt(brief: dict, headline: str, tags: list[str]) -> str:
    """Assemble a structured brief into one ordered FLUX prompt.
    Falls back to headline/tags for any empty slot so we always get an image."""
    subject     = _slot(brief, "subject")     or f"a clean conceptual illustration about {headline}"
    composition = _slot(brief, "composition") or "centered hero subject, generous negative space"
    mood        = _slot(brief, "mood")        or "modern, precise"
    palette     = _slot(brief, "palette")     or "muted modern tech palette"
    return (
        f"{subject}. "
        f"Composition: {composition}. "
        f"Mood: {mood}. "
        f"Color palette: {palette}. "
        f"Style: {BRAND_STYLE}. "
        f"Avoid: {NEGATIVES}."
    )[:2048]
```

- **Ordering is deliberate** — subject first (what FLUX weights most), then
  framing, mood, color, then the fixed style and exclusions.
- `_slot()` trims and guards against non-string/empty values from the model.
- The constant `BRAND_STYLE` + `NEGATIVES` are what make every cover one series;
  the brief supplies only the per-post variation.

### 6.4 Orchestration + failure policy (non-fatal by default)

In `main()`, after `verify_post`, before `save_to_mdx`:

```python
image_rel = None                      # front-matter stays image-less if this stays None
try:
    prompt = build_image_prompt(generated.get("image_brief", {}),
                                generated["headline"], generated.get("tags", []))
    img_bytes = image_client.generate(prompt) if not dry_run else None
    if img_bytes:
        image_rel = save_cover_image(img_bytes, slug)   # writes digests/images/{slug}.jpg
except Exception as e:                # noqa: BLE001 — image is best-effort
    print(f"⚠️ Cover image generation failed ({e}); publishing text-only.")
    if os.getenv("IMAGE_REQUIRED", "false").lower() == "true":
        raise
```

- **Key divergence from the LLM stages:** the text stages *fail the run* on error
  ("never push garbage"); the image stage is **best-effort** — a failure logs a
  warning and ships the post without an image. This matches the "never block
  publishing" goal and the existing image-less fallback for the 238 legacy posts.
- `IMAGE_REQUIRED=true` opt-in flips it to hard-fail for anyone who wants that.
- **Dry-run** skips the network entirely (consistent with the LLM dry-run mocks);
  no image is produced.

### 6.5 Front-matter changes (`build_mdx`)

Replace the naive `image_suggestion` line with real fields (only emitted when an
image was produced; absent otherwise so legacy behavior is unchanged):

```yaml
image: {yaml_safe_value(image_rel)}              # e.g. "/blog-images/{slug}.jpg"
image_alt: {yaml_safe_value(brief["subject"])}   # accessibility (subject slot)
image_prompt: {yaml_safe_value(full_prompt)}     # full assembled prompt — reproducibility / regeneration
```

`save_cover_image()` returns the site-relative path `"/blog-images/{slug}.jpg"`,
which is what `image` stores — the digest never hardcodes a host/CDN.

### 6.6 Local output + workflow (`daily-dev-digest`)

- `save_cover_image(bytes, slug)` writes `digests/images/{slug}.jpg` (`digests/`
  is already gitignored/ephemeral).
- **Workflow secrets (new):** `CF_ACCOUNT_ID`, `CF_API_TOKEN` as `env` on the
  generate step.
- **Workflow copy step (new):** after copying mdx,
  `mkdir -p blog/images && cp -v digests/images/* blog/images/ 2>/dev/null || true`,
  then `git add posts/*.mdx images/*` before the existing commit.

### 6.7 New dependency

None required. `requests` covers the HTTP call; `base64`/`json`/`os` are stdlib.
(Pillow/WebP intentionally deferred — §2.)

## 7. `portfolio-blog` changes (workstream B)

- **`scripts/build-index.mjs`:** `gray-matter` already parses all front-matter.
  Map `data.image` (and `data.image_alt`) into each `blogs.json` entry as
  `coverImage` / `coverImageAlt`. Omit when absent (legacy posts).
- **`scripts/verify-safety.mjs`:** allow the new fields; if it validates a field
  allowlist or sanitizes values, ensure a `/blog-images/…` path passes.
- The digest workflow committing files under `images/**` must **not** trigger a
  needless index rebuild loop — the build-index workflow's path filter is
  `posts/**`/`scripts/**`, so image-only commits won't rebuild; the paired
  `posts/**` commit will. (Verify during implementation.)

## 8. `next-gen-portfolio` changes (workstream C)

- **`scripts/fetch-blog-content.mjs`:** add a copy of the cloned
  `images/` dir → `public/blog-images/` (alongside the existing JSON copies).
  Fail-soft like the rest of the script (missing dir ⇒ skip, don't fail build).
- **Render:** show `coverImage` in the blog card and article header; when absent,
  render the existing fallback (hide or placeholder). Because the path is a
  site-relative static asset (`/blog-images/…`), `next/image` needs **no**
  `remotePatterns` change.

## 9. Field contract (single source of truth)

| Stage | Field | Value |
|---|---|---|
| MDX front-matter | `image` | `/blog-images/{slug}.jpg` (or absent) |
| MDX front-matter | `image_alt` | `subject` slot from the image brief |
| MDX front-matter | `image_prompt` | full prompt (concept + house style) |
| `blogs.json` entry | `coverImage` | copied from `image` |
| `blogs.json` entry | `coverImageAlt` | copied from `image_alt` |
| Static asset | file | `next-gen-portfolio/public/blog-images/{slug}.jpg` |

## 10. Failure modes

| Failure | Behavior |
|---|---|
| Cloudflare down / non-200 / bad payload | Warn, publish text-only (unless `IMAGE_REQUIRED=true`) |
| `CF_*` env unset | `generate()` raises → same best-effort fallback |
| Dry-run | No network, no image, post exported normally |
| Image copy missing in ngp fetch | Fail-soft skip; post renders with fallback |
| Legacy post (no `image`) | Frontend fallback (unchanged) |

## 11. Testing strategy

- **`image_client.generate`** (unit, mock `requests.post`): success → bytes;
  non-200 → raises; `success:false` payload → raises; missing env → raises.
- **`build_image_prompt`** (pure): full brief → ordered prompt with all slots;
  each empty/missing/non-string slot falls back to its headline/tags default;
  `BRAND_STYLE` + `NEGATIVES` always present; truncates to 2048.
- **`build_mdx`**: image fields present when `image_rel` set; fully absent when
  `None` (legacy parity).
- **Orchestration**: image exception does NOT abort the run when
  `IMAGE_REQUIRED` unset; DOES when set. Dry-run makes no image.
- **`build-index.mjs`**: a post with `image` front-matter surfaces `coverImage`
  in `blogs.json`; a post without it does not.

## 12. Rollout sequence

1. **Workstream A** (`daily-dev-digest`): adapter + concept + prompt + orchestration
   + front-matter + workflow. Ship first — dormant until B/C render it, but
   already emits fields + files harmlessly.
2. **Workstream B** (`portfolio-blog`): carry `coverImage` into `blogs.json`.
3. **Workstream C** (`next-gen-portfolio`): copy images + render + fallback.

Each workstream is independently testable and safe to merge alone (earlier stages
just produce data later stages ignore until ready).

## 13. Assumptions to verify during implementation

- FLUX schnell on Workers AI returns base64 **JPEG** in `result.image` (confirm
  content-type; adjust `IMAGE_EXT` if PNG).
- `verify-safety.mjs` has no allowlist that silently drops unknown front-matter
  keys.
- ngp blog card/article components have a clean spot for a cover image + an
  existing empty-state to reuse as the fallback.
