# Editorial Cover Template + Topic Focus — Design

**Date:** 2026-08-06  
**Repo:** `daily-dev-digest`  
**Status:** Approved for implementation planning  
**Supersedes (partial):** abstract FLUX-only cover look from `2026-07-20-cover-image-generation-design.md` §6.3 style constants for *new* posts. Front-matter fields (`image`, `image_alt`, `image_prompt`) and fail-soft publish behavior stay.

## 1. Purpose

Ship two related changes to the daily digest:

1. **Editorial cover template** — every new post gets a 1200×630 cover that matches the approved quiet-luxury diagonal layout (real fonts + topic photo), not abstract node diagrams.
2. **Topic allowlist** — candidate selection only keeps posts in a fixed set of themes; reject generic “top N / random roundup” listicles.

## 2. Goals and non-goals

### Goals

- Crisp, readable type every time (no FLUX-rendered headlines).
- Multi-step cover generation that runs in GitHub Actions.
- Catchy cover headline/subhead + topic-specific one-line pill.
- Realistic right-pane photo (tone flexible per post).
- Brand: **Mohan Sagar** / `<devmohan.in>`.
- Fonts: **Playfair Display** (brand + headline) + **DM Sans** (subhead, pill, CTA).
- Narrow blog topics to the allowlist below.

### Non-goals

- One-shot FLUX of the entire cover (rejected — text quality).
- Workstreams D/E (retry cron / full legacy backfill) — out of scope; new template applies to **new** posts. Existing `cover_backfill.py` may be updated later to the same template.
- Pillow/WebP as the primary compositor (Approach C deferred).
- Redesign of `portfolio-blog` / `next-gen-portfolio` image rendering (already consume `image`).

## 3. Cover architecture (Approach A)

```
existing: scrape → clean → dedupe → select → Bedrock generate → Bedrock verify
                              ↓
                    [NEW] topic allowlist gate on select
                              ↓
existing MDX body + front-matter (minus image until cover lands)
                              ↓
[NEW] Bedrock cover_hook → FLUX photo → Playwright template → 1200×630 JPG
                              ↓
attach image / image_alt / image_prompt → commit path unchanged
```

| Step | Owner | Output |
|---|---|---|
| 1. Cover hook | Bedrock (Nova Pro) | JSON: `headline`, `subtitle`, `pill` (3 strings), `photo_brief`, `tone` |
| 2. Photo | Cloudflare FLUX schnell | Raw bytes of **right-pane subject only** (no chrome, no text overlays) |
| 3. Compose | Playwright + Chromium | HTML template + photo → PNG/JPEG 1200×630 |
| 4. Ship | existing | `digests/images/{slug}.jpg` + front-matter; workflow copies to `portfolio-blog/images/` |

Dry-run: mock `cover_hook`, solid/gradient placeholder photo, still render template (no Bedrock/FLUX network). Fail-soft: same as today (`IMAGE_REQUIRED` default false) — post publishes text-only if any cover step fails.

## 4. Visual system (locked)

| Element | Spec |
|---|---|
| Canvas | 1200×630 |
| Layout | Diagonal split; solid cream text column (~46% width) so type never sits under the photo; photo clipped on the diagonal |
| Brand | `Mohan Sagar` (Playfair) then `<devmohan.in>` (monospace) |
| Headline | Playfair Display, large, charcoal, all-caps — tension/contradiction hook |
| Subhead | DM Sans, smaller, charcoal, all-caps — unanswered beat |
| Pill | Light grey; `✓ A \| ✓ B \| ✓ C`; topic-specific; **one line**; if it would wrap, rewrite the longest beat shorter — never ellipsis-as-design |
| CTA | Matte black; fixed `READ THE FULL POST` |
| Right pane | Realistic topic photo; **no** abstract geometry; tone flexible (`warm_bw` \| `cool_steel` \| `muted_color` \| `vivid_night`) chosen in `cover_hook` |
| Photo brief | Names a recognizable artifact (monitor, code, dashboard, etc.) + suspense detail; affirmative surfaces; no readable labels for FLUX to spell unless they are naturally in a photo scene |

Cover hook copy is **for the image only**. Post `title` / `subtitle` in MDX remain the article titles from the generate stage (unless a later change explicitly syncs them — not in this design).

## 5. `cover_hook` contract

Bedrock returns JSON only:

```json
{
  "headline": "string",
  "subtitle": "string",
  "pill": ["string", "string", "string"],
  "photo_brief": "string",
  "tone": "warm_bw | cool_steel | muted_color | vivid_night"
}
```

Rules for the model prompt:

- Headline = stakes/contradiction; not “A Guide to…”.
- Subtitle = curiosity beat; no spoilers of the full how-to.
- Pill beats meaningful but short enough for one line; compositor may re-shorten the longest if measured width overflows.
- `photo_brief` describes a photographable scene matching the post; no isometric node diagrams.

## 6. Template compositor

- HTML file(s) under e.g. `cover_template/` with self-contained CSS.
- Fonts: Playfair Display + DM Sans shipped as **local font files** in-repo (or downloaded at CI install time and cached) so CI does not depend on Google Fonts at render time.
- Playwright opens the template with `file://` or a tiny local static server, injects hook fields + photo path, screenshots at device scale 1, viewport 1200×630.
- Output JPEG via existing `downscale_cover` path (or direct JPEG save at quality suitable for 1200×630 OG/card use).
- Brand block pinned at top of cream column; hooks below — brand must never be clipped by long headlines.

## 7. CI (GitHub Actions)

Extend `.github/workflows/digest.yml`:

1. After `pip install`, install Playwright Chromium (`playwright install chromium` + OS deps as required by the Playwright Python package).
2. Existing AWS OIDC + `CF_*` secrets remain.
3. No new secrets for fonts if fonts are vendored in-repo.
4. Job time budget: expect +1–3 minutes for browser install/render on cold runners; acceptable.

## 8. Topic allowlist

Replace the current weekday strategies (`frontend` / `backend` / `design_career` / `fundamentals`) with allowlisted focus packs only:

| Key | Themes (keywords for scoring) |
|---|---|
| `ai` | ai, llm, agents, machine learning, generative, prompt, model |
| `frontend` | frontend, javascript, typescript, react, vue, css, next.js, ui engineering |
| `architecture` | architecture, system design, distributed, microservices, patterns, scalability |
| `tools` | developer tools, cli, ide, devops tools, new release, tooling |
| `ai_news` | ai news, openai, anthropic, model release, industry (AI-specific) |
| `biz_ideas` | indie hacker, saas, solopreneur, consulting, product idea, monetization |
| `client_websites` | freelance, client site, agency, portfolio site, web design for clients |

Weekday rotation maps only among these keys (exact map chosen at implementation; must stay deterministic).

### Hard reject (before or after score)

Drop candidates whose title/summary match listicle/noise patterns, unless clearly on-allowlist *and* not a generic ranking post. Examples to reject:

- `top \d+`, `best \d+`, `\d+ (tips|tools|libraries|resources) (you|for|to)`
- “roundup”, “weekly links” style fluff without a single deep topic

Implementation: regex denylist on title + summary; log skip reason. Prefer zero post over publishing off-strategy spam when nothing passes (same as empty-candidate behavior today if applicable — if today the pipeline errors when empty, keep that; do not invent a filler post).

## 9. Failure modes

| Failure | Behavior |
|---|---|
| Cover hook Bedrock fails | Warn; skip cover; publish text-only (unless `IMAGE_REQUIRED`) |
| FLUX fails | Warn; skip cover; publish text-only |
| Playwright fails | Warn; skip cover; publish text-only |
| Pill overflows measured width | Shorten longest beat once; if still overflows, drop shortest beat’s words further; never multi-line pill |
| No candidate after allowlist | Fail run clearly (no off-topic fallback) |

## 10. Testing

- Unit: `cover_hook` parsing / pill shortening helper / topic denylist + allowlist scoring.
- Template: Playwright snapshot or pixel-presence checks — brand string present, pill single-line, dimensions 1200×630.
- Dry-run: end-to-end deterministic path produces a JPG without AWS/CF.
- Regression: existing generate/verify MDX tests still pass; image fields absent when cover skipped.

## 11. Rollout

1. Implement topic allowlist + denylist (can ship before compositor).
2. Implement cover_hook + FLUX photo-only brief change + Playwright template.
3. Wire into `generate_digest.py` orchestration and `digest.yml`.
4. Run workflow_dispatch; approve one live post cover on `portfolio-blog`.
5. Leave D/E / backfill-to-new-template as a follow-up plan.

## 12. Assumptions

- Playwright Python package is acceptable as a runtime/CI dependency for cover render (dev+CI; document in README).
- FLUX remains photo-only; no return to schematic `BRAND_STYLE` / isometric defaults for new covers.
- Cover hook headline may differ from MDX `title` (intentional — image hook vs article title).
