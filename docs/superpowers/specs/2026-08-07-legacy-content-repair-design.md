# Legacy Content Repair — Design

**Date:** 2026-08-07  
**Repo:** `daily-dev-digest` (writes into `portfolio-blog` via preview branch)  
**Branch context:** `feature/post-editorial-cover-followups` (on top of editorial-cover PR)  
**Status:** Draft for Mohan review  

## 1. Purpose

Repair the large set of older `portfolio-blog` posts that predate (or only partially match) the current AI digest quality bar: incomplete scraper bodies, junk, inconsistent voice. Produce a reviewable preview-branch diff — not a silent `main` rewrite.

This is **content cleanup first**. Editorial cover image generation (Approach A template from `2026-08-06-editorial-cover-template-and-topic-focus-design.md`) is a **later batch** that consumes metadata written here.

## 2. Goals and non-goals

### Goals

- LLM triage every post: `junk` | `rewrite` | `clean`.
- Delete only **genuine junk** (not “off topic allowlist”).
- Rewrite keepers from the **existing post body as gist**; do not invent facts; **may web-search** for genuine facts about the gist and use them.
- Stamp internal front-matter for origin + triage + future covers (not shown on site).
- Refresh `image_suggestion` on **all kept** posts; set `cover_status: none`.
- Deliver via **preview branch** on `portfolio-blog` for human merge.
- Idempotent / resumable via a ledger.

### Non-goals

- Generating cover images in this workstream (FLUX / Playwright).
- Relying on `source_url` availability for rewrite grounding.
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
   4a. junk    → delete mdx (+ orphan image if present)
   4b. rewrite → web search notes → Bedrock generate → Bedrock verify
   4c. clean   → keep body
   5. for kept: set FM (triage/origin/cover_status/image_suggestion)
   6. ledger.jsonl update
        │
        ▼
 preview branch on portfolio-blog  (never main)
```

**Components (new / thin):**

| Piece | Role |
|---|---|
| `content_repair.py` | Orchestration CLI |
| `search_client.py` (or equivalent) | Env-configured web search adapter → notes text |
| Reuse `bedrock_client.py` | Triage / generate / verify / image_suggestion |
| Reuse digest generate+verify prompts (adapted) | Body-as-gist + search notes; no `source_url` requirement |
| `.github/workflows/repair-content.yml` | `workflow_dispatch` → preview push |
| `repair_ledger.json` | Idempotency |

## 5. Origin detection (`content_origin`)

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
4. Bedrock **generate** structured post (same shape as digest LLM#1: headline/subtitle/meta/tags/body) grounded in gist + search notes.
5. Bedrock **verify** against gist + search notes (not against a live source_url).
6. Preserve slug (do not rename files in v1) unless implementer discovers a hard collision rule — default: **keep slug**, may update `title`/`subtitle` in FM to match rewrite.

## 8. Front-matter (internal)

On every **kept** post after repair:

| Field | Values | Meaning |
|---|---|---|
| `content_triage` | `ai` | Passed triage; AI owns cleanliness decision |
| `content_origin` | `scraper` \| `bot` | Where the post came from (§5) |
| `cover_status` | `none` | Needs editorial cover later |
| `image_suggestion` | string | Fresh prompt/brief text for later cover batch |

**Site:** these fields must not surface in the public UI. Consumer (`portfolio-blog` / `next-gen-portfolio`) already selects known fields for display; if any unknown FM leaks, fix consumer ignore-list in a tiny follow-up — not a blocker for repair tooling.

**Later image batch (out of scope here):**

- Run editorial cover pipeline only when `cover_status != done`.
- Old FLUX one-shot covers (even if `image` exists today) are **not** “done” — repair sets `cover_status: none` so they are regenerated with the editorial template.
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
| `--dry-run` | Triage (+ search plan logging); no MDX writes; no push |
| `--limit N` | Process at most N unscanned/unfinished slugs |
| `--slugs` | Explicit subset |
| `--force` | Re-process even if ledger says done |

### Ledger

`repair_ledger.json` (repo-local or under blog-root — choose one at plan time; prefer **daily-dev-digest** repo artifact committed only if useful, otherwise Actions artifact / blog-root `.repair/` gitignored on preview).

Record per slug: input body hash, verdict, actions, timestamps, token/search counts.

### Workflow

`.github/workflows/repair-content.yml`:

- `workflow_dispatch` inputs: `limit`, `slugs`, `dry_run`, `full_run` (boolean; required true to ignore default small limit).
- Auth: AWS OIDC (Bedrock) + search API secret + `BLOG_REPO_TOKEN`.
- Clone `portfolio-blog`, run repair, push branch e.g. `repair/content-cleanup-YYYYMMDD`.
- **Never** push `main`.

### Cost / safety

- Default dispatch limit small (e.g. 10) until `full_run=true`.
- Log Bedrock call counts + search counts.
- Fail-soft per post: one failure must not abort the whole batch (record error in ledger, continue).

## 10. Testing

- Unit: origin heuristic; FM splice/preserves unknown fields; junk confidence gate; ledger skip/force.
- Unit: search_client mock → notes formatting.
- Integration (mocked Bedrock/search): clean keeps body; rewrite replaces body; junk deletes file; dry-run no writes.
- Manual: dry-run on 10 live posts → inspect triage table before first preview push.

## 11. Success criteria

- Preview branch shows deletes + rewrites + FM stamps for a sample batch.
- No invention path without search notes or gist support (prompt + verify contract).
- All kept sample posts have `content_triage: ai`, `content_origin`, `cover_status: none`, non-empty `image_suggestion`.
- `main` untouched until Mohan merges the preview branch.
- Later cover batch can select `cover_status: none` only.

## 12. Open implementation choices (plan-time, not design blockers)

1. Exact search vendor/env var names (`SEARCH_API_KEY`, etc.).
2. Ledger file location (digest repo vs blog-root `.repair/`).
3. Whether rewrite may update `title` in FM while keeping slug (default yes).
4. Whether deleted posts’ images are deleted in the same commit (default yes if slug-matched file exists).

## 13. Relationship to other workstreams

| Workstream | Status |
|---|---|
| Editorial covers + topic allowlist (2026-08-06) | Separate PR; this branch stacks on it for shared Bedrock/cover conventions |
| Cover backfill / regen-covers.yml | Unchanged now; later point at editorial compose + `cover_status` |
| Daily digest `generate_digest.py` | Unchanged; new posts already AI path — still included in triage once for labeling |

---

**Mohan:** please review this spec. After approval, next step is an implementation plan (`docs/superpowers/plans/…`) then build on `feature/post-editorial-cover-followups`.
