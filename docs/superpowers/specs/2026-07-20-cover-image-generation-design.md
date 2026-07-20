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

### 6.2 Image concept from LLM #1 (no extra call)

Extend the **existing** `generate_post` structured output. Add one key to
`GENERATE_KEYS`, the prompt's JSON schema, and the dry-run mock:

- `image_concept`: *one sentence describing a fitting visual*, e.g. *"an abstract
  circuit board morphing into a flowing river of light."* Prompt instruction:
  "Describe a single vivid, literal-but-tasteful visual for a blog cover about
  this post. No text in the image. One sentence."

This adds **zero** API calls and zero cost — it's extra output on a call we
already make.

### 6.3 `build_image_prompt()` (new — pure function in `generate_digest.py`)

Domain logic (house style), kept out of the provider adapter so the adapter stays
vendor-only and this stays unit-testable:

```python
BRAND_STYLE = (
    "editorial tech illustration, flat vector style, soft geometric shapes, "
    "muted modern palette, clean, high detail, no text, no watermark, no logos"
)
def build_image_prompt(image_concept: str, headline: str) -> str:
    concept = (image_concept or headline).strip()
    return f"{concept}. Style: {BRAND_STYLE}."[:2048]
```

The fixed `BRAND_STYLE` suffix is what makes every cover look like one series.

### 6.4 Orchestration + failure policy (non-fatal by default)

In `main()`, after `verify_post`, before `save_to_mdx`:

```python
image_rel = None                      # front-matter stays image-less if this stays None
try:
    prompt = build_image_prompt(generated.get("image_concept", ""), generated["headline"])
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
image: {yaml_safe_value(image_rel)}          # e.g. "/blog-images/{slug}.jpg"
image_alt: {yaml_safe_value(image_concept)}  # accessibility
image_prompt: {yaml_safe_value(full_prompt)} # reproducibility / regeneration
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
| MDX front-matter | `image_alt` | image concept sentence |
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
- **`build_image_prompt`** (pure): concept + house style; empty concept falls back
  to headline; truncates to 2048.
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
