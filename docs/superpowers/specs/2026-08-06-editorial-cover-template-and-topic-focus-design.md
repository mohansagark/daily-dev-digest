# Editorial Cover Template + Topic Focus — Design

**Date:** 2026-08-06  
**Repo:** `daily-dev-digest`  
**Status:** Dual-review aligned — ready for implementation planning  
**Supersedes (partial):** abstract FLUX-only cover look from `2026-07-20-cover-image-generation-design.md` §6.3 style constants for *new* posts. Front-matter fields (`image`, `image_alt`, `image_prompt`) and fail-soft publish behavior stay.  
**Mohan sign-off (2026-08-06):** §14 accepted, including residual risk on #3, off-center crop bias (§14.2 #8), and **no fixed weekday→strategy calendar in this spec** (deterministic map deferred to the implementation plan).

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

## 13. Open gaps / remediations (pre-implementation review)

Blocking (must resolve before implementation starts):

| # | Gap | Remediation |
|---|---|---|
| 1 | `cover_hook` input contract undefined. §5 gives output JSON only; §3 places the hook *after* verified MDX body/front-matter, but never says what text it reads (full body? title+tags+meta_description?). | Pin input shape explicitly, mirroring `cover_backfill.py`'s existing `BRIEF_USER` pattern (title + tags + body excerpt). |
| 2 | Third Bedrock call not reconciled with existing `image_brief`. `generate_post()`'s LLM#1 already emits `image_brief` (subject/composition/mood/palette) used by the old `build_image_prompt` path. Doc doesn't say whether to drop `image_brief` from `GENERATE_USER_TEMPLATE` for new posts (dead weight/wasted tokens if kept) or keep it, and gives no added-cost estimate for the new cover_hook Bedrock call + FLUX call. | Decide explicitly: strip `image_brief` from LLM#1's prompt/output for the new-post path (cover_backfill.py keeps its own independent brief call for legacy posts). Add a cost line (Bedrock tokens + FLUX $/step) next to the existing CI-time budget in §7. |
| 3 | FLUX has no `negative_prompt` — "no chrome, no text overlays" (§3 step 2) is unenforceable. `image_client.py` sends only `prompt`+`steps`. The existing `IMAGE_SUBJECT_INSTRUCTION` bans labels specifically because FLUX garbles any named text; realistic photos of "monitor, code, dashboard" (§4) inherently carry UI text that will garble the same way. | Either have the Playwright compositor blur/mask the photo's screen region before compositing, or add an explicit reject/retry rule for photos with garbled text, rather than relying on `photo_brief` wording alone. |
| 4 | No image dimension/aspect-ratio spec for the FLUX call. `image_client.generate()` takes no width/height param; FLUX defaults square-ish. The diagonal right-pane (~54% of 1200×630 — wide, short) needs a non-square source and a defined crop strategy. | Add width/height (or target aspect) to `image_client.generate()`'s signature; state cover-fit vs. contain crop behavior in §6. |
| 5 | Allowlist table (§8) is missing the `style`/`description` fields the pipeline requires. Current `STRATEGIES` dict has `focus` + `style` (feeds the GENERATE prompt tone) + `description` (feeds front-matter `content_strategy`). New table only lists keys+keywords. | Extend the §8 table with `style` and `description` per key now, not left to "exact map chosen at implementation." |
| 6 | Denylist field mismatch (§8): "regex denylist on title + summary" — at select-time the article dict only has `title`+`content`; `summary`/`meta_description` doesn't exist until after LLM#1 runs. | If the denylist runs pre-LLM (as §8 implies), match against `content`, not a not-yet-created `summary`. State explicitly which field and which pipeline stage. |

Non-blocking (should fix, won't break first implementation):

| # | Gap | Remediation |
|---|---|---|
| 7 | No CI test-execution step exists today. §10 references regression tests but `digest.yml` has no pytest step at all, and §7's CI changes don't add one. | Add a `pytest` step to `digest.yml` (or a separate CI workflow) alongside the Playwright install step. |
| 8 | Playwright Chromium isn't cached in CI. §7 accepts +1-3 min per run but every run re-downloads ~150MB of Chromium — added time and a new flakiness surface on a daily scheduled job. | Cache `~/.cache/ms-playwright` via `actions/cache`, keyed on Playwright version. |
| 9 | §6 leaves `file://` vs. local static server as an "or." Vendored `@font-face` fonts under `file://` can hit Chromium file-access restrictions depending on version, silently falling back to system fonts — directly undermines goal 1 ("crisp readable type every time") without erroring. | Commit to a local static server now, not deferred to implementation. |
| 10 | No content-safety guard on realistic photos. §4's "photo_brief" never states whether photorealistic people/faces are in bounds; FLUX schnell faces are typically low quality/distorted. The old `IMAGE_SUBJECT_INSTRUCTION` had this discipline (banned labels/metaphors) for a reason — new brief drops it. | Add an explicit "no human faces, artifact-only" rule to the photo_brief instructions, mirroring the old design's discipline. |
| 11 | No alerting on repeated cover failures. Fail-soft is correct per-post, but nothing signals if covers silently fail N days running (e.g. vendored fonts missing, Playwright install broken) — goal 1 degrades quietly. | Add a log-scannable marker or simple counter for consecutive cover failures, even if full alerting is out of scope. |

## 14. Spec alignment review (Cursor / Grok) — responses to §13

Review of the pre-implementation gaps in §13. Goal: one shared decision table before writing-plans. Status values: **Accept** (adopt remediation as written), **Accept with tweak** (same intent, adjusted how), **Defer**.

### Blocking

| # | Verdict | Locked decision |
|---|---|---|
| 1 | **Accept** | `cover_hook` input is explicit: **title + tags + body excerpt** (mirror `cover_backfill.py` `BRIEF_USER` shape: title, comma-joined tags, body `[:6000]`). Runs **after** generate + verify, on the verified post fields. Output remains §5 JSON. |
| 2 | **Accept** | **Strip `image_brief`** from LLM#1 (`GENERATE_USER_TEMPLATE` / structured output) on the new-post path. Photo brief ownership moves to `cover_hook` (+ FLUX). `cover_backfill.py` keeps its **independent** brief Bedrock call for legacy posts. §7 must add a **cost line**: +1 Bedrock `cover_hook` call (small max_tokens) + 1 FLUX render at configured `IMAGE_STEPS` (document $/step from current Workers AI pricing at implement time — do not hardcode stale rates). Old `build_image_prompt` / schematic `BRAND_STYLE` path is unused for new posts. |
| 3 | **Accept with tweak** | Agree FLUX cannot enforce “no chrome / no text” via negative prompts. **Do not** require Playwright to blur/mask a guessed “screen region” in v1 (fragile, no reliable detector). Instead: (a) `photo_brief` rules prefer **artifact / environment scenes** and **soft-focus or non-legible screens** when a display is present; (b) ban instructing FLUX to render sharp readable UI chrome or labeled diagrams; (c) optional **one retry** with a stricter brief if a cheap post-check flags dense glyph-like noise (v1.5 if not free in v1). Compositor does **not** OCR-mask in v1. |
| 4 | **Accept with tweak** | Today `image_client.generate()` has no width/height; Workers AI FLUX schnell typically returns ~square. **v1 crop strategy (required):** compositor treats photo as `object-fit: cover` into the diagonal right pane (wide short region of 1200×630) — defined center/focal crop, never letterbox empty bands. **If** the API accepts size params at implement time, pass a landscape-friendly size; otherwise square + cover-crop is normative. Document this in §6 at plan time. |
| 5 | **Accept** | Extend §8 allowlist rows with `style` and `description` **in this spec** (see §14.1). Weekday rotation must stay **deterministic** at implement time, but **no fixed Mon–Sun schedule is required in this design doc** (Mohan: leave calendar to the implementation plan). Each key is fully specified in §14.1. |
| 6 | **Accept** | Denylist runs **pre-LLM**, at select-time, on **`title` + `content`** (use a bounded content prefix, e.g. first 2k chars). Do **not** reference `summary` / `meta_description` (those do not exist yet). Log skip reason. |

### Non-blocking

| # | Verdict | Locked decision |
|---|---|---|
| 7 | **Accept** | Add **pytest in CI**. Prefer a **PR / push CI workflow** (or job) so the daily digest cron is not the only place tests run; digest workflow may still run a fast smoke subset if cheap. §10 stays valid once CI executes tests. |
| 8 | **Accept** | Cache `~/.cache/ms-playwright` with `actions/cache`, key including Playwright package version. |
| 9 | **Accept** | **Local static server only** for Playwright render. Drop `file://` as an option (font `@font-face` risk). |
| 10 | **Accept** | Photo brief rules: **artifact-only, no human faces / photorealistic people**. Distorted FLUX faces are out of bounds. |
| 11 | **Accept** | Every run logs a scannable marker, e.g. `COVER_STATUS=ok` or `COVER_STATUS=failed:<reason>`. Full alerting/paging is out of scope; log search is enough for v1. |

### 14.1 Allowlist table — extended (closes #5)

| Key | Keywords (scoring) | style | description |
|---|---|---|---|
| `ai` | ai, llm, agents, machine learning, generative, prompt, model | clear and rigorous | AI systems, agents, and applied ML for working engineers |
| `frontend` | frontend, javascript, typescript, react, vue, css, next.js, ui engineering | energetic and practical | Frontend and JavaScript engineering |
| `architecture` | architecture, system design, distributed, microservices, patterns, scalability | detailed and informative | Software architecture and system design |
| `tools` | developer tools, cli, ide, devops tools, new release, tooling | practical and evaluative | New and notable software tools for developers |
| `ai_news` | ai news, openai, anthropic, model release, industry | timely and analytical | AI industry news and model releases |
| `biz_ideas` | indie hacker, saas, solopreneur, consulting, product idea, monetization | pragmatic and opinionated | Business ideas and monetization for software engineers |
| `client_websites` | freelance, client site, agency, portfolio site, web design for clients | practical and client-aware | Building websites and web presence for clients |

### 14.2 Normative amendments (apply when implementing; supersede conflicting soft language above)

1. **§5 input:** title + tags + body excerpt as in §14 #1.  
2. **§3 / LLM#1:** no `image_brief` on new-post generate path (§14 #2).  
3. **§3 step 2 / §4 photo:** artifact-only, no faces; soft-focus/non-legible screens preferred; no compositor screen-mask in v1 (§14 #3, #10).  
4. **§6:** local static server required; photo `object-fit: cover` into right pane (§14 #4, #9).  
5. **§7:** Playwright cache; cost line for +1 Bedrock hook + 1 FLUX; pytest via CI workflow (§14 #2, #7, #8).  
6. **§8:** use §14.1 table; denylist on `title` + `content` prefix pre-LLM (§14 #5, #6).  
7. **§9:** emit `COVER_STATUS=...` on every path (§14 #11).  
8. **§4 photo_brief / §6 crop:** `photo_brief` must bias FLUX toward off-center, one-side subject placement (matching whichever side lands in the diagonal right pane), not a centered square composition — a plain center-crop from a near-square FLUX source into the wide/short diagonal pane will otherwise clip the named artifact or suspense detail before it ever reaches the compositor. State this bias explicitly in the `cover_hook` prompt rules (§5), not left implicit in "composition" wording.  
9. **§9 accepted risk:** v1 ships with no automated check for garbled/illegible screen-text in photos (§14 #3 dropped the OCR/mask option deliberately). This is an accepted residual risk, not a closed issue — mitigated only by brief wording, unmeasured until real renders are reviewed. Revisit (optional retry or masking) if it shows up in practice post-launch.

### 14.3 Explicit non-agreement

- **Disagree with §13 #3 remediation as written** insofar as it mandates Playwright blur/mask of a screen region as a v1 requirement. Intent (don’t ship garbled UI type) is shared; mechanism is brief discipline + crop/compose, not region masking.

### 14.4 Confirmation log (Mohan, 2026-08-06)

| Point | Decision |
|---|---|
| Gap #3 / residual garbled UI text | **OK for v1** — brief discipline only; no Playwright mask/OCR reject in v1; revisit after live renders (§14.2 #9). |
| Off-center subject bias (§14.2 #8) | **OK** — `photo_brief` / cover_hook rules must bias FLUX subject placement for diagonal cover-crop. |
| Weekday→strategy calendar | **Not in this spec** — no fixed schedule required here; plan may choose any deterministic rotation over §14.1 keys. |

§13 gaps are **resolved for planning**. Implementation plan must cite §14 (including §14.4), not re-open these decisions.
