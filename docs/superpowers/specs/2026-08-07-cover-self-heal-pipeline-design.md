# Cover Self-Heal Pipeline — Design

**Date:** 2026-08-07  
**Repo:** `daily-dev-digest` (job + secrets); queue state on `portfolio-blog` MDX  
**Status:** Spec finalized (§16–§17). Implementation updated on PR https://github.com/mohansagark/daily-dev-digest/pull/7 to match §5.1/§10/§17.2 (Pillow `(1200, 630)` classifier; denylist removed; `eligible_wrong_size` seed buckets). Awaiting Claude code review before merge (schedule stays gated until rollout §11 step 6).  
**Related:**  
- `2026-08-06-editorial-cover-template-and-topic-focus-design.md` (editorial cover path; previously deferred D/E retry cron)  
- `2026-08-07-legacy-content-repair-design.md` §8 (`cover_status` backlog; “later image batch” now this spec)  
- `2026-07-20-cover-image-generation-design.md` (older FLUX-only look; superseded for **new** and **healed** covers)

## 1. Purpose

Keep every published blog post on an **editorial** 1200×630 cover over time — not as a one-shot backfill, but as a **daily self-healing pipeline**:

1. Posts missing a cover, or carrying a wrong/old (non-editorial) cover, stay enrolled until healed.
2. When the daily create job fails cover generation, the post still publishes text-only and is enrolled for heal.
3. A **separate** daily cron (not the scrape→create digest) processes up to **50** enrolled posts per day with the editorial template.
4. Heal failures re-enroll the post for the next day’s run.

## 2. Goals and non-goals

### Goals

- Persistent queue of posts that need an editorial cover (missing or wrong template).
- Separate GitHub Actions cron from `digest.yml` scrape/create.
- Cap **50** editorial regenerations per heal run.
- Overwrite non-editorial images when regenerating.
- On success: attach `image` / `image_alt` / `image_prompt` and mark `cover_status: done`.
- On failure: mark `cover_status: failed` so the post is eligible again tomorrow.
- Reuse the existing editorial path (Bedrock cover hook → FLUX photo → Playwright compose).
- Drain the **true** backlog (missing + schematic/wrong-template) at ≤50/day — after a one-time status seed so already-editorial covers are not regenerated.
- Stop `content_repair` from corrupting `cover_status` / clobbering editorial `image_prompt` metadata.

### Non-goals

- Changing `next-gen-portfolio` cover rendering (already consumes `coverImage` from `blogs.json`).
- Making daily create hard-fail when cover fails (`IMAGE_REQUIRED` stays default false).
- One-shot regeneration of the entire catalog in a single run.
- Continuing to use schematic / old `cover_backfill.py` FLUX-only path for this pipeline.
- Putting cover-generation secrets or Playwright into `portfolio-blog` CI.
- Displaying `cover_status` on the public site (internal FM only; index allowlist already excludes it).
- Using `origin: bot` alone as “already editorial,” and using `image_prompt` text as a proxy for it either. Verified: of 22 `origin: bot` posts, only **1** is actually the real `1200×630` composed template — the other 21 are square FLUX-only photos whose prompt text doesn't contain old schematic keywords. Dimensions are the only reliable signal (§5.1).

## 3. Decisions (locked)

| Decision | Choice |
|---|---|
| Enrollment | **Missing + wrong template** — regenerate and overwrite non-editorial covers |
| Cron | **Separate** from scrape→create (`digest.yml`) |
| Job home | **`daily-dev-digest`** (editorial code + AWS/CF/Playwright secrets) |
| Queue source of truth | **`cover_status` on `portfolio-blog` post front-matter**, kept honest by repair + seed + eligibility guard |
| Editorial-already-present | Shared classifier (§5.1) — **not** `origin == bot` alone |
| Ops history | Per-run report artifact in the heal workflow (not a second queue of truth) |
| Daily limit | **50** posts per heal run |
| Selection priority | Tiered: `failed` → missing image → wrong-template; then oldest `date`, then slug |
| Push target | Heal commits land on **`portfolio-blog` `main`** (same trust model as digest). Rationale vs repair’s preview-PR path: each heal write is a narrow FM + image binary patch, not an LLM body rewrite — failure mode is wrong/missing cover, not fabricated article content (§15 #8). |
| Concurrency | Shared `concurrency` group for digest + heal writers to `portfolio-blog` main |
| Rollout order | Wire daily-create `cover_status` + prove one real digest cycle **before** enabling heal cron |

## 4. Why this lives in `daily-dev-digest`

- Editorial cover implementation already lives here: `cover_hook.py`, `cover_compose.py`, `image_client.py`, `maybe_generate_cover` in `generate_digest.py`.
- CI already has OIDC → Bedrock, Cloudflare Workers AI, Playwright, and `BLOG_REPO_TOKEN` to write `portfolio-blog`.
- `portfolio-blog` remains the content store (MDX + `images/`); it should not own image-generation infrastructure.
- A separate workflow file keeps scrape/create failure modes isolated from heal failure modes.

## 5. Queue model — `cover_status`

Internal front-matter field on each `portfolio-blog` post (not exported to `blogs.json`).

| Value | Meaning | Eligible for heal? |
|---|---|---|
| `none` | Needs editorial cover (missing or wrong-template backlog) | **Yes** (unless §5.1 says already editorial) |
| `failed` | Last create or heal attempt failed | **Yes** (always) |
| `done` | Editorial cover attached successfully | **No** |
| missing key | Treat as `none` | **Yes** (unless §5.1 says already editorial) |

### 5.1 Already-editorial classifier (shared)

`origin: bot` only means “has `image` + `image_prompt`” (`content_repair.detect_origin`). On 2026-08-07 main that includes **all 22** imaged posts. **Do not** treat `origin == bot` as done — see the dimension check below for what actually distinguishes them.

**Verified against the real corpus (2026-08-07):** prompt-text denylist matching is not sufficient. Checked actual pixel dimensions of all 22 `origin: bot` posts — only **1** (`navigating-the-llm-landscape-open-source-vs-commercial-in-20`, today's post) is `1200×630`, the real Playwright-composed output (`cover_compose.py` hardcodes `COVER_W, COVER_H = 1200, 630`). The other 21 are `800×800` / `1024×1024` — square, raw FLUX-only photos from an earlier photo-brief iteration that never went through the diagonal-split/branded template at all. Their `image_prompt` text just doesn't happen to contain the old schematic keywords, so a text-only denylist would have wrongly classified all 21 as "already editorial" and permanently skipped them. **Editorial quality is a structural property of the compose step (exact dimensions, defined layout/brand pattern), not something prompt-text phrasing can reliably signal — dimension check is the authoritative test, not a heuristic alongside the denylist.**

Shared helper (used by seed, repair FM stamping, and heal eligibility). Signature (implementation must match):

```text
is_editorial_cover(fm, blog_root, slug) -> bool
```

Rules (first match wins):

1. No usable cover file/FM `image` pointing at `images/{slug}.jpg` / `/blog-images/{slug}.jpg` → **False**
2. Actual on-disk image dimensions **≠ exactly `(1200, 630)`** → **False** (wrong template — old schematic, old FLUX-only square photo, or anything else not produced by the current `cover_compose.py` — regardless of what `image_prompt` says). Read size via `PIL.Image.open(path).size`.
3. Dimensions == `(1200, 630)` → **True** (dimensions alone are sufficient proof of a real editorial compose; do not regenerate just because `cover_status` lagged as `none`/missing)

The old prompt-text denylist (`isometric`, `schematic`, `node diagram`, `geometric forms`, `layered depth`) is **dropped** — it's redundant once dimensions are authoritative (nothing schematic or FLUX-only ever produces exact `1200×630`) and it was the source of the 21-post false-classification above.

`cover_status: failed` **short-circuits eligibility to Yes** even when an image file still exists and happens to be `1200×630` (retry create/heal failure — a `failed` status means the *last* attempt didn't finish cleanly, so don't trust a possibly-partial file). This short-circuit lives in `is_eligible`, not inside `is_editorial_cover`.

### 5.2 Enrollment rules

A post is **eligible** when:

1. `cover_status == failed`, **or**
2. `is_editorial_cover` is **False** (missing image, wrong size/template, or unknown)

A post is **ineligible** when `is_editorial_cover` is **True** and `cover_status != failed`.

### 5.3 Selection order

Among eligible posts, sort by:

1. **Tier** (ascending):  
   - `0` = `cover_status == failed` (recent create/heal failures first)  
   - `1` = no usable image  
   - `2` = wrong-template / unknown (has image, not editorial)
2. Oldest front-matter `date` first  
3. Tie-break: slug ascending  

Then take the first **N** (default `N=50`).

This prevents a multi-day schematic backlog from starving new create-time failures.

### 5.4 Status transitions

```
                 create/heal success
    none ──────────────────────────► done
    failed ─────────────────────────► done
      ▲                                │
      │         create/heal failure    │ (stays done;
      └────────────────────────────────┘  not re-enrolled
         from none/failed                 unless manually reset)
```

- Heal **success:** write/overwrite image bytes + FM `image` / `image_alt` / `image_prompt`; set `cover_status: done`.
- Heal **failure:** set `cover_status: failed`; if a prior `image` existed, **leave it**; if none existed, leave missing. Continue to next slug.
- Manual reset (ops): set `cover_status: none` (or clear `done`) to force re-enrollment.

### 5.5 Keep `cover_status` honest at the source

**Bug (verified):** `apply_kept_frontmatter()` in `content_repair.py` currently sets `cover_status = "none"` unconditionally and can overwrite `image_suggestion` with a schematic brief even when an editorial `image_prompt` already exists (example: `navigating-the-llm-landscape-open-source-vs-commercial-in-20.mdx` — editorial cover present, `origin: bot`, `cover_status: none`).

**Required fix (same implementation train as heal):**

- Never downgrade `cover_status: done` → `none`.
- If `is_editorial_cover(fm, blog_root, slug)` → set/keep `cover_status: done`; do **not** replace an existing editorial `image_prompt` with a schematic `image_suggestion`.
- If usable image exists but classifier says wrong-template → `cover_status: none` (eligible).
- If no usable image → `cover_status: none`.

**One-time seed (before first paid heal batch):**

```bash
python cover_heal.py --blog-root … --seed-status-only
```

- Walk all posts; if `is_editorial_cover` and `cover_status != done`, set `cover_status: done` (FM only, no Bedrock/FLUX).
- Report **must** list these buckets for human spot-check before commit:
  - `seeded_done` — on-disk `1200×630`, status flipped/`kept` as done
  - `eligible_wrong_size` — usable image whose pixels are not `(1200, 630)` (square FLUX / old schematic / other)
  - `eligible_missing` — no usable local cover file
  - `already_done` — already `cover_status: done` (and still `1200×630` if file present)
- Dimension check removes the false-positive risk §15 #7 originally worried about (prompt-text denylist) — it's exact and structural, not heuristic. Spot-check the `seeded_done` list in the seed report anyway (should be very small — **1** on 2026-08-07); only then commit to `portfolio-blog` main.
- **Real counts, verified on 2026-08-07 corpus (249 posts, dimension-checked directly):** only **1** post is currently `1200×630` (today's `navigating-the-llm-landscape...`) → seeds to `done`. The other **248** — 21 non-`1200×630` imaged posts + ~227 with no usable image — remain eligible. This is intentional and expected, not a bug: the editorial template only shipped recently, so the backlog really is almost the entire catalog. At `≤50/day` that's **~5 days** to fully drain. `limit`/`workflow_dispatch` may be raised temporarily if a faster initial drain is wanted — see §12.

## 6. Architecture

```
digest.yml (existing cron)              heal-covers.yml (NEW cron)
─────────────────────────              ──────────────────────────
scrape → rewrite → verify              clone portfolio-blog@main
       ↓                               scan MDX → eligible (§5)
 maybe_generate_cover                  tiered sort; take ≤50
   ├─ ok  → cover_status: done              ↓
   └─ fail → cover_status: failed      editorial cover per slug
       ↓  push post (± image)            ├─ ok  → image + done
                                        └─ fail → failed (requeue)
                                       commit + push main
                                       upload cover_heal_report.md

concurrency group: portfolio-blog-main-write  (digest.yml + heal-covers.yml)
```

Both paths use the **same** editorial compose stack. Heal must not call `cover_backfill.py` (schematic / skip-if-image behavior).

## 7. Components

### 7.1 Shared editorial cover helper

Extract the body of today’s `maybe_generate_cover` into a shared function usable by:

- Daily create (`generate_digest.py`)
- Heal (`cover_heal.py`)

Contract (conceptual):

```text
generate_editorial_cover(headline, tags, body, slug, *, dry_run=False)
  → {"image", "alt", "prompt"} | raises / returns None per caller policy
```

Flow unchanged: Bedrock `cover_hook` → FLUX photo (skip in dry-run) → Playwright `compose_cover` → JPEG under the caller’s image directory.

Also ship `is_editorial_cover(fm, blog_root, slug)` beside it (FM + on-disk Pillow dimension check; no network).

### 7.2 Daily create wiring

In `build_mdx` / create path:

- Always write `cover_status`.
- Cover success → `cover_status: done` plus existing `image` fields.
- Cover fail-soft → `cover_status: failed`, omit `image` fields (text-only publish).

This enrolls new failures into the heal queue without coupling cron schedules.

**Rollout constraint:** this wiring must ship and run on at least one real `digest.yml` cycle **before** `heal-covers.yml` schedule is enabled (§11). Otherwise posts created in the gap have a missing key, read as `none`, and can be re-enrolled despite already having a fresh editorial cover from create.

### 7.3 `cover_heal.py` (new)

CLI:

```bash
python cover_heal.py \
  --blog-root /path/to/portfolio-blog \
  [--limit 50] \
  [--slugs slug-a,slug-b] \
  [--dry-run] \
  [--seed-status-only]
```

Behavior:

1. Scan `blog-root/posts/*.mdx`; parse front-matter + enough body for cover hook gist.
2. If `--seed-status-only`: apply §5.5 seed; write report; exit (no image generation).
3. Build eligible set (§5.2); apply `--slugs` filter if provided; tiered sort (§5.3); cap `--limit`.
4. For each selected slug, run shared editorial cover helper.
5. On success: write `blog-root/images/{slug}.jpg`; patch FM (`image`, `image_alt`, `image_prompt`, `cover_status: done`). Overwrite prior image files/FM.
6. On failure: patch `cover_status: failed` only (preserve prior image if any); log and continue.
7. Write `cover_heal_report.md` summarizing attempted / succeeded / failed / remaining eligible estimate / seeded count.

Dry-run: no Bedrock/FLUX network (placeholder photo / mock hook as in digest dry-run); do not push; default dry-run does not mutate `portfolio-blog` git state in CI.

### 7.4 Workflow `heal-covers.yml` (new)

| Trigger | Detail |
|---|---|
| `schedule` | Once daily, **offset** from digest cron (digest is `30 2 * * *`; heal e.g. `0 4 * * *` UTC). **Disabled or no-op until §11 step 6** (after the real limit-5 verification, not just the dry-run at step 4). |
| `workflow_dispatch` | Inputs: `limit` (default 50), `dry_run` (boolean), `seed_status_only` (boolean), optional `slugs` |

**Concurrency** (required):

```yaml
concurrency:
  group: portfolio-blog-main-write
  cancel-in-progress: false
```

Apply the **same** `concurrency.group` to `digest.yml` so manual `workflow_dispatch` of either job cannot race the other into a wasted Bedrock/FLUX batch that loses on push.

Job outline:

1. Checkout `daily-dev-digest`
2. Setup Python + `requirements.txt` + Playwright Chromium (same as digest cover steps)
3. AWS OIDC + CF image env secrets (same names as `digest.yml`)
4. Clone `portfolio-blog` at `main` with `BLOG_REPO_TOKEN`
5. Run `cover_heal.py --blog-root blog …`
6. If not dry-run and there are changes: commit + push to `main`  
   Message shape: `chore: heal up to N editorial covers` (or `chore: seed cover_status for editorial covers`)
7. Upload `cover_heal_report.md` as a workflow artifact

**Must not** run scrape, Bedrock article generate/verify, or content repair.

Workflow `workflow_dispatch` inputs must be passed via env vars / `github.event.inputs.*` into argv **without** interpolating untrusted strings into `run:` bash (same hardening as repair-content). Prefer `python cover_heal.py --limit "$LIMIT"` with `LIMIT` from `env:`.

### 7.5 Relationship to `regen-covers.yml` / `cover_backfill.py`

- Self-heal **does not** use the old schematic backfill path.
- Existing manual `regen-covers.yml` may remain for emergency one-offs but should be documented as legacy relative to `heal-covers.yml`.
- No requirement to delete `cover_backfill.py` in the first implementation PR.

### 7.6 `content_repair.py` FM stamping

Update `apply_kept_frontmatter` per §5.5 (needs `blog_root` + slug, or precomputed classifier result). Covered by unit tests that prove: `1200×630` editorial image is not forced to `none`; `done` is not downgraded; wrong-size image stays eligible (`none`).

## 8. Consumer / index impact

- `portfolio-blog` `build-index.yml` already rebuilds on `posts/**` and `images/**` changes.
- `cover_status` remains internal (not in `blogs.json` allowlist).
- Public field remains `coverImage` ← `image` path `/blog-images/{slug}.jpg`.
- `next-gen-portfolio` fetch/prune behavior unchanged; healed images appear on next fetch/deploy.

## 9. Failure modes

| Failure | Behavior |
|---|---|
| Bedrock cover_hook error | Slug → `failed`; continue batch |
| FLUX / CF error | Slug → `failed`; continue batch |
| Playwright compose error | Slug → `failed`; continue batch |
| Single slug YAML/parse error | Skip slug as `failed` or leave unchanged + log; do not abort batch |
| Git push conflict | Should be rare with concurrency group; if it still happens, job fails; next day’s clone retries. Do not claim success in report for unpushed work. |
| Secrets missing | Job fails fast before mutating posts |
| Partial batch (e.g. 20 ok, 5 fail, hit limit) | Commit the 20 successes + 5 `failed` markers; remaining eligible wait until tomorrow |

Batch is **best-effort per slug**. One failure never blocks the other 49.

## 10. Testing

- Unit: `is_editorial_cover` matrix using **fixture JPEGs** at `(1200, 630)`, `(800, 800)`, `(1024, 1024)`, missing file; plus `cover_status: failed` eligibility short-circuit.
- Unit: eligibility + tiered selection order + limit.
- Unit: FM patch success → `done` + image fields; failure → `failed` preserves prior image.
- Unit: `--seed-status-only` flips `1200×630` + `none` → `done` without calling image APIs; wrong-size stays eligible.
- Unit: seed report buckets are `seeded_done` / `eligible_wrong_size` / `eligible_missing` / `already_done` (not prompt-based `eligible_schematic`).
- Unit: `apply_kept_frontmatter` does not corrupt `1200×630` covers / does not downgrade `done`.
- Unit: daily `build_mdx` always emits `cover_status` (`done` or `failed`).
- Optional CI dry-run / seed dispatch documented in PR.

## 11. Rollout

Strict sequence (blocking):

1. Land code on `daily-dev-digest` `master`: shared helpers, `cover_heal.py`, `apply_kept_frontmatter` fix, daily-create `cover_status` wiring, `heal-covers.yml` **with schedule commented or gated off**, concurrency on digest+heal, tests, this spec.
2. Prove daily-create wiring: wait for **one real successful `digest.yml` run** (or dispatch) that writes a new/updated post with `cover_status: done` or `failed` as appropriate.
3. `workflow_dispatch` heal with `seed_status_only=true` → spot-check report buckets → commit FM-only corrections on `portfolio-blog` main; verify the single (or few) `1200×630` posts are `done` and wrong-size/missing remain eligible.
4. `workflow_dispatch` heal `dry_run=true`, `limit=3`.
5. `workflow_dispatch` heal `dry_run=false`, `limit=5`; verify new images are exactly `1200×630` + `cover_status: done` + index rebuild.
6. **Only then** enable `heal-covers.yml` schedule.
7. Backlog drains at ≤50/day on the **true** eligible set (**248** on 2026-08-07 after seed — wrong-size + missing), not a false “already mostly done” count from prompt heuristics.
8. Steady state: queue usually empty or holds only recent create/heal failures.

## 12. Cost / ops knobs

### Cost

- **Backlog drain:** ≤50 editorial covers/day. Real eligible count after seed is **248** (verified 2026-08-07 — only 1 post is currently the true `1200×630` template; the rest, including 21 `origin: bot` posts with square photos, are eligible) — effectively the whole catalog, not a small residual. At 50/day that's **~5 days**. Unit cost ≈ one digest cover attempt (Bedrock hook + FLUX + Playwright minutes) per slug, so a full drain costs roughly 248× that unit cost regardless of how many days it's spread across.
- **Steady state (ongoing cron):** typically **0–few** covers/day — only `failed` create/heal retries and rare manual resets. Idle runs still clone/scan but skip paid generation when eligible count is 0.

### Knobs

- Exact UTC cron minute may be adjusted so heal’s paid work stays clear of digest’s Bedrock/CF burst (concurrency still serializes git writers).
- `limit` may be lowered via `workflow_dispatch` if CF/Bedrock rate limits appear.
- Forcing a re-heal of a `done` post is a manual FM edit (`cover_status: none`), not an automatic path.

## 13. Success criteria

- Separate green `heal-covers` workflow runs on schedule without invoking digest scrape/create.
- `cover_status` is trustworthy: repair does not force editorial posts back to `none`; seed corrects the existing corpus.
- Eligible posts monotonically trend toward `cover_status: done` under normal operations.
- New posts that fail cover at create time appear in the **next** heal selection (tier 0), not behind a schematic backlog.
- Heal failures remain eligible (`failed`) and are retried on a later run.
- Digest and heal do not race-push `portfolio-blog` main (shared concurrency group).
- No public exposure of `cover_status`; site only sees valid `/blog-images/*.jpg` when present.

## 14. Review findings — resolutions

Pre-implementation review gaps and how this draft locks them:

| # | Finding | Resolution |
|---|---|---|
| 1 | `cover_status: none` is corrupted by unconditional repair stamping; `origin: bot` ≠ editorial; false backlog would burn spend | **Both layers:** fix `apply_kept_frontmatter` (§5.5) + one-time `--seed-status-only` + eligibility via `is_editorial_cover` (§5.1). Explicitly **reject** “`origin == bot` ⇒ done”. |
| 2 | Daily create doesn’t write `cover_status` today; enabling heal cron in the same breath re-enrolls fresh covered posts | §7.2 + **sequenced rollout** (§11 steps 1→2 before schedule). |
| 3 | No concurrency guard; push conflict wastes paid work | Shared `concurrency.group: portfolio-blog-main-write` on `heal-covers.yml` **and** `digest.yml` (§7.4). |
| 4 | No steady-state cost note | §12 cost subsection. |
| 5 | Oldest-first makes false-positive/old schematic backlog starve new failures | Tiered selection (§5.3): `failed` → missing → wrong-template, then date/slug. Depends on #1 classifier/seed. |

Typo fix note: §9 table uses “Slug” consistently (not “Spug”).

## 15. Re-review notes (second pass, minor) — accepted

| # | Note | Resolution |
|---|---|---|
| 6 | §7.4 cross-referenced "§11 step 4" as the schedule gate; §11's actual gate is step 6 (after the real limit-5 verification, not just the dry-run). | **Fixed** in §7.4 → "until §11 step 6." |
| 7 | Schematic denylist on `image_prompt` may rare-false-positive an editorial brief. | **Superseded by §16 #9** — the denylist itself was dropped in favor of an exact dimension check (`== (1200, 630)`), which is structural rather than heuristic and closes this concern entirely rather than just accepting the risk. |
| 8 | Heal pushes up to 50 posts/day to `main` without a PR, unlike content-repair’s preview path. | **Accepted with rationale** folded into §3 Push target: mechanical FM+image only; blast radius is cover quality, not article authenticity. |

## 16. Third-pass finding (2026-08-07, post-approval) — URGENT, blocking, verify against in-progress implementation

**Status note:** this doc was marked Approved and implementation started on `feature/cover-self-heal` before this finding. If Cursor's implementation was built against §5.1/§5.5/§12's earlier prompt-text-denylist numbers, it needs to be corrected before merge, not just the doc.

| # | Finding | Fix applied to this doc |
|---|---|---|
| 9 | The originally-approved §5.1 classifier used `image_prompt` **substring denylist** matching to detect "wrong template" — verified against the real corpus this is not sufficient. Checked actual pixel dimensions of all 22 `origin: bot` posts directly: only **1** is genuinely `1200×630` (today's post, the real Playwright-composed output — `cover_compose.py` hardcodes `COVER_W, COVER_H = 1200, 630`). The other **21** are `800×800`/`1024×1024` square FLUX-only photos from an earlier photo-brief iteration that never went through the diagonal-split/branded template — their prompt text just doesn't happen to contain the old schematic keywords, so the denylist would have permanently misclassified all 21 as "already editorial" and skipped them. Editorial quality is a structural property of the compose step, not something prompt phrasing can reliably signal. | §5.1 rewritten: `is_editorial_cover` now requires exact on-disk dimensions `== (1200, 630)` as the sole authoritative test; the prompt-text denylist is dropped entirely, not just supplemented. §2 non-goals, §5.5 seed math, §12 cost estimate, and §11 step 7 updated to the real numbers: **1 post already done, 248 eligible** (not ~5 done / ~17 schematic / ~227 missing) — the backlog is effectively the whole catalog, ~5 days to drain at 50/day, same as before by coincidence of arithmetic but for a completely different (and much larger) real eligible count. |

**Action needed:** confirm with whoever is implementing `is_editorial_cover` right now that it does an actual dimension check (`PIL.Image.open(path).size == (1200, 630)`), not a prompt-text keyword match — and that nobody hand-seeded the ~5/~17/~227 split anywhere (report format, test fixtures, cost comments) based on the superseded numbers.

## 17. Fourth-pass gaps (2026-08-08) — doc consistency + implementation sync

Cursor reviewed Claude’s §16 update against the live corpus and the in-progress PR (`feature/cover-self-heal` / PR #7). **Agree with #9.** The following gaps were still open after §16 landed in the doc; this section records them and the fixes applied above (or required in code once this spec is finalized).

### 17.1 Spec consistency gaps (fixed in this doc revision)

| # | Gap | Fix in this doc |
|---|---|---|
| 10 | §5.1 listed two overlapping “dimensions == 1200×630 → True” rules (old #3 required `done`, old #4 did not). | Collapsed to a single rule: dimensions == `(1200, 630)` → True. `failed` short-circuit stays in `is_eligible` only. |
| 11 | §5.1 / §7.1 helper signature omitted `slug` while path resolution needs it. | Signature locked as `is_editorial_cover(fm, blog_root, slug)`; §7.1 updated. |
| 12 | §5.5 seed report still named bucket `eligible_schematic` (prompt-era). | Renamed to `eligible_wrong_size`; buckets listed explicitly. |
| 13 | §10 tests still described “schematic prompt / editorial prompt” matrices. | Rewritten around fixture JPEG dimensions + failed short-circuit. |
| 14 | §7.6 / §11 step 7 still used “schematic” / “false 249” wording that fought §12’s verified **248 eligible**. | Aligned to wrong-size/missing + **248** after seed. |

### 17.2 Implementation gaps vs this finalized §5.1 (do **not** merge PR until fixed)

These are present on PR #7 as of the fourth pass and must be corrected **after** this spec revision is approved — not before:

| # | Gap in current code | Required fix |
|---|---|---|
| 15 | [`cover_status.py`](cover_status.py) `is_editorial_cover` still uses `SCHEMATIC_DENYLIST` / `prompt_is_schematic` on `image_prompt` and never reads pixel size. | Replace with Pillow `Image.open(local_cover_path).size == (1200, 630)`; delete denylist path for enrollment. |
| 16 | [`cover_heal.py`](cover_heal.py) / tests still classify seed buckets as `eligible_schematic` and assert prompt-based editorial detection. | Switch to `eligible_wrong_size`; add tiny fixture JPEGs (or generate in-test with Pillow) at 1200×630 / 800×800 / 1024×1024. |
| 17 | [`tests/test_content_repair.py`](tests/test_content_repair.py) “editorial cover” case uses a non-schematic prompt string without a real `1200×630` file dimension guarantee in the classifier sense. | After #15, tests must create a real 1200×630 JPEG under `images/` for the “already editorial” case, and an 800×800 file for “wrong size stays none”. |
| 18 | Any comments/docs in the PR that still cite “~5 editorial / ~17 schematic / ~227 missing” as the backlog split. | Replace with verified **1 / 21 wrong-size / ~227 missing** (248 eligible after seed). |

### 17.3 Non-gaps / no product decision needed

- Raising `limit` above 50 for a faster first drain remains an ops knob (§12), not a spec change.
- Direct push to `main` for heal remains accepted (§15 #8).
- Schedule stays gated until §11 step 6.

**Gate:** finalize this doc (§16 + §17) with Claude → then update PR #7 implementation to match §5.1 / §10 / §17.2 → then continue rollout.
