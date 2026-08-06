# Legacy Content Repair — Design

**Date:** 2026-08-07  
**Repo:** `daily-dev-digest` (writes into `portfolio-blog` via preview branch)  
**Branch context:** `feature/post-editorial-cover-followups` (on top of editorial-cover PR)  
**Status:** Dual-review aligned — ready for implementation planning after Mohan sign-off  

## 1. Purpose

Repair the large set of older `portfolio-blog` posts that predate (or only partially match) the current AI digest quality bar: incomplete scraper bodies, junk, inconsistent voice. Produce a reviewable preview-branch diff — not a silent `main` rewrite.

This is **content cleanup first**. Editorial cover image generation (Approach A template from `2026-08-06-editorial-cover-template-and-topic-focus-design.md`) is a **later batch** that consumes metadata written here.

## 2. Goals and non-goals

### Goals

- LLM triage every post: `junk` | `rewrite` | `clean`.
- Delete only **genuine junk** (not “off topic allowlist”).
- Rewrite keepers from the **existing post body as gist**; do not invent facts; **may web-search** for genuine facts about the gist and use them.
- Stamp internal front-matter: `ai` + `origin` + cover prep fields (**not shown on site**).
- Always set public byline `author: Mohan Sagar` on kept posts.
- Keep `source_url` in front-matter only when useful as **internal reference** — never render it (or body source-attribution links) on the Posts UI.
- Refresh `image_suggestion` on **all kept** posts; set `cover_status: none`.
- Deliver via **preview branch** on `portfolio-blog` for human merge.
- Idempotent / resumable via a committed ledger.

### Non-goals

- Generating cover images in this workstream (FLUX / Playwright).
- Relying on `source_url` for rewrite grounding (body gist + optional search only).
- Deleting posts merely because they fail today’s topic allowlist.
- Pushing repair results directly to `portfolio-blog` `main`.
- Replacing `cover_backfill.py` in this pass (later batch will prefer editorial template + `cover_status`).

## 3. Inventory (observed)

Approximate `portfolio-blog/posts` state at design time:

| Cohort | Signal | Count (approx.) |
|---|---|---|
| Editorial/pipeline covers | `image` + `image_prompt` | ~6 |
| Pre-cover pipeline / mixed | `author: Agent Bot` or similar | tens |
| Older scraper mass | often `image_suggestion`, no real cover | ~230+ |
| **Total** | | **~245** |

Exact counts are re-measured at implement time. Origin detection stays intentionally simple (see §5).

## 4. Architecture (Approach A)

```
portfolio-blog/posts/*.mdx
        │
        ▼
 content_repair.py
   1. load title + body
   2. origin = bot | scraper          (heuristic)
   3. Bedrock triage → junk|rewrite|clean
   4a. junk    → delete mdx (+ local orphan image only)
   4b. rewrite → web search notes → Bedrock generate → Bedrock verify
   4c. clean   → keep body
   5. for kept: set FM (ai, origin, author, cover_status, image_suggestion)
   6. update committed repair_ledger.json + triage-report.md
        │
        ▼
 dated preview branch on portfolio-blog  (never main)
```

**Components:**

| Piece | Role |
|---|---|
| `content_repair.py` | Orchestration CLI |
| `search_client.py` | Env-configured web search adapter → notes text |
| `bedrock_client.py` (reuse) | Triage / generate / verify / image_suggestion |
| **Repair-specific** prompts (fork, not digest templates) | Body-as-gist + search notes; no source_url attribution requirement |
| `.github/workflows/repair-content.yml` | `workflow_dispatch` → preview push |
| `repair_ledger.json` | Committed in `daily-dev-digest` — durable idempotency |

## 5. Origin detection (`origin`)

Simple heuristic only:

- **`bot`** if the post clearly has digest/pipeline cover fields: both `image` and `image_prompt` present and non-empty.
- Else **`scraper`**.

No date archaeology, no author-name guessing beyond that. Ambiguity → `scraper`.

## 6. Triage (LLM)

Single Bedrock call returns JSON:

```json
{
  "verdict": "junk" | "rewrite" | "clean",
  "reason": "short explanation",
  "confidence": "high" | "medium" | "low"
}
```

**Guidance to the model:**

- **junk** — empty/near-empty, nav/boilerplate garbage, unreadable scrape failure, spam, or no recoverable technical gist. Prefer `high` confidence for junk.
- **rewrite** — has a real topic/gist but incomplete, thin, broken structure, or clearly below current blog standards.
- **clean** — already coherent enough to keep without rewrite.

**Delete policy:** only delete when `verdict == junk` **and** `confidence == high`. Medium/low junk → treat as `rewrite` (fail-soft toward keeping content).

Topic allowlist is **not** an input to junk.

## 7. Rewrite path

1. Build a **gist packet** from title + body (bounded chars).
2. **Web search** on gist/topic queries via `search_client` → `search_notes` (titles, snippets, URLs).
3. If search fails/unavailable → proceed with gist only; log warning; still **no invention**.
4. Bedrock **generate** using **repair-specific** prompts (forked from digest, not reused as-is):
   - Grounding: prior post body gist + `search_notes` only.
   - **Do not** require or invent a `SOURCE_URL` / “original source” link in the body.
   - When search notes include URLs, the model may cite those URLs as supporting references; when search was empty, state grounding is the prior post body only.
5. Bedrock **verify** against gist + search notes (not against a live `source_url`).
6. **Conflict rule:** gist wins for “what this post is about”; search may add/correct general technical facts; if they conflict on a specific claim, **soften or drop** the claim — do not invent a merge.
7. **Keep slug**; may update `title` / `subtitle` / `summary` in FM to match rewrite.
8. Set `author: Mohan Sagar` (always).

Existing `source_url` in FM may be **preserved** as an internal field if already present; repair must not add a fabricated one. It must not appear in the rewritten body.

## 8. Front-matter (internal + byline)

On every **kept** post after repair:

| Field | Values | Meaning | On site? |
|---|---|---|---|
| `ai` | `true` | Passed LLM triage (AI owns cleanliness) | **No** — internal |
| `origin` | `scraper` \| `bot` | Where the post came from (§5) | **No** — internal |
| `author` | `Mohan Sagar` | Public byline | **Yes** (byline only) |
| `cover_status` | `none` | Needs editorial cover later | **No** — internal |
| `image_suggestion` | string | Fresh prompt/brief for later cover batch | **No** — internal |
| `source_url` | string (optional) | Prior/internal reference only if already present | **No** — must not render |

**Site / consumer requirements (pre-merge checklist):**

1. Confirm `portfolio-blog` `build-index.mjs` / `next-gen-portfolio` do **not** display `sourceUrl` / `source_url` on post UI (today body attribution is already stripped in build-index; verify cards/detail never show the field).
2. Confirm unknown FM keys (`ai`, `origin`, `cover_status`, `image_suggestion`) are ignored by the index/UI and do not break the build.
3. If either check fails, fix the consumer in the same merge train **before** merging a large repair preview to `main`.

**Later image batch (out of scope here):**

- Run editorial cover pipeline only when `cover_status != done`.
- Old FLUX one-shot covers (even if `image` exists today) are **not** “done” — repair sets `cover_status: none`.
- On successful editorial compose → set `cover_status: done` (and normal `image` / `image_alt` / `image_prompt`).

## 9. Ops

### CLI

```bash
python content_repair.py \
  --blog-root /path/to/portfolio-blog \
  [--slugs slug-a,slug-b] \
  [--limit N] \
  [--dry-run] \
  [--force]
```

| Flag | Behavior |
|---|---|
| `--dry-run` | Triage (+ search plan logging); write local report only; no MDX writes; no push |
| `--limit N` | Process at most N unfinished slugs |
| `--slugs` | Explicit subset |
| `--force` | Re-process even if ledger says done |

### Ledger (durable)

- Path: **`repair_ledger.json` committed in `daily-dev-digest`** (not Actions artifacts, not ephemeral).
- Per slug: input body hash, verdict, confidence, reason, actions, timestamps, Bedrock/search counts.
- Skip completed slugs unless `--force`.

### Review artifact

Every non-dry-run preview push includes **`triage-report.md`** in the preview branch (or as a commit alongside): slug / verdict / confidence / reason / action (`deleted` \| `rewritten` \| `kept`).

### Workflow

`.github/workflows/repair-content.yml`:

- `workflow_dispatch` inputs: `limit`, `slugs`, `dry_run`, `full_run` (boolean; required true to process beyond default small limit).
- Auth: AWS OIDC (Bedrock) + search API secret + `BLOG_REPO_TOKEN`.
- Clone `portfolio-blog`, run repair, push **dated** branch: `repair/content-cleanup-YYYYMMDD-HHMM` (fail if branch exists unless explicitly forced).
- **Never** push `main`.

### Cost / time (order-of-magnitude)

Assume ~245 posts, rewrite fraction `R` (unknown until dry-run; plan with R≈0.5–0.8 worst case):

| Stage | Calls (approx.) |
|---|---|
| Triage | ~245 |
| Search | ~245×R (rewrite only) |
| Generate + verify | ~2×245×R |
| `image_suggestion` | ~245 (all kept; junk deleted skip) |

Wall-clock: tens of minutes to a few hours depending on R, Bedrock latency, and search. Implement lightweight retry/backoff around Bedrock (digest client has none today). Prefer batched `limit` runs until triage-report looks sane, then `full_run=true`.

### Failure modes

| Stage | Behavior |
|---|---|
| Triage parse/API fail | Log error; skip post (ledger `error`); continue batch |
| Search fail | Warn; rewrite from gist only; no invention |
| Generate/verify fail | Skip rewrite; leave original body; ledger `error`; continue |
| `image_suggestion` fail | Keep post; leave prior suggestion or empty; ledger warn; continue |
| MDX write fail | Ledger `error`; continue |
| Junk delete | Only `junk`+`high`; delete `.mdx`; delete **local** `images/{slug}.jpg` only if present; **never** delete/fetch external `image:` URLs |
| Preview push fail | Fail the workflow; ledger may already be partially updated — safe to re-run (idempotent skips) |

## 10. Testing

- Unit: origin heuristic; FM splice; junk confidence gate; ledger skip/force; local-vs-external image delete.
- Unit: search_client mock → notes formatting.
- Unit: repair prompts contain no `SOURCE_URL` hard requirement.
- Integration (mocked Bedrock/search): clean keeps body; rewrite replaces body + `author`; junk deletes file; dry-run no MDX writes; report emitted.
- Manual: dry-run on 10 live posts → inspect triage table before first preview push.
- Pre-merge: consumer checklist in §8.

## 11. Success criteria

- Preview branch shows deletes + rewrites + FM stamps for a sample batch.
- No invention path without search notes or gist support (prompt + verify contract).
- All kept sample posts have `ai: true`, `origin`, `author: Mohan Sagar`, `cover_status: none`, non-empty `image_suggestion`.
- Posts UI shows neither `source_url` nor internal `ai`/`origin`/`cover_status`/`image_suggestion`.
- `main` untouched until Mohan merges the preview branch.
- Later cover batch can select `cover_status: none` only.

## 12. Plan-time only (non-blocking)

1. Exact search vendor/env var names (`SEARCH_API_KEY`, etc.).
2. Whether `triage-report.md` lives on the preview branch root or under `.repair/`.

## 13. Relationship to other workstreams

| Workstream | Status |
|---|---|
| Editorial covers + topic allowlist (2026-08-06) | Separate PR; this branch stacks on it for shared Bedrock/cover conventions |
| Cover backfill / regen-covers.yml | Unchanged now; later point at editorial compose + `cover_status` |
| Daily digest `generate_digest.py` | Unchanged for daily path; repair uses forked prompts. New digest posts should eventually stamp `ai`/`origin` too (small follow-up if not in this pass) |
| Site consumer | Must hide `source_url` + internal FM (§8 checklist) |

## 14. Review decisions (locked)

Claude gaps + dual-review resolutions:

| # | Decision |
|---|---|
| 1 | **Accept** — repair-specific prompts; no source_url attribution requirement (§7). |
| 2 | **Accept** — committed `repair_ledger.json` in `daily-dev-digest` (§9). |
| 3 | **Accept** — failure-mode table (§9). |
| 4 | **Accept** — `triage-report.md` on every preview push (§9). |
| 5 | **Accept** — pre-merge consumer checklist for unknown FM + `source_url` UI (§8). |
| 6 | **Accept** — delete local cover files only (§9). |
| 7 | **Accept** — cost/time incl. `image_suggestion` on all kept (§9). |
| 8 | **Accept** — gist vs search conflict rule (§7). |
| 9 | **Mohan** — always `author: Mohan Sagar` on kept posts. |
| 10 | **Mohan** — field is `ai: true` (not `content_triage`); origin field is `origin: scraper\|bot`. |
| 11 | **Accept** — dated preview branch names; no silent overwrite (§9). |
| + | **Mohan** — `source_url` internal only; never on Posts UI. |

---

**Mohan:** please re-review this updated spec. After approval, next step is the implementation plan, then build on `feature/post-editorial-cover-followups`.
